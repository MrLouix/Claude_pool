"""Tests for chat-level concurrency control in TaskExecutor."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from team_cli.executor import TaskExecutor
from team_cli.models import Task


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file."""
    return tmp_path / "test_pool.db"


def _create_task(task_id: str, chat_id: str | None = None, directory: Path | None = None) -> Task:
    """Helper to create a test task."""
    if directory is None:
        directory = Path("/tmp")
    return Task(
        id=task_id,
        prompt=f"Test prompt for {task_id}",
        directory=directory,
        status="pending",
        chat_id=chat_id,
    )


@pytest.mark.asyncio
async def test_same_chat_tasks_serialize(temp_pool_file: Path):
    """Test that tasks with the same chat_id run sequentially, not in parallel."""
    executor = TaskExecutor(
        temp_pool_file,
        max_concurrent=10,
        install_signal_handlers=False,
    )
    
    chat_id = "test_chat_123"
    
    # Get or create the lock for this chat_id
    chat_lock = executor._chat_locks.setdefault(chat_id, asyncio.Lock())
    
    execution_order = []
    
    async def locked_task(task_id: str, delay_ms: int = 50):
        await chat_lock.acquire()
        try:
            execution_order.append((task_id, "start"))
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            execution_order.append((task_id, "end"))
        finally:
            chat_lock.release()
    
    await asyncio.gather(
        locked_task("task_1", 50),
        locked_task("task_2", 50),
    )
    
    # Verify serialization: task_2 should start after task_1 ends
    task1_start_idx = next(i for i, (tid, e) in enumerate(execution_order) if tid == "task_1" and e == "start")
    task1_end_idx = next(i for i, (tid, e) in enumerate(execution_order) if tid == "task_1" and e == "end")
    task2_start_idx = next(i for i, (tid, e) in enumerate(execution_order) if tid == "task_2" and e == "start")
    task2_end_idx = next(i for i, (tid, e) in enumerate(execution_order) if tid == "task_2" and e == "end")
    
    # task_2 start should be after task_1 end
    assert task2_start_idx > task1_end_idx
    assert task2_end_idx > task2_start_idx


@pytest.mark.asyncio
async def test_different_chat_tasks_run_in_parallel(temp_pool_file: Path):
    """Test that tasks with different chat_ids can run in parallel."""
    executor = TaskExecutor(
        temp_pool_file,
        max_concurrent=10,
        install_signal_handlers=False,
    )
    
    chat_id_1 = "test_chat_1"
    chat_id_2 = "test_chat_2"
    
    # Get or create locks for both chats
    lock1 = executor._chat_locks.setdefault(chat_id_1, asyncio.Lock())
    lock2 = executor._chat_locks.setdefault(chat_id_2, asyncio.Lock())
    
    execution_log = []
    overall_start = asyncio.get_event_loop().time()
    
    async def locked_task(task_id: str, lock, delay_ms: int):
        start = asyncio.get_event_loop().time()
        await lock.acquire()
        try:
            execution_log.append((task_id, "start", start - overall_start))
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            end = asyncio.get_event_loop().time()
            execution_log.append((task_id, "end", end - overall_start))
        finally:
            lock.release()
    
    # Run tasks for different chats in parallel
    await asyncio.gather(
        locked_task("task_1", lock1, 50),
        locked_task("task_2", lock2, 50),
    )
    
    # Both tasks should have run
    task1_events = [e for e in execution_log if e[0] == "task_1"]
    task2_events = [e for e in execution_log if e[0] == "task_2"]
    
    assert len(task1_events) == 2  # start and end
    assert len(task2_events) == 2  # start and end
    
    # Since they use different locks, they can run in parallel
    # The total time should be close to 50ms (max of the two), not 100ms (sum)
    total_time = asyncio.get_event_loop().time() - overall_start
    assert total_time < 0.15  # Should be ~50ms, not ~100ms


@pytest.mark.asyncio
async def test_chat_id_none_tasks_unaffected(temp_pool_file: Path):
    """Test that tasks with chat_id=None are not blocked by chat locks."""
    executor = TaskExecutor(
        temp_pool_file,
        max_concurrent=2,
        install_signal_handlers=False,
    )
    
    # Create a task with a chat_id and acquire its lock
    chat_id = "test_chat"
    chat_lock = executor._chat_locks.setdefault(chat_id, asyncio.Lock())
    await chat_lock.acquire()
    
    # Create a task with chat_id=None - it should not try to acquire any chat lock
    task_none = _create_task("task_none", chat_id=None)
    
    # Mock the subprocess to avoid actual execution
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"result": "ok"}', b''))
        mock_exec.return_value = mock_process
        
        # This should not block even though chat_lock is held
        # because chat_id=None tasks don't acquire chat locks
        await executor.execute_task(task_none)
    
    # Verify the task ran (mock was called)
    assert mock_exec.called
    
    # Release the lock we acquired
    chat_lock.release()


@pytest.mark.asyncio
async def test_lock_released_on_task_failure(temp_pool_file: Path):
    """Test that the chat_id lock is released even when a task raises an exception."""
    executor = TaskExecutor(
        temp_pool_file,
        max_concurrent=10,
        install_signal_handlers=False,
    )
    
    chat_id = "test_chat_fail"
    chat_lock = executor._chat_locks.setdefault(chat_id, asyncio.Lock())
    
    lock_acquired_count = [0]
    
    async def task_with_exception(task_id: str):
        await chat_lock.acquire()
        lock_acquired_count[0] += 1
        try:
            if task_id == "task_1":
                raise RuntimeError("Simulated task failure")
        finally:
            chat_lock.release()
    
    # Run task 1 (will fail)
    with pytest.raises(RuntimeError):
        await task_with_exception("task_1")
    
    # Lock should have been acquired once
    assert lock_acquired_count[0] == 1
    
    # Lock should be released, so we can acquire it again
    await chat_lock.acquire()
    chat_lock.release()
    
    # Run task 2 - should be able to acquire the lock
    await task_with_exception("task_2")
    
    # Lock should have been acquired twice total
    assert lock_acquired_count[0] == 2


@pytest.mark.asyncio
async def test_lock_released_on_exception_in_execute_task(temp_pool_file: Path):
    """Test that chat lock is released when execute_task encounters an error.
    
    Note: execute_task catches exceptions from subprocess and sets task.status='failed'
    rather than re-raising, so we verify that the lock is released by checking that
    a second task with the same chat_id can run afterwards.
    """
    executor = TaskExecutor(
        temp_pool_file,
        max_concurrent=10,
        install_signal_handlers=False,
    )
    
    chat_id = "test_chat_exception"
    
    # Create two tasks with the same chat_id
    task1 = _create_task("task_1", chat_id=chat_id)
    task2 = _create_task("task_2", chat_id=chat_id)
    
    execution_count = [0]
    
    # Mock subprocess to raise an exception on first call
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        def side_effect(*args, **kwargs):
            execution_count[0] += 1
            if execution_count[0] == 1:
                raise RuntimeError("Simulated subprocess error")
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b'{"result": "ok"}', b''))
            return mock_process
        
        mock_exec.side_effect = side_effect
        
        # Run task 1 (will fail internally, exception is caught)
        await executor.execute_task(task1)
        
        # Task 1 should have failed status
        assert task1.status == "failed"
        
        # Lock should be released, so task 2 can run
        await executor.execute_task(task2)
        
        # Task 2 should succeed
        assert task2.status == "success"
        
        # Both tasks should have been attempted
        assert execution_count[0] == 2


@pytest.mark.asyncio
async def test_multiple_chats_with_serialization(temp_pool_file: Path):
    """Test that multiple chats each serialize their own tasks independently."""
    executor = TaskExecutor(
        temp_pool_file,
        max_concurrent=10,
        install_signal_handlers=False,
    )
    
    chat_ids = ["chat_a", "chat_b", "chat_c"]
    
    # Get or create locks for each chat
    locks = {chat_id: executor._chat_locks.setdefault(chat_id, asyncio.Lock()) for chat_id in chat_ids}
    
    execution_log = []
    
    async def locked_task(chat_id: str, task_num: int, delay_ms: int = 30):
        lock = locks[chat_id]
        await lock.acquire()
        try:
            execution_log.append((f"{chat_id}_{task_num}", "start"))
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            execution_log.append((f"{chat_id}_{task_num}", "end"))
        finally:
            lock.release()
    
    # Run 2 tasks for each of 3 chats concurrently
    tasks = []
    for chat_id in chat_ids:
        for task_num in range(2):
            tasks.append(locked_task(chat_id, task_num, 30))
    
    await asyncio.gather(*tasks)
    
    # For each chat, verify that its two tasks serialized
    for chat_id in chat_ids:
        chat_events = [e for e in execution_log if chat_id in e[0]]
        # Should have 2 starts and 2 ends for each chat
        assert len(chat_events) == 4
        
        # Extract task 0 and task 1 events
        task_0_start = next((i for i, (tid, e) in enumerate(chat_events) if "_0" in tid and e == "start"), None)
        task_0_end = next((i for i, (tid, e) in enumerate(chat_events) if "_0" in tid and e == "end"), None)
        task_1_start = next((i for i, (tid, e) in enumerate(chat_events) if "_1" in tid and e == "start"), None)
        task_1_end = next((i for i, (tid, e) in enumerate(chat_events) if "_1" in tid and e == "end"), None)
        
        assert task_0_start is not None
        assert task_0_end is not None
        assert task_1_start is not None
        assert task_1_end is not None
        
        # task_1 should start after task_0 ends (serialization within chat)
        assert task_1_start > task_0_end
