"""SQLite persistence layer for TeamCLI."""

import json
from pathlib import Path
from typing import Any

import aiosqlite

_CREATE_POOL_META = """
CREATE TABLE IF NOT EXISTS pool_meta (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    suspended_until TEXT,
    provider        TEXT NOT NULL DEFAULT 'claude'
)
"""

_CREATE_BUCKETS = """
CREATE TABLE IF NOT EXISTS buckets (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    label       TEXT NOT NULL,
    directory   TEXT,
    created_at  TEXT NOT NULL
)
"""

_CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id               TEXT PRIMARY KEY,
    prompt           TEXT NOT NULL,
    directory        TEXT NOT NULL,
    args             TEXT NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL DEFAULT 'pending',
    exit_code        INTEGER,
    duration_ms      INTEGER,
    json_output      TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    session_id       TEXT,
    bucket_id        TEXT NOT NULL DEFAULT 'main',
    priority         INTEGER NOT NULL DEFAULT 2,
    provider         TEXT,
    context_messages TEXT DEFAULT '[]',
    rerouted_from    TEXT,
    rerouted_to      TEXT,
    model            TEXT DEFAULT ''
)
"""

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    directory       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    default_cli     TEXT,
    allow_cli_switch INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_PROJECT_MESSAGES = """
CREATE TABLE IF NOT EXISTS project_messages (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    content         TEXT NOT NULL,
    role            TEXT NOT NULL,
    cli_used        TEXT,
    linked_message_id TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 2,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
)
"""

_INSERT_DEFAULT_META = """
INSERT OR IGNORE INTO pool_meta (id, retry_count, suspended_until, provider)
VALUES (1, 0, NULL, 'claude')
"""


class DatabaseManager:
    """Async SQLite backend for pool state.

    Each public method opens and closes its own connection so the instance is
    safe to share across concurrent asyncio tasks without an explicit lock.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        """Create tables and ensure the single pool_meta row exists."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(_CREATE_POOL_META)
            await db.execute(_CREATE_BUCKETS)
            await db.execute(_CREATE_TASKS)
            await db.execute(_CREATE_PROJECTS)
            await db.execute(_CREATE_PROJECT_MESSAGES)
            await db.execute(_INSERT_DEFAULT_META)
            # Migration: add priority column if it does not exist yet
            try:
                await db.execute(
                    "ALTER TABLE project_messages ADD COLUMN priority INTEGER NOT NULL DEFAULT 2"
                )
            except Exception:
                pass  # Column already exists
            await db.commit()

    # ------------------------------------------------------------------
    # Pool metadata
    # ------------------------------------------------------------------

    async def get_pool_meta(self) -> dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pool_meta WHERE id = 1") as cur:
                row = await cur.fetchone()
        if row is None:
            return {"retry_count": 0, "suspended_until": None, "provider": "claude"}
        return dict(row)

    async def set_pool_meta(
        self,
        retry_count: int,
        suspended_until: str | None,
        provider: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO pool_meta (id, retry_count, suspended_until, provider)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    retry_count     = excluded.retry_count,
                    suspended_until = excluded.suspended_until,
                    provider        = excluded.provider
                """,
                (retry_count, suspended_until, provider),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def upsert_task(self, task_dict: dict[str, Any]) -> None:
        """Insert or replace a task row. JSON fields are serialized automatically."""
        args = task_dict.get("args", [])
        json_output = task_dict.get("json_output")
        context_messages = task_dict.get("context_messages", [])

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO tasks
                    (id, prompt, directory, args, status, exit_code, duration_ms,
                     json_output, retry_count, created_at, session_id, bucket_id,
                     priority, provider, context_messages, rerouted_from, rerouted_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_dict["id"],
                    task_dict["prompt"],
                    str(task_dict["directory"]),
                    json.dumps(args) if not isinstance(args, str) else args,
                    task_dict.get("status", "pending"),
                    task_dict.get("exit_code"),
                    task_dict.get("duration_ms"),
                    json.dumps(json_output) if json_output is not None and not isinstance(json_output, str) else json_output,
                    task_dict.get("retry_count", 0),
                    task_dict["created_at"],
                    task_dict.get("session_id"),
                    task_dict.get("bucket_id", "main"),
                    task_dict.get("priority", 2),
                    task_dict.get("provider"),
                    json.dumps(context_messages) if not isinstance(context_messages, str) else context_messages,
                    task_dict.get("rerouted_from"),
                    task_dict.get("rerouted_to"),
                ),
            )
            await db.commit()

    async def get_all_tasks(self) -> list[dict[str, Any]]:
        """Return all tasks ordered by created_at ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks ORDER BY created_at ASC") as cur:
                rows = await cur.fetchall()
        return [_deserialize_task(dict(row)) for row in rows]

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return _deserialize_task(dict(row))

    async def delete_task(self, task_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await db.commit()

    # ------------------------------------------------------------------
    # Buckets
    # ------------------------------------------------------------------

    async def upsert_bucket(self, bucket_dict: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO buckets (id, type, label, directory, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    bucket_dict["id"],
                    bucket_dict["type"],
                    bucket_dict["label"],
                    bucket_dict.get("directory"),
                    bucket_dict["created_at"],
                ),
            )
            await db.commit()

    async def get_all_buckets(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM buckets") as cur:
                rows = await cur.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def upsert_project(self, project_dict: dict[str, Any]) -> None:
        """Insert or replace a project row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO projects
                    (id, name, directory, created_at, default_cli, allow_cli_switch)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_dict["id"],
                    project_dict["name"],
                    project_dict["directory"],
                    project_dict["created_at"],
                    project_dict.get("default_cli"),
                    1 if project_dict.get("allow_cli_switch", True) else 0,
                ),
            )
            await db.commit()

    async def get_all_projects(self) -> list[dict[str, Any]]:
        """Return all projects ordered by created_at ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM projects ORDER BY created_at ASC") as cur:
                rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get a single project by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return dict(row)

    async def delete_project(self, project_id: str) -> None:
        """Delete a project and all its messages (cascade)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            await db.commit()

    # ------------------------------------------------------------------
    # Project Messages
    # ------------------------------------------------------------------

    async def upsert_project_message(self, message_dict: dict[str, Any]) -> None:
        """Insert or replace a project message row. Metadata is JSON-serialized."""
        metadata = message_dict.get("metadata", {})
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO project_messages
                    (id, project_id, content, role, cli_used, linked_message_id, metadata, created_at, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_dict["id"],
                    message_dict["project_id"],
                    message_dict["content"],
                    message_dict["role"],
                    message_dict.get("cli_used"),
                    message_dict.get("linked_message_id"),
                    json.dumps(metadata) if not isinstance(metadata, str) else metadata,
                    message_dict["created_at"],
                    message_dict.get("priority", 2),
                ),
            )
            await db.commit()

    async def get_project_messages(self, project_id: str) -> list[dict[str, Any]]:
        """Return all messages for a project ordered by created_at ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM project_messages WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [_deserialize_project_message(dict(row)) for row in rows]

    async def get_project_message(self, message_id: str) -> dict[str, Any] | None:
        """Get a single project message by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM project_messages WHERE id = ?", (message_id,)
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return _deserialize_project_message(dict(row))

    async def delete_project_message(self, message_id: str) -> None:
        """Delete a single project message."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM project_messages WHERE id = ?", (message_id,))
            await db.commit()

    async def get_message_history(self, message_id: str, limit: int = 3) -> list[dict[str, Any]]:
        """Get message history by following linked_message_id chain.
        
        Returns up to `limit` messages from the chain, INCLUDING the given message_id
        and going backwards through linked_message_id.
        Results are ordered from oldest to newest.
        
        Example: If msg3 has linked_message_id=msg2, and msg2 has linked_message_id=msg1:
        - get_message_history('msg3', limit=3) returns [msg1, msg2, msg3]
        - get_message_history('msg3', limit=2) returns [msg2, msg3]
        """
        history: list[dict[str, Any]] = []
        current_id = message_id
        
        async with aiosqlite.connect(self.db_path) as db:
            for _ in range(limit):
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM project_messages WHERE id = ?", (current_id,)
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    break
                message = _deserialize_project_message(dict(row))
                # Prepend to maintain chronological order (oldest first)
                history.insert(0, message)
                # Move to parent
                current_id = message.get("linked_message_id") or ""
                if not current_id:
                    break
        
        return history

    async def close(self) -> None:
        """No-op: connections are opened/closed per operation."""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _deserialize_task(row: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON-encoded fields back to Python objects."""
    for field in ("args", "context_messages"):
        raw = row.get(field)
        if isinstance(raw, str):
            try:
                row[field] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                row[field] = []

    raw_output = row.get("json_output")
    if isinstance(raw_output, str):
        try:
            row["json_output"] = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError):
            row["json_output"] = None

    return row


def _deserialize_project_message(row: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON-encoded metadata field back to Python dict."""
    metadata_raw = row.get("metadata")
    if isinstance(metadata_raw, str):
        try:
            row["metadata"] = json.loads(metadata_raw)
        except (json.JSONDecodeError, ValueError):
            row["metadata"] = {}
    return row
