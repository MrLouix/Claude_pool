"""Task executor for running Claude Code CLI commands."""

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .concurrency import TaskSemaphore
from .models import PoolState, Task
from .parser import parse_claude_output
from .storage import cleanup_old_tasks, load_pool, save_pool

logger = logging.getLogger(__name__)

_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "session limit",
    "quota exceeded",
    "you've hit your limit",
    "hit your limit",
    "rate limited",
    "too many requests",
)


class TaskExecutor:
    """Executes tasks from a pool sequentially with global rate-limit handling."""

    def __init__(
        self,
        pool_file: Path,
        on_task_update: Callable[[Task], None] | None = None,
        max_concurrent: int = 1,
        install_signal_handlers: bool = True,
    ):
        """Initialize the executor.

        Args:
            pool_file: Path to pool.json
            on_task_update: Optional callback called when a task is updated
            max_concurrent: Maximum number of tasks to run concurrently (default: 1)
            install_signal_handlers: Whether to install SIGINT/SIGTERM handlers.
                Set to False when running inside a server (e.g. uvicorn) that
                manages its own signal handling.
        """
        self.pool_file = pool_file
        self.pool = PoolState(pool_file=pool_file)
        self.current_task: Task | None = None
        self.paused = False
        self.should_stop = False
        self.skip_requested = False
        self.on_task_update = on_task_update
        self.last_pool_mtime = pool_file.stat().st_mtime if pool_file.exists() else 0
        self._last_save_mtime = 0.0  # Track our own saves to avoid self-triggered reloads

        # Concurrency control
        self.max_concurrent = max_concurrent
        self.semaphore = TaskSemaphore(max_concurrent)
        self._save_lock = asyncio.Lock()  # Thread-safe state saving

        # Registry of running subprocesses, keyed by task_id.
        # Populated by execute_task(); consulted by stop_task().
        self._running_processes: dict[str, asyncio.subprocess.Process] = {}

        # Setup signal handlers (skip when embedded in a server like uvicorn)
        if install_signal_handlers:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.should_stop = True
        self._save_state()

    def _do_save(self) -> None:
        """Write pool to disk and update the self-write mtime stamp."""
        save_pool(self.pool)
        if self.pool_file.exists():
            self._last_save_mtime = os.path.getmtime(str(self.pool_file))
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
        """Load tasks and pool state from pool file."""
        try:
            self.pool = load_pool(self.pool_file)
            # Ensure pool_file is preserved after load
            self.pool.pool_file = self.pool_file
            logger.info(f"Loaded {len(self.pool.tasks)} tasks from {self.pool_file}")

            # Automatic cleanup of old tasks (older than 48 hours)
            removed = cleanup_old_tasks(self.pool, max_age_hours=48)
            if removed > 0:
                logger.info(f"Automatically cleaned up {removed} old completed tasks")
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
        """Map subprocess exit to (status_string, is_rate_limit).

        Returns:
            status: one of 'success', 'rate_limit_retry', 'failed'
            is_rate_limit: True when the exit signals a rate-limit event
        """
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

    def _build_command(self, task: "Task", session_id: str | None) -> list[str]:
        """Assemble the claude CLI command for *task*, optionally resuming *session_id*."""
        cmd = [
            "claude",
            "-p",
            task.prompt,
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]
        if session_id:
            logger.info(f"Resuming session {session_id} for directory {task.directory}")
            cmd.extend(["--resume", session_id])
        cmd.extend(task.args)
        return cmd

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

    async def execute_task(self, task: Task) -> None:
        """Execute a single task.

        Args:
            task: Task to execute
        """
        self.current_task = task
        task.status = "running"
        self._notify_update(task)
        self._save_state()

        # Check if skip was requested before executing
        if self.skip_requested:
            logger.info(f"Skipping task {task.id} as requested")
            self.skip_requested = False
            task.status = "skipped"
            task.json_output = {"result": "Task skipped by user"}
            self.current_task = None
            self._notify_update(task)
            self._save_state()
            return

        start_time = time.time()

        logger.info(f"Executing task {task.id}: {task.prompt[:50]}...")
        logger.info(f"Working directory: {task.directory}")

        # Check for existing session in the same directory
        session_id = self._find_session_for_directory(task.directory, task.bucket_id)
        cmd = self._build_command(task, session_id)

        try:
            # Execute with timeout (30 minutes)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(task.directory),
            )
            self._running_processes[task.id] = process

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30 * 60)
            except asyncio.TimeoutError:
                logger.error(f"Task {task.id} timed out after 30 minutes")
                process.kill()
                await process.wait()
                task.status = "failed"
                task.exit_code = -1
                task.json_output = {"result": "Task timed out after 30 minutes"}
                task.duration_ms = int((time.time() - start_time) * 1000)
                self._notify_update(task)
                self._save_state()
                return

            task.exit_code = process.returncode
            task.duration_ms = int((time.time() - start_time) * 1000)

            self._write_debug_log(task.id, task.exit_code, task.duration_ms, stdout, stderr)

            # Parse output
            if stdout:
                task.json_output = parse_claude_output(stdout)
            else:
                task.json_output = {
                    "result": stderr.decode("utf-8", errors="replace")[:1000],
                    "parse_error": True,
                }

            if task.status == "stopped":
                # Hard-stopped externally — do not reclassify; preserve "stopped" status
                logger.info(f"Task {task.id} was hard-stopped; skipping status reclassification")
            else:
                # Determine status based on exit code
                new_status, is_rate_limit = self._classify_exit(
                    task.exit_code, stdout, stderr, task.json_output
                )
                task.status = new_status

                if new_status == "success":
                    logger.info(f"Task {task.id} completed successfully")
                    if task.json_output:
                        sid = task.json_output.get("session_id")
                        if sid:
                            task.session_id = sid
                            logger.info(f"Persisted session_id for task {task.id}: {sid}")
                    usage = task.json_output.get("session_usage_percent", 0)
                    if usage >= 80:
                        logger.warning(
                            f"Task {task.id} succeeded but session usage is {usage}% — "
                            f"next rate limit will use shorter initial backoff"
                        )
                elif is_rate_limit:
                    self._on_rate_limit_detected(task)
                else:
                    logger.error(f"Task {task.id} failed with exit code {task.exit_code}")

        except Exception as e:
            logger.error(f"Error executing task {task.id}: {e}")
            task.status = "failed"
            task.exit_code = -1
            task.duration_ms = int((time.time() - start_time) * 1000)
            task.json_output = {"result": f"Execution error: {str(e)}", "parse_error": True}
        finally:
            self._running_processes.pop(task.id, None)

        self._notify_update(task)
        self._save_state()
        self.current_task = None

    def _on_rate_limit_detected(self, task: Task) -> None:
        """Handle global pool suspension when a rate limit is detected.

        Args:
            task: Task that triggered the rate limit
        """
        self.pool.retry_count += 1
        task.status = "rate_limit_retry"

        # Fixed 1-hour backoff between retries
        wait_seconds = 3600

        self.pool.suspended_until = datetime.now() + timedelta(seconds=wait_seconds)

        logger.info(
            f"Rate limit detected; pool suspended for {wait_seconds}s "
            f"(retry #{self.pool.retry_count}, resuming at {self.pool.suspended_until:%H:%M:%S})"
        )

        self._save_state()

    async def wait_for_suspension(self) -> None:
        """Sleep until the pool suspension expires, with periodic should_stop checks.

        The TUI can reflect countdown via self.pool.suspension_remaining.
        """
        while not self.should_stop and self.pool.is_suspended:
            remaining = self.pool.suspension_remaining
            if remaining <= 0:
                break
            await asyncio.sleep(min(1, remaining))

    async def _handle_initial_suspension(self) -> bool:
        """Wait out any suspension that was active when the pool was loaded.

        Returns:
            True if should_stop was set during the wait (caller should return early).
        """
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
            # Check for new tasks in pool.json
            self.check_pool_updates()

            # If pool is currently suspended, wait for expiration
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

            # After suspension: retry the rate-limited task first
            retry_task = self._find_rate_limit_task()
            if retry_task:
                logger.info(f"Retrying rate-limited task: {retry_task.id}")
                await self.execute_task(retry_task)

                # If it succeeded, reset the global retry counter and clear suspension
                if retry_task.status == "success":
                    self.pool.retry_count = 0
                    self.pool.suspended_until = None
                    logger.info("Retry task succeeded — pool retry counter reset to 0")
                continue  # Loop back to check remaining tasks

            # No rate-limit task found after suspension — reset counter and fall through
            if self.pool.retry_count > 0:
                self.pool.retry_count = 0
                logger.info("No rate-limit task after suspension — retry counter reset to 0")
                await self._save_state_async()

            # Handle paused state (manual pause)
            while self.paused and not self.should_stop:
                await asyncio.sleep(1)

            if self.should_stop:
                break

            # Find next pending task
            pending_tasks = [t for t in self.pool.tasks if t.status == "pending"]

            if not pending_tasks:
                # No pending tasks - wait and check again for file updates
                await asyncio.sleep(1)
                continue

            # Sort pending tasks by (priority ASC, created_at ASC), recalculated each iteration
            pending_tasks.sort(key=lambda t: (t.priority, t.created_at))

            # Execute next pending task
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
            # Check for new tasks
            self.check_pool_updates()

            # If pool is currently suspended, block ALL tasks
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

            # Handle paused state
            while self.paused and not self.should_stop:
                await asyncio.sleep(1)

            if self.should_stop:
                break

            # Get pending tasks and retry task
            retry_task = self._find_rate_limit_task()

            # If the timer expired but no rate-limit task exists anymore (user deleted it),
            # reset the global counter so the pool is fully unblocked.
            if not retry_task and self.pool.retry_count > 0:
                self.pool.retry_count = 0
                logger.info("No rate-limit task after suspension — retry counter reset to 0")
                await self._save_state_async()

            pending_tasks = [t for t in self.pool.tasks if t.status == "pending"]

            if retry_task:
                # Retry task takes priority
                tasks_to_execute = [retry_task]
                # Then add more pending tasks up to max_concurrent
                available_slots = self.max_concurrent - len(tasks_to_execute)
                if available_slots > 0:
                    pending_tasks.sort(key=lambda t: (t.priority, t.created_at))
                    tasks_to_execute.extend(pending_tasks[:available_slots])
            else:
                # Execute pending tasks up to max_concurrent
                pending_tasks.sort(key=lambda t: (t.priority, t.created_at))
                tasks_to_execute = pending_tasks[: self.max_concurrent]

            if not tasks_to_execute:
                # No tasks to execute, wait and check again
                await asyncio.sleep(1)
                continue

            # Create execution coroutines with semaphore protection
            coros = [
                self.semaphore.execute_with_limit(self.execute_task(task))
                for task in tasks_to_execute
            ]

            # Execute all coroutines concurrently
            logger.debug(f"Executing {len(tasks_to_execute)} tasks concurrently")
            await asyncio.gather(*coros, return_exceptions=False)

            # Check if retry task succeeded
            if retry_task and retry_task.status == "success":
                self.pool.retry_count = 0
                logger.info("Retry task succeeded — pool retry counter reset to 0")

        logger.info("Task pool execution finished")
        self._save_state()

    def _find_rate_limit_task(self) -> Task | None:
        """Find the task currently in rate_limit_retry status.

        Returns:
            The task or None if no rate-limit task exists
        """
        for t in self.pool.tasks:
            if t.status == "rate_limit_retry":
                return t
        return None

    def check_pool_updates(self) -> bool:
        """Check if pool.json has been modified by an external source and reload if needed.

        Ignores modifications made by our own _save_state() to prevent self-triggered reloads.

        Returns:
            True if pool was reloaded, False otherwise
        """
        try:
            if not self.pool_file.exists():
                return False

            current_mtime = os.path.getmtime(str(self.pool_file))

            # Ignore our own saves — only react to external modifications
            if current_mtime <= self._last_save_mtime:
                return False

            # Allow a small debounce window for our own saves (filesystem mtime granularity)
            if current_mtime - self._last_save_mtime < 0.1:
                return False

            self.last_pool_mtime = current_mtime
            logger.info("Pool file modified externally, reloading tasks...")
            try:
                new_pool = load_pool(self.pool_file)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.error(f"Invalid pool.json format: {e}")
                return False

            self._merge_new_tasks(new_pool)

            # Preserve pool metadata from the file, but keep in-memory
            # suspended_until if the pool is currently suspended (an external
            # edit must not erase a suspension computed by _on_rate_limit_detected)
            self.pool.retry_count = new_pool.retry_count
            if not self.pool.is_suspended:
                # Only reload suspended_until from file if it's still in the future.
                # If it's expired, don't reload a stale date — keep it cleared.
                if new_pool.suspended_until is not None and new_pool.is_suspended:
                    self.pool.suspended_until = new_pool.suspended_until

            # Save back to file to persist auto-generated IDs and initialized fields
            self._save_state()

            return True
        except Exception as e:
            logger.error(f"Error checking pool updates: {e}")
        return False

    def _merge_new_tasks(self, new_pool: "PoolState") -> bool:
        """Merge tasks from *new_pool* into the in-memory pool.

        Adds genuinely new tasks and resets tasks that were set back to pending
        in the file.  Triggers cleanup after each new task is added.

        Returns:
            True if any task was added or reset.
        """
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

    def reset_task_for_retry(self, task: "Task") -> None:
        """Reset *task* back to pending and increment its retry counter.

        Args:
            task: Task to reset (must be in a terminal status: failed or success).
        """
        task.status = "pending"
        task.exit_code = None
        task.duration_ms = None
        task.json_output = None
        task.retry_count += 1
        logger.info(f"Task {task.id} reset to pending (retry #{task.retry_count})")
        self._save_state()

    async def stop_task(self, task_id: str) -> bool:
        """Send SIGTERM (then SIGKILL) to the subprocess for *task_id*.

        Sets task.status to 'stopped' and persists state.
        Returns True if the task was found and signalled, False otherwise.
        """
        task = next((t for t in self.pool.tasks if t.id == task_id), None)
        if task is None or task.status != "running":
            return False

        # Mark stopped immediately so execute_task() skips status reclassification
        task.status = "stopped"
        logger.info(f"Hard-stopping task {task_id}")

        process = self._running_processes.get(task_id)
        if process is not None:
            try:
                process.terminate()  # SIGTERM — polite shutdown
                await asyncio.sleep(5)
                if process.returncode is None:
                    process.kill()  # SIGKILL — force kill
            except ProcessLookupError:
                pass  # process already exited before we could signal it

        self._notify_update(task)
        await self._save_state_async()
        return True

    def delete_task(self, task_id: str) -> bool:
        """Delete a task from the pool.

        Args:
            task_id: ID of task to delete

        Returns:
            True if task was deleted, False if not found
        """
        for i, task in enumerate(self.pool.tasks):
            if task.id == task_id:
                del self.pool.tasks[i]
                logger.info(f"Deleted task {task_id}")
                self._save_state()
                return True
        return False

    def delete_bucket(self, bucket_id: str) -> int:
        """Delete a chat bucket and all its tasks.

        If the currently running task belongs to the bucket, a skip is
        requested so the executor loop abandons it on the next iteration.

        Args:
            bucket_id: ID of the bucket to delete.

        Returns:
            Number of tasks removed.

        Raises:
            ValueError: When bucket_id is "main" (immutable).
        """
        if bucket_id == "main":
            raise ValueError("The 'main' bucket cannot be deleted")

        # Ask the executor to abandon the running task if it belongs to this bucket
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
