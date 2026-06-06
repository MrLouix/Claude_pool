"""Shared migration definitions for the TeamCLI SQLite database.

Each entry describes one schema change. All ALTER TABLE statements are
idempotent: running them on a database that already has the column raises
sqlite3.OperationalError which apply_migrations() silently skips.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------

MIGRATIONS: list[dict[str, Any]] = [
    {
        "id": "001",
        "description": "Add allow_cli_switch and default_cli to projects table",
        "sql": [
            "ALTER TABLE projects ADD COLUMN allow_cli_switch INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE projects ADD COLUMN default_cli TEXT",
        ],
    },
    {
        "id": "002",
        "description": "Add cli_used, linked_message_id, priority to project_messages table",
        "sql": [
            "ALTER TABLE project_messages ADD COLUMN cli_used TEXT",
            "ALTER TABLE project_messages ADD COLUMN linked_message_id TEXT",
            "ALTER TABLE project_messages ADD COLUMN priority INTEGER NOT NULL DEFAULT 2",
        ],
    },
    {
        "id": "003",
        "description": "Ensure pool_meta has provider column from Phase 3",
        "sql": [
            "ALTER TABLE pool_meta ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude'",
        ],
    },
    {
        "id": "004",
        "description": "Create step_plans table for multi-step coding planner skill",
        "sql": [
            """CREATE TABLE IF NOT EXISTS step_plans (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL,
    message_id       TEXT NOT NULL,
    description      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    final_evaluation TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (message_id) REFERENCES project_messages(id)
)""",
        ],
    },
    {
        "id": "005",
        "description": "Create step_tasks table for multi-step coding planner skill",
        "sql": [
            """CREATE TABLE IF NOT EXISTS step_tasks (
    id           TEXT PRIMARY KEY,
    plan_id      TEXT NOT NULL,
    step_number  INTEGER NOT NULL,
    description  TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    cli_used     TEXT,
    model_used   TEXT,
    output       TEXT,
    error        TEXT,
    tokens_used  INTEGER,
    duration_ms  INTEGER,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    FOREIGN KEY (plan_id) REFERENCES step_plans(id)
)""",
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_alter_add_column(sql: str) -> tuple[str, str] | None:
    """Extract (table_name, column_name) from an ALTER TABLE … ADD COLUMN statement."""
    m = re.match(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
        sql.strip(),
        re.IGNORECASE,
    )
    return (m.group(1), m.group(2)) if m else None


def _parse_create_table_if_not_exists(sql: str) -> str | None:
    """Extract table_name from a CREATE TABLE IF NOT EXISTS statement, or None."""
    m = re.match(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)",
        sql.strip(),
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if *column* is present in *table*."""
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())
    except sqlite3.OperationalError:
        return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True if *table* exists in the database."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def apply_migrations(db_path: str) -> list[dict[str, Any]]:
    """Run MIGRATIONS idempotently on the database at *db_path*.

    Each SQL statement that raises sqlite3.OperationalError (duplicate column
    or missing table) is recorded as "skipped". All others are "applied".

    Returns:
        List of result dicts with keys: id, sql, status ("applied"|"skipped").
    """
    results: list[dict[str, Any]] = []
    conn = sqlite3.connect(db_path)
    try:
        for migration in MIGRATIONS:
            for sql in migration["sql"]:
                # For CREATE TABLE IF NOT EXISTS: skip if the table already exists.
                table_name = _parse_create_table_if_not_exists(sql)
                if table_name is not None and _table_exists(conn, table_name):
                    results.append({"id": migration["id"], "sql": sql, "status": "skipped"})
                    continue
                try:
                    conn.execute(sql)
                    conn.commit()
                    results.append({"id": migration["id"], "sql": sql, "status": "applied"})
                except sqlite3.OperationalError:
                    results.append({"id": migration["id"], "sql": sql, "status": "skipped"})
    finally:
        conn.close()
    return results


def check_migration_status(db_path: str) -> dict[str, list[str]]:
    """Inspect the live schema and classify each migration as applied or pending.

    A migration is "applied" when every column it would add already exists in
    the database. It is "pending" when at least one column is missing.

    Returns:
        {"applied": [...migration ids...], "pending": [...migration ids...]}
    """
    applied: list[str] = []
    pending: list[str] = []

    conn = sqlite3.connect(db_path)
    try:
        for migration in MIGRATIONS:
            all_present = True
            for sql in migration["sql"]:
                # Check CREATE TABLE IF NOT EXISTS migrations.
                table_name = _parse_create_table_if_not_exists(sql)
                if table_name is not None:
                    if not _table_exists(conn, table_name):
                        all_present = False
                        break
                    continue
                # Check ALTER TABLE ADD COLUMN migrations.
                parsed = _parse_alter_add_column(sql)
                if parsed is None:
                    continue
                table, column = parsed
                if not _column_exists(conn, table, column):
                    all_present = False
                    break
            if all_present:
                applied.append(migration["id"])
            else:
                pending.append(migration["id"])
    finally:
        conn.close()

    return {"applied": applied, "pending": pending}
