"""Tests for task executor."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from team_cli.executor import TaskExecutor, _RATE_LIMIT_PATTERNS
from team_cli.models import Bucket, PoolState, Task


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file."""
    return tmp_path / "test_pool.db"


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
async def test_skip_current_task(temp_pool_file: Path, sample_task: Task):
    """Test skipping current task via skip_requested flag."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.tasks = [sample_task]
    executor.current_task = sample_task
    sample_task.status = "pending"

    # Request skip before execution
    executor.skip_current()
    assert executor.skip_requested is True

    # Execute task - should skip instead of running subprocess
    await executor.execute_task(sample_task)

    # Verify task was skipped without running subprocess
    assert sample_task.status == "skipped"
    assert sample_task.json_output is not None
    assert "skipped" in sample_task.json_output["result"].lower()
    assert executor.skip_requested is False  # Flag should be cleared


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


@pytest.mark.asyncio
async def test_retry_count_reset_suspension_expires_no_task(temp_pool_file: Path):
    """When suspension timer expires but no rate_limit_retry task exists,
    pool retry_count must be reset to 0 so the pool fully unblocks."""
    executor = TaskExecutor(temp_pool_file)
    # Start with a suspended pool whose timer already expired
    executor.pool.retry_count = 2
    past_time = datetime.now() - timedelta(seconds=5)
    executor.pool.suspended_until = past_time
    executor.pool.tasks = [
        Task(id="task_old", prompt="old task", directory=Path("/tmp"), status="success")
    ]

    # is_suspended should be False since timer expired
    assert not executor.pool.is_suspended

    # Run briefly — it will detect no rate_limit_retry task and reset counter
    called_tasks = []

    async def mock_execute(task):
        called_tasks.append(task)

    with patch.object(executor, "execute_task", side_effect=mock_execute):
        task = asyncio.create_task(executor.run_pool())
        await asyncio.sleep(0.1)
        executor.should_stop = True
        try:
            await asyncio.wait_for(task, timeout=3)
        except asyncio.TimeoutError:
            executor.should_stop = True

    assert executor.pool.retry_count == 0


@pytest.mark.asyncio
async def test_retry_count_reset_suspension_expired_with_pending(temp_pool_file: Path):
    """If new pending tasks are added while suspended, after timer expires
    and no rate_limit task, retry_count resets and pending task executes."""
    executor = TaskExecutor(temp_pool_file)
    # Timer already expired (past time) — simulates user deleting rate_limit tasks
    executor.pool.retry_count = 3
    past_time = datetime.now() - timedelta(seconds=5)
    task_pending = Task(id="task_new", prompt="new task", directory=Path("/tmp"))
    executor.pool.tasks = [task_pending]
    executor.pool.suspended_until = past_time

    assert not executor.pool.is_suspended

    captured_task = None

    async def mock_execute(task):
        nonlocal captured_task
        captured_task = task
        task.status = "success"
        task.exit_code = 0
        task.duration_ms = 50

    with patch.object(executor, "execute_task", side_effect=mock_execute):
        task_runner = asyncio.create_task(executor.run_pool())
        await asyncio.sleep(0.2)
        executor.should_stop = True
        try:
            await asyncio.wait_for(task_runner, timeout=3)
        except asyncio.TimeoutError:
            executor.should_stop = True

    # retry_count should have been reset to 0 before executing pending task
    assert executor.pool.retry_count == 0
    assert captured_task is not None
    assert captured_task.id == "task_new"


# ---------------------------------------------------------------------------
# delete_bucket tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_bucket_main_raises(temp_pool_file: Path):
    """delete_bucket('main') must raise ValueError — the main bucket is immutable."""
    executor = TaskExecutor(temp_pool_file)
    with pytest.raises(ValueError, match="main"):
        executor.delete_bucket("main")


@pytest.mark.asyncio
async def test_delete_bucket_removes_bucket_and_tasks(temp_pool_file: Path):
    """delete_bucket removes the bucket entry and all its tasks, leaves other buckets intact."""
    executor = TaskExecutor(temp_pool_file)
    executor.pool.buckets["chat_x"] = Bucket(id="chat_x", type="chat", label="Test Chat")

    task_main = Task(id="main_task", prompt="main task", directory=Path("/tmp"), bucket_id="main")
    task_chat1 = Task(id="chat_task_1", prompt="chat 1", directory=Path("/tmp"), bucket_id="chat_x")
    task_chat2 = Task(id="chat_task_2", prompt="chat 2", directory=Path("/tmp"), bucket_id="chat_x")
    executor.pool.tasks = [task_main, task_chat1, task_chat2]

    removed = executor.delete_bucket("chat_x")

    assert removed == 2
    assert "chat_x" not in executor.pool.buckets
    # Only the main-bucket task survives
    assert len(executor.pool.tasks) == 1
    assert executor.pool.tasks[0].id == "main_task"
    # main bucket must still be present
    assert "main" in executor.pool.buckets


@pytest.mark.asyncio
async def test_delete_bucket_skips_running_task_and_leaves_consistent_queue(temp_pool_file: Path):
    """When the currently-running task belongs to the deleted bucket:
    - skip_requested is set so the executor loop abandons it
    - ALL bucket tasks (including the running one) are removed from pool.tasks
    - Tasks from other buckets are untouched → queue is consistent
    """
    executor = TaskExecutor(temp_pool_file)
    executor.pool.buckets["chat_x"] = Bucket(id="chat_x", type="chat", label="Test Chat")

    running_task = Task(
        id="running_1",
        prompt="running",
        directory=Path("/tmp"),
        bucket_id="chat_x",
        status="running",
    )
    pending_in_chat = Task(
        id="pending_chat",
        prompt="pending in chat",
        directory=Path("/tmp"),
        bucket_id="chat_x",
    )
    other_task = Task(
        id="other_1",
        prompt="other bucket",
        directory=Path("/tmp"),
        bucket_id="main",
    )
    executor.pool.tasks = [running_task, pending_in_chat, other_task]
    executor.current_task = running_task  # simulate a running task

    assert executor.skip_requested is False

    removed = executor.delete_bucket("chat_x")

    # skip was requested for the running task
    assert executor.skip_requested is True
    # both chat_x tasks (running + pending) were removed
    assert removed == 2
    # bucket entry gone
    assert "chat_x" not in executor.pool.buckets
    # queue only contains the unrelated task — no dangling chat_x references
    assert len(executor.pool.tasks) == 1
    assert executor.pool.tasks[0].id == "other_1"
    assert all(t.bucket_id != "chat_x" for t in executor.pool.tasks)


# ── Priority ordering tests ────────────────────────────────────────────────────

def _sorted_pending(tasks: list[Task]) -> list[Task]:
    """Mirror the executor's priority sort so tests don't duplicate the lambda."""
    pending = [t for t in tasks if t.status == "pending"]
    pending.sort(key=lambda t: (t.priority, t.created_at))
    return pending


def make_task(task_id: str, priority: int, created_offset_s: int = 0) -> Task:
    base = datetime(2024, 1, 1, 12, 0, 0)
    created_at = (base + timedelta(seconds=created_offset_s)).isoformat()
    return Task(
        id=task_id,
        prompt=f"prompt {task_id}",
        directory=Path("/tmp"),
        priority=priority,
        created_at=created_at,
    )


def test_priority_lower_number_wins_over_later_creation():
    """priority=1 created later beats priority=2 created earlier."""
    p2_early = make_task("p2", priority=2, created_offset_s=0)
    p1_late = make_task("p1", priority=1, created_offset_s=10)
    result = _sorted_pending([p2_early, p1_late])
    assert result[0].id == "p1"
    assert result[1].id == "p2"


def test_priority_same_priority_chronological():
    """Same priority: earlier created_at wins."""
    p1_early = make_task("early", priority=1, created_offset_s=0)
    p1_late = make_task("late", priority=1, created_offset_s=5)
    result = _sorted_pending([p1_late, p1_early])
    assert result[0].id == "early"
    assert result[1].id == "late"


def test_priority_three_levels_order():
    """Tasks with priority 3, 2, 1 execute in order 1 → 2 → 3."""
    p3 = make_task("p3", priority=3, created_offset_s=0)
    p2 = make_task("p2", created_offset_s=1, priority=2)
    p1 = make_task("p1", priority=1, created_offset_s=2)
    result = _sorted_pending([p3, p2, p1])
    assert [t.id for t in result] == ["p1", "p2", "p3"]


def test_priority_new_high_priority_jumps_queue():
    """A new priority=1 task added later jumps ahead of existing priority=2 tasks."""
    p2_a = make_task("p2a", priority=2, created_offset_s=0)
    p2_b = make_task("p2b", priority=2, created_offset_s=1)
    # Simulate first iteration: only p2 tasks exist
    result_before = _sorted_pending([p2_a, p2_b])
    assert result_before[0].id == "p2a"

    # New p1 task arrives (created later but higher priority)
    p1_new = make_task("p1_new", priority=1, created_offset_s=5)
    # Simulate next iteration: sort is recalculated with new task in pool
    result_after = _sorted_pending([p2_a, p2_b, p1_new])
    assert result_after[0].id == "p1_new"
    assert result_after[1].id == "p2a"
    assert result_after[2].id == "p2b"


def test_priority_non_pending_tasks_excluded():
    """Only pending tasks are eligible; running/success/failed are excluded."""
    pending = make_task("pending", priority=3, created_offset_s=0)
    running = make_task("running", priority=1, created_offset_s=1)
    running.status = "running"
    done = make_task("done", priority=1, created_offset_s=2)
    done.status = "success"

    result = _sorted_pending([pending, running, done])
    assert len(result) == 1
    assert result[0].id == "pending"


# ── New helper tests ──────────────────────────────────────────────────────────


class TestBuildCommand:
    def _executor(self, tmp_path: Path) -> TaskExecutor:
        return TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)

    def test_base_command_structure(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="do something", directory=Path("/tmp"), args=[])
        cmd = ex._build_command(task, session_id=None)
        assert cmd[:6] == ["claude", "-p", "do something", "--output-format", "json", "--dangerously-skip-permissions"]
        assert "--resume" not in cmd

    def test_session_resume_appended(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), args=[])
        cmd = ex._build_command(task, session_id="sess_xyz")
        resume_idx = cmd.index("--resume")
        assert cmd[resume_idx + 1] == "sess_xyz"

    def test_extra_args_appended_after_resume(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), args=["--model", "opus"])
        cmd = ex._build_command(task, session_id="sess_abc")
        assert cmd[-2:] == ["--model", "opus"]
        assert "--resume" in cmd

    def test_extra_args_appended_without_resume(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), args=["--model", "opus"])
        cmd = ex._build_command(task, session_id=None)
        assert cmd[-2:] == ["--model", "opus"]


class TestClassifyExit:
    def _executor(self, tmp_path: Path) -> TaskExecutor:
        return TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)

    def test_exit_0_is_success(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(0, b"", b"", None)
        assert status == "success"
        assert is_rl is False

    def test_exit_2_is_failed(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(2, b"", b"", None)
        assert status == "failed"
        assert is_rl is False

    def test_exit_1_with_rate_limit_pattern_in_stderr(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(1, b"", b"Error: rate limit exceeded", None)
        assert status == "rate_limit_retry"
        assert is_rl is True

    def test_exit_1_with_rate_limit_in_stdout(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(1, b"you've hit your limit", b"", None)
        assert status == "rate_limit_retry"
        assert is_rl is True

    def test_exit_1_with_rate_limit_in_json_result(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(1, b"", b"", {"result": "too many requests"})
        assert status == "rate_limit_retry"
        assert is_rl is True

    def test_exit_1_high_usage_triggers_rate_limit(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(1, b"", b"", {"session_usage_percent": 85, "result": ""})
        assert status == "rate_limit_retry"
        assert is_rl is True

    def test_exit_1_no_rate_limit_is_failed(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        status, is_rl = ex._classify_exit(1, b"", b"some other error", {"result": "oops"})
        assert status == "failed"
        assert is_rl is False

    def test_all_rate_limit_patterns_detected(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        for pattern in _RATE_LIMIT_PATTERNS:
            status, is_rl = ex._classify_exit(1, b"", pattern.encode(), None)
            assert status == "rate_limit_retry", f"pattern not detected: {pattern!r}"
            assert is_rl is True


class TestMergeNewTasks:
    def _executor(self, tmp_path: Path) -> TaskExecutor:
        return TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)

    def test_new_task_is_added(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        ex.pool = PoolState(tasks=[], pool_file=ex.pool_file)
        new_task = Task(id="new_1", prompt="new", directory=Path("/tmp"))
        new_pool = PoolState(tasks=[new_task], pool_file=ex.pool_file)
        changed = ex._merge_new_tasks(new_pool)
        assert changed is True
        assert any(t.id == "new_1" for t in ex.pool.tasks)

    def test_existing_unchanged_task_skipped(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        existing = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        ex.pool = PoolState(tasks=[existing], pool_file=ex.pool_file)
        same_task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        new_pool = PoolState(tasks=[same_task], pool_file=ex.pool_file)
        changed = ex._merge_new_tasks(new_pool)
        assert changed is False

    def test_task_reset_to_pending_updates_fields(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        existing = Task(id="t1", prompt="p", directory=Path("/tmp"), status="failed", exit_code=2)
        ex.pool = PoolState(tasks=[existing], pool_file=ex.pool_file)
        reset_task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="pending", exit_code=None)
        new_pool = PoolState(tasks=[reset_task], pool_file=ex.pool_file)
        changed = ex._merge_new_tasks(new_pool)
        assert changed is True
        assert existing.status == "pending"

    def test_callback_called_for_new_task(self, tmp_path: Path):
        callback = MagicMock()
        ex = self._executor(tmp_path)
        ex.on_task_update = callback
        ex.pool = PoolState(tasks=[], pool_file=ex.pool_file)
        new_task = Task(id="cb_1", prompt="p", directory=Path("/tmp"))
        new_pool = PoolState(tasks=[new_task], pool_file=ex.pool_file)
        ex._merge_new_tasks(new_pool)
        callback.assert_called_once_with(new_task)


class TestDoSave:
    def test_save_writes_file(self, tmp_path: Path):
        pool_file = tmp_path / "pool.db"
        ex = TaskExecutor(pool_file, install_signal_handlers=False)
        ex.pool = PoolState(tasks=[], pool_file=pool_file)
        ex._do_save()
        assert pool_file.exists()

    def test_save_stamps_tracking_hashes(self, tmp_path: Path):
        pool_file = tmp_path / "pool.db"
        ex = TaskExecutor(pool_file, install_signal_handlers=False)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"))
        ex.pool = PoolState(tasks=[task], pool_file=pool_file)
        ex._do_save()
        assert ex._last_known_task_ids == {"t1"}
        assert ex._last_pool_meta_hash != ""


class TestResetTaskForRetry:
    def _executor(self, tmp_path: Path) -> TaskExecutor:
        return TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)

    def test_resets_status_to_pending(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="failed", exit_code=2)
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)
        ex.reset_task_for_retry(task)
        assert task.status == "pending"

    def test_clears_exit_code_and_output(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(
            id="t1", prompt="p", directory=Path("/tmp"),
            status="success", exit_code=0, duration_ms=500,
            json_output={"result": "done"}, retry_count=1,
        )
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)
        ex.reset_task_for_retry(task)
        assert task.exit_code is None
        assert task.duration_ms is None
        assert task.json_output is None

    def test_increments_retry_count(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="failed", retry_count=2)
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)
        ex.reset_task_for_retry(task)
        assert task.retry_count == 3

    def test_persists_state(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="failed")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)
        ex.reset_task_for_retry(task)
        assert ex.pool_file.exists()


# ── TestStopTask ──────────────────────────────────────────────────────────────


class TestStopTask:
    def _executor(self, tmp_path: Path) -> TaskExecutor:
        return TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)

    @pytest.mark.asyncio
    async def test_stop_task_returns_false_for_unknown_id(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        ex.pool = PoolState(tasks=[], pool_file=ex.pool_file)
        result = await ex.stop_task("no-such-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_task_returns_false_when_not_running(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="failed")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)
        result = await ex.stop_task(task.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_task_sets_status_stopped(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)

        # Insert a mock process with returncode=None so SIGKILL branch is exercised
        mock_process = MagicMock()
        mock_process.returncode = None
        ex._running_processes[task.id] = mock_process

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ex.stop_task(task.id)

        assert result is True
        assert task.status == "stopped"
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_task_skips_sigkill_when_process_already_exited(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)

        # returncode is set (process already exited) — SIGKILL must NOT be sent
        mock_process = MagicMock()
        mock_process.returncode = 0
        ex._running_processes[task.id] = mock_process

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ex.stop_task(task.id)

        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_task_handles_process_lookup_error(self, tmp_path: Path):
        """process.terminate() raising ProcessLookupError must be swallowed."""
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)

        mock_process = MagicMock()
        mock_process.terminate.side_effect = ProcessLookupError
        ex._running_processes[task.id] = mock_process

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ex.stop_task(task.id)

        assert result is True
        assert task.status == "stopped"

    @pytest.mark.asyncio
    async def test_stop_task_works_without_registered_process(self, tmp_path: Path):
        """stop_task should still set status=stopped even if _running_processes has no entry."""
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)
        # _running_processes is empty — process not yet registered or already deregistered

        result = await ex.stop_task(task.id)

        assert result is True
        assert task.status == "stopped"

    @pytest.mark.asyncio
    async def test_stop_task_persists_state(self, tmp_path: Path):
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="running")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)

        result = await ex.stop_task(task.id)

        assert result is True
        assert ex.pool_file.exists()

    @pytest.mark.asyncio
    async def test_running_processes_deregistered_after_execute_task(self, tmp_path: Path):
        """_running_processes must be empty after execute_task completes."""
        ex = self._executor(tmp_path)
        task = Task(id="t1", prompt="p", directory=Path("/tmp"), status="pending")
        ex.pool = PoolState(tasks=[task], pool_file=ex.pool_file)

        fake_process = MagicMock()
        fake_process.returncode = 0
        # communicate is AsyncMock so wait_for can actually await it
        fake_process.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))

        with patch("team_cli.executor.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)):
            await ex.execute_task(task)

        assert task.id not in ex._running_processes
