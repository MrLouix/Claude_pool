"""Unit tests for team_cli.database.DatabaseManager."""

from datetime import datetime
from pathlib import Path

import pytest

from team_cli.database import DatabaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(task_id: str, created_at: str = "2025-01-01T00:00:00") -> dict:
    return {
        "id": task_id,
        "prompt": f"prompt for {task_id}",
        "directory": "/tmp",
        "args": ["--model", "haiku"],
        "status": "pending",
        "exit_code": None,
        "duration_ms": None,
        "json_output": None,
        "retry_count": 0,
        "created_at": created_at,
        "session_id": None,
        "bucket_id": "main",
        "priority": 2,
        "provider": None,
        "context_messages": [],
        "rerouted_from": None,
        "rerouted_to": None,
    }


def _make_bucket(bucket_id: str = "main") -> dict:
    return {
        "id": bucket_id,
        "type": "cli",
        "label": "Main",
        "directory": None,
        "created_at": "2025-01-01T00:00:00",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_creates_tables(tmp_path: Path) -> None:
    """init() is idempotent — calling it twice raises no error."""
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    await db.init()  # second call must not raise


@pytest.mark.asyncio
async def test_default_pool_meta(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    meta = await db.get_pool_meta()
    assert meta["retry_count"] == 0
    assert meta["suspended_until"] is None
    assert meta["provider"] == "claude"


@pytest.mark.asyncio
async def test_set_pool_meta(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    await db.set_pool_meta(
        retry_count=3,
        suspended_until="2025-06-15T22:45:00",
        provider="qwen",
    )
    meta = await db.get_pool_meta()
    assert meta["retry_count"] == 3
    assert meta["suspended_until"] == "2025-06-15T22:45:00"
    assert meta["provider"] == "qwen"


@pytest.mark.asyncio
async def test_set_pool_meta_null_suspended_until(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    await db.set_pool_meta(retry_count=1, suspended_until="2025-01-01T00:00:00", provider="claude")
    await db.set_pool_meta(retry_count=0, suspended_until=None, provider="claude")
    meta = await db.get_pool_meta()
    assert meta["suspended_until"] is None


@pytest.mark.asyncio
async def test_get_all_tasks_empty(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    tasks = await db.get_all_tasks()
    assert tasks == []


@pytest.mark.asyncio
async def test_upsert_and_get_task(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    task = _make_task("task_001")
    task["args"] = ["--model", "sonnet", "--max-turns", "5"]
    task["json_output"] = {"result": "done", "tokens_used": 100}
    task["context_messages"] = [{"role": "user", "content": "hello"}]

    await db.upsert_task(task)
    result = await db.get_task("task_001")

    assert result is not None
    assert result["id"] == "task_001"
    assert result["prompt"] == "prompt for task_001"
    assert result["args"] == ["--model", "sonnet", "--max-turns", "5"]
    assert result["json_output"] == {"result": "done", "tokens_used": 100}
    assert result["context_messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_upsert_task_overwrites(tmp_path: Path) -> None:
    """Second upsert with same id replaces the first."""
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    task = _make_task("task_001")
    await db.upsert_task(task)

    task["status"] = "success"
    task["exit_code"] = 0
    task["duration_ms"] = 5000
    await db.upsert_task(task)

    result = await db.get_task("task_001")
    assert result is not None
    assert result["status"] == "success"
    assert result["exit_code"] == 0
    assert result["duration_ms"] == 5000


@pytest.mark.asyncio
async def test_get_task_returns_none_for_missing(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    result = await db.get_task("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_all_tasks_order(tmp_path: Path) -> None:
    """Tasks are returned in created_at ASC order."""
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    await db.upsert_task(_make_task("task_c", "2025-01-03T00:00:00"))
    await db.upsert_task(_make_task("task_a", "2025-01-01T00:00:00"))
    await db.upsert_task(_make_task("task_b", "2025-01-02T00:00:00"))

    tasks = await db.get_all_tasks()
    assert [t["id"] for t in tasks] == ["task_a", "task_b", "task_c"]


@pytest.mark.asyncio
async def test_delete_task(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    await db.upsert_task(_make_task("task_001"))
    await db.upsert_task(_make_task("task_002"))

    await db.delete_task("task_001")

    tasks = await db.get_all_tasks()
    ids = [t["id"] for t in tasks]
    assert "task_001" not in ids
    assert "task_002" in ids


@pytest.mark.asyncio
async def test_delete_nonexistent_task_no_error(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    await db.delete_task("ghost_task")  # must not raise


@pytest.mark.asyncio
async def test_upsert_and_get_bucket(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    bucket = _make_bucket("chat_123")
    bucket["type"] = "chat"
    bucket["label"] = "Chat session"
    bucket["directory"] = "/home/user/project"
    await db.upsert_bucket(bucket)

    buckets = await db.get_all_buckets()
    assert len(buckets) == 1
    b = buckets[0]
    assert b["id"] == "chat_123"
    assert b["type"] == "chat"
    assert b["label"] == "Chat session"
    assert b["directory"] == "/home/user/project"


@pytest.mark.asyncio
async def test_upsert_bucket_overwrites(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    await db.upsert_bucket(_make_bucket("main"))
    updated = _make_bucket("main")
    updated["label"] = "Updated label"
    await db.upsert_bucket(updated)

    buckets = await db.get_all_buckets()
    assert len(buckets) == 1
    assert buckets[0]["label"] == "Updated label"


@pytest.mark.asyncio
async def test_get_all_buckets_empty(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    assert await db.get_all_buckets() == []


@pytest.mark.asyncio
async def test_close_is_noop(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()
    await db.close()  # must not raise


@pytest.mark.asyncio
async def test_task_all_fields_roundtrip(tmp_path: Path) -> None:
    """Every task field survives a write-then-read cycle."""
    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    task = {
        "id": "task_full",
        "prompt": "Do something complex",
        "directory": "/home/user/repo",
        "args": ["--model", "opus", "--max-turns", "20"],
        "status": "success",
        "exit_code": 0,
        "duration_ms": 12345,
        "json_output": {"result": "ok", "tokens_used": 999, "session_usage_percent": 1.5},
        "retry_count": 2,
        "created_at": "2025-06-04T10:00:00",
        "session_id": "sess_abc123",
        "bucket_id": "bucket_x",
        "priority": 1,
        "provider": "qwen",
        "context_messages": [
            {"role": "user", "content": "previous prompt"},
            {"role": "assistant", "content": "previous response"},
        ],
        "rerouted_from": "task_original",
        "rerouted_to": None,
    }
    await db.upsert_task(task)
    result = await db.get_task("task_full")

    assert result is not None
    assert result["session_id"] == "sess_abc123"
    assert result["provider"] == "qwen"
    assert result["priority"] == 1
    assert result["retry_count"] == 2
    assert result["rerouted_from"] == "task_original"
    assert result["rerouted_to"] is None
    assert len(result["context_messages"]) == 2
    assert result["context_messages"][0]["role"] == "user"
    assert result["json_output"]["tokens_used"] == 999
