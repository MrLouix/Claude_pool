"""Task pool driver — TaskExecutor and execute_message, extracted from executor.py."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .cli_executors import (
    _RATE_LIMIT_PATTERNS,
    MAX_RETRIES,
    CLIManager,
    NoCLIAvailableError,
    build_cmd_from_profile,
    truncate_context_messages,
)
from .concurrency import TaskSemaphore
from .models import CLIConfig, CliCommand, PoolState, Project, ProjectMessage, Task
from .parser import parse_claude_output, parse_output
from .routing import NoCLICommandError, build_command, resolve_command, resolve_command_chain
from .storage import cleanup_old_tasks, load_pool

logger = logging.getLogger(__name__)

MAX_SUBTASKS_PER_TASK = 10


def _make_subtask_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def _meta_hash(state: PoolState) -> str:
    """Stable string representation of pool-level metadata for change detection."""
    return f"{state.retry_count}|{state.suspended_until}|{getattr(state, 'provider', 'claude')}"


async def execute_message(
    message: ProjectMessage,
    project: Project,
    cli_manager: CLIManager,
    db_path: str,
    model: str | None = None,
) -> dict:
    """Execute a project message with automatic CLI switching on rate limit.

    Builds conversation context from the last 3 linked messages, then attempts
    execution up to MAX_RETRIES times. On rate limit, switches CLI when the
    project permits it (allow_cli_switch=True).

    Args:
        message: The user message to execute.
        project: The project owning the message (controls default_cli / switching).
        cli_manager: Manages all available CLI executors.
        db_path: Path to the SQLite database (for context retrieval).
        model: Optional model override; executor default is used when None.

    Returns:
        Result dict from the executor merged with {"cli_used": <cli_name>}.

    Raises:
        NoCLIAvailableError: When no CLI is available or all retries are exhausted.
        RuntimeError: When rate-limited and allow_cli_switch is False.
    """
    import team_cli.executor as _exec_mod
    raw_context = await asyncio.to_thread(_exec_mod.build_context, message, Path(db_path))
    context = truncate_context_messages(raw_context)

    # Resolve starting executor
    if project.default_cli:
        cli = cli_manager.get_executor_by_name(project.default_cli)
        if cli is None or cli.check_rate_limit():
            if project.allow_cli_switch:
                cli = cli_manager.get_next_available_cli(exclude=[])
            else:
                raise NoCLIAvailableError(
                    f"Default CLI '{project.default_cli}' is unavailable"
                )
    else:
        cli = cli_manager.get_next_available_cli(exclude=[])

    if cli is None:
        raise NoCLIAvailableError("No CLI available")

    tried_clis: list[str] = []

    for _ in range(MAX_RETRIES):
        formatted_context = cli.format_context(context)
        full_prompt = formatted_context + message.content if formatted_context else message.content
        result = await asyncio.to_thread(
            cli.execute,
            prompt=full_prompt,
            context=context,
            directory=project.directory,
            model=model or "",
        )

        if not cli.check_rate_limit():
            result["cli_used"] = result.get("cli_name", cli.config.name)
            if "cli_name" not in result:
                result["cli_name"] = cli.config.name
            return result

        # Rate-limited — record and optionally switch
        tried_clis.append(cli.config.name)
        if not project.allow_cli_switch:
            raise RuntimeError(
                f"CLI '{cli.config.name}' is rate-limited and switching is disabled"
            )

        next_cli = cli_manager.get_next_available_cli(exclude=tried_clis)
        if next_cli is None:
            raise NoCLIAvailableError("All CLIs are rate-limited")
        cli = next_cli

    raise NoCLIAvailableError("Max retries exceeded")


class TaskExecutor:
    """Executes tasks from a pool sequentially with global rate-limit handling."""

    def __init__(
        self,
        pool_file: Path,
        on_task_update: Callable[[Task], None] | None = None,
        max_concurrent: int = 1,
        install_signal_handlers: bool = True,
        cli_manager: "CLIManager | None" = None,
    ):
        """Initialize the executor.

        Args:
            pool_file: Path to pool.db
            on_task_update: Optional callback called when a task is updated
            max_concurrent: Maximum number of tasks to run concurrently (default: 1)
            install_signal_handlers: Whether to install SIGINT/SIGTERM handlers.
                Set to False when running inside a server (e.g. uvicorn) that
                manages its own signal handling.
            cli_manager: Optional CLIManager for multi-CLI support.
                If None, creates a fallback Claude-only manager.
        """
        self.pool_file = pool_file
        self.pool = PoolState(pool_file=pool_file)
        self.current_task: Task | None = None
        self.paused = False
        self.should_stop = False
        self.skip_requested = False
        self.on_task_update = on_task_update
        self._last_known_task_ids: set[str] = set()
        self._last_pool_meta_hash: str = ""

        self.max_concurrent = max_concurrent
        self.semaphore = TaskSemaphore(max_concurrent)
        self._save_lock = asyncio.Lock()

        self._running_processes: dict[str, asyncio.subprocess.Process] = {}
        self._chat_locks: dict[str, asyncio.Lock] = {}

        if cli_manager is not None:
            self.cli_manager = cli_manager
        else:
            fallback_config = CLIConfig(
                name="claude",
                path="claude",
                models=[],
                cli_type="anthropic",
            )
            self.cli_manager = CLIManager([fallback_config])

        if install_signal_handlers:
            from .signal_handler import install_handlers
            install_handlers(self)

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.should_stop = True
        self._save_state()

    def _do_save(self) -> None:
        """Write pool to DB and stamp tracking hashes to suppress self-triggered reloads."""
        import team_cli.executor as _exec_mod
        _exec_mod.save_pool(self.pool)
        self._last_known_task_ids = {t.id for t in self.pool.tasks}
        self._last_pool_meta_hash = _meta_hash(self.pool)
        logger.debug("State saved successfully")

    async def _save_state_async(self) -> None:
        """Save current state to pool file (async, thread-safe)."""
        async with self._save_lock:
            try:
                self._do_save()
            except Exception as e:
                logger.error(f"Failed to save state: {e}")

    def _save_state(self) -> None:
        """Save current state to pool file (sync version for signal handlers)."""
        try:
            self._do_save()
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    async def load_tasks(self) -> None:
        """Load tasks and pool state from the database."""
        try:
            self.pool = load_pool(self.pool_file)
            self.pool.pool_file = self.pool_file
            logger.info(f"Loaded {len(self.pool.tasks)} tasks from {self.pool_file}")

            removed = cleanup_old_tasks(self.pool, max_age_hours=48)
            if removed > 0:
                logger.info(f"Automatically cleaned up {removed} old completed tasks")

            self._last_known_task_ids = {t.id for t in self.pool.tasks}
            self._last_pool_meta_hash = _meta_hash(self.pool)
        except Exception as e:
            logger.error(f"Error loading tasks: {e}")
            raise

    def _classify_exit(
        self,
        exit_code: int,
        stdout: bytes,
        stderr: bytes,
        json_output: dict | None,
    ) -> tuple[str, bool]:
        """Map subprocess exit to (status_string, is_rate_limit)."""
        if exit_code == 0:
            return "success", False

        if exit_code == 1:
            stderr_text = stderr.decode("utf-8", errors="replace").lower()
            stdout_text = stdout.decode("utf-8", errors="replace").lower()
            result_text = (json_output.get("result", "") if json_output else "").lower()
            is_rate_limit = any(
                pattern in text
                for pattern in _RATE_LIMIT_PATTERNS
                for text in [stderr_text, stdout_text, result_text]
            )
            is_high_usage = (json_output.get("session_usage_percent", 0) if json_output else 0) >= 80
            if is_rate_limit or is_high_usage:
                return "rate_limit_retry", True

        return "failed", False

    def _write_debug_log(
        self,
        task_id: str,
        exit_code: int,
        duration_ms: int,
        stdout: bytes,
        stderr: bytes,
    ) -> None:
        """Write raw subprocess output to last_claude_output.log for inspection."""
        log_path = self.pool_file.parent / "last_claude_output.log"
        with open(log_path, "w", encoding="utf-8") as _f:
            _f.write(f"=== task {task_id} | exit_code {exit_code} | {duration_ms} ms ===\n")
            _f.write("--- stdout ---\n")
            _f.write(stdout.decode("utf-8", errors="replace") if stdout else "(empty)\n")
            _f.write("--- stderr ---\n")
            _f.write(stderr.decode("utf-8", errors="replace") if stderr else "(empty)\n")

    def _write_debug_log_with_result(
        self,
        task_id: str,
        exit_code: int,
        duration_ms: int,
        result: dict,
    ) -> None:
        """Write CLIManager result to last_claude_output.log for inspection."""
        import json
        log_path = self.pool_file.parent / "last_claude_output.log"
        with open(log_path, "w", encoding="utf-8") as _f:
            _f.write(f"=== task {task_id} | exit_code {exit_code} | {duration_ms} ms ===\n")
            _f.write("--- result ---\n")
            _f.write(json.dumps(result, indent=2, default=str))

    def _build_command(self, task: Task, session_id: str | None) -> list[str]:
        """Assemble the claude CLI command for *task*, optionally resuming *session_id*."""
        extra: list[str] = []
        if session_id:
            logger.info(f"Resuming session {session_id} for directory {task.directory}")
            extra.extend(["--resume", session_id])
        extra.extend(task.args)
        return build_cmd_from_profile("claude", "claude_pool", task.prompt, extra_flags=extra)

    def _find_session_for_directory(self, directory: Path, bucket_id: str) -> str | None:
        """Find the most recent session_id for tasks in the same directory and bucket."""
        matching_tasks = [
            t
            for t in self.pool.tasks
            if (
                t.status == "success"
                and t.directory == directory
                and t.bucket_id == bucket_id
                and t.session_id is not None
            )
        ]

        if not matching_tasks:
            return None

        matching_tasks.sort(key=lambda t: t.created_at, reverse=True)
        return matching_tasks[0].session_id

    async def _load_cli_commands(self) -> list[CliCommand]:
        """Load CliCommand rows from the database (returns [] on any error)."""
        try:
            from .database import DatabaseManager
            db = DatabaseManager(self.pool_file)
            rows = await db.get_all_cli_commands()
            return [CliCommand.from_dict(r) for r in rows]
        except Exception as e:
            logger.debug("Could not load CLI commands from DB: %s", e)
            return []

    def _handle_rate_limit(
        self,
        task: Task,
        current_cli: CliCommand | None,
        cli_commands: list[CliCommand],
    ) -> None:
        """Try CLI fallback routing first; suspend pool only if all CLIs exhausted."""
        if current_cli and cli_commands:
            next_chain = resolve_command_chain(
                task.kind, None, cli_commands, exclude_ids=[current_cli.id]
            )
            if next_chain:
                next_cli = next_chain[0]
                task.rerouted_from = current_cli.id
                task.rerouted_to = next_cli.id
                task.cli_id = next_cli.id
                task.status = "pending"
                logger.info(
                    "Rate limit on %s; rerouting task %s to %s (no delay)",
                    current_cli.id, task.id, next_cli.id,
                )
                return
        # No fallback available — fall back to global pool suspension
        self._on_rate_limit_detected(task)

    async def execute_task(self, task: Task) -> None:
        """Execute a single task using asyncio subprocess."""
        # Load CLI commands BEFORE _save_state to avoid the DB seeding side-effect:
        # _save_state → save_pool → db.init() seeds the 'claude' CLI, causing
        # _load_cli_commands() to find a non-empty DB and ignore the monkey-patched
        # _build_command in tests that haven't configured any CLI commands.
        cli_commands = await self._load_cli_commands()

        self.current_task = task
        task.status = "running"
        self._notify_update(task)
        self._save_state()

        if self.skip_requested:
            logger.info(f"Skipping task {task.id} as requested")
            self.skip_requested = False
            task.status = "skipped"
            task.json_output = {"result": "Task skipped by user"}
            self.current_task = None
            self._notify_update(task)
            self._save_state()
            return

        # Chat-level concurrency control
        chat_lock = None
        if task.chat_id is not None:
            chat_lock = self._chat_locks.setdefault(task.chat_id, asyncio.Lock())
            await chat_lock.acquire()

        try:
            start_time = time.time()
            logger.info(f"Executing task {task.id}: {task.prompt[:50]}...")
            logger.info(f"Working directory: {task.directory}")

            stdout = b""
            stderr = b""
            exit_code = -1

            current_cli: CliCommand | None = None

            try:
                session_id = self._find_session_for_directory(task.directory, task.bucket_id)
                if cli_commands:
                    current_cli = resolve_command(task.kind, task.cli_id, cli_commands)
                    task.session_id = session_id
                    cmd = build_command(task, current_cli)
                else:
                    cmd = self._build_command(task, session_id)
            except NoCLICommandError as e:
                logger.warning("No CLI command available for task %s: %s", task.id, e)
                task.status = "failed"
                task.exit_code = -1
                task.duration_ms = int((time.time() - start_time) * 1000)
                task.json_output = {"result": str(e), "parse_error": True}
                self._notify_update(task)
                self._save_state()
                self.current_task = None
                return

            try:
                import shlex as _shlex
                logger.info("[claude/pool] CLI command: %s", _shlex.join(cmd))

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(task.directory),
                )
                self._running_processes[task.id] = process

                stdout, stderr = await process.communicate()
                exit_code = process.returncode
                logger.info("[claude/pool] exit_code=%d stdout=%r stderr=%r",
                            exit_code, stdout[:2000], stderr[:500])

            except Exception as e:
                logger.error(f"Error spawning subprocess for task {task.id}: {e}")
                task.status = "failed"
                task.exit_code = -1
                task.duration_ms = int((time.time() - start_time) * 1000)
                task.json_output = {"result": f"Execution error: {str(e)}", "parse_error": True}
                self._running_processes.pop(task.id, None)
                self._notify_update(task)
                self._save_state()
                self.current_task = None
                return

            task.duration_ms = int((time.time() - start_time) * 1000)
            task.exit_code = exit_code
            self._running_processes.pop(task.id, None)

            self._write_debug_log(task.id, exit_code, task.duration_ms, stdout, stderr)

            if task.status == "stopped":
                self._notify_update(task)
                await self._save_state_async()
                self.current_task = None
                return

            parser_type = current_cli.parser if current_cli else "claude_json"
            json_output = parse_output(stdout, parser_type) if stdout else None
            task.json_output = json_output

            status, is_rate_limit = self._classify_exit(exit_code, stdout, stderr, json_output)
            task.status = status

            if status == "success":
                sid = (json_output or {}).get("session_id")
                if sid:
                    task.session_id = sid
                    logger.info(f"Persisted session_id for task {task.id}: {sid}")
                usage = (json_output or {}).get("session_usage_percent", 0)
                if usage >= 80:
                    logger.warning(
                        f"Task {task.id} succeeded but session usage is {usage}% — "
                        "next rate limit will use shorter initial backoff"
                    )
                logger.info(f"Task {task.id} completed successfully")

                # Spawn subtasks (depth limit: subtasks may not spawn sub-subtasks)
                raw_subtasks = (json_output or {}).get("subtasks", [])
                if raw_subtasks and task.parent_task_id is None:
                    specs = raw_subtasks[:MAX_SUBTASKS_PER_TASK]
                    created: list[Task] = []
                    for spec in specs:
                        if not isinstance(spec, dict) or not spec.get("prompt"):
                            continue
                        try:
                            resolved_cli = resolve_command("subtask", spec.get("cli_id"), cli_commands)
                            resolved_cli_id: str | None = resolved_cli.id
                        except NoCLICommandError:
                            resolved_cli_id = None
                        subtask = Task(
                            id=_make_subtask_id(),
                            prompt=spec["prompt"],
                            directory=task.directory,
                            kind="subtask",
                            parent_task_id=task.id,
                            parent_message_id=task.parent_message_id,
                            project_id=task.project_id,
                            chat_id=task.chat_id,
                            model=spec.get("model") or "",
                            cli_id=resolved_cli_id,
                            bucket_id=task.bucket_id,
                            priority=task.priority,
                        )
                        self.pool.tasks.append(subtask)
                        created.append(subtask)
                    if created:
                        logger.info("Spawned %d subtasks for task %s", len(created), task.id)
            elif is_rate_limit:
                logger.warning(f"Task {task.id} hit rate limit (exit_code={exit_code})")
                self._handle_rate_limit(task, current_cli, cli_commands)
            else:
                logger.error(
                    f"Task {task.id} failed (exit_code={exit_code}): "
                    f"{stderr.decode('utf-8', errors='replace')[:200]}"
                )

            self._notify_update(task)
            self._save_state()
            self.current_task = None
        finally:
            if chat_lock is not None:
                chat_lock.release()

    def _on_rate_limit_detected(self, task: Task) -> None:
        """Handle global pool suspension when a rate limit is detected."""
        wait_seconds = 1800  # fixed 30-minute retry interval
        self.pool.retry_count += 1
        task.status = "rate_limit_retry"
        self.pool.suspended_until = datetime.now() + timedelta(seconds=wait_seconds)

        logger.info(
            f"Rate limit detected; pool suspended for {wait_seconds}s "
            f"(retry #{self.pool.retry_count}, resuming at {self.pool.suspended_until:%H:%M:%S})"
        )

        self._save_state()

    async def wait_for_suspension(self) -> None:
        """Sleep until the pool suspension expires, with periodic should_stop checks."""
        while not self.should_stop and self.pool.is_suspended:
            remaining = self.pool.suspension_remaining
            if remaining <= 0:
                break
            await asyncio.sleep(min(1, remaining))

    async def _handle_initial_suspension(self) -> bool:
        """Wait out any suspension that was active when the pool was loaded."""
        if self.pool.is_suspended:
            logger.info(
                f"Pool was suspended on load, waiting until {self.pool.suspended_until:%H:%M:%S}"
            )
            await self.wait_for_suspension()
            if self.should_stop:
                return True
            self.pool.suspended_until = None
        return False

    async def run_pool(self) -> None:
        """Run tasks with concurrency support."""
        if self.max_concurrent > 1:
            await self.run_pool_concurrent()
        else:
            await self.run_pool_sequential()

    async def run_pool_sequential(self) -> None:
        """Run all pending tasks sequentially with global rate-limit suspension."""
        logger.info("Starting task pool execution (sequential mode)")

        if await self._handle_initial_suspension():
            return

        while not self.should_stop:
            self.check_pool_updates()

            if self.pool.is_suspended:
                resume_time = self.pool.suspended_until
                logger.info(
                    f"Pool suspended, resuming at {resume_time:%H:%M:%S} "
                    f"({self.pool.suspension_remaining:.0f}s remaining)"
                )
                await self.wait_for_suspension()
                if self.should_stop:
                    break

                logger.info("Pool suspension ended, resuming execution")
                self.pool.suspended_until = None
                await self._save_state_async()

            retry_task = self._find_rate_limit_task()
            if retry_task:
                logger.info(f"Retrying rate-limited task: {retry_task.id}")
                await self.execute_task(retry_task)

                if retry_task.status == "success":
                    self.pool.retry_count = 0
                    self.pool.suspended_until = None
                    logger.info("Retry task succeeded — pool retry counter reset to 0")
                continue

            if self.pool.retry_count > 0:
                self.pool.retry_count = 0
                logger.info("No rate-limit task after suspension — retry counter reset to 0")
                await self._save_state_async()

            while self.paused and not self.should_stop:
                await asyncio.sleep(1)

            if self.should_stop:
                break

            pending_tasks = [t for t in self.pool.tasks if t.status == "pending"]

            if not pending_tasks:
                await asyncio.sleep(1)
                continue

            pending_tasks.sort(key=lambda t: (t.priority, t.created_at))

            task = pending_tasks[0]
            await self.execute_task(task)

            if self.should_stop:
                break

        logger.info("Task pool execution finished")
        self._save_state()

    async def run_pool_concurrent(self) -> None:
        """Run up to N tasks concurrently with global rate-limit blocking."""
        logger.info(f"Starting task pool execution (concurrent mode, max {self.max_concurrent})")

        if await self._handle_initial_suspension():
            return

        while not self.should_stop:
            self.check_pool_updates()

            if self.pool.is_suspended:
                resume_time = self.pool.suspended_until
                logger.info(
                    f"Pool suspended (blocking all {self.semaphore.active_count} active tasks), "
                    f"resuming at {resume_time:%H:%M:%S} "
                    f"({self.pool.suspension_remaining:.0f}s remaining)"
                )
                await self.wait_for_suspension()
                if self.should_stop:
                    break

                logger.info("Pool suspension ended, resuming execution")
                self.pool.suspended_until = None
                await self._save_state_async()

            while self.paused and not self.should_stop:
                await asyncio.sleep(1)

            if self.should_stop:
                break

            retry_task = self._find_rate_limit_task()

            if not retry_task and self.pool.retry_count > 0:
                self.pool.retry_count = 0
                logger.info("No rate-limit task after suspension — retry counter reset to 0")
                await self._save_state_async()

            pending_tasks = [t for t in self.pool.tasks if t.status == "pending"]

            if retry_task:
                tasks_to_execute = [retry_task]
                available_slots = self.max_concurrent - len(tasks_to_execute)
                if available_slots > 0:
                    pending_tasks.sort(key=lambda t: (t.priority, t.created_at))
                    tasks_to_execute.extend(pending_tasks[:available_slots])
            else:
                pending_tasks.sort(key=lambda t: (t.priority, t.created_at))
                tasks_to_execute = pending_tasks[: self.max_concurrent]

            if not tasks_to_execute:
                await asyncio.sleep(1)
                continue

            coros = [
                self.semaphore.execute_with_limit(self.execute_task(task))
                for task in tasks_to_execute
            ]

            logger.debug(f"Executing {len(tasks_to_execute)} tasks concurrently")
            await asyncio.gather(*coros, return_exceptions=False)

            if retry_task and retry_task.status == "success":
                self.pool.retry_count = 0
                logger.info("Retry task succeeded — pool retry counter reset to 0")

        logger.info("Task pool execution finished")
        self._save_state()

    def _find_rate_limit_task(self) -> Task | None:
        """Find the task currently in rate_limit_retry status."""
        for t in self.pool.tasks:
            if t.status == "rate_limit_retry":
                return t
        return None

    def check_pool_updates(self) -> None:
        """Detect external DB changes and merge them into the in-memory pool."""
        try:
            new_pool = load_pool(self.pool_file)
        except Exception as e:
            logger.error(f"Error reading pool DB for update check: {e}")
            return

        new_task_ids = {t.id for t in new_pool.tasks}
        new_meta_hash = _meta_hash(new_pool)

        if new_task_ids == self._last_known_task_ids and new_meta_hash == self._last_pool_meta_hash:
            return

        logger.info("External DB change detected, merging updates...")

        self._merge_new_tasks(new_pool)

        self.pool.retry_count = new_pool.retry_count
        if not self.pool.is_suspended:
            if new_pool.suspended_until is not None and new_pool.is_suspended:
                self.pool.suspended_until = new_pool.suspended_until

        self._last_known_task_ids = new_task_ids
        self._last_pool_meta_hash = new_meta_hash

    def _merge_new_tasks(self, new_pool: PoolState) -> bool:
        """Merge tasks from *new_pool* into the in-memory pool."""
        existing_tasks = {t.id: t for t in self.pool.tasks}
        changes_detected = False

        for new_task in new_pool.tasks:
            if new_task.id not in existing_tasks:
                self.pool.tasks.append(new_task)
                logger.info(f"Added new task: {new_task.id}")
                changes_detected = True
                if self.on_task_update:
                    self.on_task_update(new_task)
                removed = cleanup_old_tasks(self.pool, max_age_hours=48)
                if removed > 0:
                    logger.info(f"Automatically cleaned up {removed} old completed tasks")
            else:
                existing = existing_tasks[new_task.id]
                if new_task.status == "pending" and existing.status != "pending":
                    existing.status = new_task.status
                    existing.exit_code = new_task.exit_code
                    existing.duration_ms = new_task.duration_ms
                    existing.json_output = new_task.json_output
                    existing.retry_count = new_task.retry_count
                    logger.info(
                        f"Task {new_task.id} was reset to pending (retry #{existing.retry_count})"
                    )
                    changes_detected = True
                    if self.on_task_update:
                        self.on_task_update(existing)

        return changes_detected

    def _notify_update(self, task: Task) -> None:
        """Notify callback of task update, passing bucket_id in the task object."""
        if self.on_task_update:
            self.on_task_update(task)

    def pause(self) -> None:
        """Pause execution."""
        self.paused = True
        logger.info("Execution paused")

    def resume(self) -> None:
        """Resume execution."""
        self.paused = False
        logger.info("Execution resumed")

    def skip_current(self) -> None:
        """Request to skip the current task."""
        if self.current_task:
            logger.info(f"Skip requested for task {self.current_task.id}")
            self.skip_requested = True
        else:
            logger.warning("No current task to skip")

    def reset_task_for_retry(self, task: Task) -> None:
        """Reset *task* back to pending and increment its retry counter."""
        task.status = "pending"
        task.exit_code = None
        task.duration_ms = None
        task.json_output = None
        task.retry_count += 1
        logger.info(f"Task {task.id} reset to pending (retry #{task.retry_count})")
        self._save_state()

    async def stop_task(self, task_id: str) -> bool:
        """Send SIGTERM (then SIGKILL) to the subprocess for *task_id*."""
        task = next((t for t in self.pool.tasks if t.id == task_id), None)
        if task is None or task.status != "running":
            return False

        task.status = "stopped"
        logger.info(f"Hard-stopping task {task_id}")

        process = self._running_processes.get(task_id)
        if process is not None:
            try:
                process.terminate()
                await asyncio.sleep(5)
                if process.returncode is None:
                    process.kill()
            except ProcessLookupError:
                pass

        self._notify_update(task)
        await self._save_state_async()
        return True

    def delete_task(self, task_id: str) -> bool:
        """Delete a task from the pool."""
        for i, task in enumerate(self.pool.tasks):
            if task.id == task_id:
                del self.pool.tasks[i]
                logger.info(f"Deleted task {task_id}")
                self._save_state()
                return True
        return False

    def delete_bucket(self, bucket_id: str) -> int:
        """Delete a chat bucket and all its tasks."""
        if bucket_id == "main":
            raise ValueError("The 'main' bucket cannot be deleted")

        if self.current_task and self.current_task.bucket_id == bucket_id:
            logger.info(
                f"Running task {self.current_task.id} belongs to bucket {bucket_id}; "
                "requesting skip before deletion"
            )
            self.skip_requested = True

        before = len(self.pool.tasks)
        self.pool.tasks = [t for t in self.pool.tasks if t.bucket_id != bucket_id]
        removed = before - len(self.pool.tasks)

        if bucket_id in self.pool.buckets:
            del self.pool.buckets[bucket_id]

        logger.info(f"Deleted bucket {bucket_id} ({removed} tasks removed)")
        self._save_state()
        return removed
