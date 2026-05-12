"""Task executor for running Claude Code CLI commands."""

import asyncio
import logging
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from .models import Task
from .parser import parse_claude_output
from .storage import load_pool, save_pool

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes tasks from a pool sequentially with rate-limit handling."""

    def __init__(self, pool_file: Path, on_task_update: Callable[[Task], None] | None = None):
        """Initialize the executor.

        Args:
            pool_file: Path to pool.json
            on_task_update: Optional callback called when a task is updated
        """
        self.pool_file = pool_file
        self.tasks: list[Task] = []
        self.current_task: Task | None = None
        self.paused = False
        self.should_stop = False
        self.on_task_update = on_task_update

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
            save_pool(self.pool_file, self.tasks)
            logger.info("State saved successfully")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    async def load_tasks(self) -> None:
        """Load tasks from pool file."""
        try:
            self.tasks = load_pool(self.pool_file)
            logger.info(f"Loaded {len(self.tasks)} tasks from {self.pool_file}")
        except FileNotFoundError:
            logger.warning(f"Pool file {self.pool_file} not found, starting with empty pool")
            self.tasks = []
        except Exception as e:
            logger.error(f"Error loading tasks: {e}")
            raise

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

        # Build command
        cmd = [
            "claude",
            "-p",
            task.prompt,
            "--output-format",
            "json",
        ] + task.args

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
            elif task.exit_code == 1:
                # Check for rate limit
                stderr_text = stderr.decode("utf-8", errors="replace").lower()
                is_rate_limit = any(
                    pattern in stderr_text
                    for pattern in ["rate limit", "session limit", "quota exceeded"]
                )

                if is_rate_limit and task.retry_count < 5:
                    task.status = "rate_limit_retry"
                    logger.warning(f"Task {task.id} hit rate limit, will retry")
                else:
                    task.status = "failed"
                    logger.error(f"Task {task.id} failed with exit code 1")
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

    async def handle_rate_limit(self, task: Task) -> None:
        """Handle rate limit retry with exponential backoff.

        Args:
            task: Task that hit rate limit
        """
        task.retry_count += 1
        wait_seconds = min(60 * (2**task.retry_count), 5 * 3600)

        logger.info(
            f"Rate limit retry {task.retry_count}/5 for task {task.id}, "
            f"waiting {wait_seconds} seconds ({wait_seconds/60:.1f} minutes)"
        )

        # Wait with periodic checks for should_stop
        elapsed = 0
        while elapsed < wait_seconds and not self.should_stop:
            await asyncio.sleep(min(10, wait_seconds - elapsed))
            elapsed += 10

        if not self.should_stop:
            task.status = "pending"
            self._notify_update(task)
            self._save_state()

    async def run_pool(self) -> None:
        """Run all pending tasks sequentially."""
        logger.info("Starting task pool execution")

        while not self.should_stop:
            # Find next pending task
            pending_tasks = [t for t in self.tasks if t.status == "pending"]
            retry_tasks = [t for t in self.tasks if t.status == "rate_limit_retry"]

            if not pending_tasks and not retry_tasks:
                logger.info("All tasks completed")
                break

            # Handle paused state
            while self.paused and not self.should_stop:
                await asyncio.sleep(1)

            if self.should_stop:
                break

            # Process rate limit retries first
            if retry_tasks:
                task = retry_tasks[0]
                await self.handle_rate_limit(task)
                if self.should_stop:
                    break

            # Execute next pending task
            if pending_tasks:
                task = pending_tasks[0]
                await self.execute_task(task)

        logger.info("Task pool execution finished")
        self._save_state()

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
            self.current_task.status = "failed"
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
        for i, task in enumerate(self.tasks):
            if task.id == task_id:
                del self.tasks[i]
                logger.info(f"Deleted task {task_id}")
                self._save_state()
                return True
        return False
