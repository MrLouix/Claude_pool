"""Tests for concurrent task execution."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_pool.concurrency import TaskSemaphore
from claude_pool.executor import TaskExecutor
from claude_pool.models import PoolState, Task


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file."""
    return tmp_path / "test_pool.json"


@pytest.fixture
def sample_tasks() -> list[Task]:
    """Create multiple sample tasks."""
    return [
        Task(
            id=f"task_{i:03d}",
            prompt=f"Task {i}",
            directory=Path("/tmp"),
            status="pending",
        )
        for i in range(5)
    ]


class TestTaskSemaphore:
    """Test TaskSemaphore concurrency control."""

    @pytest.mark.asyncio
    async def test_semaphore_init(self):
        """Test semaphore initialization."""
        semaphore = TaskSemaphore(max_concurrent=2)
        assert semaphore.max_concurrent == 2
        assert semaphore.available_slots == 2
        assert semaphore.active_count == 0

    @pytest.mark.asyncio
    async def test_semaphore_acquire_release(self):
        """Test semaphore acquire and release."""
        semaphore = TaskSemaphore(max_concurrent=1)

        await semaphore.acquire()
        assert semaphore.available_slots == 0

        semaphore.release()
        assert semaphore.available_slots == 1

    @pytest.mark.asyncio
    async def test_semaphore_blocking(self):
        """Test that semaphore blocks when full."""
        semaphore = TaskSemaphore(max_concurrent=1)

        # Acquire the only slot
        await semaphore.acquire()
        assert semaphore.available_slots == 0

        # Try to acquire again - should not be able to
        acquire_task = asyncio.create_task(semaphore.acquire())
        await asyncio.sleep(0.1)

        # Task should still be waiting
        assert not acquire_task.done()

        # Release and task should complete
        semaphore.release()
        await asyncio.wait_for(acquire_task, timeout=1.0)
        assert acquire_task.done()

    @pytest.mark.asyncio
    async def test_semaphore_multiple_concurrent(self):
        """Test semaphore with multiple concurrent tasks."""
        semaphore = TaskSemaphore(max_concurrent=2)

        async def task_work(task_id: int, delay: float = 0.1):
            await semaphore.acquire()
            try:
                await asyncio.sleep(delay)
                return task_id
            finally:
                semaphore.release()

        # Run 5 tasks with max 2 concurrent
        tasks = [task_work(i) for i in range(5)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert set(results) == {0, 1, 2, 3, 4}

    @pytest.mark.asyncio
    async def test_semaphore_execute_with_limit(self):
        """Test execute_with_limit method."""
        semaphore = TaskSemaphore(max_concurrent=1)

        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"

        # Execute with limit
        result = await semaphore.execute_with_limit(slow_task())
        assert result == "done"


class TestConcurrentExecution:
    """Test concurrent task execution in TaskExecutor."""

    @pytest.mark.asyncio
    async def test_executor_concurrent_init(self, temp_pool_file: Path):
        """Test executor initialization with concurrent mode."""
        executor = TaskExecutor(temp_pool_file, max_concurrent=2)

        assert executor.max_concurrent == 2
        assert executor.semaphore.max_concurrent == 2
        assert executor.semaphore.available_slots == 2

    @pytest.mark.asyncio
    async def test_executor_sequential_init(self, temp_pool_file: Path):
        """Test executor initialization with sequential mode (default)."""
        executor = TaskExecutor(temp_pool_file)

        assert executor.max_concurrent == 1
        assert executor.semaphore.available_slots == 1

    @pytest.mark.asyncio
    async def test_concurrent_task_execution(self, temp_pool_file: Path, sample_tasks: list[Task]):
        """Test that concurrent execution runs up to N tasks in parallel."""
        executor = TaskExecutor(temp_pool_file, max_concurrent=2)
        executor.pool = PoolState(tasks=sample_tasks, pool_file=temp_pool_file)

        # Mock execute_task to track execution
        execution_times = []

        async def mock_execute(task: Task):
            start = asyncio.get_event_loop().time()
            execution_times.append((task.id, start))
            await asyncio.sleep(0.1)
            task.status = "success"
            task.exit_code = 0

        with patch.object(executor, "execute_task", side_effect=mock_execute):
            # Get tasks to execute
            pending = [t for t in executor.pool.tasks if t.status == "pending"]
            pending.sort(key=lambda t: t.created_at)

            # Execute first 2 concurrently
            tasks_to_execute = pending[:2]
            coros = [
                executor.semaphore.execute_with_limit(executor.execute_task(task))
                for task in tasks_to_execute
            ]
            await asyncio.gather(*coros)

        # Should have executed 2 tasks
        assert len(execution_times) == 2

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_all(self, temp_pool_file: Path, sample_tasks: list[Task]):
        """Test that rate-limit blocks ALL concurrent tasks."""
        executor = TaskExecutor(temp_pool_file, max_concurrent=2)
        executor.pool = PoolState(tasks=sample_tasks, pool_file=temp_pool_file)

        # Set suspension to block all tasks
        executor.pool.suspended_until = datetime.now() + timedelta(seconds=1)

        # All concurrent tasks should be blocked
        assert executor.pool.is_suspended

        # Wait for suspension to end
        await executor.wait_for_suspension()
        assert not executor.pool.is_suspended

    @pytest.mark.asyncio
    async def test_save_state_thread_safety(self, temp_pool_file: Path, sample_tasks: list[Task]):
        """Test that _save_state_async is thread-safe."""
        executor = TaskExecutor(temp_pool_file, max_concurrent=2)
        executor.pool = PoolState(tasks=sample_tasks, pool_file=temp_pool_file)

        # Mock save_pool to verify it's called
        call_count = 0

        def mock_save(pool):
            nonlocal call_count
            call_count += 1

        with patch("claude_pool.executor.save_pool", side_effect=mock_save):
            # Call save_state_async multiple times concurrently
            await asyncio.gather(
                executor._save_state_async(),
                executor._save_state_async(),
                executor._save_state_async(),
            )

        # Should have been called 3 times (all serialized by lock)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_concurrent_parallel_execution(self, temp_pool_file: Path):
        """Test that concurrent execution runs tasks in parallel."""
        # Create 2 tasks
        tasks = [
            Task(id=f"task_{i}", prompt=f"Task {i}", directory=Path("/tmp"), status="pending")
            for i in range(2)
        ]

        executor = TaskExecutor(temp_pool_file, max_concurrent=2)
        executor.pool = PoolState(tasks=tasks.copy(), pool_file=temp_pool_file)

        # Track when tasks complete
        completion_times = []

        async def mock_execute_with_delay(task: Task):
            task.status = "success"
            await asyncio.sleep(0.1)
            completion_times.append(asyncio.get_event_loop().time())

        # Execute 2 tasks concurrently
        with patch.object(executor, "execute_task", side_effect=mock_execute_with_delay):
            pending = executor.pool.tasks
            coros = [
                executor.semaphore.execute_with_limit(executor.execute_task(task))
                for task in pending
            ]
            await asyncio.gather(*coros)

        # Both tasks should be completed
        assert len(completion_times) == 2
        assert executor.semaphore.available_slots == 2


class TestRunPoolConcurrent:
    """Test the concurrent run_pool logic."""

    @pytest.mark.asyncio
    async def test_run_pool_selects_correct_mode(self, temp_pool_file: Path):
        """Test that run_pool selects sequential or concurrent mode."""
        executor_seq = TaskExecutor(temp_pool_file, max_concurrent=1)
        executor_conc = TaskExecutor(temp_pool_file, max_concurrent=2)

        # Mock both methods to track which is called
        with patch.object(executor_seq, "run_pool_sequential", new_callable=AsyncMock) as mock_seq:
            with patch.object(executor_seq, "run_pool_concurrent", new_callable=AsyncMock) as mock_conc:
                executor_seq.should_stop = True
                await executor_seq.run_pool()
                mock_seq.assert_called_once()
                mock_conc.assert_not_called()

        with patch.object(executor_conc, "run_pool_sequential", new_callable=AsyncMock) as mock_seq:
            with patch.object(executor_conc, "run_pool_concurrent", new_callable=AsyncMock) as mock_conc:
                executor_conc.should_stop = True
                await executor_conc.run_pool()
                mock_seq.assert_not_called()
                mock_conc.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_respects_max_concurrent_limit(self, temp_pool_file: Path):
        """Test that concurrent mode respects the max_concurrent limit."""
        # Create 5 tasks
        tasks = [
            Task(id=f"task_{i}", prompt=f"Task {i}", directory=Path("/tmp"), status="pending")
            for i in range(5)
        ]

        executor = TaskExecutor(temp_pool_file, max_concurrent=2)
        executor.pool = PoolState(tasks=tasks, pool_file=temp_pool_file)

        active_at_once = []

        async def mock_execute(task: Task):
            current_active = executor.semaphore.active_count
            active_at_once.append(current_active)
            task.status = "success"
            await asyncio.sleep(0.1)

        with patch.object(executor, "execute_task", side_effect=mock_execute):
            # Simulate one iteration of run_pool_concurrent
            pending = [t for t in executor.pool.tasks if t.status == "pending"]
            pending.sort(key=lambda t: t.created_at)

            tasks_to_execute = pending[:2]
            coros = [
                executor.semaphore.execute_with_limit(executor.execute_task(task))
                for task in tasks_to_execute
            ]
            await asyncio.gather(*coros)

        # Should never exceed max_concurrent
        assert max(active_at_once) <= executor.max_concurrent
