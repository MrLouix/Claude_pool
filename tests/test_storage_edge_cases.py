"""Edge-case tests for storage functions: load_project, build_context, ProjectMessage round-trip."""

from datetime import datetime
from pathlib import Path

from team_cli.models import Project, ProjectMessage
from team_cli.storage import (
    build_context,
    load_project,
    load_project_messages,
    save_project,
    save_project_message,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> Path:
    """Return an initialised DB path (migrations applied via DatabaseManager.init)."""
    import asyncio

    from team_cli.database import DatabaseManager
    db_path = tmp_path / "pool.db"
    asyncio.run(DatabaseManager(db_path).init())
    return db_path


def _project(pid: str = "proj-1") -> Project:
    return Project(
        id=pid,
        name="Test Project",
        directory="/tmp/test",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        default_cli="claude",
        allow_cli_switch=True,
    )


def _message(mid: str, project_id: str = "proj-1", **kwargs) -> ProjectMessage:
    defaults = dict(
        content="hello",
        role="user",
        cli_used=None,
        linked_message_id=None,
        metadata={},
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        priority=2,
    )
    defaults.update(kwargs)
    return ProjectMessage(id=mid, project_id=project_id, **defaults)


# ---------------------------------------------------------------------------
# load_project
# ---------------------------------------------------------------------------

class TestLoadProject:
    def test_returns_none_for_unknown_id(self, tmp_path):
        db = _make_db(tmp_path)
        result = load_project(db, "nonexistent-project-id")
        assert result is None

    def test_returns_project_after_save(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)
        result = load_project(db, "proj-1")
        assert result is not None
        assert result.id == "proj-1"
        assert result.name == "Test Project"

    def test_returns_none_for_different_id(self, tmp_path):
        db = _make_db(tmp_path)
        save_project(db, _project("proj-A"))
        assert load_project(db, "proj-B") is None


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_returns_empty_list_when_no_linked_message(self, tmp_path):
        db = _make_db(tmp_path)
        msg = _message("msg-1")  # linked_message_id=None
        result = build_context(msg, db)
        assert result == []

    def test_returns_empty_list_for_empty_history(self, tmp_path):
        db = _make_db(tmp_path)
        # linked_message_id points to a message that doesn't exist
        msg = _message("msg-new", linked_message_id="ghost-id")
        result = build_context(msg, db)
        assert result == []

    def test_returns_context_from_linked_message(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        parent = _message("msg-parent", content="What is Python?", role="user")
        save_project_message(db, parent)

        child = _message("msg-child", linked_message_id="msg-parent")
        context = build_context(child, db)

        assert len(context) == 1
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "What is Python?"

    def test_context_ordered_oldest_first(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        m1 = _message("m1", content="first", role="user",
                       created_at=datetime(2026, 1, 1, 10, 0, 0))
        m2 = _message("m2", content="second", role="assistant",
                       linked_message_id="m1",
                       created_at=datetime(2026, 1, 1, 10, 1, 0))
        save_project_message(db, m1)
        save_project_message(db, m2)

        requester = _message("m3", linked_message_id="m2")
        context = build_context(requester, db)

        assert [c["content"] for c in context] == ["first", "second"]


# ---------------------------------------------------------------------------
# ProjectMessage round-trip
# ---------------------------------------------------------------------------

class TestProjectMessageRoundTrip:
    def test_basic_fields_survive_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-rt", content="Round trip content", role="user")
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert len(msgs) == 1
        loaded = msgs[0]
        assert loaded.id == "msg-rt"
        assert loaded.content == "Round trip content"
        assert loaded.role == "user"

    def test_priority_survives_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-prio", priority=5)
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert msgs[0].priority == 5

    def test_cli_used_survives_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-cli", cli_used="mistral")
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert msgs[0].cli_used == "mistral"

    def test_linked_message_id_survives_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-linked", linked_message_id="msg-parent-ref")
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert msgs[0].linked_message_id == "msg-parent-ref"

    def test_metadata_survives_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-meta", metadata={"tokens": 42, "model": "haiku"})
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert msgs[0].metadata == {"tokens": 42, "model": "haiku"}

    def test_assistant_role_survives_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-asst", role="assistant", content="I can help with that.")
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert msgs[0].role == "assistant"

    def test_null_cli_used_survives_round_trip(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = _message("msg-null-cli", cli_used=None)
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert msgs[0].cli_used is None

    def test_all_fields_together(self, tmp_path):
        db = _make_db(tmp_path)
        proj = _project()
        save_project(db, proj)

        msg = ProjectMessage(
            id="msg-full",
            project_id="proj-1",
            content="Full field test",
            role="assistant",
            cli_used="claude",
            linked_message_id="parent-ref",
            metadata={"duration_ms": 1234},
            created_at=datetime(2026, 3, 15, 9, 30, 0),
            priority=4,
        )
        save_project_message(db, msg)

        msgs = load_project_messages(db, "proj-1")
        assert len(msgs) == 1
        loaded = msgs[0]
        assert loaded.id == "msg-full"
        assert loaded.role == "assistant"
        assert loaded.cli_used == "claude"
        assert loaded.linked_message_id == "parent-ref"
        assert loaded.metadata == {"duration_ms": 1234}
        assert loaded.priority == 4
