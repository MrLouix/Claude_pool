"""Tests for the SQLite-backed storage layer."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from team_cli.database import DatabaseManager
from team_cli.models import Bucket, PoolState, Task
from team_cli.storage import (
    _should_keep_task,
    cleanup_old_tasks,
    load_pool,
    migrate_from_json,
    save_pool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(
    task_id: str,
    status: str = "pending",
    created_at: str | None = None,
    bucket_id: str = "main",
) -> Task:
    return Task(
        id=task_id,
        prompt=f"Prompt for {task_id}",
        directory=Path("/tmp/project"),
        args=["--model", "haiku"],
        status=status,  # type: ignore[arg-type]
        created_at=created_at or datetime.now().isoformat(),
        bucket_id=bucket_id,
    )


def _make_pool_state(tmp_path: Path, tasks: list[Task] | None = None) -> PoolState:
    return PoolState(
        pool_file=tmp_path / "pool.db",
        tasks=tasks or [],
        retry_count=0,
        provider="claude",
    )


def _write_json_pool(json_path: Path, tasks: list[dict] | None = None) -> None:
    data = {
        "pool_retry_count": 2,
        "pool_suspended_until": "2025-06-15T22:45:00",
        "provider": "qwen",
        "buckets": {
            "main": {"id": "main", "type": "cli", "label": "Main", "created_at": "2025-01-01T00:00:00"},
        },
        "tasks": tasks or [
            {
                "id": "task_json_001",
                "prompt": "Fix bug",
                "directory": "/tmp",
                "args": [],
                "status": "pending",
                "exit_code": None,
                "duration_ms": None,
                "json_output": None,
                "retry_count": 0,
                "created_at": "2025-01-01T10:00:00",
                "session_id": None,
                "bucket_id": "main",
                "priority": 2,
            }
        ],
    }
    json_path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# load_pool / save_pool roundtrip
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    task1 = _make_task("task_001", status="pending")
    task1.args = ["--model", "sonnet"]
    task1.json_output = {"result": "ok", "tokens_used": 500}

    task2 = _make_task("task_002", status="success")
    task2.exit_code = 0
    task2.duration_ms = 3000

    extra_bucket = Bucket(id="chat_abc", type="chat", label="My chat", created_at="2025-01-01T00:00:00")

    state = PoolState(
        pool_file=tmp_path / "pool.db",
        tasks=[task1, task2],
        retry_count=1,
        suspended_until=datetime.fromisoformat("2025-06-15T22:45:00"),
        buckets={
            "main": Bucket(id="main", type="cli", label="CLI / Dashboard", created_at="2025-01-01T00:00:00"),
            "chat_abc": extra_bucket,
        },
        provider="qwen",
    )

    save_pool(state)
    loaded = load_pool(tmp_path / "pool.db")

    assert loaded.retry_count == 1
    assert loaded.suspended_until == datetime.fromisoformat("2025-06-15T22:45:00")
    assert loaded.provider == "qwen"
    assert len(loaded.tasks) == 2

    t1 = next(t for t in loaded.tasks if t.id == "task_001")
    assert t1.status == "pending"
    assert t1.args == ["--model", "sonnet"]
    assert t1.json_output == {"result": "ok", "tokens_used": 500}

    t2 = next(t for t in loaded.tasks if t.id == "task_002")
    assert t2.status == "success"
    assert t2.exit_code == 0
    assert t2.duration_ms == 3000

    assert "main" in loaded.buckets
    assert "chat_abc" in loaded.buckets
    assert loaded.buckets["chat_abc"].type == "chat"


def test_load_empty_db(tmp_path: Path) -> None:
    """Loading from a fresh (non-existent) DB returns a valid empty PoolState."""
    state = load_pool(tmp_path / "pool.db")
    assert isinstance(state, PoolState)
    assert state.tasks == []
    assert state.retry_count == 0
    assert state.suspended_until is None
    assert "main" in state.buckets


def test_load_creates_db_file(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    assert not db_path.exists()
    load_pool(db_path)
    assert db_path.exists()


def test_save_persists_suspended_until_null(tmp_path: Path) -> None:
    state = _make_pool_state(tmp_path)
    state.suspended_until = datetime.fromisoformat("2025-06-15T22:45:00")
    save_pool(state)

    state.suspended_until = None
    save_pool(state)

    loaded = load_pool(tmp_path / "pool.db")
    assert loaded.suspended_until is None


# ---------------------------------------------------------------------------
# save_pool deletes tasks removed from state
# ---------------------------------------------------------------------------

def test_save_deletes_removed_tasks(tmp_path: Path) -> None:
    task_a = _make_task("task_a")
    task_b = _make_task("task_b")
    state = _make_pool_state(tmp_path, tasks=[task_a, task_b])
    save_pool(state)

    # Remove task_a from state and save again
    state.tasks = [task_b]
    save_pool(state)

    loaded = load_pool(tmp_path / "pool.db")
    ids = [t.id for t in loaded.tasks]
    assert "task_a" not in ids
    assert "task_b" in ids


def test_save_updates_existing_task(tmp_path: Path) -> None:
    task = _make_task("task_x", status="pending")
    state = _make_pool_state(tmp_path, tasks=[task])
    save_pool(state)

    task.status = "success"  # type: ignore[assignment]
    task.exit_code = 0
    save_pool(state)

    loaded = load_pool(tmp_path / "pool.db")
    assert loaded.tasks[0].status == "success"
    assert loaded.tasks[0].exit_code == 0


# ---------------------------------------------------------------------------
# cleanup_old_tasks
# ---------------------------------------------------------------------------

def test_cleanup_old_tasks_removes_old_completed(tmp_path: Path) -> None:
    old_time = (datetime.now() - timedelta(hours=72)).isoformat()
    recent_time = datetime.now().isoformat()

    old_success = _make_task("old_success", status="success", created_at=old_time)
    old_failed  = _make_task("old_failed",  status="failed",  created_at=old_time)
    old_pending = _make_task("old_pending", status="pending", created_at=old_time)
    new_success = _make_task("new_success", status="success", created_at=recent_time)

    state = _make_pool_state(tmp_path, tasks=[old_success, old_failed, old_pending, new_success])
    save_pool(state)

    removed = cleanup_old_tasks(state, max_age_hours=48)

    assert removed == 2
    ids = [t.id for t in state.tasks]
    assert "old_success" not in ids
    assert "old_failed" not in ids
    assert "old_pending" in ids   # active — never removed
    assert "new_success" in ids   # recent — kept


def test_cleanup_old_tasks_returns_count(tmp_path: Path) -> None:
    old_time = (datetime.now() - timedelta(hours=100)).isoformat()
    tasks = [
        _make_task(f"task_{i}", status="success", created_at=old_time)
        for i in range(5)
    ]
    state = _make_pool_state(tmp_path, tasks=tasks)
    save_pool(state)

    count = cleanup_old_tasks(state, max_age_hours=48)
    assert count == 5


def test_cleanup_old_tasks_removes_all_eligible_statuses(tmp_path: Path) -> None:
    old_time = (datetime.now() - timedelta(hours=72)).isoformat()
    eligible = ["success", "failed", "skipped", "stopped", "rerouted"]
    tasks = [
        _make_task(f"task_{s}", status=s, created_at=old_time)  # type: ignore[arg-type]
        for s in eligible
    ]
    state = _make_pool_state(tmp_path, tasks=tasks)
    save_pool(state)

    count = cleanup_old_tasks(state, max_age_hours=48)
    assert count == len(eligible)


def test_cleanup_old_tasks_no_op_when_nothing_to_remove(tmp_path: Path) -> None:
    task = _make_task("task_001", status="pending")
    state = _make_pool_state(tmp_path, tasks=[task])
    save_pool(state)

    count = cleanup_old_tasks(state, max_age_hours=48)
    assert count == 0
    assert len(state.tasks) == 1


def test_cleanup_old_tasks_persists_to_db(tmp_path: Path) -> None:
    old_time = (datetime.now() - timedelta(hours=72)).isoformat()
    old_task = _make_task("old", status="success", created_at=old_time)
    keep_task = _make_task("keep", status="pending")

    state = _make_pool_state(tmp_path, tasks=[old_task, keep_task])
    save_pool(state)

    cleanup_old_tasks(state, max_age_hours=48)

    # Reload from DB — old task must be gone
    loaded = load_pool(tmp_path / "pool.db")
    ids = [t.id for t in loaded.tasks]
    assert "old" not in ids
    assert "keep" in ids


# ---------------------------------------------------------------------------
# migrate_from_json
# ---------------------------------------------------------------------------

def test_migrate_from_json(tmp_path: Path) -> None:
    json_path = tmp_path / "pool.json"
    db_path = tmp_path / "pool.db"

    _write_json_pool(json_path)
    assert json_path.exists()
    assert not db_path.exists()

    # Triggering load_pool should auto-migrate
    loaded = load_pool(json_path)

    assert db_path.exists()
    assert (tmp_path / "pool.json.bak").exists()
    assert not json_path.exists()

    assert loaded.retry_count == 2
    assert loaded.provider == "qwen"
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].id == "task_json_001"


def test_migrate_from_json_direct(tmp_path: Path) -> None:
    json_path = tmp_path / "pool.json"
    db_path = tmp_path / "pool.db"

    _write_json_pool(json_path)

    result = migrate_from_json(json_path, db_path)
    assert result is True
    assert db_path.exists()
    assert (tmp_path / "pool.json.bak").exists()
    assert not json_path.exists()


def test_migrate_skips_if_db_exists(tmp_path: Path) -> None:
    json_path = tmp_path / "pool.json"
    db_path = tmp_path / "pool.db"

    _write_json_pool(json_path)
    db_path.touch()  # DB already exists

    result = migrate_from_json(json_path, db_path)
    assert result is False
    assert json_path.exists()  # json untouched


def test_migrate_skips_if_no_json(tmp_path: Path) -> None:
    result = migrate_from_json(tmp_path / "pool.json", tmp_path / "pool.db")
    assert result is False


def test_migrate_preserves_all_fields(tmp_path: Path) -> None:
    json_path = tmp_path / "pool.json"
    tasks = [
        {
            "id": "task_full",
            "prompt": "Do something",
            "directory": "/home/user/repo",
            "args": ["--model", "opus"],
            "status": "success",
            "exit_code": 0,
            "duration_ms": 5000,
            "json_output": {"result": "done", "tokens_used": 1234},
            "retry_count": 1,
            "created_at": "2025-06-04T10:00:00",
            "session_id": "sess_abc",
            "bucket_id": "main",
            "priority": 1,
        }
    ]
    _write_json_pool(json_path, tasks=tasks)
    migrate_from_json(json_path, tmp_path / "pool.db")

    loaded = load_pool(tmp_path / "pool.db")
    t = loaded.tasks[0]
    assert t.id == "task_full"
    assert t.args == ["--model", "opus"]
    assert t.exit_code == 0
    assert t.duration_ms == 5000
    assert t.json_output == {"result": "done", "tokens_used": 1234}
    assert t.session_id == "sess_abc"
    assert t.priority == 1


# ---------------------------------------------------------------------------
# _should_keep_task (logic unit test)
# ---------------------------------------------------------------------------

def test_should_keep_active_task() -> None:
    cutoff = datetime.now() - timedelta(hours=48)
    for status in ("pending", "running", "rate_limit_retry"):
        task = _make_task("t", status=status, created_at=(datetime.now() - timedelta(hours=100)).isoformat())
        assert _should_keep_task(task, cutoff) is True


def test_should_remove_old_completed_task() -> None:
    cutoff = datetime.now() - timedelta(hours=48)
    task = _make_task("t", status="success", created_at=(datetime.now() - timedelta(hours=72)).isoformat())
    assert _should_keep_task(task, cutoff) is False


def test_should_keep_recent_completed_task() -> None:
    cutoff = datetime.now() - timedelta(hours=48)
    task = _make_task("t", status="success", created_at=datetime.now().isoformat())
    assert _should_keep_task(task, cutoff) is True
