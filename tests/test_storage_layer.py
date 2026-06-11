"""Storage-layer tests: WAL mode, FK constraints, CRUD round-trips, delta-writes, buckets.

All tests use real SQLite files under pytest's tmp_path — no mocking.
asyncio_mode = "auto" (set in pyproject.toml) means every async test
function is discovered and run automatically.
"""

from datetime import datetime
from pathlib import Path

import aiosqlite
import pytest

from team_cli.database import DatabaseManager
from team_cli.models import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_db(tmp_path: Path, name: str = "test.db") -> DatabaseManager:
    """Return an uninitialised DatabaseManager pointing to a unique file."""
    return DatabaseManager(tmp_path / name)


def _task(
    task_id: str = "t_001",
    status: str = "pending",
    bucket_id: str = "main",
    prompt: str = "test prompt",
) -> Task:
    return Task(
        id=task_id,
        prompt=prompt,
        directory=Path("/tmp"),
        status=status,
        bucket_id=bucket_id,
    )


def _bucket(bucket_id: str = "b_001", label: str = "Test") -> dict:
    return {
        "id": bucket_id,
        "type": "cli",
        "label": label,
        "directory": None,
        "created_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# WAL mode
# ---------------------------------------------------------------------------


class TestWALMode:
    async def test_journal_mode_is_wal(self, tmp_path: Path) -> None:
        """PRAGMA journal_mode returns 'wal' after DatabaseManager.init()."""
        db = _fresh_db(tmp_path, "wal.db")
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute("PRAGMA journal_mode") as cur:
                row = await cur.fetchone()
        assert row is not None
        assert row[0] == "wal"

    async def test_wal_mode_survives_reconnect(self, tmp_path: Path) -> None:
        """WAL mode persists across independent aiosqlite connections."""
        db = _fresh_db(tmp_path, "wal2.db")
        await db.init()

        # Open a fresh connection — WAL is stored in the DB header
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute("PRAGMA journal_mode") as cur:
                row = await cur.fetchone()
        assert row[0] == "wal"


# ---------------------------------------------------------------------------
# Foreign key constraints
# ---------------------------------------------------------------------------


class TestForeignKeyConstraints:
    async def test_fk_project_message_rejects_unknown_project(self, tmp_path: Path) -> None:
        """Inserting a project_message with a non-existent project_id raises an error when FK is ON."""
        db = _fresh_db(tmp_path, "fk_reject.db")
        await db.init()

        with pytest.raises(Exception):
            async with aiosqlite.connect(db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys=ON")
                await conn.execute(
                    "INSERT INTO project_messages (id, project_id, content, role, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("msg_bad", "proj_nonexistent", "hello", "user", datetime.now().isoformat()),
                )
                await conn.commit()

    async def test_fk_project_message_accepts_valid_project(self, tmp_path: Path) -> None:
        """Inserting a project_message with a valid project_id succeeds."""
        db = _fresh_db(tmp_path, "fk_accept.db")
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute(
                "INSERT INTO projects (id, name, directory, created_at) VALUES (?, ?, ?, ?)",
                ("proj_ok", "Test Project", "/tmp", datetime.now().isoformat()),
            )
            await conn.execute(
                "INSERT INTO project_messages (id, project_id, content, role, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("msg_ok", "proj_ok", "hello", "user", datetime.now().isoformat()),
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# Task CRUD round-trip
# ---------------------------------------------------------------------------


class TestTaskCRUD:
    async def test_upsert_and_get_round_trip(self, tmp_path: Path) -> None:
        """upsert_task then get_task returns a row with all fields intact."""
        db = _fresh_db(tmp_path, "crud.db")
        await db.init()

        task = _task("task_rt", status="pending", prompt="round-trip prompt")
        await db.upsert_task(task.to_dict())

        row = await db.get_task("task_rt")
        assert row is not None
        assert row["id"] == "task_rt"
        assert row["prompt"] == "round-trip prompt"
        assert row["status"] == "pending"
        assert row["bucket_id"] == "main"

    async def test_get_returns_none_for_missing_id(self, tmp_path: Path) -> None:
        """get_task returns None for an ID that was never inserted."""
        db = _fresh_db(tmp_path, "missing.db")
        await db.init()

        result = await db.get_task("id_does_not_exist")
        assert result is None

    async def test_upsert_stores_all_task_fields(self, tmp_path: Path) -> None:
        """Scalar and JSON fields (exit_code, priority, json_output) survive the round-trip."""
        db = _fresh_db(tmp_path, "fields.db")
        await db.init()

        task = _task("task_fields")
        task.exit_code = 0
        task.duration_ms = 1234
        task.priority = 3
        task.json_output = {"result": "ok", "tokens_used": 7}
        await db.upsert_task(task.to_dict())

        row = await db.get_task("task_fields")
        assert row["exit_code"] == 0
        assert row["duration_ms"] == 1234
        assert row["priority"] == 3
        assert isinstance(row["json_output"], dict)
        assert row["json_output"]["tokens_used"] == 7

    async def test_delete_task_removes_row(self, tmp_path: Path) -> None:
        """delete_task removes the row; subsequent get_task returns None."""
        db = _fresh_db(tmp_path, "delete.db")
        await db.init()

        task = _task("task_del")
        await db.upsert_task(task.to_dict())
        assert await db.get_task("task_del") is not None

        await db.delete_task("task_del")
        assert await db.get_task("task_del") is None


# ---------------------------------------------------------------------------
# Delta-write (second upsert updates in place)
# ---------------------------------------------------------------------------


class TestDeltaWrite:
    async def test_second_upsert_updates_status(self, tmp_path: Path) -> None:
        """A second upsert on the same ID updates the status without creating a duplicate."""
        db = _fresh_db(tmp_path, "delta.db")
        await db.init()

        task = _task("task_delta", status="pending")
        await db.upsert_task(task.to_dict())

        task.status = "success"
        task.exit_code = 0
        await db.upsert_task(task.to_dict())

        all_tasks = await db.get_all_tasks()
        matching = [t for t in all_tasks if t["id"] == "task_delta"]
        assert len(matching) == 1
        assert matching[0]["status"] == "success"
        assert matching[0]["exit_code"] == 0

    async def test_second_upsert_does_not_overwrite_created_at(self, tmp_path: Path) -> None:
        """ON CONFLICT DO UPDATE preserves created_at (it is excluded from the SET clause)."""
        db = _fresh_db(tmp_path, "created.db")
        await db.init()

        task = _task("task_ts")
        task.created_at = "2024-01-01T00:00:00"
        await db.upsert_task(task.to_dict())

        # Re-upsert with a different created_at in the dict — should be ignored
        d = task.to_dict()
        d["created_at"] = "2099-12-31T00:00:00"
        d["status"] = "success"
        await db.upsert_task(d)

        row = await db.get_task("task_ts")
        assert row["created_at"] == "2024-01-01T00:00:00"

    async def test_upsert_many_tasks_no_duplicates(self, tmp_path: Path) -> None:
        """Upserting 10 tasks then upserting them again yields exactly 10 rows."""
        db = _fresh_db(tmp_path, "many.db")
        await db.init()

        tasks = [_task(f"t_{i}", status="pending") for i in range(10)]
        for t in tasks:
            await db.upsert_task(t.to_dict())
        for t in tasks:
            t.status = "success"
            await db.upsert_task(t.to_dict())

        all_tasks = await db.get_all_tasks()
        assert len(all_tasks) == 10
        assert all(t["status"] == "success" for t in all_tasks)


# ---------------------------------------------------------------------------
# Bucket CRUD
# ---------------------------------------------------------------------------


class TestBucketCRUD:
    async def test_upsert_and_list_bucket(self, tmp_path: Path) -> None:
        """A freshly upserted bucket appears in get_all_buckets."""
        db = _fresh_db(tmp_path, "bucket.db")
        await db.init()

        await db.upsert_bucket(_bucket("b_001", "Bucket One"))

        buckets = await db.get_all_buckets()
        ids = [b["id"] for b in buckets]
        assert "b_001" in ids

    async def test_bucket_label_stored_correctly(self, tmp_path: Path) -> None:
        """Bucket label is preserved through INSERT OR REPLACE."""
        db = _fresh_db(tmp_path, "bucket_label.db")
        await db.init()

        await db.upsert_bucket(_bucket("b_lbl", "My Label"))

        buckets = await db.get_all_buckets()
        match = next(b for b in buckets if b["id"] == "b_lbl")
        assert match["label"] == "My Label"

    async def test_bucket_replace_on_duplicate_id(self, tmp_path: Path) -> None:
        """INSERT OR REPLACE: a second upsert with the same ID updates the label."""
        db = _fresh_db(tmp_path, "bucket_replace.db")
        await db.init()

        await db.upsert_bucket(_bucket("b_dup", "Old Label"))
        await db.upsert_bucket(_bucket("b_dup", "New Label"))

        buckets = await db.get_all_buckets()
        matching = [b for b in buckets if b["id"] == "b_dup"]
        assert len(matching) == 1
        assert matching[0]["label"] == "New Label"

    async def test_cascade_delete_removes_project_messages(self, tmp_path: Path) -> None:
        """Deleting a project with FK ON cascades to its project_messages."""
        db = _fresh_db(tmp_path, "cascade.db")
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute(
                "INSERT INTO projects (id, name, directory, created_at) VALUES (?, ?, ?, ?)",
                ("proj_cs", "Cascade", "/tmp", datetime.now().isoformat()),
            )
            await conn.execute(
                "INSERT INTO project_messages (id, project_id, content, role, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("msg_cs", "proj_cs", "hello", "user", datetime.now().isoformat()),
            )
            await conn.commit()

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("DELETE FROM projects WHERE id = ?", ("proj_cs",))
            await conn.commit()

            async with conn.execute(
                "SELECT id FROM project_messages WHERE id = ?", ("msg_cs",)
            ) as cur:
                row = await cur.fetchone()
        assert row is None

    async def test_multiple_buckets_all_listed(self, tmp_path: Path) -> None:
        """All inserted buckets appear in get_all_buckets."""
        db = _fresh_db(tmp_path, "multi_bucket.db")
        await db.init()

        bucket_ids = [f"bkt_{i}" for i in range(5)]
        for bid in bucket_ids:
            await db.upsert_bucket(_bucket(bid, f"Label {bid}"))

        listed_ids = {b["id"] for b in await db.get_all_buckets()}
        assert set(bucket_ids).issubset(listed_ids)
