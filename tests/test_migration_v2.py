"""Tests for the v2 data migration: projects, chats, messages, cli_commands."""

import json
import sqlite3
from pathlib import Path

import pytest

from team_cli.migrations import (
    MIGRATIONS,
    _column_exists,
    _table_exists,
    apply_migrations,
    run_migration_v2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_v1_db(path: Path) -> None:
    """Create a minimal v1 database with buckets and tasks."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        PRAGMA foreign_keys=OFF;
        CREATE TABLE IF NOT EXISTS pool_meta (
            id INTEGER PRIMARY KEY DEFAULT 1,
            retry_count INTEGER NOT NULL DEFAULT 0,
            suspended_until TEXT,
            provider TEXT NOT NULL DEFAULT 'claude'
        );
        CREATE TABLE IF NOT EXISTS buckets (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            label TEXT NOT NULL,
            directory TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            directory TEXT NOT NULL,
            args TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            exit_code INTEGER,
            duration_ms INTEGER,
            json_output TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            session_id TEXT,
            bucket_id TEXT NOT NULL DEFAULT 'main',
            priority INTEGER NOT NULL DEFAULT 2,
            provider TEXT,
            context_messages TEXT DEFAULT '[]',
            rerouted_from TEXT,
            rerouted_to TEXT,
            model TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            directory TEXT NOT NULL,
            created_at TEXT NOT NULL,
            default_cli TEXT,
            allow_cli_switch INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS project_messages (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            content TEXT NOT NULL,
            role TEXT NOT NULL,
            cli_used TEXT,
            linked_message_id TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 2
        );
        INSERT OR IGNORE INTO pool_meta (id) VALUES (1);
    """)
    # Insert a chat bucket with a linked directory.
    conn.execute(
        "INSERT INTO buckets (id, type, label, directory, created_at) VALUES (?, ?, ?, ?, ?)",
        ("chat_abc", "chat", "My Chat", "/home/user/myproject", "2025-01-01T10:00:00"),
    )
    # Insert a CLI bucket without directory.
    conn.execute(
        "INSERT INTO buckets (id, type, label, directory, created_at) VALUES (?, ?, ?, ?, ?)",
        ("main", "cli", "CLI / Dashboard", None, "2025-01-01T00:00:00"),
    )
    # Insert tasks — some in the chat bucket, one in main.
    conn.execute(
        "INSERT INTO tasks (id, prompt, directory, bucket_id, status, created_at, json_output) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("task_001", "Fix auth module", "/home/user/myproject", "chat_abc", "success", "2025-01-01T10:01:00",
         json.dumps({"result": "Done! Auth module fixed.", "tokens": 500})),
    )
    conn.execute(
        "INSERT INTO tasks (id, prompt, directory, bucket_id, status, created_at, json_output) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("task_002", "Write tests", "/home/user/myproject", "chat_abc", "pending", "2025-01-01T10:05:00", None),
    )
    conn.execute(
        "INSERT INTO tasks (id, prompt, directory, bucket_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("task_003", "CLI standalone task", "/home/user/other", "main", "pending", "2025-01-01T11:00:00"),
    )
    conn.commit()
    conn.close()


def _apply_full_schema_migrations(db_path: Path) -> None:
    """Apply all structural migrations so the v2 tables exist."""
    apply_migrations(str(db_path))

    conn = sqlite3.connect(str(db_path))
    # Create v2 tables that migrations 008-010 would create.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            thread_root_id TEXT REFERENCES messages(id),
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            task_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cli_commands (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            binary TEXT NOT NULL,
            args_template TEXT NOT NULL,
            resume_template TEXT,
            model_flag TEXT,
            models TEXT NOT NULL DEFAULT '[]',
            default_model TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            priority_requests INTEGER NOT NULL DEFAULT 100,
            priority_subtasks INTEGER NOT NULL DEFAULT 100
        );
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# New migrations 006-010 are present in MIGRATIONS
# ---------------------------------------------------------------------------

class TestNewMigrationsRegistered:
    def test_migration_006_present(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "006" in ids

    def test_migration_007_present(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "007" in ids

    def test_migration_008_present(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "008" in ids

    def test_migration_009_present(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "009" in ids

    def test_migration_010_present(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "010" in ids

    def test_migration_006_adds_git_remote_and_archived(self):
        m = next(m for m in MIGRATIONS if m["id"] == "006")
        sql_combined = " ".join(m["sql"])
        assert "git_remote" in sql_combined
        assert "archived" in sql_combined

    def test_migration_007_adds_task_v2_columns(self):
        m = next(m for m in MIGRATIONS if m["id"] == "007")
        sql_combined = " ".join(m["sql"])
        assert "project_id" in sql_combined
        assert "chat_id" in sql_combined
        assert "parent_message_id" in sql_combined
        assert "parent_task_id" in sql_combined
        assert "kind" in sql_combined


# ---------------------------------------------------------------------------
# apply_migrations on v1 DB adds v2 structural changes
# ---------------------------------------------------------------------------

class TestApplyMigrationsV2:
    def test_adds_git_remote_to_projects(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "projects", "git_remote")
        conn.close()

    def test_adds_archived_to_projects(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "projects", "archived")
        conn.close()

    def test_adds_v2_task_columns(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        for col in ("project_id", "chat_id", "parent_message_id", "parent_task_id", "kind"):
            assert _column_exists(conn, "tasks", col), f"Missing column: {col}"
        conn.close()

    def test_creates_chats_table(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "chats")
        conn.close()

    def test_creates_messages_table(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "messages")
        conn.close()

    def test_creates_cli_commands_table(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "cli_commands")
        conn.close()

    def test_idempotent_on_v1_db(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        apply_migrations(str(db_path))
        # Second run should be all skipped (no error).
        results = apply_migrations(str(db_path))
        assert all(r["status"] == "skipped" for r in results)


# ---------------------------------------------------------------------------
# run_migration_v2 — data migration
# ---------------------------------------------------------------------------

class TestRunMigrationV2DataMigration:
    def _prepare(self, tmp_path: Path) -> Path:
        """Set up a v1 DB and apply structural migrations, return db_path."""
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        _apply_full_schema_migrations(db_path)
        return db_path

    def test_returns_result_dict(self, tmp_path):
        db_path = self._prepare(tmp_path)
        result = run_migration_v2(str(db_path))
        assert isinstance(result, dict)
        for key in ("projects_created", "chats_created", "messages_created", "cli_commands_seeded"):
            assert key in result

    def test_seeds_claude_cli_command(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id, binary FROM cli_commands WHERE id = 'claude'").fetchone()
        conn.close()
        assert row is not None
        assert row[1] == "claude"

    def test_claude_cli_seeded_only_once(self, tmp_path):
        db_path = self._prepare(tmp_path)
        r1 = run_migration_v2(str(db_path))
        r2 = run_migration_v2(str(db_path))
        assert r1["cli_commands_seeded"] == 1
        assert r2["cli_commands_seeded"] == 0  # already exists → INSERT OR IGNORE skips

    def test_claude_cli_args_template_is_valid_json(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT args_template FROM cli_commands WHERE id = 'claude'").fetchone()
        conn.close()
        assert row is not None
        parsed = json.loads(row[0])
        assert isinstance(parsed, list)
        assert "-p" in parsed
        assert "{prompt}" in parsed

    def test_creates_project_from_bucket_directory(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id FROM projects WHERE directory = '/home/user/myproject'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_creates_project_from_task_directory(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        # task_003 has directory '/home/user/other' and bucket_id 'main'
        row = conn.execute(
            "SELECT id FROM projects WHERE directory = '/home/user/other'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_creates_chat_from_chat_bucket(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id, label FROM chats WHERE id = 'chat_abc'").fetchone()
        conn.close()
        assert row is not None
        assert row[1] == "My Chat"

    def test_chat_linked_to_correct_project(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        chat = conn.execute("SELECT project_id FROM chats WHERE id = 'chat_abc'").fetchone()
        project = conn.execute(
            "SELECT id FROM projects WHERE directory = '/home/user/myproject'"
        ).fetchone()
        conn.close()
        assert chat is not None and project is not None
        assert chat[0] == project[0]

    def test_reconstructs_user_message_from_task_prompt(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT role, content FROM messages WHERE id = 'msg_user_task_001'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "user"
        assert row[1] == "Fix auth module"

    def test_reconstructs_assistant_message_from_json_output(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT role, content, task_id FROM messages WHERE id = 'msg_asst_task_001'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "assistant"
        assert "Auth module fixed" in row[1]
        assert row[2] == "task_001"

    def test_no_assistant_message_when_no_json_output(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id FROM messages WHERE id = 'msg_asst_task_002'"
        ).fetchone()
        conn.close()
        assert row is None  # task_002 has no json_output

    def test_main_bucket_tasks_do_not_create_messages(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        # task_003 is in the 'main' CLI bucket, not a chat bucket → no message
        row = conn.execute(
            "SELECT id FROM messages WHERE id = 'msg_user_task_003'"
        ).fetchone()
        conn.close()
        assert row is None

    def test_messages_linked_to_correct_chat(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT DISTINCT chat_id FROM messages"
        ).fetchall()
        conn.close()
        chat_ids = {r[0] for r in rows}
        assert "chat_abc" in chat_ids


# ---------------------------------------------------------------------------
# run_migration_v2 — idempotency
# ---------------------------------------------------------------------------

class TestRunMigrationV2Idempotency:
    def _prepare(self, tmp_path: Path) -> Path:
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        _apply_full_schema_migrations(db_path)
        return db_path

    def test_running_twice_is_safe(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        # Second run must not raise and must not duplicate rows.
        run_migration_v2(str(db_path))

    def test_no_duplicate_projects_after_second_run(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE directory = '/home/user/myproject'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_no_duplicate_chats_after_second_run(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM chats WHERE id = 'chat_abc'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_no_duplicate_messages_after_second_run(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        run_migration_v2(str(db_path))
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE id = 'msg_user_task_001'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_second_run_creates_zero_new_records(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        result2 = run_migration_v2(str(db_path))
        assert result2["projects_created"] == 0
        assert result2["chats_created"] == 0


# ---------------------------------------------------------------------------
# Backup creation
# ---------------------------------------------------------------------------

class TestRunMigrationV2Backup:
    def _prepare(self, tmp_path: Path) -> Path:
        db_path = tmp_path / "pool.db"
        _init_v1_db(db_path)
        _apply_full_schema_migrations(db_path)
        return db_path

    def test_creates_backup_on_first_run(self, tmp_path):
        db_path = self._prepare(tmp_path)
        result = run_migration_v2(str(db_path))
        assert result["backup_created"] is True
        assert (tmp_path / "pool.db.bak").exists()

    def test_skips_backup_if_already_exists(self, tmp_path):
        db_path = self._prepare(tmp_path)
        backup = tmp_path / "pool.db.bak"
        backup.write_bytes(b"existing backup")
        result = run_migration_v2(str(db_path))
        assert result["backup_created"] is False
        assert backup.read_bytes() == b"existing backup"  # untouched

    def test_backup_is_readable_sqlite(self, tmp_path):
        db_path = self._prepare(tmp_path)
        run_migration_v2(str(db_path))
        backup = tmp_path / "pool.db.bak"
        conn = sqlite3.connect(str(backup))
        # Should be able to read from backup without error.
        conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        conn.close()


# ---------------------------------------------------------------------------
# DatabaseManager.init() integrates all v2 changes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_manager_init_creates_v2_tables(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "fresh.db")
    await db.init()

    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    for table in ("chats", "messages", "cli_commands"):
        assert _table_exists(conn, table), f"Missing table: {table}"
    conn.close()


@pytest.mark.asyncio
async def test_db_manager_init_seeds_claude_cli(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "fresh.db")
    await db.init()

    commands = await db.get_all_cli_commands()
    ids = [c["id"] for c in commands]
    assert "claude" in ids


@pytest.mark.asyncio
async def test_db_manager_init_is_idempotent(tmp_path):
    from team_cli.database import DatabaseManager
    from team_cli.database import _initialized_paths

    db_path = tmp_path / "fresh.db"
    _initialized_paths.discard(str(db_path))

    db = DatabaseManager(db_path)
    await db.init()
    await db.init()  # second call must not raise

    commands = await db.get_all_cli_commands()
    # Must not have duplicate 'claude' rows.
    claude_rows = [c for c in commands if c["id"] == "claude"]
    assert len(claude_rows) == 1
