"""Concurrency control for Claude Pool task execution."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class TaskSemaphore:
    """Semaphore-based concurrency control for task execution.

    Allows up to N tasks to run concurrently while maintaining a global
    rate-limit that blocks ALL concurrent tasks when triggered.
    """

    def __init__(self, max_concurrent: int = 1):
        """Initialize the task semaphore.

        Args:
            max_concurrent: Maximum number of tasks to run concurrently (default: 1)
        """
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_tasks = set()

    async def acquire(self) -> None:
        """Acquire a semaphore slot for a task.

        Blocks until a slot is available.
        """
        await self.semaphore.acquire()

    def release(self) -> None:
        """Release a semaphore slot."""
        self.semaphore.release()

    async def execute_with_limit(self, coro) -> any:
        """Execute a coroutine with semaphore protection.

        Args:
            coro: Coroutine to execute

        Returns:
            Result of the coroutine
        """
        await self.acquire()
        task_id = id(asyncio.current_task())
        self.active_tasks.add(task_id)

        try:
            logger.debug(
                f"Task acquired semaphore slot (active: {len(self.active_tasks)}/{self.max_concurrent})"
            )
            return await coro
        finally:
            self.active_tasks.discard(task_id)
            self.release()
            logger.debug(
                f"Task released semaphore slot (active: {len(self.active_tasks)}/{self.max_concurrent})"
            )

    @property
    def available_slots(self) -> int:
        """Get number of available semaphore slots."""
        return self.semaphore._value

    @property
    def active_count(self) -> int:
        """Get number of active tasks."""
        return len(self.active_tasks)

    async def cancel_all(self) -> None:
        """Cancel all active tasks."""
        logger.info(f"Cancelling {len(self.active_tasks)} active tasks")
        for task_id in list(self.active_tasks):
            self.active_tasks.discard(task_id)
        self.release()


class GlobalRateLimitLock:
    """Global rate-limit lock that blocks ALL concurrent tasks.

    When a rate-limit is triggered, this lock ensures that:
    1. All running tasks are blocked
    2. No new tasks can start
    3. Wait period is enforced globally
    """

    def __init__(self):
        """Initialize the global rate-limit lock."""
        self.lock = asyncio.Lock()
        self.suspended = False
        self.suspension_end_time = None

    async def acquire_if_not_suspended(self) -> bool:
        """Try to acquire the lock if not suspended.

        Returns:
            True if lock was acquired, False if suspended
        """
        if self.suspended:
            return False

        return await self.lock.acquire()

    def release(self) -> None:
        """Release the lock."""
        if self.lock.locked():
            self.lock.release()

    async def wait_for_suspension_end(self, end_time) -> None:
        """Wait until the suspension period ends.

        Args:
            end_time: datetime when suspension should end
        """
        while self.suspended:
            remaining = (end_time - asyncio.get_event_loop().time()).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1, remaining))
