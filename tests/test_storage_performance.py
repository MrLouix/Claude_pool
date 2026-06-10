"""Tests for storage bottleneck fixes (C4) and performance improvements.

Covers:
- init() idempotency: schema creation runs only once per DB path
- WAL journal mode is active after init()
- update_task_fields() issues a targeted UPDATE (immutable fields untouched)
- get_message_history() returns correct order using a single CTE query
- _thread_pool is a module-level singleton, not re-created per call
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

import team_cli.database as db_module
import team_cli.storage as storage_module
from team_cli.database import DatabaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_init_cache(db_path: Path) -> None:
    """Remove a path from the init guard so tests start clean."""
    db_module._initialized_paths.discard(str(db_path))


async def _make_db(db_path: Path) -> DatabaseManager:
    """Create and initialise a DatabaseManager, bypassing real migrations."""
    _clear_init_cache(db_path)
    db = DatabaseManager(db_path)
    with patch("team_cli.database.asyncio.to_thread", new=AsyncMock(return_value=None)):
        await db.init()
    return db


# ---------------------------------------------------------------------------
# init() idempotency
# ---------------------------------------------------------------------------


class TestInitIdempotency:
    @pytest.mark.asyncio
    async def test_second_init_does_not_open_db(self, tmp_path: Path):
        """After the first init, a second init() must not open any connection."""
        db_path = tmp_path / "idempotent.db"
        await _make_db(db_path)  # First real init

        with patch("team_cli.database.aiosqlite.connect") as mock_connect:
            with patch("team_cli.database.asyncio.to_thread", new=AsyncMock(return_value=None)):
                db = DatabaseManager(db_path)
                await db.init()  # Second call — must be a no-op

        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_paths_each_initialised(self, tmp_path: Path):
        """Two different DB paths are each initialised independently."""
        path_a = tmp_path / "a.db"
        path_b = tmp_path / "b.db"
        await _make_db(path_a)
        await _make_db(path_b)

        assert str(path_a) in db_module._initialized_paths
        assert str(path_b) in db_module._initialized_paths

    @pytest.mark.asyncio
    async def test_path_recorded_after_init(self, tmp_path: Path):
        """The DB path is added to _initialized_paths after a successful init."""
        db_path = tmp_path / "recorded.db"
        _clear_init_cache(db_path)
        assert str(db_path) not in db_module._initialized_paths
        await _make_db(db_path)
        assert str(db_path) in db_module._initialized_paths


# ---------------------------------------------------------------------------
# WAL mode
# ---------------------------------------------------------------------------


class TestWALMode:
    @pytest.mark.asyncio
    async def test_wal_mode_enabled_after_init(self, tmp_path: Path):
        """journal_mode must be 'wal' after init()."""
        db_path = tmp_path / "wal.db"
        await _make_db(db_path)

        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute("PRAGMA journal_mode") as cur:
                row = await cur.fetchone()
        assert row is not None and row[0] == "wal", f"Expected WAL, got {row}"


# ---------------------------------------------------------------------------
# update_task_fields
# ---------------------------------------------------------------------------


class TestUpdateTaskFields:
    @pytest.mark.asyncio
    async def test_updates_mutable_fields(self, tmp_path: Path):
        """update_task_fields changes the specified columns."""
        db = await _make_db(tmp_path / "upd.db")
        await db.upsert_task({
            "id": "t1",
            "prompt": "original",
            "directory": "/original",
            "created_at": "2026-01-01T00:00:00",
        })

        await db.update_task_fields("t1", status="running", exit_code=0)
        row = await db.get_task("t1")

        assert row["status"] == "running"
        assert row["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_immutable_fields_preserved(self, tmp_path: Path):
        """prompt, directory, and created_at must not be changed by update_task_fields."""
        db = await _make_db(tmp_path / "immut.db")
        await db.upsert_task({
            "id": "t2",
            "prompt": "keep this",
            "directory": "/keep",
            "created_at": "2026-01-01T00:00:00",
        })

        await db.update_task_fields("t2", status="done")
        row = await db.get_task("t2")

        assert row["prompt"] == "keep this"
        assert row["directory"] == "/keep"
        assert row["created_at"] == "2026-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_unknown_fields_silently_ignored(self, tmp_path: Path):
        """Fields not in the allowed set must be silently dropped — no exception."""
        db = await _make_db(tmp_path / "unk.db")
        await db.upsert_task({
            "id": "t3",
            "prompt": "test",
            "directory": "/tmp",
            "created_at": "2026-01-01T00:00:00",
        })

        await db.update_task_fields("t3", status="done", evil_col="hacked", prompt="pwned")
        row = await db.get_task("t3")
        assert row["status"] == "done"
        assert row["prompt"] == "test"

    @pytest.mark.asyncio
    async def test_noop_when_no_valid_fields(self, tmp_path: Path):
        """update_task_fields with only disallowed keys must be a clean no-op."""
        db = await _make_db(tmp_path / "noop.db")
        await db.upsert_task({
            "id": "t4",
            "prompt": "stable",
            "directory": "/tmp",
            "status": "pending",
            "created_at": "2026-01-01T00:00:00",
        })

        await db.update_task_fields("t4", bad_key="value")
        row = await db.get_task("t4")
        assert row["status"] == "pending"


# ---------------------------------------------------------------------------
# get_message_history — CTE-based, no N+1
# ---------------------------------------------------------------------------


class TestGetMessageHistory:
    @pytest.mark.asyncio
    async def test_returns_oldest_first(self, tmp_path: Path):
        """History must be ordered oldest → newest (depth DESC in CTE)."""
        db = await _make_db(tmp_path / "hist.db")
        for mid, linked in [("m1", None), ("m2", "m1"), ("m3", "m2")]:
            await db.upsert_project_message({
                "id": mid, "project_id": "p1", "content": mid,
                "role": "user", "linked_message_id": linked,
                "created_at": f"2026-01-01T00:00:0{mid[-1]}",
            })

        history = await db.get_message_history("m3", limit=3)
        assert [h["id"] for h in history] == ["m1", "m2", "m3"]

    @pytest.mark.asyncio
    async def test_limit_truncates_oldest(self, tmp_path: Path):
        """limit=2 should return only the 2 most recent messages."""
        db = await _make_db(tmp_path / "lim.db")
        for mid, linked in [("m1", None), ("m2", "m1"), ("m3", "m2")]:
            await db.upsert_project_message({
                "id": mid, "project_id": "p1", "content": mid,
                "role": "user", "linked_message_id": linked,
                "created_at": f"2026-01-01T00:00:0{mid[-1]}",
            })

        history = await db.get_message_history("m3", limit=2)
        assert [h["id"] for h in history] == ["m2", "m3"]

    @pytest.mark.asyncio
    async def test_single_message_chain(self, tmp_path: Path):
        """A message with no linked_message_id returns only itself."""
        db = await _make_db(tmp_path / "single.db")
        await db.upsert_project_message({
            "id": "only", "project_id": "p1", "content": "solo",
            "role": "user", "linked_message_id": None,
            "created_at": "2026-01-01T00:00:01",
        })

        history = await db.get_message_history("only", limit=3)
        assert len(history) == 1
        assert history[0]["id"] == "only"

    @pytest.mark.asyncio
    async def test_missing_message_returns_empty(self, tmp_path: Path):
        """Querying a non-existent message_id returns an empty list."""
        db = await _make_db(tmp_path / "miss.db")
        history = await db.get_message_history("nonexistent", limit=3)
        assert history == []


# ---------------------------------------------------------------------------
# Module-level thread pool singleton
# ---------------------------------------------------------------------------


class TestThreadPoolSingleton:
    def test_thread_pool_exists_at_module_level(self):
        """_thread_pool must be defined at module level in storage.py."""
        import concurrent.futures
        assert hasattr(storage_module, "_thread_pool")
        assert isinstance(storage_module._thread_pool, concurrent.futures.ThreadPoolExecutor)

    def test_same_object_across_multiple_imports(self):
        """Re-importing storage must return the same _thread_pool instance."""
        import importlib
        import team_cli.storage as s2
        assert storage_module._thread_pool is s2._thread_pool
