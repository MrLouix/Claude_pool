"""Concurrency control for Claude Pool task execution."""

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class TaskSemaphore:
    """Semaphore-based concurrency control for task execution.

    Allows up to N tasks to run concurrently while maintaining a global
    rate-limit that blocks ALL concurrent tasks when triggered.
    """

    def __init__(self, max_concurrent: int = 1):
        """Initialise the task semaphore.

        Args:
            max_concurrent: Maximum number of tasks to run concurrently (default: 1)
        """
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_tasks: set[int] = set()

    async def acquire(self) -> None:
        """Acquire a semaphore slot, blocking until one is available."""
        await self.semaphore.acquire()

    def release(self) -> None:
        """Release a previously acquired semaphore slot."""
        self.semaphore.release()

    async def execute_with_limit(self, coro: Any) -> Any:
        """Execute *coro* inside a semaphore slot.

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
        """Number of semaphore slots not currently held."""
        return self.semaphore._value  # type: ignore[attr-defined]

    @property
    def active_count(self) -> int:
        """Number of tasks currently holding a slot."""
        return len(self.active_tasks)

    def clear_tracking(self) -> None:
        """Clear the in-memory active-task tracking set.

        This resets the ``active_tasks`` set used for ``active_count`` and
        logging.  It does NOT cancel running asyncio coroutines.
        """
        logger.info(f"Clearing tracking for {len(self.active_tasks)} active tasks")
        self.active_tasks.clear()


# NOTE: GlobalRateLimitLock is currently unused by the executor.  The executor
# implements its own suspension via ``PoolState.suspended_until`` and
# ``TaskExecutor.wait_for_suspension()``.  This class is retained for potential
# future use but is not exercised in production code paths.
class GlobalRateLimitLock:
    """Global rate-limit lock that blocks ALL concurrent tasks.

    When a rate-limit is triggered, this lock ensures that:
    1. All running tasks are blocked
    2. No new tasks can start
    3. Wait period is enforced globally
    """

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.suspended = False
        self.suspension_end_time: datetime | None = None

    async def acquire_if_not_suspended(self) -> bool:
        """Try to acquire the lock when not suspended.

        Returns:
            True if the lock was acquired, False if currently suspended.
        """
        if self.suspended:
            return False
        return await self.lock.acquire()

    def release(self) -> None:
        """Release the lock if it is currently held."""
        if self.lock.locked():
            self.lock.release()

    async def wait_for_suspension_end(self, end_time: datetime) -> None:
        """Sleep until *end_time*, polling ``self.suspended`` each second."""
        while self.suspended:
            remaining = (end_time - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.0, remaining))
