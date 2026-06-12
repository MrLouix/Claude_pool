"""Tests for step_plans and step_tasks DB schema and migrations (Step 1)."""

import sqlite3
from pathlib import Path

import pytest

from team_cli.migrations import MIGRATIONS, apply_migrations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_base_db(path: Path) -> None:
    """Create a DB with the pre-step-planner schema (no step_plans/step_tasks)."""
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
            priority INTEGER NOT NULL DEFAULT 2,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        INSERT OR IGNORE INTO pool_meta (id) VALUES (1);
    """)
    conn.commit()
    conn.close()


def _init_full_db(path: Path) -> None:
    """Create a DB with the full current schema including step_plans and step_tasks."""
    _init_base_db(path)
    apply_migrations(str(path))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _get_columns(conn: sqlite3.Connection, table: str) -> dict[str, dict]:
    """Return column info keyed by column name from PRAGMA table_info."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1]: {"type": row[2], "notnull": row[3], "default": row[4], "pk": row[5]}
            for row in cur.fetchall()}


def _get_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Return foreign key info from PRAGMA foreign_key_list."""
    cur = conn.execute(f"PRAGMA foreign_key_list({table})")
    return [{"from": row[3], "table": row[2], "to": row[4]} for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Table existence after migrations
# ---------------------------------------------------------------------------

class TestTablesCreatedByMigrations:
    def test_step_plans_table_created(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "step_plans")
        conn.close()

    def test_step_tasks_table_created(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "step_tasks")
        conn.close()

    def test_existing_tables_unaffected(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        for table in ("pool_meta", "buckets", "tasks", "projects", "project_messages"):
            assert _table_exists(conn, table), f"{table} should still exist"
        conn.close()


# ---------------------------------------------------------------------------
# step_plans columns
# ---------------------------------------------------------------------------

class TestStepPlansColumns:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        self.conn = sqlite3.connect(str(db_path))
        self.cols = _get_columns(self.conn, "step_plans")
        yield
        self.conn.close()

    def test_id_column_is_primary_key(self):
        assert "id" in self.cols
        assert self.cols["id"]["pk"] == 1

    def test_project_id_not_null(self):
        assert "project_id" in self.cols
        assert self.cols["project_id"]["notnull"] == 1

    def test_message_id_not_null(self):
        assert "message_id" in self.cols
        assert self.cols["message_id"]["notnull"] == 1

    def test_description_not_null(self):
        assert "description" in self.cols
        assert self.cols["description"]["notnull"] == 1

    def test_status_has_default_pending(self):
        assert "status" in self.cols
        assert self.cols["status"]["notnull"] == 1
        assert self.cols["status"]["default"] == "'pending'"

    def test_created_at_not_null(self):
        assert "created_at" in self.cols
        assert self.cols["created_at"]["notnull"] == 1

    def test_completed_at_nullable(self):
        assert "completed_at" in self.cols
        assert self.cols["completed_at"]["notnull"] == 0

    def test_final_evaluation_nullable(self):
        assert "final_evaluation" in self.cols
        assert self.cols["final_evaluation"]["notnull"] == 0

    def test_all_expected_columns_present(self):
        expected = {
            "id", "project_id", "message_id", "description",
            "status", "created_at", "completed_at", "final_evaluation",
        }
        assert expected.issubset(set(self.cols.keys()))


# ---------------------------------------------------------------------------
# step_tasks columns
# ---------------------------------------------------------------------------

class TestStepTasksColumns:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        self.conn = sqlite3.connect(str(db_path))
        self.cols = _get_columns(self.conn, "step_tasks")
        yield
        self.conn.close()

    def test_id_column_is_primary_key(self):
        assert "id" in self.cols
        assert self.cols["id"]["pk"] == 1

    def test_plan_id_not_null(self):
        assert "plan_id" in self.cols
        assert self.cols["plan_id"]["notnull"] == 1

    def test_step_number_not_null(self):
        assert "step_number" in self.cols
        assert self.cols["step_number"]["notnull"] == 1

    def test_description_not_null(self):
        assert "description" in self.cols
        assert self.cols["description"]["notnull"] == 1

    def test_prompt_not_null(self):
        assert "prompt" in self.cols
        assert self.cols["prompt"]["notnull"] == 1

    def test_status_has_default_pending(self):
        assert "status" in self.cols
        assert self.cols["status"]["notnull"] == 1
        assert self.cols["status"]["default"] == "'pending'"

    def test_created_at_not_null(self):
        assert "created_at" in self.cols
        assert self.cols["created_at"]["notnull"] == 1

    def test_optional_fields_are_nullable(self):
        for col in ("cli_used", "model_used", "output", "error",
                    "tokens_used", "duration_ms", "started_at", "completed_at"):
            assert col in self.cols, f"Missing column: {col}"
            assert self.cols[col]["notnull"] == 0, f"{col} should be nullable"

    def test_all_expected_columns_present(self):
        expected = {
            "id", "plan_id", "step_number", "description", "prompt", "status",
            "cli_used", "model_used", "output", "error", "tokens_used",
            "duration_ms", "created_at", "started_at", "completed_at",
        }
        assert expected.issubset(set(self.cols.keys()))


# ---------------------------------------------------------------------------
# Foreign key constraints
# ---------------------------------------------------------------------------

class TestForeignKeys:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        self.conn = sqlite3.connect(str(db_path))
        yield
        self.conn.close()

    def test_step_plans_project_id_references_projects(self):
        fks = _get_foreign_keys(self.conn, "step_plans")
        project_fk = next((fk for fk in fks if fk["from"] == "project_id"), None)
        assert project_fk is not None
        assert project_fk["table"] == "projects"
        assert project_fk["to"] == "id"

    def test_step_plans_message_id_references_project_messages(self):
        fks = _get_foreign_keys(self.conn, "step_plans")
        msg_fk = next((fk for fk in fks if fk["from"] == "message_id"), None)
        assert msg_fk is not None
        assert msg_fk["table"] == "project_messages"
        assert msg_fk["to"] == "id"

    def test_step_tasks_plan_id_references_step_plans(self):
        fks = _get_foreign_keys(self.conn, "step_tasks")
        plan_fk = next((fk for fk in fks if fk["from"] == "plan_id"), None)
        assert plan_fk is not None
        assert plan_fk["table"] == "step_plans"
        assert plan_fk["to"] == "id"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    def test_applying_twice_does_not_raise(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        # Second run must not raise
        apply_migrations(str(db_path))

    def test_tables_still_exist_after_second_run(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "step_plans")
        assert _table_exists(conn, "step_tasks")
        conn.close()

    def test_columns_unchanged_after_second_run(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_base_db(db_path)
        apply_migrations(str(db_path))
        apply_migrations(str(db_path))
        conn = sqlite3.connect(str(db_path))
        cols_plans = _get_columns(conn, "step_plans")
        cols_tasks = _get_columns(conn, "step_tasks")
        conn.close()
        assert "id" in cols_plans
        assert "final_evaluation" in cols_plans
        assert "id" in cols_tasks
        assert "duration_ms" in cols_tasks

    def test_applying_to_full_db_skips_old_migrations(self, tmp_path):
        db_path = tmp_path / "pool.db"
        _init_full_db(db_path)
        results = apply_migrations(str(db_path))
        # Old ALTER TABLE migrations should be skipped; CREATE TABLE IF NOT EXISTS is applied
        alter_results = [r for r in results if r["id"] in ("001", "002", "003")]
        assert all(r["status"] == "skipped" for r in alter_results)


# ---------------------------------------------------------------------------
# MIGRATIONS list integrity
# ---------------------------------------------------------------------------

class TestMigrationsListHasNewEntries:
    def test_migration_004_exists(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "004" in ids

    def test_migration_005_exists(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert "005" in ids

    def test_migration_004_describes_step_plans(self):
        m = next(m for m in MIGRATIONS if m["id"] == "004")
        assert "step_plans" in m["description"].lower() or any(
            "step_plans" in sql for sql in m["sql"]
        )

    def test_migration_005_describes_step_tasks(self):
        m = next(m for m in MIGRATIONS if m["id"] == "005")
        assert "step_tasks" in m["description"].lower() or any(
            "step_tasks" in sql for sql in m["sql"]
        )

    def test_all_migration_ids_unique(self):
        ids = [m["id"] for m in MIGRATIONS]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# DatabaseManager integration
# ---------------------------------------------------------------------------

class TestDatabaseManagerCreatesNewTables:
    def test_init_creates_step_plans(self, tmp_path):
        import asyncio

        from team_cli.database import DatabaseManager

        db_path = tmp_path / "pool.db"
        mgr = DatabaseManager(db_path)
        asyncio.run(mgr.init())

        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "step_plans")
        conn.close()

    def test_init_creates_step_tasks(self, tmp_path):
        import asyncio

        from team_cli.database import DatabaseManager

        db_path = tmp_path / "pool.db"
        mgr = DatabaseManager(db_path)
        asyncio.run(mgr.init())

        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "step_tasks")
        conn.close()

    def test_init_is_idempotent(self, tmp_path):
        import asyncio

        from team_cli.database import DatabaseManager

        db_path = tmp_path / "pool.db"
        mgr = DatabaseManager(db_path)
        asyncio.run(mgr.init())
        asyncio.run(mgr.init())  # second call must not raise

        conn = sqlite3.connect(str(db_path))
        assert _table_exists(conn, "step_plans")
        assert _table_exists(conn, "step_tasks")
        conn.close()
