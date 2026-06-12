"""Tests for Phase 4 Step 3: priority auto-calculation and /promote endpoint."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.database import DatabaseManager
from team_cli.models import PoolState, Project, ProjectMessage
from team_cli.storage import save_pool, save_project_message

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_api_phase3 fixtures)
# ---------------------------------------------------------------------------

@contextmanager
def _make_api(pool_file: Path):
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


def _seed_project(db_path: Path, project: Project) -> None:
    async def _run() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.upsert_project(project.to_dict())

    asyncio.run(_run())


def _make_project(project_id: str = "proj_p4s3") -> Project:
    return Project(
        id=project_id,
        name="Priority Test Project",
        directory=str(Path.home()),
        created_at=datetime.now(),
    )


def _setup(tmp_path: Path, project: Project | None = None):
    pool_file = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pool_file))
    proj = project or _make_project()
    _seed_project(pool_file, proj)
    return pool_file, proj


def _seed_message(db_path: Path, message: ProjectMessage) -> None:
    save_project_message(db_path, message)


def _make_msg(project_id: str = "proj_p4s3", priority: int = 2, **kwargs) -> ProjectMessage:
    defaults = dict(
        id="msg_seed0001",
        project_id=project_id,
        content="generic message",
        role="user",
        priority=priority,
    )
    defaults.update(kwargs)
    return ProjectMessage(**defaults)


# ---------------------------------------------------------------------------
# POST /api/projects/{id}/messages — priority auto-calculation
# ---------------------------------------------------------------------------

class TestAutoCalculatePriority:
    def test_bug_content_assigns_priority_5(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "fixed", "cli_used": "claude"}
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "there is a bug in the login flow", "role": "user"},
                )

        assert resp.status_code == 201
        assert resp.json()["priority"] == 5

    def test_feature_content_assigns_priority_3(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "done", "cli_used": "claude"}
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "add a new feature: dark mode", "role": "user"},
                )

        assert resp.status_code == 201
        assert resp.json()["priority"] == 3

    def test_generic_content_assigns_priority_2(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "ok", "cli_used": "claude"}
            )):
                # Disable embedding so keyword-heuristic default (2) is deterministic
                with patch("team_cli.priority_engine.EMBEDDING_AVAILABLE", False):
                    resp = client.post(
                        f"/api/projects/{proj.id}/messages",
                        json={"content": "how do I reset my password?", "role": "user"},
                    )

        assert resp.status_code == 201
        assert resp.json()["priority"] == 2

    def test_explicit_priority_overrides_auto_calculation(self, tmp_path: Path):
        """When caller provides priority != 2 it must be used as-is."""
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "ok", "cli_used": "claude"}
            )):
                # Content contains "bug" which would auto-assign 5,
                # but explicit priority=4 should win
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "there is a bug here", "role": "user", "priority": 4},
                )

        assert resp.status_code == 201
        assert resp.json()["priority"] == 4

    def test_explicit_priority_1_is_preserved(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "ok", "cli_used": "claude"}
            )):
                resp = client.post(
                    f"/api/projects/{proj.id}/messages",
                    json={"content": "low priority note", "role": "user", "priority": 1},
                )

        assert resp.status_code == 201
        assert resp.json()["priority"] == 1

    def test_mocked_calculate_priority_is_used(self, tmp_path: Path):
        """Verify the API delegates to calculate_priority (isolation test)."""
        pool_file, proj = _setup(tmp_path)
        captured = {}

        def _fake_calculate(message, project=None):
            captured["called"] = True
            captured["content"] = message.content
            return 3

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "ok", "cli_used": "claude"}
            )):
                with patch("team_cli.api.calculate_priority", side_effect=_fake_calculate):
                    resp = client.post(
                        f"/api/projects/{proj.id}/messages",
                        json={"content": "anything", "role": "user"},
                    )

        assert resp.status_code == 201
        assert captured.get("called") is True
        assert resp.json()["priority"] == 3

    def test_calculate_priority_not_called_when_override_provided(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            with patch("team_cli.api.execute_message", new=AsyncMock(
                return_value={"result": "ok", "cli_used": "claude"}
            )):
                with patch("team_cli.api.calculate_priority") as mock_calc:
                    client.post(
                        f"/api/projects/{proj.id}/messages",
                        json={"content": "anything", "role": "user", "priority": 3},
                    )

        mock_calc.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/messages — priority in response
# ---------------------------------------------------------------------------

class TestGetMessagesPriority:
    def test_list_messages_includes_priority_field(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        _seed_message(db_path, _make_msg(project_id=proj.id, priority=5))

        with _make_api(pool_file) as (client, _):
            resp = client.get(f"/api/projects/{proj.id}/messages")

        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 1
        assert msgs[0]["priority"] == 5

    def test_list_messages_default_priority_is_2(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        _seed_message(db_path, _make_msg(project_id=proj.id))  # default priority=2

        with _make_api(pool_file) as (client, _):
            resp = client.get(f"/api/projects/{proj.id}/messages")

        assert resp.status_code == 200
        assert resp.json()[0]["priority"] == 2


# ---------------------------------------------------------------------------
# POST /api/projects/{id}/messages/{msg_id}/promote
# ---------------------------------------------------------------------------

class TestPromoteEndpoint:
    def test_promote_increases_priority_by_1(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        _seed_message(db_path, _make_msg(project_id=proj.id, priority=2))

        with _make_api(pool_file) as (client, _):
            resp = client.post(
                f"/api/projects/{proj.id}/messages/msg_seed0001/promote"
            )

        assert resp.status_code == 200
        assert resp.json()["priority"] == 3

    def test_promote_at_5_stays_at_5(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        _seed_message(db_path, _make_msg(project_id=proj.id, priority=5))

        with _make_api(pool_file) as (client, _):
            resp = client.post(
                f"/api/projects/{proj.id}/messages/msg_seed0001/promote"
            )

        assert resp.status_code == 200
        assert resp.json()["priority"] == 5

    def test_promote_persists_to_db(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        _seed_message(db_path, _make_msg(project_id=proj.id, priority=3))

        with _make_api(pool_file) as (client, _):
            client.post(f"/api/projects/{proj.id}/messages/msg_seed0001/promote")

        from team_cli.storage import load_project_message
        reloaded = load_project_message(db_path, "msg_seed0001")
        assert reloaded is not None
        assert reloaded.priority == 4

    def test_promote_returns_404_for_unknown_message(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.post(
                f"/api/projects/{proj.id}/messages/nonexistent_msg/promote"
            )

        assert resp.status_code == 404

    def test_promote_returns_404_for_wrong_project(self, tmp_path: Path):
        """Message exists but belongs to a different project."""
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        # Seed message under proj.id
        _seed_message(db_path, _make_msg(project_id=proj.id, priority=2))

        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/projects/other_project_id/messages/msg_seed0001/promote"
            )

        assert resp.status_code == 404

    def test_promote_response_includes_all_fields(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        _seed_message(db_path, _make_msg(project_id=proj.id, priority=1))

        with _make_api(pool_file) as (client, _):
            resp = client.post(
                f"/api/projects/{proj.id}/messages/msg_seed0001/promote"
            )

        data = resp.json()
        assert "id" in data
        assert "project_id" in data
        assert "content" in data
        assert "role" in data
        assert "priority" in data
        assert "created_at" in data
