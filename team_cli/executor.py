"""Task executor for running Claude Code CLI commands."""

import asyncio
import logging
import signal
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from .concurrency import TaskSemaphore
from .models import CLIConfig, PoolState, Project, ProjectMessage, Task
from .parser import parse_claude_output
from .storage import build_context, cleanup_old_tasks, load_pool, save_pool

logger = logging.getLogger(__name__)

MAX_RETRIES = 5

# Rate limit patterns (used by both TaskExecutor and CLI executors)
_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "session limit",
    "quota exceeded",
    "you've hit your limit",
    "hit your limit",
    "rate limited",
    "too many requests",
)


class NoCLIAvailableError(Exception):
    """Raised when no CLI executor is available (all rate-limited or excluded)."""


class BaseCLIExecutor(ABC):
    """Abstract base class for CLI executors."""

    def __init__(self, config: CLIConfig):
        self.config = config

    @abstractmethod
    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run the CLI and return parsed output dict. Raises on fatal error."""
        ...

    @abstractmethod
    def check_rate_limit(self) -> bool:
        """Return True if this CLI is currently rate-limited."""
        ...

    def get_model_list(self) -> list[str]:
        """Return the list of available models from the config."""
        return self.config.models


class ClaudeExecutor(BaseCLIExecutor):
    """Executor for Anthropic Claude CLI."""

    def __init__(self, config: CLIConfig):
        super().__init__(config)
        self._last_exit_code: int | None = None
        self._last_stderr: str = ""
        self._last_stdout: str = ""

    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run Claude CLI and return parsed output dict."""
        import json
        import tempfile
        import os

        # Build command as specified
        cmd = [
            self.config.path,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--structured-output",
            "--model",
            model,
        ]
        
        # Add context if available (for multi-turn conversations)
        ctx_file = None
        if context:
            try:
                ctx_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", dir=directory, delete=False
                )
                json.dump(context, ctx_file)
                ctx_file.close()
                cmd.extend(["--context", ctx_file.name])
            except Exception:
                if ctx_file:
                    try:
                        os.unlink(ctx_file.name)
                    except OSError:
                        pass
                ctx_file = None
        
        # Add extra args from config if present
        if self.config.args_template:
            # For now, just append any extra template args
            # This is a placeholder for future expansion
            pass

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,  # 30 minutes
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            self._last_stdout = result.stdout
            self._last_stderr = result.stderr

            # Parse output
            if result.stdout:
                return parse_claude_output(result.stdout.encode("utf-8"))
            else:
                return {
                    "result": result.stderr or "No output",
                    "parse_error": True,
                }
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            self._last_stderr = "Task timed out after 30 minutes"
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            self._last_stderr = str(e)
            return {"result": f"Execution error: {str(e)}", "parse_error": True}
        finally:
            # Clean up temp context file
            if ctx_file:
                try:
                    os.unlink(ctx_file.name)
                except OSError:
                    pass

    def check_rate_limit(self) -> bool:
        """Check if the last execution hit a rate limit."""
        if self._last_exit_code == 1 and self._last_stderr:
            stderr_lower = self._last_stderr.lower()
            return any(pattern in stderr_lower for pattern in _RATE_LIMIT_PATTERNS)
        return False


class MistralExecutor(BaseCLIExecutor):
    """Executor for Mistral CLI."""

    def __init__(self, config: CLIConfig):
        super().__init__(config)
        self._last_exit_code: int | None = None
        self._last_stdout: str = ""
        self._last_stderr: str = ""

    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run Mistral CLI and return parsed output dict."""
        import json
        import tempfile
        import os

        cmd = [self.config.path, "--prompt", prompt]
        
        # Serialize context to temp JSON file
        ctx_file = None
        if context:
            try:
                ctx_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", dir=directory, delete=False
                )
                json.dump(context, ctx_file)
                ctx_file.close()
                cmd.extend(["--context", ctx_file.name])
            except Exception:
                if ctx_file:
                    try:
                        os.unlink(ctx_file.name)
                    except OSError:
                        pass
                ctx_file = None

        if model:
            cmd.extend(["--model", model])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            self._last_stdout = result.stdout
            self._last_stderr = result.stderr

            # Parse and normalize output
            if result.stdout:
                try:
                    parsed = json.loads(result.stdout)
                    # Normalize to Claude-like shape
                    normalized = {
                        "result": parsed.get("result", ""),
                        "model": parsed.get("model", model),
                        "usage": parsed.get("usage", {}),
                    }
                    # Preserve any other keys
                    for key, value in parsed.items():
                        if key not in normalized:
                            normalized[key] = value
                    return normalized
                except json.JSONDecodeError:
                    return {
                        "result": result.stdout,
                        "parse_error": True,
                    }
            else:
                return {
                    "result": result.stderr or "No output",
                    "parse_error": True,
                }
        finally:
            # Clean up temp file
            if ctx_file and os.path.exists(ctx_file.name):
                try:
                    os.unlink(ctx_file.name)
                except OSError:
                    pass

    def check_rate_limit(self) -> bool:
        """Check if the last execution hit a rate limit."""
        if self._last_exit_code != 0:
            output_text = (self._last_stdout + self._last_stderr).lower()
            return "rate" in output_text or "429" in output_text
        return False


class GenericCLIExecutor(BaseCLIExecutor):
    """Executor for custom CLIs configured via clis.json."""

    def __init__(self, config: CLIConfig):
        super().__init__(config)
        self._last_exit_code: int | None = None

    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run custom CLI using args_template formatting."""
        import json

        # Format args_template with available variables
        template = self.config.args_template or "{prompt}"
        formatted = template.format(
            prompt=prompt,
            context=json.dumps(context) if context else "",
            model=model,
        )
        
        # Split into argv
        import shlex
        try:
            cmd = [self.config.path] + shlex.split(formatted)
        except ValueError:
            # Fallback: split on whitespace
            cmd = [self.config.path] + formatted.split()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,
                cwd=directory,
            )
            self._last_exit_code = result.returncode

            # Return raw output
            if result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"result": result.stdout}
            else:
                return {"result": result.stderr or "No output"}
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            return {"result": f"Execution error: {str(e)}", "parse_error": True}

    def check_rate_limit(self) -> bool:
        """Custom CLIs are assumed not to rate-limit by default."""
        return False


class LlamaExecutor(GenericCLIExecutor):
    """Executor for Llama CLI (uses GenericCLIExecutor logic)."""
    pass


class GemmaExecutor(GenericCLIExecutor):
    """Executor for Gemma CLI (uses GenericCLIExecutor logic)."""
    pass


def create_executor(config: CLIConfig) -> BaseCLIExecutor:
    """Factory function to create a CLI executor based on config type."""
    if config.cli_type == "anthropic":
        return ClaudeExecutor(config)
    elif config.cli_type == "mistral":
        return MistralExecutor(config)
    elif config.cli_type == "llama":
        return LlamaExecutor(config)
    elif config.cli_type == "gemma":
        return GemmaExecutor(config)
    elif config.cli_type == "custom":
        return GenericCLIExecutor(config)
    elif config.cli_type in ("antigravity", "hermes", "opencode", "openai"):
        # These CLIs use GenericCLIExecutor with their args_template from config
        return GenericCLIExecutor(config)
    # Future: other CLI types
    raise ValueError(f"Unsupported CLI type: {config.cli_type}")


class CLIManager:
    """Manages multiple CLI executors with fallback logic."""

    def __init__(self, configs: list[CLIConfig]):
        self._executors: list[BaseCLIExecutor] = [
            create_executor(c) for c in configs if c.enabled
        ]

    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str = "",
    ) -> dict:
        """Try executors in order; skip any that are currently rate-limited.
        
        Raises:
            RuntimeError: If all CLI executors are rate-limited or failed.
        """
        # Determine model to use
        if not model:
            for executor in self._executors:
                if executor.config.default_model:
                    model = executor.config.default_model
                    break
            else:
                # Use first executor's first model if available
                if self._executors and self._executors[0].config.models:
                    model = self._executors[0].config.models[0]

        # Get available executors (not rate-limited)
        available = self.available_executors()
        if not available:
            raise RuntimeError("All CLI executors are rate-limited or failed")

        # Try each available executor
        for executor in available:
            result = executor.execute(prompt, context, directory, model)
            # Check if this executor is now rate-limited
            if executor.check_rate_limit():
                # Skip to next executor
                continue
            # Success
            return result

        # All available executors were tried but hit rate limits
        raise RuntimeError("All CLI executors are rate-limited or failed")

    def available_executors(self) -> list[BaseCLIExecutor]:
        """Return list of executors that are not currently rate-limited."""
        return [e for e in self._executors if not e.check_rate_limit()]

    def get_next_available_cli(self, exclude: list[str]) -> "BaseCLIExecutor | None":
        """Return the first executor that is not excluded and not rate-limited.

        Args:
            exclude: List of CLI names to skip (e.g. already-tried CLIs).

        Returns:
            The first eligible BaseCLIExecutor, or None if none found.
        """
        for executor in self._executors:
            if executor.config.name in exclude:
                continue
            if executor.check_rate_limit():
                continue
            return executor
        return None

    def get_executor_by_name(self, name: str) -> "BaseCLIExecutor | None":
        """Return the executor whose config.name matches *name*, or None."""
        for executor in self._executors:
            if executor.config.name == name:
                return executor
        return None


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
    context = await asyncio.to_thread(build_context, message, Path(db_path))

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
        result = await asyncio.to_thread(
            cli.execute,
            prompt=message.content,
            context=context,
            directory=project.directory,
            model=model or "",
        )

        if not cli.check_rate_limit():
            result["cli_used"] = cli.config.name
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


def _meta_hash(state: "PoolState") -> str:
    """Stable string representation of pool-level metadata for change detection."""
    return f"{state.retry_count}|{state.suspended_until}|{getattr(state, 'provider', 'claude')}"



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
        # DB-based change detection (replaces legacy mtime tracking)
        self._last_known_task_ids: set[str] = set()
        self._last_pool_meta_hash: str = ""

        # Concurrency control
        self.max_concurrent = max_concurrent
        self.semaphore = TaskSemaphore(max_concurrent)
        self._save_lock = asyncio.Lock()  # Thread-safe state saving

        # Registry of running subprocesses, keyed by task_id.
        # Populated by execute_task(); consulted by stop_task().
        self._running_processes: dict[str, asyncio.subprocess.Process] = {}

        # CLI Manager setup
        if cli_manager is not None:
            self.cli_manager = cli_manager
        else:
            # Fallback: create a default Claude-only manager
            from team_cli.models import CLIConfig
            from team_cli.executor import CLIManager
            fallback_config = CLIConfig(
                name="claude",
                path="claude",
                models=[],
                cli_type="anthropic",
            )
            self.cli_manager = CLIManager([fallback_config])

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
        """Write pool to DB and stamp tracking hashes to suppress self-triggered reloads."""
        save_pool(self.pool)
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
            # Ensure pool_file is preserved after load
            self.pool.pool_file = self.pool_file
            logger.info(f"Loaded {len(self.pool.tasks)} tasks from {self.pool_file}")

            # Automatic cleanup of old tasks (older than 48 hours)
            removed = cleanup_old_tasks(self.pool, max_age_hours=48)
            if removed > 0:
                logger.info(f"Automatically cleaned up {removed} old completed tasks")

            # Stamp tracking hashes so the first check_pool_updates call after load
            # does not treat the initial DB state as an external change.
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

        # Use CLIManager for multi-CLI support
        try:
            # Get model from task or use default
            effective_model = task.model if task.model else ""
            
            # Get context from task if available (for project messages)
            context = []
            if task.json_output and isinstance(task.json_output, dict):
                context = task.json_output.get("context", [])
            
            # Execute via CLIManager (runs in thread pool to avoid blocking)
            result = await asyncio.to_thread(
                self.cli_manager.execute,
                prompt=task.prompt,
                context=context,
                directory=str(task.directory),
                model=effective_model,
            )
            
            task.exit_code = 0  # CLIManager doesn't return exit code directly
            task.duration_ms = int((time.time() - start_time) * 1000)
            task.json_output = result
            
            # Write debug log with result
            self._write_debug_log_with_result(task.id, task.exit_code, task.duration_ms, result)
            
            # Determine status based on result
            if task.json_output and isinstance(task.json_output, dict):
                if task.json_output.get("parse_error"):
                    task.status = "failed"
                    logger.error(f"Task {task.id} failed with parse error")
                else:
                    task.status = "success"
                    logger.info(f"Task {task.id} completed successfully")
                    # Extract session_id if available
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
            else:
                task.status = "success"
                
        except RuntimeError as e:
            # All executors rate-limited or failed
            logger.error(f"Task {task.id} failed: all CLI executors are rate-limited or failed")
            task.status = "rate_limit_retry"
            task.exit_code = -1
            task.duration_ms = int((time.time() - start_time) * 1000)
            task.json_output = {"result": str(e)}
            self._on_rate_limit_detected(task)
            
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
            # Check for new tasks in pool.db
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

    def check_pool_updates(self) -> None:
        """Detect external DB changes and merge them into the in-memory pool.

        Compares the current DB state against the last-known task-ID set and
        pool-metadata hash.  Our own saves stamp those hashes via _do_save(),
        so they are never mistaken for external changes.
        """
        try:
            new_pool = load_pool(self.pool_file)
        except Exception as e:
            logger.error(f"Error reading pool DB for update check: {e}")
            return

        new_task_ids = {t.id for t in new_pool.tasks}
        new_meta_hash = _meta_hash(new_pool)

        if new_task_ids == self._last_known_task_ids and new_meta_hash == self._last_pool_meta_hash:
            return  # Nothing changed externally

        logger.info("External DB change detected, merging updates...")

        self._merge_new_tasks(new_pool)

        # Update pool metadata, but never erase an active suspension
        self.pool.retry_count = new_pool.retry_count
        if not self.pool.is_suspended:
            if new_pool.suspended_until is not None and new_pool.is_suspended:
                self.pool.suspended_until = new_pool.suspended_until

        # Stamp tracking state to reflect the DB we just read
        self._last_known_task_ids = new_task_ids
        self._last_pool_meta_hash = new_meta_hash

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
