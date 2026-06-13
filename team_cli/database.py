"""SQLite persistence layer for TeamCLI."""

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite

from .migrations import apply_migrations, run_migration_v2

# Tracks DB paths that have already been fully initialised in this process.
# init() is a no-op for any path already in this set.
_initialized_paths: set[str] = set()

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
    id                TEXT PRIMARY KEY,
    prompt            TEXT NOT NULL,
    directory         TEXT NOT NULL,
    args              TEXT NOT NULL DEFAULT '[]',
    status            TEXT NOT NULL DEFAULT 'pending',
    exit_code         INTEGER,
    duration_ms       INTEGER,
    json_output       TEXT,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    session_id        TEXT,
    bucket_id         TEXT NOT NULL DEFAULT 'main',
    priority          INTEGER NOT NULL DEFAULT 2,
    provider          TEXT,
    context_messages  TEXT DEFAULT '[]',
    rerouted_from     TEXT,
    rerouted_to       TEXT,
    model             TEXT DEFAULT '',
    project_id        TEXT,
    chat_id           TEXT,
    parent_message_id TEXT,
    parent_task_id    TEXT,
    kind              TEXT NOT NULL DEFAULT 'request',
    cli_id            TEXT
)
"""

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    directory        TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    default_cli      TEXT,
    allow_cli_switch INTEGER NOT NULL DEFAULT 1,
    git_remote       TEXT,
    archived         INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_CHATS = """
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    chat_id         TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    thread_root_id  TEXT REFERENCES messages(id),
    role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    task_id         TEXT,
    created_at      TEXT NOT NULL
)
"""

_CREATE_CLI_COMMANDS = """
CREATE TABLE IF NOT EXISTS cli_commands (
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
    priority_subtasks INTEGER NOT NULL DEFAULT 100,
    parser            TEXT NOT NULL DEFAULT 'claude_json'
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

_CREATE_STEP_PLANS = """
CREATE TABLE IF NOT EXISTS step_plans (
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
)
"""

_CREATE_STEP_TASKS = """
CREATE TABLE IF NOT EXISTS step_tasks (
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
)
"""

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_INSERT_DEFAULT_META = """
INSERT OR IGNORE INTO pool_meta (id, retry_count, suspended_until, provider)
VALUES (1, 0, NULL, 'claude')
"""

_SEED_SETTINGS = [
    "INSERT OR IGNORE INTO settings (key, value) VALUES ('max_subtasks_per_task', '10')",
    "INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_decompose', 'true')",
]

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tasks_status        ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_bucket_id     ON tasks(bucket_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_created_at    ON tasks(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_priority      ON tasks(priority)",
    "CREATE INDEX IF NOT EXISTS idx_step_plans_status   ON step_plans(status)",
    "CREATE INDEX IF NOT EXISTS idx_step_tasks_plan_id  ON step_tasks(plan_id)",
    "CREATE INDEX IF NOT EXISTS idx_step_tasks_status   ON step_tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_messages_chat       ON messages(chat_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_messages_thread     ON messages(thread_root_id)",
    "CREATE INDEX IF NOT EXISTS idx_chats_project       ON chats(project_id, position)",
]

_SEED_CLAUDE_CLI = """
INSERT INTO cli_commands
    (id, name, binary, args_template, resume_template, model_flag,
     models, default_model, enabled, priority_requests, priority_subtasks, parser)
VALUES (
    'claude', 'Claude Code', 'claude',
    '["-p","{prompt}","--output-format","json","--dangerously-skip-permissions"]',
    '["--resume","{session_id}"]',
    '--model',
    '["haiku","sonnet","opus"]',
    'sonnet',
    1, 1, 1, 'claude_json'
)
ON CONFLICT(id) DO UPDATE SET parser = 'claude_json'
"""


class DatabaseManager:
    """Async SQLite backend for pool state.

    Each public method opens and closes its own connection so the instance is
    safe to share across concurrent asyncio tasks without an explicit lock.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        """Create tables, self-heal any missing columns, then seed default rows.

        Idempotent within a process: the second call for the same path is a
        no-op so callers do not need to guard against double-initialisation.
        """
        path_key = str(self.db_path)
        if path_key in _initialized_paths:
            return

        # Phase 1: WAL mode, performance PRAGMAs, and schema creation.
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA cache_size=-64000")
            await db.execute(_CREATE_POOL_META)
            await db.execute(_CREATE_BUCKETS)
            await db.execute(_CREATE_TASKS)
            await db.execute(_CREATE_PROJECTS)
            await db.execute(_CREATE_PROJECT_MESSAGES)
            await db.execute(_CREATE_STEP_PLANS)
            await db.execute(_CREATE_STEP_TASKS)
            # v2 tables
            await db.execute(_CREATE_CHATS)
            await db.execute(_CREATE_MESSAGES)
            await db.execute(_CREATE_CLI_COMMANDS)
            await db.execute(_CREATE_SETTINGS)
            for idx_sql in _CREATE_INDEXES:
                await db.execute(idx_sql)
            await db.commit()

        # Phase 2: add any columns that were introduced after the DB was created.
        # Must run before the INSERT so seeding uses the fully-migrated schema.
        await asyncio.to_thread(apply_migrations, str(self.db_path))

        # Phase 3: seed the single pool_meta row, default CLI command, and settings.
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(_INSERT_DEFAULT_META)
            await db.execute(_SEED_CLAUDE_CLI)
            for seed_sql in _SEED_SETTINGS:
                await db.execute(seed_sql)
            await db.commit()

        # Phase 4: data migration v1 → v2 (idempotent).
        await asyncio.to_thread(run_migration_v2, str(self.db_path))

        _initialized_paths.add(path_key)

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
        """Insert or update a task row. JSON fields are serialized automatically.

        Uses ON CONFLICT DO UPDATE so existing rows are updated in-place
        (no DELETE+INSERT) and created_at is never overwritten.
        """
        args = task_dict.get("args", [])
        json_output = task_dict.get("json_output")
        context_messages = task_dict.get("context_messages", [])

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tasks
                    (id, prompt, directory, args, status, exit_code, duration_ms,
                     json_output, retry_count, created_at, session_id, bucket_id,
                     priority, provider, context_messages, rerouted_from, rerouted_to,
                     model, project_id, chat_id, parent_message_id, parent_task_id, kind,
                     cli_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    prompt            = excluded.prompt,
                    directory         = excluded.directory,
                    args              = excluded.args,
                    status            = excluded.status,
                    exit_code         = excluded.exit_code,
                    duration_ms       = excluded.duration_ms,
                    json_output       = excluded.json_output,
                    retry_count       = excluded.retry_count,
                    session_id        = excluded.session_id,
                    bucket_id         = excluded.bucket_id,
                    priority          = excluded.priority,
                    provider          = excluded.provider,
                    context_messages  = excluded.context_messages,
                    rerouted_from     = excluded.rerouted_from,
                    rerouted_to       = excluded.rerouted_to,
                    model             = excluded.model,
                    project_id        = excluded.project_id,
                    chat_id           = excluded.chat_id,
                    parent_message_id = excluded.parent_message_id,
                    parent_task_id    = excluded.parent_task_id,
                    kind              = excluded.kind,
                    cli_id            = excluded.cli_id
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
                    task_dict.get("model", ""),
                    task_dict.get("project_id"),
                    task_dict.get("chat_id"),
                    task_dict.get("parent_message_id"),
                    task_dict.get("parent_task_id"),
                    task_dict.get("kind", "request"),
                    task_dict.get("cli_id"),
                ),
            )
            await db.commit()

    async def update_task_fields(self, task_id: str, **fields: Any) -> None:
        """Update only the specified mutable fields of a task row.

        Emits a single targeted UPDATE — no DELETE+INSERT overhead.
        Immutable fields (id, prompt, directory, created_at) are silently ignored.
        """
        _ALLOWED = frozenset({  # noqa: N806
            "status", "exit_code", "duration_ms", "json_output", "retry_count",
            "session_id", "bucket_id", "priority", "provider", "context_messages",
            "rerouted_from", "rerouted_to", "model",
            "project_id", "chat_id", "parent_message_id", "parent_task_id", "kind",
            "cli_id",
        })
        updates = {k: v for k, v in fields.items() if k in _ALLOWED}
        if not updates:
            return
        for field in ("json_output", "context_messages"):
            if field in updates and not isinstance(updates[field], (str, type(None))):
                updates[field] = json.dumps(updates[field])
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = list(updates.values()) + [task_id]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ?",  # noqa: S608
                values,
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
                    (id, name, directory, created_at, default_cli, allow_cli_switch,
                     git_remote, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_dict["id"],
                    project_dict["name"],
                    project_dict["directory"],
                    project_dict["created_at"],
                    project_dict.get("default_cli"),
                    1 if project_dict.get("allow_cli_switch", True) else 0,
                    project_dict.get("git_remote"),
                    1 if project_dict.get("archived", False) else 0,
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

        Uses a single recursive CTE query instead of N+1 individual SELECTs.
        Returns up to `limit` messages ordered oldest-first.

        Example: If msg3 has linked_message_id=msg2, and msg2 has linked_message_id=msg1:
        - get_message_history('msg3', limit=3) returns [msg1, msg2, msg3]
        - get_message_history('msg3', limit=2) returns [msg2, msg3]
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                WITH RECURSIVE chain AS (
                    SELECT *, 0 AS depth FROM project_messages WHERE id = ?
                    UNION ALL
                    SELECT pm.*, chain.depth + 1
                    FROM project_messages pm
                    JOIN chain ON pm.id = chain.linked_message_id
                    WHERE chain.depth < ?
                )
                SELECT id, project_id, content, role, cli_used, linked_message_id,
                       metadata, created_at, priority
                FROM chain ORDER BY depth DESC
                """,
                (message_id, limit - 1),
            ) as cur:
                rows = await cur.fetchall()
        return [_deserialize_project_message(dict(row)) for row in rows]

    # ------------------------------------------------------------------
    # Chats (v2)
    # ------------------------------------------------------------------

    async def upsert_chat(self, chat_dict: dict[str, Any]) -> None:
        """Insert or replace a chat row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO chats (id, project_id, label, position, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chat_dict["id"],
                    chat_dict["project_id"],
                    chat_dict["label"],
                    chat_dict.get("position", 0),
                    chat_dict["created_at"],
                ),
            )
            await db.commit()

    async def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        """Get a single chat by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)) as cur:
                row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def get_chats_for_project(self, project_id: str) -> list[dict[str, Any]]:
        """Return all chats for a project ordered by position ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM chats WHERE project_id = ? ORDER BY position ASC, created_at ASC",
                (project_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete_chat(self, chat_id: str) -> None:
        """Delete a chat (cascades to messages)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            await db.commit()

    # ------------------------------------------------------------------
    # Messages (v2)
    # ------------------------------------------------------------------

    async def upsert_message(self, message_dict: dict[str, Any]) -> None:
        """Insert or replace a message row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO messages
                    (id, chat_id, thread_root_id, role, content, task_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_dict["id"],
                    message_dict["chat_id"],
                    message_dict.get("thread_root_id"),
                    message_dict["role"],
                    message_dict["content"],
                    message_dict.get("task_id"),
                    message_dict["created_at"],
                ),
            )
            await db.commit()

    async def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Get a single message by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)) as cur:
                row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def get_messages_for_chat(
        self,
        chat_id: str,
        thread_root_id: str | None = None,
        limit: int | None = None,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return messages for a chat, optionally filtered by thread.

        thread_root_id=None   → main-thread messages (thread_root_id IS NULL).
        thread_root_id=<id>   → reply messages for that thread root.
        before_id             → return messages with created_at < that message's timestamp.
        limit                 → cap number of results.
        Results are ordered created_at ASC.
        """
        params: list[Any] = [chat_id]
        where = "chat_id = ?"

        if thread_root_id is None:
            where += " AND thread_root_id IS NULL"
        else:
            where += " AND thread_root_id = ?"
            params.append(thread_root_id)

        if before_id is not None:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT created_at FROM messages WHERE id = ?", (before_id,)
                ) as cur:
                    row = await cur.fetchone()
            if row:
                where += " AND created_at < ?"
                params.append(row[0])

        order = "ORDER BY created_at ASC"
        if limit is not None:
            order += f" LIMIT {int(limit)}"

        sql = f"SELECT * FROM messages WHERE {where} {order}"  # noqa: S608
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_thread_replies(self, thread_root_id: str) -> int:
        """Return the number of reply messages for a given thread root."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE thread_root_id = ?", (thread_root_id,)
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def delete_message(self, message_id: str) -> None:
        """Delete a single message."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            await db.commit()

    # ------------------------------------------------------------------
    # CliCommands (v2)
    # ------------------------------------------------------------------

    async def upsert_cli_command(self, cmd_dict: dict[str, Any]) -> None:
        """Insert or replace a cli_commands row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO cli_commands
                    (id, name, binary, args_template, resume_template, model_flag,
                     models, default_model, enabled, priority_requests, priority_subtasks,
                     parser)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cmd_dict["id"],
                    cmd_dict["name"],
                    cmd_dict["binary"],
                    cmd_dict["args_template"],
                    cmd_dict.get("resume_template"),
                    cmd_dict.get("model_flag"),
                    cmd_dict.get("models", "[]"),
                    cmd_dict.get("default_model"),
                    1 if cmd_dict.get("enabled", True) else 0,
                    cmd_dict.get("priority_requests", 100),
                    cmd_dict.get("priority_subtasks", 100),
                    cmd_dict.get("parser", "claude_json"),
                ),
            )
            await db.commit()

    async def get_cli_command(self, cmd_id: str) -> dict[str, Any] | None:
        """Get a single cli_command by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM cli_commands WHERE id = ?", (cmd_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def get_all_cli_commands(self) -> list[dict[str, Any]]:
        """Return all cli_commands ordered by priority_requests ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM cli_commands ORDER BY priority_requests ASC, id ASC"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete_cli_command(self, cmd_id: str) -> None:
        """Delete a cli_command by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM cli_commands WHERE id = ?", (cmd_id,))
            await db.commit()

    async def nullify_project_tasks(self, project_id: str) -> None:
        """Set project_id = NULL on all tasks that belong to *project_id*."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE tasks SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Settings (key-value store)
    # ------------------------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        """Return the value for *key*, or None if not set."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row is not None else None

    async def set_setting(self, key: str, value: str) -> None:
        """Upsert a single setting key-value pair."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            await db.commit()

    async def get_all_settings(self) -> dict[str, str]:
        """Return all settings as a plain dict."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT key, value FROM settings ORDER BY key ASC") as cur:
                rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}

    async def close(self) -> None:
        """No-op: connections are opened/closed per operation."""

    # ------------------------------------------------------------------
    # Step Plans
    # ------------------------------------------------------------------

    async def upsert_step_plan(self, plan_dict: dict[str, Any]) -> None:
        """Insert or replace a step_plan row. final_evaluation is JSON-serialized."""
        final_eval = plan_dict.get("final_evaluation")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO step_plans
                    (id, project_id, message_id, description, status,
                     created_at, completed_at, final_evaluation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_dict["id"],
                    plan_dict["project_id"],
                    plan_dict["message_id"],
                    plan_dict["description"],
                    plan_dict.get("status", "pending"),
                    plan_dict["created_at"],
                    plan_dict.get("completed_at"),
                    json.dumps(final_eval) if final_eval is not None and not isinstance(final_eval, str) else final_eval,
                ),
            )
            await db.commit()

    async def get_step_plan(self, plan_id: str) -> dict[str, Any] | None:
        """Fetch a single step_plan row by id, or None."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM step_plans WHERE id = ?", (plan_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def get_step_plans_for_message(self, message_id: str) -> list[dict[str, Any]]:
        """Return all step_plans for a given message_id, ordered by created_at ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM step_plans WHERE message_id = ? ORDER BY created_at ASC",
                (message_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_step_plan(
        self,
        plan_id: str,
        status: str,
        completed_at: str | None = None,
        final_evaluation: str | None = None,
    ) -> None:
        """Update status and optional fields on a step_plan row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE step_plans
                SET status = ?,
                    completed_at = COALESCE(?, completed_at),
                    final_evaluation = COALESCE(?, final_evaluation)
                WHERE id = ?
                """,
                (status, completed_at, final_evaluation, plan_id),
            )
            await db.commit()

    async def delete_step_plan(self, plan_id: str) -> None:
        """Delete a step_plan and all its step_tasks."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM step_tasks WHERE plan_id = ?", (plan_id,))
            await db.execute("DELETE FROM step_plans WHERE id = ?", (plan_id,))
            await db.commit()

    # ------------------------------------------------------------------
    # Step Tasks
    # ------------------------------------------------------------------

    async def upsert_step_task(self, task_dict: dict[str, Any]) -> None:
        """Insert or replace a step_task row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO step_tasks
                    (id, plan_id, step_number, description, prompt, status,
                     cli_used, model_used, output, error, tokens_used, duration_ms,
                     created_at, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_dict["id"],
                    task_dict["plan_id"],
                    task_dict["step_number"],
                    task_dict["description"],
                    task_dict["prompt"],
                    task_dict.get("status", "pending"),
                    task_dict.get("cli_used"),
                    task_dict.get("model_used"),
                    task_dict.get("output"),
                    task_dict.get("error"),
                    task_dict.get("tokens_used"),
                    task_dict.get("duration_ms"),
                    task_dict["created_at"],
                    task_dict.get("started_at"),
                    task_dict.get("completed_at"),
                ),
            )
            await db.commit()

    async def get_step_task(self, task_id: str) -> dict[str, Any] | None:
        """Fetch a single step_task row by id, or None."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM step_tasks WHERE id = ?", (task_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def get_step_tasks_for_plan(self, plan_id: str) -> list[dict[str, Any]]:
        """Return all step_tasks for a plan, ordered by step_number ASC."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM step_tasks WHERE plan_id = ? ORDER BY step_number ASC",
                (plan_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_step_task(self, task_id: str, **fields: Any) -> None:
        """Update arbitrary fields on a step_task row.

        Only keys present in *fields* are written; all others are untouched.
        """
        _ALLOWED = frozenset({  # noqa: N806
            "status", "cli_used", "model_used", "output", "error",
            "tokens_used", "duration_ms", "started_at", "completed_at",
        })
        updates = {k: v for k, v in fields.items() if k in _ALLOWED}
        if not updates:
            return
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = list(updates.values()) + [task_id]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE step_tasks SET {set_clause} WHERE id = ?",
                values,
            )
            await db.commit()


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
