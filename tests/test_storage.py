"""Tests for storage functions."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from claude_pool.models import Bucket, PoolState, Task
from claude_pool.storage import (
    _apply_migrations,
    _ensure_unique_id,
    _load_buckets,
    _load_tasks,
    _should_keep_task,
    cleanup_old_tasks,
    load_pool,
    save_pool,
)


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


# ── Helper function tests ──────────────────────────────────────────────────────


class TestApplyMigrations:
    def test_v0_bare_list_returns_wrapped_dict_and_needs_save(self):
        tasks = [{"id": "t1", "prompt": "p", "directory": "/tmp"}]
        data, needs_save = _apply_migrations(tasks)
        assert needs_save is True
        assert isinstance(data, dict)
        assert data["tasks"] == tasks
        assert data["pool_retry_count"] == 0
        assert data["pool_suspended_until"] is None

    def test_v1_dict_without_buckets_needs_save(self):
        v1 = {"pool_retry_count": 0, "pool_suspended_until": None, "tasks": []}
        data, needs_save = _apply_migrations(v1)
        assert needs_save is True
        assert data is v1  # same object, no copy

    def test_v2_dict_with_buckets_does_not_need_save(self):
        v2 = {"pool_retry_count": 0, "pool_suspended_until": None, "tasks": [], "buckets": {}}
        data, needs_save = _apply_migrations(v2)
        assert needs_save is False
        assert data is v2

    def test_invalid_type_raises_value_error(self):
        with pytest.raises(ValueError, match="JSON object or array"):
            _apply_migrations("not a dict or list")

    def test_integer_raises_value_error(self):
        with pytest.raises(ValueError):
            _apply_migrations(42)


class TestLoadBuckets:
    def test_empty_input_synthesises_main_bucket(self):
        buckets = _load_buckets({})
        assert "main" in buckets
        assert buckets["main"].type == "cli"

    def test_none_input_synthesises_main_bucket(self):
        buckets = _load_buckets(None)
        assert "main" in buckets

    def test_parses_chat_bucket(self):
        raw = {
            "chat_abc": {
                "id": "chat_abc",
                "type": "chat",
                "label": "My Chat",
                "directory": "/tmp",
                "created_at": "2024-01-01T00:00:00",
            }
        }
        buckets = _load_buckets(raw)
        assert "chat_abc" in buckets
        assert buckets["chat_abc"].type == "chat"
        assert buckets["chat_abc"].label == "My Chat"

    def test_injects_id_when_missing_from_bucket_data(self):
        raw = {"main": {"type": "cli", "label": "CLI / Dashboard"}}
        buckets = _load_buckets(raw)
        assert buckets["main"].id == "main"

    def test_non_dict_bucket_data_is_skipped(self):
        raw = {"bad_bucket": "not-a-dict", "main": {"type": "cli", "label": "L"}}
        buckets = _load_buckets(raw)
        assert "bad_bucket" not in buckets
        assert "main" in buckets


class TestEnsureUniqueId:
    def test_generates_id_when_missing(self):
        item: dict = {"prompt": "p", "directory": "/tmp"}
        ids: set[str] = set()
        _ensure_unique_id(item, ids)
        assert "id" in item
        assert item["id"].startswith("task_")
        assert item["id"] in ids

    def test_generates_id_when_empty_string(self):
        item: dict = {"id": "", "prompt": "p", "directory": "/tmp"}
        ids: set[str] = set()
        _ensure_unique_id(item, ids)
        assert item["id"] != ""

    def test_keeps_existing_valid_id(self):
        item: dict = {"id": "my_id", "prompt": "p", "directory": "/tmp"}
        ids: set[str] = set()
        _ensure_unique_id(item, ids)
        assert item["id"] == "my_id"

    def test_deduplicates_on_collision(self):
        item: dict = {"id": "clash", "prompt": "p", "directory": "/tmp"}
        ids: set[str] = {"clash"}
        _ensure_unique_id(item, ids)
        assert item["id"] != "clash"
        assert item["id"].startswith("clash_")

    def test_adds_id_to_existing_set(self):
        item: dict = {"id": "new_id", "prompt": "p", "directory": "/tmp"}
        ids: set[str] = set()
        _ensure_unique_id(item, ids)
        assert "new_id" in ids


class TestLoadTasks:
    def test_valid_minimal_task(self):
        raw = [{"id": "t1", "prompt": "do it", "directory": "/tmp"}]
        tasks = _load_tasks(raw)
        assert len(tasks) == 1
        assert tasks[0].id == "t1"

    def test_missing_prompt_raises_key_error(self):
        raw = [{"id": "t1", "directory": "/tmp"}]
        with pytest.raises(KeyError, match="prompt"):
            _load_tasks(raw)

    def test_missing_directory_raises_key_error(self):
        raw = [{"id": "t1", "prompt": "p"}]
        with pytest.raises(KeyError, match="directory"):
            _load_tasks(raw)

    def test_non_dict_item_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid task data"):
            _load_tasks(["not-a-dict"])

    def test_auto_generates_missing_id(self):
        raw = [{"prompt": "p", "directory": "/tmp"}]
        tasks = _load_tasks(raw)
        assert tasks[0].id.startswith("task_")

    def test_deduplicates_colliding_ids(self):
        raw = [
            {"id": "same", "prompt": "p1", "directory": "/tmp"},
            {"id": "same", "prompt": "p2", "directory": "/tmp"},
        ]
        tasks = _load_tasks(raw)
        assert tasks[0].id != tasks[1].id

    def test_defaults_optional_fields_via_task_from_dict(self):
        raw = [{"id": "t1", "prompt": "p", "directory": "/tmp"}]
        tasks = _load_tasks(raw)
        t = tasks[0]
        assert t.args == []
        assert t.status == "pending"
        assert t.exit_code is None
        assert t.retry_count == 0


class TestShouldKeepTask:
    def _task(self, status: str, age_hours: float) -> Task:
        created = (datetime.now() - timedelta(hours=age_hours)).isoformat()
        return Task(id="t", prompt="p", directory=Path("/tmp"), status=status, created_at=created)  # type: ignore[call-arg]

    def test_pending_always_kept(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("pending", age_hours=100), cutoff) is True

    def test_running_always_kept(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("running", age_hours=100), cutoff) is True

    def test_rate_limit_retry_always_kept(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("rate_limit_retry", age_hours=100), cutoff) is True

    def test_recent_success_is_kept(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("success", age_hours=1), cutoff) is True

    def test_old_success_is_removed(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("success", age_hours=72), cutoff) is False

    def test_old_failed_is_removed(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("failed", age_hours=72), cutoff) is False

    def test_old_skipped_is_removed(self):
        cutoff = datetime.now() - timedelta(hours=48)
        assert _should_keep_task(self._task("skipped", age_hours=72), cutoff) is False


class TestCleanupOldTasks:
    def _make_state(self, tasks: list[Task], pool_file: Path) -> PoolState:
        return PoolState(tasks=tasks, pool_file=pool_file)

    def test_removes_old_finished_tasks(self, temp_pool_file: Path):
        old_time = (datetime.now() - timedelta(hours=72)).isoformat()
        tasks = [
            Task(id="old", prompt="p", directory=Path("/tmp"), status="success", created_at=old_time),  # type: ignore[call-arg]
            Task(id="new", prompt="p", directory=Path("/tmp"), status="pending"),
        ]
        state = self._make_state(tasks, temp_pool_file)
        removed = cleanup_old_tasks(state, max_age_hours=48)
        assert removed == 1
        assert len(state.tasks) == 1
        assert state.tasks[0].id == "new"

    def test_returns_zero_when_nothing_removed(self, temp_pool_file: Path):
        tasks = [Task(id="t", prompt="p", directory=Path("/tmp"), status="pending")]
        state = self._make_state(tasks, temp_pool_file)
        removed = cleanup_old_tasks(state, max_age_hours=48)
        assert removed == 0
