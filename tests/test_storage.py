"""Tests for storage functions."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from claude_pool.models import PoolState, Task
from claude_pool.storage import load_pool, save_pool


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file path."""
    return tmp_path / "test_pool.json"


@pytest.fixture
def sample_pool_data() -> dict:
    """Sample pool data for testing (new wrapped format)."""
    return {
        "pool_retry_count": 0,
        "pool_suspended_until": None,
        "tasks": [
            {
                "id": "task_001",
                "prompt": "Fix login bug",
                "directory": "/home/user/project",
                "args": ["--model", "sonnet-4"],
                "status": "pending",
                "exit_code": None,
                "duration_ms": None,
                "json_output": None,
                "retry_count": 0,
            },
            {
                "id": "task_002",
                "prompt": "Review code",
                "directory": "/home/user/project",
                "args": [],
                "status": "success",
                "exit_code": 0,
                "duration_ms": 5000,
                "json_output": {"result": "Code reviewed"},
                "retry_count": 0,
            },
        ],
    }


def test_save_pool(temp_pool_file: Path):
    """Test saving tasks to a pool file."""
    tasks = [
        Task(
            id="task_001",
            prompt="Test task",
            directory=Path("/tmp/test"),
            args=["--verbose"],
        ),
        Task(
            id="task_002",
            prompt="Another task",
            directory=Path("/tmp/test2"),
            status="success",
            exit_code=0,
        ),
    ]
    state = PoolState(tasks=tasks, pool_file=temp_pool_file)

    save_pool(state)

    assert temp_pool_file.exists()

    # Verify JSON content is wrapped
    content = json.loads(temp_pool_file.read_text())
    assert isinstance(content, dict)
    assert "tasks" in content
    assert "pool_retry_count" in content
    assert "pool_suspended_until" in content
    assert len(content["tasks"]) == 2
    assert content["tasks"][0]["id"] == "task_001"
    assert content["tasks"][1]["status"] == "success"


def test_load_pool(temp_pool_file: Path, sample_pool_data: dict):
    """Test loading tasks from a pool file."""
    temp_pool_file.write_text(json.dumps(sample_pool_data, indent=2))

    state = load_pool(temp_pool_file)

    assert isinstance(state, PoolState)
    assert len(state.tasks) == 2
    assert state.tasks[0].id == "task_001"
    assert state.tasks[0].prompt == "Fix login bug"
    assert state.tasks[0].status == "pending"
    assert state.tasks[1].id == "task_002"
    assert state.tasks[1].status == "success"
    assert state.tasks[1].exit_code == 0
    assert state.retry_count == 0
    assert state.suspended_until is None


def test_load_pool_file_not_found(temp_pool_file: Path):
    """Test loading from non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_pool(temp_pool_file)


def test_load_pool_invalid_json(temp_pool_file: Path):
    """Test loading invalid JSON raises JSONDecodeError."""
    temp_pool_file.write_text("invalid json {")

    with pytest.raises(json.JSONDecodeError):
        load_pool(temp_pool_file)


def test_load_pool_legacy_array_format(temp_pool_file: Path):
    """Test loading legacy bare-array format is automatically migrated."""
    legacy_data = [
        {
            "id": "task_001",
            "prompt": "Legacy task",
            "directory": "/tmp",
            "args": [],
            "status": "pending",
            "exit_code": None,
            "duration_ms": None,
            "json_output": None,
            "retry_count": 0,
        }
    ]
    temp_pool_file.write_text(json.dumps(legacy_data))

    state = load_pool(temp_pool_file)

    assert isinstance(state, PoolState)
    assert len(state.tasks) == 1
    assert state.tasks[0].id == "task_001"
    assert state.retry_count == 0
    assert state.suspended_until is None


def test_load_pool_suspended_until(temp_pool_file: Path):
    """Test loading pool with suspension metadata."""
    future_time = (datetime.now() + timedelta(hours=1)).isoformat()
    data = {
        "pool_retry_count": 3,
        "pool_suspended_until": future_time,
        "tasks": [],
    }
    temp_pool_file.write_text(json.dumps(data))

    state = load_pool(temp_pool_file)

    assert state.retry_count == 3
    assert state.is_suspended is True
    assert state.suspension_remaining > 3500  # ~1 hour in seconds


def test_pool_state_is_suspended(temp_pool_file: Path):
    """Test PoolState.is_suspended property."""
    future = datetime.now() + timedelta(minutes=10)
    past = datetime.now() - timedelta(minutes=10)

    state_future = PoolState(suspended_until=future, pool_file=temp_pool_file)
    state_past = PoolState(suspended_until=past, pool_file=temp_pool_file)
    state_none = PoolState(suspended_until=None, pool_file=temp_pool_file)

    assert state_future.is_suspended is True
    assert state_past.is_suspended is False
    assert state_none.is_suspended is False


def test_load_pool_missing_required_field(temp_pool_file: Path):
    """Test loading task with missing required field raises KeyError."""
    invalid_data = {
        "pool_retry_count": 0,
        "pool_suspended_until": None,
        "tasks": [
            {
                "id": "task_001",
                # Missing "prompt" and "directory"
            }
        ],
    }
    temp_pool_file.write_text(json.dumps(invalid_data))

    with pytest.raises(KeyError, match="Missing required field"):
        load_pool(temp_pool_file)


def test_save_load_roundtrip(temp_pool_file: Path):
    """Test that saving and loading preserves all task data."""
    original_tasks = [
        Task(
            id="task_001",
            prompt="Roundtrip test",
            directory=Path("/home/user/app"),
            args=["--test", "--verbose"],
            status="running",
            exit_code=None,
            duration_ms=None,
            json_output=None,
            retry_count=1,
        ),
        Task(
            id="task_002",
            prompt="Completed task",
            directory=Path("/opt/service"),
            args=[],
            status="success",
            exit_code=0,
            duration_ms=8500,
            json_output={"result": "Success", "tokens_used": 1500},
            retry_count=0,
        ),
    ]
    original_state = PoolState(
        retry_count=2,
        suspended_until=datetime.now() + timedelta(hours=1),
        tasks=original_tasks,
        pool_file=temp_pool_file,
    )

    save_pool(original_state)
    loaded_state = load_pool(temp_pool_file)

    assert len(loaded_state.tasks) == len(original_state.tasks)
    assert loaded_state.retry_count == 2
    assert loaded_state.suspended_until is not None

    for original, loaded in zip(original_state.tasks, loaded_state.tasks):
        assert loaded.id == original.id
        assert loaded.prompt == original.prompt
        assert loaded.directory == original.directory
        assert loaded.args == original.args
        assert loaded.status == original.status
        assert loaded.exit_code == original.exit_code
        assert loaded.duration_ms == original.duration_ms
        assert loaded.json_output == original.json_output
        assert loaded.retry_count == original.retry_count


def test_save_pool_creates_parent_directory(tmp_path: Path):
    """Test that save_pool creates parent directories if they don't exist."""
    nested_file = tmp_path / "subdir" / "nested" / "pool.json"

    tasks = [Task(id="task_001", prompt="Test", directory=Path("/tmp"))]
    state = PoolState(tasks=tasks, pool_file=nested_file)
    save_pool(state)

    assert nested_file.exists()
    assert nested_file.parent.exists()
