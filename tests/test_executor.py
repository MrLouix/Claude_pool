"""Tests for task executor."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_pool.executor import TaskExecutor
from claude_pool.models import Task


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


@pytest.mark.asyncio
async def test_executor_init(temp_pool_file: Path):
    """Test executor initialization."""
    executor = TaskExecutor(temp_pool_file)

    assert executor.pool_file == temp_pool_file
    assert executor.tasks == []
    assert executor.current_task is None
    assert executor.paused is False
    assert executor.should_stop is False


@pytest.mark.asyncio
async def test_load_tasks_empty_file(temp_pool_file: Path):
    """Test loading tasks from non-existent file."""
    executor = TaskExecutor(temp_pool_file)
    await executor.load_tasks()

    assert executor.tasks == []


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
    executor.tasks = [sample_task]

    result = executor.delete_task("test_001")
    assert result is True
    assert len(executor.tasks) == 0

    result = executor.delete_task("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_execute_task_success(temp_pool_file: Path, sample_task: Task):
    """Test successful task execution."""
    executor = TaskExecutor(temp_pool_file)
    executor.tasks = [sample_task]

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
    executor.tasks = [sample_task]

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
    executor.tasks = [sample_task]

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


@pytest.mark.asyncio
async def test_handle_rate_limit(temp_pool_file: Path, sample_task: Task):
    """Test rate limit handling with backoff."""
    executor = TaskExecutor(temp_pool_file)
    sample_task.status = "rate_limit_retry"
    sample_task.retry_count = 0

    # Mock asyncio.sleep to avoid actual waiting
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await executor.handle_rate_limit(sample_task)

    assert sample_task.retry_count == 1
    assert sample_task.status == "pending"
    assert mock_sleep.called


@pytest.mark.asyncio
async def test_handle_rate_limit_max_retries(temp_pool_file: Path, sample_task: Task):
    """Test rate limit with max retries exceeded."""
    executor = TaskExecutor(temp_pool_file)
    executor.tasks = [sample_task]
    sample_task.retry_count = 5

    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        b'{"result": "Still rate limited"}',
        b"Error: rate limit exceeded",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    # Should fail instead of retry
    assert sample_task.status == "failed"


@pytest.mark.asyncio
async def test_skip_current(temp_pool_file: Path, sample_task: Task):
    """Test skipping current task."""
    executor = TaskExecutor(temp_pool_file)
    executor.current_task = sample_task
    sample_task.status = "running"

    executor.skip_current()

    assert sample_task.status == "failed"
    assert sample_task.json_output is not None
    assert "skipped" in sample_task.json_output["result"].lower()


@pytest.mark.asyncio
async def test_callback_on_update(temp_pool_file: Path, sample_task: Task):
    """Test that callback is called on task update."""
    callback = MagicMock()
    executor = TaskExecutor(temp_pool_file, on_task_update=callback)
    executor.tasks = [sample_task]

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b'{"result": "Done"}', b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    # Should be called at least twice: when starting and when done
    assert callback.call_count >= 2
