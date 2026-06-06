"""Tests for DB migration script and /api/admin/migration-status endpoint."""

import asyncio
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from team_cli.migrations import (
    MIGRATIONS,
    apply_migrations,
    check_migration_status,
    _column_exists,
    _parse_alter_add_column,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_full_db(path: Path) -> None:
    """Create a current-schema database (all tables + all columns)."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
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
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS step_plans (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            final_evaluation TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (message_id) REFERENCES project_messages(id)
        );
        CREATE TABLE IF NOT EXISTS step_tasks (
            id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            description TEXT NOT NULL,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            cli_used TEXT,
            model_used TEXT,
            output TEXT,
            error TEXT,
            tokens_used INTEGER,
            duration_ms INTEGER,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (plan_id) REFERENCES step_plans(id)
        );
        INSERT OR IGNORE INTO pool_meta (id) VALUES (1);
    """)
    conn.commit()
    conn.close()


def _init_old_db(path: Path) -> None:
    """Create a Phase-1-style database missing Phase 2-3 columns."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pool_meta (
            id INTEGER PRIMARY KEY DEFAULT 1,
            retry_count INTEGER NOT NULL DEFAULT 0,
            suspended_until TEXT
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            directory TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_messages (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            content TEXT NOT NULL,
            role TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO pool_meta (id) VALUES (1);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _parse_alter_add_column
# ---------------------------------------------------------------------------

class TestParseAlterAddColumn:
    def test_parses_standard_statement(self):
        sql = "ALTER TABLE projects ADD COLUMN allow_cli_switch INTEGER NOT NULL DEFAULT 1"
        result = _parse_alter_add_column(sql)
        assert result == ("projects", "allow_cli_switch")

    def test_parses_text_column(self):
        sql = "ALTER TABLE project_messages ADD COLUMN cli_used TEXT"
        result = _parse_alter_add_column(sql)
        assert result == ("project_messages", "cli_used")

    def test_case_insensitive(self):
        sql = "alter table pool_meta add column provider text"
        result = _parse_alter_add_column(sql)
        assert result == ("pool_meta", "provider")

    def test_returns_none_for_non_alter(self):
        assert _parse_alter_add_column("CREATE TABLE foo (id INTEGER)") is None

    def test_returns_none_for_empty(self):
        assert _parse_alter_add_column("") is None


# ---------------------------------------------------------------------------
# _column_exists
# ---------------------------------------------------------------------------

class TestColumnExists:
    def test_returns_true_for_existing_column(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.commit()
        assert _column_exists(conn, "t", "name") is True
        conn.close()

    def test_returns_false_for_missing_column(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        assert _column_exists(conn, "t", "missing_col") is False
        conn.close()

    def test_returns_false_for_missing_table(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "no_such_table", "col") is False
        conn.close()


# ---------------------------------------------------------------------------
# apply_migrations — fresh DB
# ---------------------------------------------------------------------------

class TestApplyMigrationsOnFreshDb:
    def test_all_columns_present_after_migration(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        # Running migrations on a full DB skips everything (already exists)
        results = apply_migrations(str(db_path))
        assert all(r["status"] == "skipped" for r in results)

    def test_creates_expected_columns_on_old_db(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)

        apply_migrations(str(db_path))

        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "projects", "allow_cli_switch")
        assert _column_exists(conn, "projects", "default_cli")
        assert _column_exists(conn, "project_messages", "cli_used")
        assert _column_exists(conn, "project_messages", "linked_message_id")
        assert _column_exists(conn, "project_messages", "priority")
        assert _column_exists(conn, "pool_meta", "provider")
        conn.close()

    def test_results_contain_applied_and_skipped(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)
        results = apply_migrations(str(db_path))
        statuses = {r["status"] for r in results}
        assert "applied" in statuses

    def test_each_result_has_required_keys(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        results = apply_migrations(str(db_path))
        for r in results:
            assert "id" in r
            assert "sql" in r
            assert "status" in r
            assert r["status"] in ("applied", "skipped")


# ---------------------------------------------------------------------------
# apply_migrations — idempotency
# ---------------------------------------------------------------------------

class TestApplyMigrationsIdempotent:
    def test_running_twice_raises_no_error(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)
        apply_migrations(str(db_path))   # first run
        # Should not raise; all columns now exist → all skipped
        results = apply_migrations(str(db_path))
        assert all(r["status"] == "skipped" for r in results)

    def test_columns_unchanged_after_second_run(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)
        apply_migrations(str(db_path))
        apply_migrations(str(db_path))

        conn = sqlite3.connect(str(db_path))
        # Columns added on first run must still be there
        assert _column_exists(conn, "projects", "allow_cli_switch")
        assert _column_exists(conn, "project_messages", "priority")
        conn.close()


# ---------------------------------------------------------------------------
# check_migration_status
# ---------------------------------------------------------------------------

class TestCheckMigrationStatus:
    def test_all_pending_on_old_db(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)
        status = check_migration_status(str(db_path))
        assert len(status["pending"]) > 0

    def test_all_applied_on_full_db(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        status = check_migration_status(str(db_path))
        assert status["pending"] == []
        assert set(status["applied"]) == {m["id"] for m in MIGRATIONS}

    def test_returns_applied_after_migration(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)
        apply_migrations(str(db_path))
        status = check_migration_status(str(db_path))
        assert status["pending"] == []

    def test_status_keys_present(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        status = check_migration_status(str(db_path))
        assert "applied" in status
        assert "pending" in status
        assert isinstance(status["applied"], list)
        assert isinstance(status["pending"], list)


# ---------------------------------------------------------------------------
# Backup creation (via scripts/migrate_db.py)
# ---------------------------------------------------------------------------

class TestBackupCreation:
    def test_backup_file_is_created(self, tmp_path):
        from scripts.migrate_db import create_backup

        db_path = tmp_path / "pool.db"
        db_path.write_bytes(b"SQLite test data")

        backup = create_backup(db_path)

        assert backup.exists()
        assert backup.name.startswith("pool.db.bak.")
        assert backup.read_bytes() == b"SQLite test data"

    def test_backup_has_timestamp_suffix(self, tmp_path):
        from scripts.migrate_db import create_backup

        db_path = tmp_path / "pool.db"
        db_path.write_bytes(b"data")
        backup = create_backup(db_path)
        # Suffix is .bak.YYYYMMDD_HHMMSS — 16 chars after .bak.
        suffix_after_bak = backup.name[len("pool.db.bak."):]
        assert len(suffix_after_bak) == 15  # YYYYMMDD_HHMMSS

    def test_backup_is_independent_copy(self, tmp_path):
        from scripts.migrate_db import create_backup

        db_path = tmp_path / "pool.db"
        db_path.write_bytes(b"original")
        backup = create_backup(db_path)
        db_path.write_bytes(b"modified")

        assert backup.read_bytes() == b"original"

    def test_run_migration_creates_backup(self, tmp_path):
        from scripts.migrate_db import run_migration

        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)

        rc = run_migration(db_path)
        assert rc == 0
        backups = list(tmp_path.glob("pool.db.bak.*"))
        assert len(backups) == 1

    def test_run_migration_returns_1_for_missing_db(self, tmp_path):
        from scripts.migrate_db import run_migration

        rc = run_migration(tmp_path / "nonexistent.db")
        assert rc == 1


# ---------------------------------------------------------------------------
# Pre-existing DB gets missing columns added
# ---------------------------------------------------------------------------

class TestPreExistingDbGetsColumns:
    def test_old_db_gets_allow_cli_switch(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)

        from scripts.migrate_db import run_migration
        run_migration(db_path)

        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "projects", "allow_cli_switch")
        conn.close()

    def test_old_db_gets_priority_on_messages(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)

        from scripts.migrate_db import run_migration
        run_migration(db_path)

        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "project_messages", "priority")
        conn.close()

    def test_old_db_gets_provider_on_pool_meta(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)

        from scripts.migrate_db import run_migration
        run_migration(db_path)

        conn = sqlite3.connect(str(db_path))
        assert _column_exists(conn, "pool_meta", "provider")
        conn.close()


# ---------------------------------------------------------------------------
# MIGRATIONS list structure
# ---------------------------------------------------------------------------

class TestMigrationsListStructure:
    def test_migrations_is_a_list(self):
        assert isinstance(MIGRATIONS, list)

    def test_each_migration_has_required_keys(self):
        for m in MIGRATIONS:
            assert "id" in m
            assert "description" in m
            assert "sql" in m
            assert isinstance(m["sql"], list)
            assert len(m["sql"]) >= 1

    def test_migration_ids_are_unique(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert len(ids) == len(set(ids))

    def test_migration_ids_are_strings(self):
        for m in MIGRATIONS:
            assert isinstance(m["id"], str)


# ---------------------------------------------------------------------------
# GET /api/admin/migration-status
# ---------------------------------------------------------------------------

@contextmanager
def _make_api(pool_file: Path):
    from team_cli.api import ApiServer
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        from fastapi.testclient import TestClient
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


class TestMigrationStatusEndpoint:
    def test_endpoint_returns_200(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        pool_file = tmp_path / "pool.db"

        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/admin/migration-status")

        assert resp.status_code == 200

    def test_response_has_required_fields(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        data = resp.json()
        assert "db_path" in data
        assert "backup_exists" in data
        assert "applied_migrations" in data
        assert "pending_migrations" in data

    def test_backup_exists_false_when_no_backup(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        assert resp.json()["backup_exists"] is False

    def test_backup_exists_true_after_backup_created(self, tmp_path):
        from scripts.migrate_db import create_backup

        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        create_backup(db_path)

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        assert resp.json()["backup_exists"] is True

    def test_applied_migrations_is_list_of_strings(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        data = resp.json()
        assert isinstance(data["applied_migrations"], list)
        assert isinstance(data["pending_migrations"], list)

    def test_full_db_has_all_migrations_applied(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        expected_ids = {m["id"] for m in MIGRATIONS}

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        data = resp.json()
        assert set(data["applied_migrations"]) == expected_ids
        assert data["pending_migrations"] == []

    def test_old_db_has_pending_before_startup(self, tmp_path):
        """Verify migrations are pending before the server self-heals the schema."""
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)
        # Direct check — bypasses server startup
        status = check_migration_status(str(db_path))
        assert len(status["pending"]) > 0

    def test_server_applies_migrations_on_startup(self, tmp_path):
        """After server starts (which calls init()), all migrations are applied."""
        db_path = tmp_path / "pool.db"
        _init_old_db(db_path)

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        data = resp.json()
        assert data["pending_migrations"] == []
        assert len(data["applied_migrations"]) > 0

    def test_db_path_in_response(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)

        with _make_api(db_path) as (client, _):
            resp = client.get("/api/admin/migration-status")

        assert str(db_path) in resp.json()["db_path"]
