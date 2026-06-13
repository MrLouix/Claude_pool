"""Shared migration definitions for the TeamCLI SQLite database.

Each entry describes one schema change. All ALTER TABLE statements are
idempotent: running them on a database that already has the column raises
sqlite3.OperationalError which apply_migrations() silently skips.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
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
    {
        "id": "006",
        "description": "Add git_remote and archived columns to projects table (v2)",
        "sql": [
            "ALTER TABLE projects ADD COLUMN git_remote TEXT",
            "ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
        ],
    },
    {
        "id": "007",
        "description": "Add v2 task fields: project_id, chat_id, parent_message_id, parent_task_id, kind",
        "sql": [
            "ALTER TABLE tasks ADD COLUMN project_id TEXT",
            "ALTER TABLE tasks ADD COLUMN chat_id TEXT",
            "ALTER TABLE tasks ADD COLUMN parent_message_id TEXT",
            "ALTER TABLE tasks ADD COLUMN parent_task_id TEXT",
            "ALTER TABLE tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'request'",
        ],
    },
    {
        "id": "008",
        "description": "Create chats table for v2 project-based chat sessions",
        "sql": [
            """CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
)""",
        ],
    },
    {
        "id": "009",
        "description": "Create messages table for v2 thread-based messages",
        "sql": [
            """CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    chat_id         TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    thread_root_id  TEXT REFERENCES messages(id),
    role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    task_id         TEXT,
    created_at      TEXT NOT NULL
)""",
        ],
    },
    {
        "id": "010",
        "description": "Create cli_commands table for v2 multi-CLI configuration",
        "sql": [
            """CREATE TABLE IF NOT EXISTS cli_commands (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    binary            TEXT NOT NULL,
    args_template     TEXT NOT NULL,
    resume_template   TEXT,
    model_flag        TEXT,
    models            TEXT NOT NULL DEFAULT '[]',
    default_model     TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1,
    priority_requests INTEGER NOT NULL DEFAULT 100,
    priority_subtasks INTEGER NOT NULL DEFAULT 100
)""",
        ],
    },
    {
        "id": "011",
        "description": "Add parser column to cli_commands (Step 3 multi-CLI routing)",
        "sql": [
            "ALTER TABLE cli_commands ADD COLUMN parser TEXT NOT NULL DEFAULT 'claude_json'",
        ],
    },
    {
        "id": "012",
        "description": "Add cli_id column to tasks (Step 3 multi-CLI routing)",
        "sql": [
            "ALTER TABLE tasks ADD COLUMN cli_id TEXT",
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


def run_migration_v2(db_path: str) -> dict[str, Any]:
    """Migrate v1 data to v2 schema: populate projects, chats, messages, cli_commands.

    Idempotent — safe to run multiple times. Structural schema changes (new
    columns, new tables) are handled by apply_migrations(); this function only
    performs the *data* migration.

    Returns a dict summarising what was created/skipped.
    """
    db = Path(db_path)
    results: dict[str, Any] = {
        "backup_created": False,
        "backup_path": None,
        "projects_created": 0,
        "chats_created": 0,
        "messages_created": 0,
        "cli_commands_seeded": 0,
    }

    # Backup pool.db → pool.db.bak (only once; skip if already exists).
    backup_path = db.parent / f"{db.name}.bak"
    if db.exists() and not backup_path.exists():
        shutil.copy2(db, backup_path)
        results["backup_created"] = True
        results["backup_path"] = str(backup_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")

        # ── Seed cli_commands ─────────────────────────────────────────────
        affected = conn.execute(
            """
            INSERT OR IGNORE INTO cli_commands
                (id, name, binary, args_template, resume_template, model_flag,
                 models, default_model, enabled, priority_requests, priority_subtasks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "claude",
                "Claude Code",
                "claude",
                json.dumps(["-p", "{prompt}", "--output-format", "json", "--dangerously-skip-permissions"]),
                json.dumps(["--resume", "{session_id}"]),
                "--model",
                json.dumps(["haiku", "sonnet", "opus"]),
                "sonnet",
                1,
                1,
                1,
            ),
        ).rowcount
        results["cli_commands_seeded"] += affected

        # ── Build project index: directory → project_id ───────────────────
        existing_projects: dict[str, str] = {
            row[0]: row[1]
            for row in conn.execute("SELECT directory, id FROM projects").fetchall()
        }

        # Collect all directories from buckets (where set) and tasks.
        dirs_to_migrate: set[str] = set()
        bucket_rows = conn.execute(
            "SELECT id, type, label, directory, created_at FROM buckets WHERE directory IS NOT NULL"
        ).fetchall()
        for _, _, _, bdir, _ in bucket_rows:
            if bdir:
                dirs_to_migrate.add(bdir)
        for (tdir,) in conn.execute("SELECT DISTINCT directory FROM tasks").fetchall():
            dirs_to_migrate.add(tdir)

        for directory in sorted(dirs_to_migrate):  # sorted for determinism
            if directory in existing_projects:
                continue
            proj_id = "proj_" + hashlib.md5(directory.encode()).hexdigest()[:12]
            name = Path(directory).name or directory
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, name, directory, created_at) VALUES (?, ?, ?, ?)",
                (proj_id, name, directory, datetime.now().isoformat()),
            )
            existing_projects[directory] = proj_id
            results["projects_created"] += 1

        conn.commit()

        # ── Create chats from chat-type buckets ───────────────────────────
        for bucket_id, btype, blabel, bdir, bcreated in bucket_rows:
            if btype != "chat":
                continue
            proj_id = existing_projects.get(bdir) if bdir else None
            if proj_id is None:
                continue
            affected = conn.execute(
                """
                INSERT OR IGNORE INTO chats (id, project_id, label, position, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (bucket_id, proj_id, blabel, 0, bcreated),
            ).rowcount
            results["chats_created"] += affected

        conn.commit()

        # ── Reconstruct messages from tasks that belong to chat buckets ───
        # Collect known chat ids.
        chat_ids: set[str] = {
            row[0] for row in conn.execute("SELECT id FROM chats").fetchall()
        }

        task_data = conn.execute(
            "SELECT id, bucket_id, prompt, json_output, created_at FROM tasks ORDER BY created_at ASC"
        ).fetchall()

        for task_id, bucket_id, prompt, json_output_raw, task_created in task_data:
            if bucket_id not in chat_ids:
                continue

            # User message
            user_msg_id = f"msg_user_{task_id}"
            affected = conn.execute(
                """
                INSERT OR IGNORE INTO messages
                    (id, chat_id, thread_root_id, role, content, task_id, created_at)
                VALUES (?, ?, NULL, 'user', ?, NULL, ?)
                """,
                (user_msg_id, bucket_id, prompt, task_created),
            ).rowcount
            results["messages_created"] += affected

            # Assistant message (if a result exists in json_output)
            if json_output_raw:
                try:
                    jout = json.loads(json_output_raw) if isinstance(json_output_raw, str) else json_output_raw
                    result_text: str | None = None
                    if isinstance(jout, dict):
                        result_text = jout.get("result") or jout.get("content")
                        if result_text is None:
                            result_text = str(jout)
                    if result_text:
                        asst_msg_id = f"msg_asst_{task_id}"
                        affected = conn.execute(
                            """
                            INSERT OR IGNORE INTO messages
                                (id, chat_id, thread_root_id, role, content, task_id, created_at)
                            VALUES (?, ?, NULL, 'assistant', ?, ?, ?)
                            """,
                            (asst_msg_id, bucket_id, result_text, task_id, task_created),
                        ).rowcount
                        results["messages_created"] += affected
                except (json.JSONDecodeError, ValueError):
                    pass

        conn.commit()

    finally:
        conn.execute("PRAGMA foreign_keys=ON")
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
