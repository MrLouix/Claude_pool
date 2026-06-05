"""Tests for Phase 3 Step 3: execute_message() wired into the project message endpoint."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.database import DatabaseManager
from team_cli.executor import NoCLIAvailableError
from team_cli.models import PoolState, Project
from team_cli.storage import save_pool, save_project


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@contextmanager
def _make_api(pool_file: Path):
    """Yield (TestClient, ApiServer) with run_pool and signals stubbed."""
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


def _seed_project(db_path: Path, project: Project) -> None:
    """Write a project row directly into the test DB."""
    async def _run() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.upsert_project(project.to_dict())

    asyncio.run(_run())


def _make_project(
    project_id: str = "proj_test01",
    name: str = "Test Project",
    default_cli: str | None = None,
    allow_cli_switch: bool = True,
    directory: str | None = None,
) -> Project:
    from datetime import datetime
    return Project(
        id=project_id,
        name=name,
        directory=directory or str(Path.home()),
        created_at=datetime.now(),
        default_cli=default_cli,
        allow_cli_switch=allow_cli_switch,
    )


def _setup(tmp_path: Path, project: Project | None = None):
    """Create pool.db, seed one project, return (pool_file, project)."""
    pool_file = tmp_path / "pool.db"
    state = PoolState(tasks=[], pool_file=pool_file)
    save_pool(state)

    proj = project or _make_project()
    _seed_project(pool_file, proj)
    return pool_file, proj


# ---------------------------------------------------------------------------
# Helpers to read DB state
# ---------------------------------------------------------------------------

def _load_messages(db_path: Path, project_id: str) -> list[dict]:
    async def _run() -> list[dict]:
        db = DatabaseManager(db_path)
        await db.init()
        return await db.get_project_messages(project_id)

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tests: successful execution stores assistant reply
# ---------------------------------------------------------------------------

class TestSuccessfulExecution:
    def test_stores_assistant_reply_with_correct_cli_used(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "Hello from claude", "cli_used": "claude"}
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "Say hello", "role": "user"},
                )

        assert resp.status_code == 201

        db_path = pool_file.with_suffix(".db")
        messages = _load_messages(db_path, proj.id)
        assert len(messages) == 2  # user + assistant

        assistant = next(m for m in messages if m["role"] == "assistant")
        assert assistant["content"] == "Hello from claude"
        assert assistant["cli_used"] == "claude"

    def test_assistant_message_linked_to_user_message(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "answer", "cli_used": "claude"}
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "question", "role": "user"},
                )

        assert resp.status_code == 201
        user_id = resp.json()["id"]

        db_path = pool_file.with_suffix(".db")
        messages = _load_messages(db_path, proj.id)
        assistant = next(m for m in messages if m["role"] == "assistant")
        assert assistant["linked_message_id"] == user_id

    def test_returns_user_message_in_response(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "ok", "cli_used": "claude"}
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "test prompt", "role": "user"},
                )

        data = resp.json()
        assert data["content"] == "test prompt"
        assert data["role"] == "user"

    def test_assistant_message_not_created_for_non_user_role(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "should not be called", "cli_used": "claude"}
            )) as mock_exec:
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "assistant note", "role": "assistant"},
                )

        assert resp.status_code == 201
        mock_exec.assert_not_called()

        db_path = pool_file.with_suffix(".db")
        messages = _load_messages(db_path, proj.id)
        assert len(messages) == 1  # only the assistant message itself, no reply


# ---------------------------------------------------------------------------
# Tests: 503 on NoCLIAvailableError
# ---------------------------------------------------------------------------

class TestNoCLIAvailable:
    def test_returns_503_when_no_cli_available(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                side_effect=NoCLIAvailableError("All CLIs are rate-limited")
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "hello", "role": "user"},
                )

        assert resp.status_code == 503

    def test_503_body_has_error_key(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                side_effect=NoCLIAvailableError("All CLIs exhausted")
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "hello", "role": "user"},
                )

        body = resp.json()
        detail = body.get("detail", body)
        assert detail.get("error") == "no_cli_available"
        assert "All CLIs exhausted" in detail.get("message", "")

    def test_user_message_still_saved_before_503(self, tmp_path: Path):
        """The user message is persisted even when execution fails."""
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                side_effect=NoCLIAvailableError("no CLI")
            )):
                client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "my prompt", "role": "user"},
                )

        db_path = pool_file.with_suffix(".db")
        messages = _load_messages(db_path, proj.id)
        assert any(m["content"] == "my prompt" and m["role"] == "user" for m in messages)


# ---------------------------------------------------------------------------
# Tests: per-message CLI override
# ---------------------------------------------------------------------------

class TestPerMessageCLIOverride:
    def test_cli_used_override_passed_as_default_cli(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path, _make_project(allow_cli_switch=True))

        captured: dict = {}

        async def _fake_execute_message(message, project, cli_manager, db_path, model=None):
            captured["default_cli"] = project.default_cli
            captured["allow_cli_switch"] = project.allow_cli_switch
            return {"result": "ok", "cli_used": "hermes"}

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", side_effect=_fake_execute_message):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "test", "role": "user", "cli_used": "hermes"},
                )

        assert resp.status_code == 201
        assert captured["default_cli"] == "hermes"
        assert captured["allow_cli_switch"] is False

    def test_original_project_not_mutated_by_override(self, tmp_path: Path):
        proj = _make_project(default_cli="claude", allow_cli_switch=True)
        pool_file, proj = _setup(tmp_path, proj)

        captured_projects: list = []

        async def _fake(message, project, cli_manager, db_path, model=None):
            captured_projects.append((project.default_cli, project.allow_cli_switch))
            return {"result": "ok", "cli_used": "hermes"}

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", side_effect=_fake):
                client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "go", "role": "user", "cli_used": "hermes"},
                )

        # The project passed to execute_message has the override applied
        assert captured_projects[0] == ("hermes", False)

        # Reload from DB to confirm the original project row was not changed
        from team_cli.storage import load_project
        reloaded = load_project(pool_file.with_suffix(".db"), proj.id)
        assert reloaded.default_cli == "claude"
        assert reloaded.allow_cli_switch is True

    def test_no_override_when_cli_used_is_none(self, tmp_path: Path):
        proj = _make_project(default_cli="claude", allow_cli_switch=False)
        pool_file, proj = _setup(tmp_path, proj)

        captured: dict = {}

        async def _fake(message, project, cli_manager, db_path, model=None):
            captured["default_cli"] = project.default_cli
            captured["allow_cli_switch"] = project.allow_cli_switch
            return {"result": "ok", "cli_used": "claude"}

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", side_effect=_fake):
                client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "hi", "role": "user"},
                )

        assert captured["default_cli"] == "claude"
        assert captured["allow_cli_switch"] is False


# ---------------------------------------------------------------------------
# Tests: WebSocket broadcast
# ---------------------------------------------------------------------------

class TestWebSocketBroadcast:
    def test_broadcast_called_for_user_message(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "reply", "cli_used": "claude"}
            )):
                broadcast_calls: list[dict] = []
                original_broadcast = server._broadcast_event

                async def _capturing_broadcast(event: dict) -> None:
                    broadcast_calls.append(event)
                    await original_broadcast(event)

                server._broadcast_event = _capturing_broadcast

                client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "hello", "role": "user"},
                )

        project_events = [
            e for e in broadcast_calls
            if e.get("event") == "project_message_created"
        ]
        # Expect at least 2 broadcasts: user message + assistant reply
        assert len(project_events) >= 2

    def test_broadcast_includes_assistant_cli_used(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, server):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "hi", "cli_used": "hermes"}
            )):
                broadcast_calls: list[dict] = []
                original_broadcast = server._broadcast_event

                async def _capturing_broadcast(event: dict) -> None:
                    broadcast_calls.append(event)
                    await original_broadcast(event)

                server._broadcast_event = _capturing_broadcast

                client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "ping", "role": "user"},
                )

        assistant_events = [
            e for e in broadcast_calls
            if e.get("event") == "project_message_created"
            and e.get("message", {}).get("role") == "assistant"
        ]
        assert len(assistant_events) == 1
        assert assistant_events[0]["message"]["cli_used"] == "hermes"


# ---------------------------------------------------------------------------
# Tests: 404 for unknown project
# ---------------------------------------------------------------------------

class TestProjectNotFound:
    def test_returns_404_for_unknown_project(self, tmp_path: Path):
        pool_file = tmp_path / "pool.db"
        state = PoolState(tasks=[], pool_file=pool_file)
        save_pool(state)

        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/projects/nonexistent_id/messages",
                json={"content": "hi", "role": "user"},
            )

        assert resp.status_code == 404
