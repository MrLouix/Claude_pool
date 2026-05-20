"""Task executor for running Claude Code CLI commands."""

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .models import PoolState, Task
from .parser import parse_claude_output
from .storage import cleanup_old_tasks, load_pool, save_pool

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes tasks from a pool sequentially with global rate-limit handling."""

    def __init__(self, pool_file: Path, on_task_update: Callable[[Task], None] | None = None):
        """Initialize the executor.

        Args:
            pool_file: Path to pool.json
            on_task_update: Optional callback called when a task is updated
        """
        self.pool_file = pool_file
        self.pool = PoolState(pool_file=pool_file)
        self.current_task: Task | None = None
        self.paused = False
        self.should_stop = False
        self.on_task_update = on_task_update
        self.last_pool_mtime = pool_file.stat().st_mtime if pool_file.exists() else 0
        self._last_save_mtime = 0.0  # Track our own saves to avoid self-triggered reloads

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.should_stop = True
        self._save_state()

    def _save_state(self) -> None:
        """Save current state to pool file."""
        try:
            save_pool(self.pool)
            # Track our own mtime so check_pool_updates doesn't trigger on our writes
            if self.pool_file.exists():
                self._last_save_mtime = os.path.getmtime(str(self.pool_file))
            logger.info("State saved successfully")
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

    def _find_session_for_directory(self, directory: Path) -> str | None:
        """Find the most recent session_id for tasks in a given directory.

        Searches for the most recently completed task with status == "success"
        in the same directory and with a non-None session_id.

        Args:
            directory: Directory to search for

        Returns:
            session_id if found, None otherwise
        """
        matching_tasks = [
            t for t in self.pool.tasks
            if (t.status == "success" and
                t.directory == directory and
                t.session_id is not None)
        ]

        if not matching_tasks:
            return None

        # Sort by created_at descending (most recent first)
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

        start_time = time.time()

        logger.info(f"Executing task {task.id}: {task.prompt[:50]}...")
        logger.info(f"Working directory: {task.directory}")

        # Check for existing session in the same directory
        session_id = self._find_session_for_directory(task.directory)

        # Build command
        cmd = [
            "claude",
            "-p",
            task.prompt,
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]

        # Add session resume if one exists
        if session_id:
            logger.info(f"Resuming session {session_id} for directory {task.directory}")
            cmd.extend(["--resume", session_id])

        cmd.extend(task.args)

        try:
            # Execute with timeout (30 minutes)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(task.directory),
            )

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

            # Parse output
            if stdout:
                task.json_output = parse_claude_output(stdout)
            else:
                task.json_output = {
                    "result": stderr.decode("utf-8", errors="replace")[:1000],
                    "parse_error": True,
                }

            # Determine status based on exit code
            if task.exit_code == 0:
                task.status = "success"
                logger.info(f"Task {task.id} completed successfully")

                # Extract and persist session_id if present
                if task.json_output:
                    session_id = task.json_output.get("session_id")
                    if session_id:
                        task.session_id = session_id
                        logger.info(f"Persisted session_id for task {task.id}: {session_id}")

                # Check post-success session usage — if ≥80%, set warning flag
                usage = task.json_output.get("session_usage_percent", 0)
                if usage >= 80:
                    logger.warning(
                        f"Task {task.id} succeeded but session usage is {usage}% — "
                        f"next rate limit will use shorter initial backoff"
                    )
            elif task.exit_code == 1:
                # Check for rate limit in stderr AND stdout/json_output
                stderr_text = stderr.decode("utf-8", errors="replace").lower()
                stdout_text = stdout.decode("utf-8", errors="replace").lower() if stdout else ""
                result_text = (
                    task.json_output.get("result", "").lower()
                    if task.json_output
                    else ""
                )

                rate_limit_patterns = [
                    "rate limit",
                    "session limit",
                    "quota exceeded",
                    "you've hit your limit",
                    "hit your limit",
                    "rate limited",
                    "too many requests",
                ]

                is_rate_limit = any(
                    pattern in text
                    for pattern in rate_limit_patterns
                    for text in [stderr_text, stdout_text, result_text]
                )

                is_high_usage = (
                    task.json_output.get("session_usage_percent", 0) >= 80
                )

                if is_rate_limit or is_high_usage:
                    self._on_rate_limit_detected(task)
                else:
                    task.status = "failed"
                    logger.error(f"Task {task.id} failed with exit code 1 (no rate limit)")
            else:
                task.status = "failed"
                logger.error(f"Task {task.id} failed with exit code {task.exit_code}")

        except Exception as e:
            logger.error(f"Error executing task {task.id}: {e}")
            task.status = "failed"
            task.exit_code = -1
            task.duration_ms = int((time.time() - start_time) * 1000)
            task.json_output = {"result": f"Execution error: {str(e)}", "parse_error": True}

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

    def _suspend_aware_sleep(self, seconds: float) -> None:
        """Track time spent during suspension for backoff credit."""
        pass  # No-op — the pool loop handles this via wait_for_suspension

    async def run_pool(self) -> None:
        """Run all pending tasks sequentially with global rate-limit suspension."""
        logger.info("Starting task pool execution")

        # If the pool was loaded while already suspended (e.g. restart), wait
        if self.pool.is_suspended:
            logger.info(
                f"Pool was suspended on load, waiting until {self.pool.suspended_until:%H:%M:%S}"
            )
            await self.wait_for_suspension()
            if self.should_stop:
                return
            self.pool.suspended_until = None

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
                self._save_state()

            # After suspension: retry the rate-limited task first
            retry_task = self._find_rate_limit_task()
            if retry_task:
                logger.info(f"Retrying rate-limited task: {retry_task.id}")
                await self.execute_task(retry_task)

                # If it succeeded, reset the global retry counter
                if retry_task.status == "success":
                    self.pool.retry_count = 0
                    logger.info("Retry task succeeded — pool retry counter reset to 0")
                continue  # Loop back to check remaining tasks
            
            # No rate-limit task found after suspension — fall through to pending tasks

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

            # Sort pending tasks by created_at (chronological order)
            pending_tasks.sort(key=lambda t: t.created_at)

            # Execute next pending task
            task = pending_tasks[0]
            await self.execute_task(task)

            if self.should_stop:
                break

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
            
            # Merge: add new tasks and update modified ones
            existing_tasks = {t.id: t for t in self.pool.tasks}
            changes_detected = False
            
            for new_task in new_pool.tasks:
                if new_task.id not in existing_tasks:
                    # New task - add it
                    self.pool.tasks.append(new_task)
                    logger.info(f"Added new task: {new_task.id}")
                    changes_detected = True
                    if self.on_task_update:
                        self.on_task_update(new_task)
                    
                    # Automatic cleanup when new tasks are detected
                    removed = cleanup_old_tasks(self.pool, max_age_hours=48)
                    if removed > 0:
                        logger.info(f"Automatically cleaned up {removed} old completed tasks")
                else:
                    # Existing task - update if it was reset to pending
                    existing = existing_tasks[new_task.id]
                    if new_task.status == "pending" and existing.status != "pending":
                        # Task was reset - update all fields
                        existing.status = new_task.status
                        existing.exit_code = new_task.exit_code
                        existing.duration_ms = new_task.duration_ms
                        existing.json_output = new_task.json_output
                        existing.retry_count = new_task.retry_count
                        logger.info(f"Task {new_task.id} was reset to pending (retry #{existing.retry_count})")
                        changes_detected = True
                        if self.on_task_update:
                            self.on_task_update(existing)
            
            # Preserve pool metadata from the file, but keep in-memory
            # suspended_until if the pool is currently suspended (an external
            # edit must not erase a suspension computed by _on_rate_limit_detected)
            self.pool.retry_count = new_pool.retry_count
            if not self.pool.is_suspended:
                self.pool.suspended_until = new_pool.suspended_until
            
            # Save back to file to persist auto-generated IDs and initialized fields
            self._save_state()
            
            return True
        except Exception as e:
            logger.error(f"Error checking pool updates: {e}")
        return False

    def _notify_update(self, task: Task) -> None:
        """Notify callback of task update."""
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
        """Skip the current task."""
        if self.current_task:
            logger.info(f"Skipping task {self.current_task.id}")
            self.current_task.status = "skipped"
            self.current_task.json_output = {"result": "Task skipped by user"}
            self._notify_update(self.current_task)
            self._save_state()

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
