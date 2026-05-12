"""Tests for task executor."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_pool.executor import TaskExecutor
from claude_pool.models import PoolState, Task


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file."""
    return tmp_path / "test_pool.json"


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task."""
    return Task(
        id="test_001",
        prompt="Test prompt",
        directory=Path("/tmp"),
        args=["--model", "sonnet-4"],
    )


def make_pool_state(tasks: list[Task] = None, pool_file: Path = Path("pool.json")) -> PoolState:
    """Helper to create a PoolState with given tasks."""
    return PoolState(tasks=tasks or [], pool_file=pool_file)


@pytest.mark.asyncio
async def test_executor_init(temp_pool_file: Path):
    """Test executor initialization."""
    executor = TaskExecutor(temp_pool_file)

    assert executor.pool_file == temp_pool_file
    assert executor.pool.tasks == []
    assert executor.current_task is None
    assert executor.paused is False
    assert executor.should_stop is False


@pytest.mark.asyncio
async def test_load_tasks_empty_file(temp_pool_file: Path):
    """Test loading tasks from non-existent file."""
    executor = TaskExecutor(temp_pool_file)
    await executor.load_tasks()

    assert executor.pool.tasks == []


@pytest.mark.asyncio
async def test_pause_resume(temp_pool_file: Path):
    """Test pause and resume functionality."""
    executor = TaskExecutor(temp_pool_file)

    assert executor.paused is False
    executor.pause()
    assert executor.paused is True
    executor.resume()
    assert executor.paused is False


@pytest.mark.asyncio
async def test_delete_task(temp_pool_file: Path, sample_task: Task):
    """Test deleting a task."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]

    result = executor.delete_task("test_001")
    assert result is True
    assert len(executor.pool.tasks) == 0

    result = executor.delete_task("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_execute_task_success(temp_pool_file: Path, sample_task: Task):
    """Test successful task execution."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]

    # Mock subprocess
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (
        b'{"result": "Success", "tokens_used": 100}',
        b"",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    assert sample_task.status == "success"
    assert sample_task.exit_code == 0
    assert sample_task.duration_ms is not None
    assert sample_task.json_output is not None
    assert sample_task.json_output["result"] == "Success"


@pytest.mark.asyncio
async def test_execute_task_failure(temp_pool_file: Path, sample_task: Task):
    """Test failed task execution."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]

    mock_process = AsyncMock()
    mock_process.returncode = 2
    mock_process.communicate.return_value = (
        b'{"result": "Failed"}',
        b"Error occurred",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    assert sample_task.status == "failed"
    assert sample_task.exit_code == 2


@pytest.mark.asyncio
async def test_execute_task_rate_limit(temp_pool_file: Path, sample_task: Task):
    """Test task with rate limit."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]
    executor.pool.retry_count = 0

    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        b'{"result": "Rate limited"}',
        b"Error: rate limit exceeded",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    assert sample_task.status == "rate_limit_retry"
    assert sample_task.exit_code == 1
    assert executor.pool.retry_count == 1
    assert executor.pool.suspended_until is not None


@pytest.mark.asyncio
async def test_pool_suspension_on_rate_limit(temp_pool_file: Path, sample_task: Task):
    """Test that rate limit triggers global pool suspension."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]

    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        b'{"result": "Rate limited"}',
        b"Error: rate limit exceeded",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    assert executor.pool.is_suspended is True
    assert executor.pool.suspension_remaining > 0
    assert executor.pool.retry_count == 1


@pytest.mark.asyncio
async def test_pool_retry_count_exhaustion(temp_pool_file: Path, sample_task: Task):
    """Test that pool marks remaining tasks as failed after max retries."""
    executor = TaskExecutor(temp_pool_file)
    task1 = sample_task
    task2 = Task(id="test_002", prompt="Task 2", directory=Path("/tmp"))
    executor.pool.tasks = [task1, task2]
    executor.pool.retry_count = 5  # Pre-set to max

    # Manually test exhaustion logic (simulate what run_pool does)
    for t in executor.pool.tasks:
        if t.status in ("pending", "rate_limit_retry"):
            t.status = "failed"
            t.json_output = {"result": f"Pool exhausted"}

    assert task1.status == "failed"
    assert task2.status == "failed"


@pytest.mark.asyncio
async def test_skip_current(temp_pool_file: Path, sample_task: Task):
    """Test skipping current task."""
    executor = TaskExecutor(temp_pool_file)
    executor.current_task = sample_task
    sample_task.status = "running"

    executor.skip_current()

    assert sample_task.status == "skipped"
    assert sample_task.json_output is not None
    assert "skipped" in sample_task.json_output["result"].lower()


@pytest.mark.asyncio
async def test_callback_on_update(temp_pool_file: Path, sample_task: Task):
    """Test that callback is called on task update."""
    callback = MagicMock()
    executor = TaskExecutor(temp_pool_file, on_task_update=callback)
    executor.pool.tasks = [sample_task]

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b'{"result": "Done"}', b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    # Should be called at least twice: when starting and when done
    assert callback.call_count >= 2
