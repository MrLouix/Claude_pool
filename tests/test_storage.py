"""Tests for storage functions."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from claude_pool.models import Bucket, PoolState, Task
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
    """Test loading from non-existent file auto-creates empty pool."""
    state = load_pool(temp_pool_file)

    assert isinstance(state, PoolState)
    assert len(state.tasks) == 0
    assert temp_pool_file.exists()


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


# ---------------------------------------------------------------------------
# v2 schema — bucket migration tests
# ---------------------------------------------------------------------------


def test_v1_pool_migrates_to_v2(temp_pool_file: Path):
    """v1 format (no 'buckets' key) → tasks get bucket_id='main', 'main' bucket synthesized,
    and the file is rewritten in v2 format immediately."""
    v1_data = {
        "pool_retry_count": 0,
        "pool_suspended_until": None,
        "tasks": [
            {
                "id": "task_001",
                "prompt": "Fix bug",
                "directory": "/tmp",
                "status": "pending",
            },
        ],
    }
    temp_pool_file.write_text(json.dumps(v1_data))

    state = load_pool(temp_pool_file)

    # In-memory: bucket "main" exists and task carries bucket_id="main"
    assert "main" in state.buckets
    assert state.buckets["main"].type == "cli"
    assert state.tasks[0].bucket_id == "main"

    # On disk: file must have been rewritten as v2
    on_disk = json.loads(temp_pool_file.read_text())
    assert "buckets" in on_disk
    assert "main" in on_disk["buckets"]
    assert on_disk["tasks"][0].get("bucket_id") == "main"


def test_v2_roundtrip_preserves_buckets(temp_pool_file: Path):
    """v2 format with a custom chat bucket round-trips without mutation."""
    original_state = PoolState(
        tasks=[
            Task(id="task_001", prompt="hello", directory=Path("/tmp"), bucket_id="chat_abc"),
        ],
        pool_file=temp_pool_file,
        buckets={
            "main": Bucket(id="main", type="cli", label="CLI / Dashboard"),
            "chat_abc": Bucket(
                id="chat_abc", type="chat", label="My Feature Chat", directory="/tmp"
            ),
        },
    )
    save_pool(original_state)

    loaded = load_pool(temp_pool_file)

    assert "main" in loaded.buckets
    assert "chat_abc" in loaded.buckets
    assert loaded.buckets["chat_abc"].type == "chat"
    assert loaded.buckets["chat_abc"].label == "My Feature Chat"
    assert loaded.buckets["chat_abc"].directory == "/tmp"
    assert loaded.tasks[0].bucket_id == "chat_abc"

    # v2 file must not be treated as needing migration → file is not re-written
    # (i.e. second load round-trips cleanly without error)
    loaded2 = load_pool(temp_pool_file)
    assert "chat_abc" in loaded2.buckets
    assert loaded2.tasks[0].bucket_id == "chat_abc"


def test_v0_bare_array_migrates_to_v2(temp_pool_file: Path):
    """v0 bare-array → both tasks and buckets are correctly migrated to v2 in one pass."""
    v0_data = [
        {"id": "t1", "prompt": "task 1", "directory": "/tmp"},
        {"id": "t2", "prompt": "task 2", "directory": "/tmp"},
    ]
    temp_pool_file.write_text(json.dumps(v0_data))

    state = load_pool(temp_pool_file)

    # In-memory assertions
    assert len(state.tasks) == 2
    assert all(t.bucket_id == "main" for t in state.tasks)
    assert "main" in state.buckets

    # On-disk: written as v2 dict (not a bare array)
    on_disk = json.loads(temp_pool_file.read_text())
    assert isinstance(on_disk, dict)
    assert "buckets" in on_disk
    assert "main" in on_disk["buckets"]
    assert all(t.get("bucket_id") == "main" for t in on_disk["tasks"])


def test_pool_state_post_init_ensures_main_bucket():
    """PoolState.__post_init__ injects 'main' bucket even when buckets={} is passed."""
    state = PoolState(buckets={})
    assert "main" in state.buckets
    assert state.buckets["main"].type == "cli"


def test_save_pool_emits_buckets_key(temp_pool_file: Path):
    """save_pool always writes a 'buckets' key in the v2 layout."""
    state = PoolState(tasks=[], pool_file=temp_pool_file)
    save_pool(state)

    on_disk = json.loads(temp_pool_file.read_text())
    assert "buckets" in on_disk
    assert "main" in on_disk["buckets"]
    assert on_disk["buckets"]["main"]["type"] == "cli"
