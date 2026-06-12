"""Tests for Phase 4 Step 1: priority field on ProjectMessage, database, and API models."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from team_cli.database import DatabaseManager
from team_cli.models import ProjectMessage
from team_cli.storage import load_project_messages, save_project_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_msg(priority: int = 2, **kwargs) -> ProjectMessage:
    defaults = dict(
        id="msg_test0001",
        project_id="proj_test0001",
        content="Hello",
        role="user",
        priority=priority,
    )
    defaults.update(kwargs)
    return ProjectMessage(**defaults)


def _seed_project(db_path: Path) -> None:
    from team_cli.models import Project

    async def _run() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        proj = Project(
            id="proj_test0001",
            name="Test",
            directory=str(Path.home()),
            created_at=datetime.now(),
        )
        await db.upsert_project(proj.to_dict())

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# ProjectMessage dataclass
# ---------------------------------------------------------------------------

class TestProjectMessageModel:
    def test_default_priority_is_2(self):
        msg = _make_msg()
        assert msg.priority == 2

    def test_priority_can_be_set(self):
        msg = _make_msg(priority=1)
        assert msg.priority == 1

    def test_to_dict_includes_priority(self):
        msg = _make_msg(priority=3)
        d = msg.to_dict()
        assert "priority" in d
        assert d["priority"] == 3

    def test_from_dict_reads_priority(self):
        d = _make_msg(priority=1).to_dict()
        restored = ProjectMessage.from_dict(d)
        assert restored.priority == 1

    def test_from_dict_defaults_priority_to_2_when_missing(self):
        d = _make_msg(priority=3).to_dict()
        del d["priority"]
        restored = ProjectMessage.from_dict(d)
        assert restored.priority == 2

    def test_from_dict_coerces_string_to_int(self):
        d = _make_msg().to_dict()
        d["priority"] = "1"
        restored = ProjectMessage.from_dict(d)
        assert restored.priority == 1

    def test_roundtrip_preserves_priority_1(self):
        msg = _make_msg(priority=1)
        assert ProjectMessage.from_dict(msg.to_dict()).priority == 1

    def test_roundtrip_preserves_priority_3(self):
        msg = _make_msg(priority=3)
        assert ProjectMessage.from_dict(msg.to_dict()).priority == 3


# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------

class TestStoragePriority:
    def test_save_and_reload_preserves_priority(self, tmp_path: Path):
        db_path = tmp_path / "pool.db"
        _seed_project(db_path)

        msg = _make_msg(priority=1)
        save_project_message(db_path, msg)

        loaded = load_project_messages(db_path, "proj_test0001")
        assert len(loaded) == 1
        assert loaded[0].priority == 1

    def test_default_priority_persists(self, tmp_path: Path):
        db_path = tmp_path / "pool.db"
        _seed_project(db_path)

        msg = _make_msg()  # priority=2 default
        save_project_message(db_path, msg)

        loaded = load_project_messages(db_path, "proj_test0001")
        assert loaded[0].priority == 2

    def test_priority_3_persists(self, tmp_path: Path):
        db_path = tmp_path / "pool.db"
        _seed_project(db_path)

        save_project_message(db_path, _make_msg(id="msg_a", priority=3))
        save_project_message(db_path, _make_msg(id="msg_b", priority=1))

        messages = load_project_messages(db_path, "proj_test0001")
        by_id = {m.id: m for m in messages}
        assert by_id["msg_a"].priority == 3
        assert by_id["msg_b"].priority == 1


# ---------------------------------------------------------------------------
# DB migration
# ---------------------------------------------------------------------------

class TestDbMigration:
    def test_fresh_db_has_priority_column(self, tmp_path: Path):
        db_path = tmp_path / "pool.db"

        async def _run() -> list[str]:
            db = DatabaseManager(db_path)
            await db.init()
            async with __import__("aiosqlite").connect(db_path) as conn:
                async with conn.execute("PRAGMA table_info(project_messages)") as cur:
                    rows = await cur.fetchall()
            return [row[1] for row in rows]  # column names

        columns = asyncio.run(_run())
        assert "priority" in columns

    def test_migration_is_idempotent(self, tmp_path: Path):
        """Running init() twice should not raise (column already exists)."""
        db_path = tmp_path / "pool.db"

        async def _run() -> None:
            db = DatabaseManager(db_path)
            await db.init()
            await db.init()  # second call: ALTER TABLE should be swallowed

        asyncio.run(_run())  # must not raise

    def test_existing_db_without_priority_gets_column_added(self, tmp_path: Path):
        """Simulate an old DB missing the priority column; init() should add it."""
        import sqlite3
        db_path = tmp_path / "pool.db"

        # Create the table WITHOUT priority to simulate a legacy DB
        con = sqlite3.connect(str(db_path))
        con.execute("""
            CREATE TABLE project_messages (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                content TEXT NOT NULL,
                role TEXT NOT NULL,
                cli_used TEXT,
                linked_message_id TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS pool_meta (
                id INTEGER PRIMARY KEY,
                retry_count INTEGER NOT NULL DEFAULT 0,
                suspended_until TEXT,
                provider TEXT NOT NULL DEFAULT 'claude'
            )
        """)
        con.commit()
        con.close()

        async def _run() -> list[str]:
            db = DatabaseManager(db_path)
            await db.init()
            async with __import__("aiosqlite").connect(db_path) as conn:
                async with conn.execute("PRAGMA table_info(project_messages)") as cur:
                    rows = await cur.fetchall()
            return [row[1] for row in rows]

        columns = asyncio.run(_run())
        assert "priority" in columns


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

class TestApiModelsPriority:
    def test_project_message_input_default_priority(self):
        from team_cli.api_models import ProjectMessageInput
        m = ProjectMessageInput(content="hi")
        assert m.priority == 2

    def test_project_message_input_accepts_valid_priority(self):
        from team_cli.api_models import ProjectMessageInput
        assert ProjectMessageInput(content="hi", priority=1).priority == 1
        assert ProjectMessageInput(content="hi", priority=3).priority == 3

    def test_project_message_input_rejects_invalid_priority(self):
        from pydantic import ValidationError

        from team_cli.api_models import ProjectMessageInput
        with pytest.raises(ValidationError):
            ProjectMessageInput(content="hi", priority=6)

    def test_project_message_response_includes_priority(self):
        from team_cli.api_models import ProjectMessageResponse
        r = ProjectMessageResponse(
            id="m1", project_id="p1", content="hi", role="user",
            created_at="2026-01-01T00:00:00", priority=3,
        )
        assert r.priority == 3

    def test_project_message_response_default_priority(self):
        from team_cli.api_models import ProjectMessageResponse
        r = ProjectMessageResponse(
            id="m1", project_id="p1", content="hi", role="user",
            created_at="2026-01-01T00:00:00",
        )
        assert r.priority == 2
