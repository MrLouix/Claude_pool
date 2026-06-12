"""Tests for v2 dataclasses (Chat, Message, CliCommand) and updated Task/Project."""

import json
import sqlite3
from pathlib import Path

import pytest

from team_cli.models import (
    Chat,
    CliCommand,
    Message,
    MessageRole,
    Project,
    Task,
    TaskKind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path) -> sqlite3.Connection:
    """Create an in-memory-style SQLite DB with all v2 tables."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            directory TEXT NOT NULL,
            created_at TEXT NOT NULL,
            default_cli TEXT,
            allow_cli_switch INTEGER NOT NULL DEFAULT 1,
            git_remote TEXT,
            archived INTEGER NOT NULL DEFAULT 0
        );
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
            model TEXT DEFAULT '',
            project_id TEXT,
            chat_id TEXT,
            parent_message_id TEXT,
            parent_task_id TEXT,
            kind TEXT NOT NULL DEFAULT 'request'
        );
    """)
    return conn


# ---------------------------------------------------------------------------
# TaskKind type alias
# ---------------------------------------------------------------------------

class TestTaskKind:
    def test_task_kind_values(self):
        assert TaskKind.__args__ == ("request", "subtask")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# MessageRole includes 'system'
# ---------------------------------------------------------------------------

class TestMessageRole:
    def test_message_role_includes_system(self):
        assert "system" in MessageRole.__args__  # type: ignore[attr-defined]

    def test_message_role_includes_user(self):
        assert "user" in MessageRole.__args__  # type: ignore[attr-defined]

    def test_message_role_includes_assistant(self):
        assert "assistant" in MessageRole.__args__  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Project v2 fields
# ---------------------------------------------------------------------------

class TestProjectV2Fields:
    def test_default_git_remote_is_none(self):
        p = Project(id="p1", name="Test", directory="/tmp/test", created_at=None)  # type: ignore[arg-type]
        assert p.git_remote is None

    def test_default_archived_is_false(self):
        p = Project(id="p1", name="Test", directory="/tmp/test", created_at=None)  # type: ignore[arg-type]
        assert p.archived is False

    def test_from_dict_parses_git_remote(self):
        data = {
            "id": "p1", "name": "Test", "directory": "/tmp",
            "created_at": "2025-01-01T00:00:00",
            "git_remote": "https://github.com/user/repo.git",
            "archived": 0,
        }
        p = Project.from_dict(data)
        assert p.git_remote == "https://github.com/user/repo.git"

    def test_from_dict_parses_archived(self):
        data = {
            "id": "p1", "name": "Test", "directory": "/tmp",
            "created_at": "2025-01-01T00:00:00",
            "archived": 1,
        }
        p = Project.from_dict(data)
        assert p.archived is True

    def test_to_dict_includes_git_remote(self):
        from datetime import datetime
        p = Project(
            id="p1", name="Test", directory="/tmp",
            created_at=datetime(2025, 1, 1),
            git_remote="git@github.com:user/repo.git",
        )
        d = p.to_dict()
        assert d["git_remote"] == "git@github.com:user/repo.git"

    def test_to_dict_encodes_archived_as_int(self):
        from datetime import datetime
        p = Project(id="p1", name="Test", directory="/tmp", created_at=datetime(2025, 1, 1), archived=True)
        d = p.to_dict()
        assert d["archived"] == 1

    def test_round_trip_via_db(self, tmp_path):
        conn = _make_db(tmp_path / "test.db")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO projects (id, name, directory, created_at, git_remote, archived) "
            "VALUES ('p1','My Project','/tmp/proj','2025-01-01T00:00:00','git@host:repo.git',0)"
        )
        conn.commit()
        row = dict(conn.execute("SELECT * FROM projects WHERE id='p1'").fetchone())
        p = Project.from_dict(row)
        assert p.id == "p1"
        assert p.git_remote == "git@host:repo.git"
        assert p.archived is False
        conn.close()


# ---------------------------------------------------------------------------
# Chat dataclass
# ---------------------------------------------------------------------------

class TestChatDataclass:
    def test_creation_with_defaults(self):
        c = Chat(id="chat_1", project_id="proj_1", label="Main Chat")
        assert c.id == "chat_1"
        assert c.project_id == "proj_1"
        assert c.label == "Main Chat"
        assert c.position == 0
        assert c.created_at != ""

    def test_from_dict(self):
        data = {
            "id": "chat_1",
            "project_id": "proj_1",
            "label": "Dev Chat",
            "position": 2,
            "created_at": "2025-06-01T12:00:00",
        }
        c = Chat.from_dict(data)
        assert c.id == "chat_1"
        assert c.project_id == "proj_1"
        assert c.label == "Dev Chat"
        assert c.position == 2
        assert c.created_at == "2025-06-01T12:00:00"

    def test_to_dict_round_trip(self):
        c = Chat(id="c1", project_id="p1", label="Chat", position=1, created_at="2025-01-01T00:00:00")
        d = c.to_dict()
        assert d["id"] == "c1"
        assert d["project_id"] == "p1"
        assert d["position"] == 1

    def test_round_trip_via_db(self, tmp_path):
        conn = _make_db(tmp_path / "test.db")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO projects (id, name, directory, created_at) VALUES ('p1','P','/tmp','2025-01-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO chats (id, project_id, label, position, created_at) "
            "VALUES ('c1','p1','My Chat',3,'2025-01-01T12:00:00')"
        )
        conn.commit()
        row = dict(conn.execute("SELECT * FROM chats WHERE id='c1'").fetchone())
        c = Chat.from_dict(row)
        assert c.id == "c1"
        assert c.project_id == "p1"
        assert c.position == 3
        conn.close()


# ---------------------------------------------------------------------------
# Message dataclass
# ---------------------------------------------------------------------------

class TestMessageDataclass:
    def test_creation_with_defaults(self):
        m = Message(id="m1", chat_id="c1", role="user", content="Hello")
        assert m.id == "m1"
        assert m.chat_id == "c1"
        assert m.role == "user"
        assert m.content == "Hello"
        assert m.thread_root_id is None
        assert m.task_id is None

    def test_creation_with_thread_root(self):
        m = Message(
            id="m2", chat_id="c1", role="assistant", content="Hi there",
            thread_root_id="m1", task_id="task_001"
        )
        assert m.thread_root_id == "m1"
        assert m.task_id == "task_001"

    def test_system_role_is_valid(self):
        m = Message(id="m1", chat_id="c1", role="system", content="System prompt")
        assert m.role == "system"

    def test_from_dict(self):
        data = {
            "id": "m1",
            "chat_id": "c1",
            "role": "user",
            "content": "Fix the bug",
            "thread_root_id": None,
            "task_id": None,
            "created_at": "2025-01-01T10:00:00",
        }
        m = Message.from_dict(data)
        assert m.id == "m1"
        assert m.content == "Fix the bug"
        assert m.thread_root_id is None

    def test_from_dict_with_thread_root(self):
        data = {
            "id": "m2", "chat_id": "c1", "role": "assistant",
            "content": "Done!", "thread_root_id": "m1",
            "task_id": "task_1", "created_at": "2025-01-01T10:01:00",
        }
        m = Message.from_dict(data)
        assert m.thread_root_id == "m1"
        assert m.task_id == "task_1"

    def test_to_dict_round_trip(self):
        m = Message(
            id="m1", chat_id="c1", role="user", content="Hello",
            created_at="2025-01-01T00:00:00"
        )
        d = m.to_dict()
        assert d["id"] == "m1"
        assert d["role"] == "user"
        assert d["thread_root_id"] is None

    def test_round_trip_via_db(self, tmp_path):
        conn = _make_db(tmp_path / "test.db")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO projects (id, name, directory, created_at) VALUES ('p1','P','/tmp','2025-01-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO chats (id, project_id, label, position, created_at) VALUES ('c1','p1','C',0,'2025-01-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO messages (id, chat_id, thread_root_id, role, content, task_id, created_at) "
            "VALUES ('m1','c1',NULL,'user','Hello world',NULL,'2025-01-01T10:00:00')"
        )
        conn.commit()
        row = dict(conn.execute("SELECT * FROM messages WHERE id='m1'").fetchone())
        m = Message.from_dict(row)
        assert m.id == "m1"
        assert m.chat_id == "c1"
        assert m.role == "user"
        assert m.content == "Hello world"
        conn.close()


# ---------------------------------------------------------------------------
# CliCommand dataclass
# ---------------------------------------------------------------------------

class TestCliCommandDataclass:
    def test_creation_with_defaults(self):
        cmd = CliCommand(
            id="claude",
            name="Claude Code",
            binary="claude",
            args_template='["-p","{prompt}"]',
        )
        assert cmd.id == "claude"
        assert cmd.enabled is True
        assert cmd.priority_requests == 100
        assert cmd.priority_subtasks == 100
        assert cmd.models == "[]"
        assert cmd.default_model is None

    def test_from_dict_full(self):
        data = {
            "id": "claude",
            "name": "Claude Code",
            "binary": "claude",
            "args_template": '["-p","{prompt}","--output-format","json"]',
            "resume_template": '["--resume","{session_id}"]',
            "model_flag": "--model",
            "models": '["haiku","sonnet","opus"]',
            "default_model": "sonnet",
            "enabled": 1,
            "priority_requests": 1,
            "priority_subtasks": 1,
        }
        cmd = CliCommand.from_dict(data)
        assert cmd.id == "claude"
        assert cmd.binary == "claude"
        assert cmd.model_flag == "--model"
        assert cmd.default_model == "sonnet"
        assert cmd.enabled is True
        assert cmd.priority_requests == 1
        assert cmd.priority_subtasks == 1

    def test_from_dict_enabled_coerced_from_int(self):
        data = {
            "id": "x", "name": "X", "binary": "x",
            "args_template": "[]", "enabled": 0,
            "priority_requests": 5, "priority_subtasks": 5,
        }
        cmd = CliCommand.from_dict(data)
        assert cmd.enabled is False

    def test_to_dict_encodes_enabled_as_int(self):
        cmd = CliCommand(id="x", name="X", binary="x", args_template="[]", enabled=True)
        assert cmd.to_dict()["enabled"] == 1

    def test_to_dict_encodes_disabled_as_int(self):
        cmd = CliCommand(id="x", name="X", binary="x", args_template="[]", enabled=False)
        assert cmd.to_dict()["enabled"] == 0

    def test_round_trip_via_db(self, tmp_path):
        conn = _make_db(tmp_path / "test.db")
        conn.row_factory = sqlite3.Row
        args = json.dumps(["-p", "{prompt}", "--output-format", "json"])
        resume = json.dumps(["--resume", "{session_id}"])
        models = json.dumps(["haiku", "sonnet"])
        conn.execute(
            "INSERT INTO cli_commands "
            "(id, name, binary, args_template, resume_template, model_flag, "
            " models, default_model, enabled, priority_requests, priority_subtasks) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("claude", "Claude Code", "claude", args, resume, "--model", models, "sonnet", 1, 2, 3),
        )
        conn.commit()
        row = dict(conn.execute("SELECT * FROM cli_commands WHERE id='claude'").fetchone())
        cmd = CliCommand.from_dict(row)
        assert cmd.id == "claude"
        assert cmd.default_model == "sonnet"
        assert cmd.priority_requests == 2
        assert cmd.priority_subtasks == 3
        conn.close()


# ---------------------------------------------------------------------------
# Task v2 fields
# ---------------------------------------------------------------------------

class TestTaskV2Fields:
    def test_default_v2_fields(self):
        t = Task(id="t1", prompt="test", directory=Path("/tmp"))
        assert t.project_id is None
        assert t.chat_id is None
        assert t.parent_message_id is None
        assert t.parent_task_id is None
        assert t.kind == "request"

    def test_from_dict_parses_v2_fields(self):
        data = {
            "id": "t1",
            "prompt": "Do something",
            "directory": "/tmp",
            "project_id": "proj_001",
            "chat_id": "chat_001",
            "parent_message_id": "msg_001",
            "parent_task_id": "task_parent",
            "kind": "subtask",
        }
        t = Task.from_dict(data)
        assert t.project_id == "proj_001"
        assert t.chat_id == "chat_001"
        assert t.parent_message_id == "msg_001"
        assert t.parent_task_id == "task_parent"
        assert t.kind == "subtask"

    def test_from_dict_null_v2_fields(self):
        data = {
            "id": "t1",
            "prompt": "Do something",
            "directory": "/tmp",
            "project_id": None,
            "chat_id": None,
            "parent_message_id": None,
            "parent_task_id": None,
            "kind": "request",
        }
        t = Task.from_dict(data)
        assert t.project_id is None
        assert t.parent_task_id is None
        assert t.kind == "request"

    def test_to_dict_includes_v2_fields(self):
        t = Task(
            id="t1", prompt="p", directory=Path("/tmp"),
            project_id="proj_1", chat_id="chat_1",
            parent_message_id="msg_root", parent_task_id=None,
            kind="subtask",
        )
        d = t.to_dict()
        assert d["project_id"] == "proj_1"
        assert d["chat_id"] == "chat_1"
        assert d["parent_message_id"] == "msg_root"
        assert d["parent_task_id"] is None
        assert d["kind"] == "subtask"

    def test_backward_compat_creation_without_v2_fields(self):
        """Existing code creating Task(id, prompt, directory) still works."""
        t = Task(id="t1", prompt="hello", directory=Path("/home"))
        assert t.kind == "request"
        assert t.project_id is None

    def test_round_trip_via_db(self, tmp_path):
        conn = _make_db(tmp_path / "test.db")
        conn.execute(
            "INSERT INTO tasks (id, prompt, directory, created_at, project_id, chat_id, kind) "
            "VALUES ('t1','fix bug','/tmp','2025-01-01T00:00:00','proj_1','chat_1','subtask')"
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM tasks WHERE id='t1'").fetchone())
        t = Task.from_dict(row)
        assert t.project_id == "proj_1"
        assert t.chat_id == "chat_1"
        assert t.kind == "subtask"
        conn.close()


# ---------------------------------------------------------------------------
# DatabaseManager CRUD for new v2 types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_manager_chat_crud(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    # Create a project first.
    await db.upsert_project({
        "id": "proj_1", "name": "Test Project", "directory": "/tmp/test",
        "created_at": "2025-01-01T00:00:00",
    })

    chat_dict = {
        "id": "chat_1", "project_id": "proj_1",
        "label": "Dev Session", "position": 0,
        "created_at": "2025-01-01T10:00:00",
    }

    # Create
    await db.upsert_chat(chat_dict)

    # Read
    c = await db.get_chat("chat_1")
    assert c is not None
    assert c["label"] == "Dev Session"

    # List
    chats = await db.get_chats_for_project("proj_1")
    assert len(chats) == 1
    assert chats[0]["id"] == "chat_1"

    # Update via upsert
    chat_dict["label"] = "Renamed"
    await db.upsert_chat(chat_dict)
    c = await db.get_chat("chat_1")
    assert c["label"] == "Renamed"

    # Delete
    await db.delete_chat("chat_1")
    assert await db.get_chat("chat_1") is None


@pytest.mark.asyncio
async def test_db_manager_message_crud(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    await db.upsert_project({
        "id": "proj_1", "name": "P", "directory": "/tmp/p",
        "created_at": "2025-01-01T00:00:00",
    })
    await db.upsert_chat({
        "id": "chat_1", "project_id": "proj_1", "label": "C",
        "position": 0, "created_at": "2025-01-01T00:00:00",
    })

    msg = {
        "id": "msg_1", "chat_id": "chat_1", "role": "user",
        "content": "Hello world", "thread_root_id": None,
        "task_id": None, "created_at": "2025-01-01T10:00:00",
    }

    # Create
    await db.upsert_message(msg)

    # Read single
    m = await db.get_message("msg_1")
    assert m is not None
    assert m["content"] == "Hello world"

    # List main-thread messages
    msgs = await db.get_messages_for_chat("chat_1")
    assert len(msgs) == 1

    # Thread reply count starts at 0
    count = await db.count_thread_replies("msg_1")
    assert count == 0

    # Add a thread reply
    reply = {
        "id": "msg_2", "chat_id": "chat_1", "role": "assistant",
        "content": "Hi!", "thread_root_id": "msg_1",
        "task_id": "task_001", "created_at": "2025-01-01T10:01:00",
    }
    await db.upsert_message(reply)

    count = await db.count_thread_replies("msg_1")
    assert count == 1

    # Main chat returns only thread_root_id IS NULL
    main_msgs = await db.get_messages_for_chat("chat_1")
    assert all(m["thread_root_id"] is None for m in main_msgs)

    # Thread query returns only replies
    thread_msgs = await db.get_messages_for_chat("chat_1", thread_root_id="msg_1")
    assert len(thread_msgs) == 1
    assert thread_msgs[0]["id"] == "msg_2"

    # Delete
    await db.delete_message("msg_1")
    assert await db.get_message("msg_1") is None


@pytest.mark.asyncio
async def test_db_manager_cli_command_crud(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    # 'claude' is seeded at init time
    cmd = await db.get_cli_command("claude")
    assert cmd is not None
    assert cmd["binary"] == "claude"

    # Upsert a second command
    await db.upsert_cli_command({
        "id": "codex",
        "name": "Codex CLI",
        "binary": "codex",
        "args_template": '["-p","{prompt}"]',
        "enabled": True,
        "priority_requests": 50,
        "priority_subtasks": 50,
    })

    all_cmds = await db.get_all_cli_commands()
    ids = [c["id"] for c in all_cmds]
    assert "claude" in ids
    assert "codex" in ids

    # Delete
    await db.delete_cli_command("codex")
    assert await db.get_cli_command("codex") is None


@pytest.mark.asyncio
async def test_db_manager_upsert_task_with_v2_fields(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    task_dict = {
        "id": "task_001",
        "prompt": "Fix the auth bug",
        "directory": "/tmp/project",
        "created_at": "2025-01-01T10:00:00",
        "project_id": "proj_1",
        "chat_id": "chat_1",
        "parent_message_id": "msg_root",
        "parent_task_id": None,
        "kind": "request",
        "model": "sonnet",
    }
    await db.upsert_task(task_dict)

    row = await db.get_task("task_001")
    assert row is not None
    assert row["project_id"] == "proj_1"
    assert row["chat_id"] == "chat_1"
    assert row["parent_message_id"] == "msg_root"
    assert row["parent_task_id"] is None
    assert row["kind"] == "request"
    assert row["model"] == "sonnet"


@pytest.mark.asyncio
async def test_db_manager_update_task_v2_fields(tmp_path):
    from team_cli.database import DatabaseManager

    db = DatabaseManager(tmp_path / "test.db")
    await db.init()

    await db.upsert_task({
        "id": "task_001",
        "prompt": "p",
        "directory": "/tmp",
        "created_at": "2025-01-01T00:00:00",
    })

    await db.update_task_fields(
        "task_001",
        project_id="proj_1",
        chat_id="chat_1",
        kind="subtask",
        parent_task_id="task_parent",
    )

    row = await db.get_task("task_001")
    assert row["project_id"] == "proj_1"
    assert row["kind"] == "subtask"
    assert row["parent_task_id"] == "task_parent"
