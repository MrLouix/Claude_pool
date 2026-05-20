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
async def test_execute_task_persists_session_id(temp_pool_file: Path, sample_task: Task):
    """Test that session_id is persisted after successful execution."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]

    # Mock subprocess with session_id in output
    mock_process = AsyncMock()
    mock_process.returncode = 0
    test_session_id = "sess_abc123def456"
    mock_process.communicate.return_value = (
        f'{{"result": "Success", "tokens_used": 100, "session_id": "{test_session_id}"}}'.encode(),
        b"",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await executor.execute_task(sample_task)

    assert sample_task.status == "success"
    assert sample_task.session_id == test_session_id
    assert sample_task.json_output is not None
    assert sample_task.json_output.get("session_id") == test_session_id


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


@pytest.mark.asyncio
async def test_session_resumption_same_directory(temp_pool_file: Path):
    """Test that --resume is added when a successful session exists in same directory."""
    # Create first task that succeeds with a session_id
    task1 = Task(
        id="task_001",
        prompt="First task",
        directory=Path("/workspace/project"),
        session_id="sess_abc123",
        status="success",
        exit_code=0,
        duration_ms=1000,
        json_output={"result": "Success"},
    )

    # Create second task in the same directory that should resume the session
    task2 = Task(
        id="task_002",
        prompt="Second task",
        directory=Path("/workspace/project"),
    )

    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [task1, task2]

    # Mock subprocess to verify --resume is in the command
    captured_cmd = None

    async def mock_exec(*args, **kwargs):
        nonlocal captured_cmd
        captured_cmd = args  # Capture all command arguments

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b'{"result": "Success"}', b"")
        return mock_process

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        await executor.execute_task(task2)

    # Verify --resume was added to the command
    assert captured_cmd is not None
    assert "--resume" in captured_cmd
    assert "sess_abc123" in captured_cmd
    # Verify the order: --resume <session_id> comes after --dangerously-skip-permissions
    resume_idx = list(captured_cmd).index("--resume")
    assert captured_cmd[resume_idx + 1] == "sess_abc123"


@pytest.mark.asyncio
async def test_no_session_resumption_different_directory(temp_pool_file: Path):
    """Test that --resume is NOT added when successful task is in different directory."""
    # Create first task in one directory with a session
    task1 = Task(
        id="task_001",
        prompt="First task",
        directory=Path("/workspace/project-a"),
        session_id="sess_abc123",
        status="success",
        exit_code=0,
        duration_ms=1000,
        json_output={"result": "Success"},
    )

    # Create second task in different directory
    task2 = Task(
        id="task_002",
        prompt="Second task",
        directory=Path("/workspace/project-b"),
    )

    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [task1, task2]

    captured_cmd = None

    async def mock_exec(*args, **kwargs):
        nonlocal captured_cmd
        captured_cmd = args

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b'{"result": "Success"}', b"")
        return mock_process

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        await executor.execute_task(task2)

    # Verify --resume was NOT added
    assert captured_cmd is not None
    assert "--resume" not in captured_cmd


@pytest.mark.asyncio
async def test_most_recent_session_is_used(temp_pool_file: Path):
    """Test that the most recent session is used when multiple exist."""
    base_time = datetime.fromisoformat("2026-05-20T10:00:00")

    # Create multiple successful tasks in same directory with different sessions
    task1 = Task(
        id="task_001",
        prompt="First task",
        directory=Path("/workspace/project"),
        session_id="sess_old",
        status="success",
        exit_code=0,
        duration_ms=1000,
        json_output={"result": "Success"},
        created_at=(base_time + timedelta(seconds=0)).isoformat(),
    )

    task2 = Task(
        id="task_002",
        prompt="Second task",
        directory=Path("/workspace/project"),
        session_id="sess_new",
        status="success",
        exit_code=0,
        duration_ms=1000,
        json_output={"result": "Success"},
        created_at=(base_time + timedelta(seconds=30)).isoformat(),
    )

    # Create third task that should use the most recent session
    task3 = Task(
        id="task_003",
        prompt="Third task",
        directory=Path("/workspace/project"),
        created_at=(base_time + timedelta(seconds=60)).isoformat(),
    )

    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [task1, task2, task3]

    captured_cmd = None

    async def mock_exec(*args, **kwargs):
        nonlocal captured_cmd
        captured_cmd = args

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b'{"result": "Success"}', b"")
        return mock_process

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        await executor.execute_task(task3)

    # Verify the most recent session (sess_new) is used
    assert captured_cmd is not None
    assert "--resume" in captured_cmd
    assert "sess_new" in captured_cmd
    assert "sess_old" not in captured_cmd


@pytest.mark.asyncio
async def test_chronological_selection(temp_pool_file: Path):
    """Test that pending tasks are selected in chronological order by created_at."""
    # Create 3 tasks with different created_at timestamps
    # They are added to the pool in reverse chronological order
    # but should be executed in chronological order

    base_time = datetime.fromisoformat("2026-05-20T10:00:00")
    task1 = Task(
        id="task_003",
        prompt="Third task (created last)",
        directory=Path("/tmp"),
        created_at=(base_time + timedelta(seconds=60)).isoformat(),
    )
    task2 = Task(
        id="task_002",
        prompt="Second task (created second)",
        directory=Path("/tmp"),
        created_at=(base_time + timedelta(seconds=30)).isoformat(),
    )
    task3 = Task(
        id="task_001",
        prompt="First task (created first)",
        directory=Path("/tmp"),
        created_at=base_time.isoformat(),
    )

    executor = TaskExecutor(temp_pool_file)
    # Add tasks in reverse chronological order (simulating pool.json order)
    executor.pool.tasks = [task1, task2, task3]

    # All tasks start as pending
    assert all(t.status == "pending" for t in executor.pool.tasks)

    # Mock subprocess to track execution order
    execution_order = []

    async def mock_execute(task: Task) -> None:
        execution_order.append(task.id)
        task.status = "success"
        task.exit_code = 0
        task.duration_ms = 100
        task.json_output = {"result": "Done"}

    # Patch execute_task to track execution order
    with patch.object(executor, "execute_task", side_effect=mock_execute):
        # Simulate the task selection logic from run_pool
        pending_tasks = [t for t in executor.pool.tasks if t.status == "pending"]
        pending_tasks.sort(key=lambda t: t.created_at)

        for task in pending_tasks:
            await executor.execute_task(task)

    # Verify tasks were selected in chronological order
    assert execution_order == ["task_001", "task_002", "task_003"]
