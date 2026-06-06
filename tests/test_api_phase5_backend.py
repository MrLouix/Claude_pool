"""Tests for Phase 5 Step 1: PATCH project, single-message GET/DELETE, linked_to filter."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.database import DatabaseManager
from team_cli.models import PoolState, Project, ProjectMessage
from team_cli.storage import save_pool, save_project, save_project_message


# ---------------------------------------------------------------------------
# Helpers
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


def _make_project(project_id: str = "proj_p5s1", **kwargs) -> Project:
    defaults = dict(
        id=project_id,
        name="Phase5 Project",
        directory=str(Path.home()),
        created_at=datetime.now(),
        default_cli=None,
        allow_cli_switch=True,
    )
    defaults.update(kwargs)
    return Project(**defaults)


def _setup(tmp_path: Path, project: Project | None = None):
    pool_file = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pool_file))
    proj = project or _make_project()
    _seed_project(pool_file, proj)
    return pool_file, proj


def _make_msg(project_id: str = "proj_p5s1", msg_id: str = "msg_test0001",
              linked_message_id: str | None = None, **kwargs) -> ProjectMessage:
    defaults = dict(
        id=msg_id,
        project_id=project_id,
        content="Test message",
        role="user",
        priority=2,
        linked_message_id=linked_message_id,
    )
    defaults.update(kwargs)
    return ProjectMessage(**defaults)


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}
# ---------------------------------------------------------------------------

class TestPatchProject:
    def test_patch_updates_name(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.patch(
                f"/api/projects/{proj.id}",
                json={"name": "Renamed Project"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Renamed Project"
        assert data["directory"] == proj.directory  # unchanged

    def test_patch_updates_directory(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        new_dir = str(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.patch(
                f"/api/projects/{proj.id}",
                json={"directory": new_dir},
            )

        assert resp.status_code == 200
        assert resp.json()["directory"] == new_dir
        assert resp.json()["name"] == proj.name  # unchanged

    def test_patch_updates_allow_cli_switch(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path, _make_project(allow_cli_switch=True))

        with _make_api(pool_file) as (client, _):
            resp = client.patch(
                f"/api/projects/{proj.id}",
                json={"allow_cli_switch": False},
            )

        assert resp.status_code == 200
        assert resp.json()["allow_cli_switch"] is False

    def test_patch_updates_default_cli(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.patch(
                f"/api/projects/{proj.id}",
                json={"default_cli": "mistral"},
            )

        assert resp.status_code == 200
        assert resp.json()["default_cli"] == "mistral"

    def test_patch_empty_body_leaves_all_fields_unchanged(self, tmp_path: Path):
        proj = _make_project(name="Original", allow_cli_switch=False, default_cli="claude")
        pool_file, proj = _setup(tmp_path, proj)

        with _make_api(pool_file) as (client, _):
            resp = client.patch(f"/api/projects/{proj.id}", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Original"
        assert data["allow_cli_switch"] is False
        assert data["default_cli"] == "claude"

    def test_patch_returns_404_for_unknown_project(self, tmp_path: Path):
        pool_file = tmp_path / "pool.db"
        save_pool(PoolState(tasks=[], pool_file=pool_file))

        with _make_api(pool_file) as (client, _):
            resp = client.patch("/api/projects/nonexistent", json={"name": "New"})

        assert resp.status_code == 404

    def test_patch_persists_to_db(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            client.patch(f"/api/projects/{proj.id}", json={"name": "Persisted"})

        from team_cli.storage import load_project
        reloaded = load_project(pool_file.with_suffix(".db"), proj.id)
        assert reloaded is not None
        assert reloaded.name == "Persisted"

    def test_patch_returns_project_entry_shape(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.patch(f"/api/projects/{proj.id}", json={"name": "X"})

        data = resp.json()
        for field in ("id", "name", "directory", "created_at", "allow_cli_switch", "message_count"):
            assert field in data


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/messages/{message_id}
# ---------------------------------------------------------------------------

class TestGetSingleMessage:
    def test_returns_correct_message(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id, content="Hello"))

        with _make_api(pool_file) as (client, _):
            resp = client.get(f"/api/projects/{proj.id}/messages/msg_test0001")

        assert resp.status_code == 200
        assert resp.json()["content"] == "Hello"
        assert resp.json()["id"] == "msg_test0001"

    def test_returns_priority_field(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id, priority=5))

        with _make_api(pool_file) as (client, _):
            resp = client.get(f"/api/projects/{proj.id}/messages/msg_test0001")

        assert resp.json()["priority"] == 5

    def test_returns_404_for_unknown_message(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.get(f"/api/projects/{proj.id}/messages/nonexistent")

        assert resp.status_code == 404

    def test_returns_404_for_wrong_project(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id))

        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/projects/other_project/messages/msg_test0001")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/projects/{project_id}/messages/{message_id}
# ---------------------------------------------------------------------------

class TestDeleteMessage:
    def test_returns_204_on_success(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id))

        with _make_api(pool_file) as (client, _):
            resp = client.delete(f"/api/projects/{proj.id}/messages/msg_test0001")

        assert resp.status_code == 204

    def test_message_gone_after_delete(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id))

        with _make_api(pool_file) as (client, _):
            client.delete(f"/api/projects/{proj.id}/messages/msg_test0001")
            resp = client.get(f"/api/projects/{proj.id}/messages/msg_test0001")

        assert resp.status_code == 404

    def test_returns_404_for_unknown_message(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)

        with _make_api(pool_file) as (client, _):
            resp = client.delete(f"/api/projects/{proj.id}/messages/nonexistent")

        assert resp.status_code == 404

    def test_returns_404_for_wrong_project(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id))

        with _make_api(pool_file) as (client, _):
            resp = client.delete("/api/projects/wrong_project/messages/msg_test0001")

        assert resp.status_code == 404

    def test_other_messages_unaffected(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id, msg_id="msg_a"))
        save_project_message(db_path, _make_msg(project_id=proj.id, msg_id="msg_b"))

        with _make_api(pool_file) as (client, _):
            client.delete(f"/api/projects/{proj.id}/messages/msg_a")
            resp = client.get(f"/api/projects/{proj.id}/messages/msg_b")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/messages?linked_to=
# ---------------------------------------------------------------------------

class TestLinkedToFilter:
    def test_returns_only_linked_messages(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id, msg_id="msg_parent"))
        save_project_message(db_path, _make_msg(
            project_id=proj.id, msg_id="msg_reply",
            linked_message_id="msg_parent"
        ))
        save_project_message(db_path, _make_msg(project_id=proj.id, msg_id="msg_other"))

        with _make_api(pool_file) as (client, _):
            resp = client.get(
                f"/api/projects/{proj.id}/messages",
                params={"linked_to": "msg_parent"},
            )

        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert ids == ["msg_reply"]

    def test_without_filter_returns_all_messages(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        for i in range(3):
            save_project_message(db_path, _make_msg(project_id=proj.id, msg_id=f"msg_{i}"))

        with _make_api(pool_file) as (client, _):
            resp = client.get(f"/api/projects/{proj.id}/messages")

        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_filter_with_no_matches_returns_empty_list(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id))

        with _make_api(pool_file) as (client, _):
            resp = client.get(
                f"/api/projects/{proj.id}/messages",
                params={"linked_to": "nonexistent_parent"},
            )

        assert resp.status_code == 200
        assert resp.json() == []

    def test_filter_returns_multiple_replies(self, tmp_path: Path):
        pool_file, proj = _setup(tmp_path)
        db_path = pool_file.with_suffix(".db")
        save_project_message(db_path, _make_msg(project_id=proj.id, msg_id="msg_root"))
        save_project_message(db_path, _make_msg(
            project_id=proj.id, msg_id="msg_r1", linked_message_id="msg_root"
        ))
        save_project_message(db_path, _make_msg(
            project_id=proj.id, msg_id="msg_r2", linked_message_id="msg_root"
        ))

        with _make_api(pool_file) as (client, _):
            resp = client.get(
                f"/api/projects/{proj.id}/messages",
                params={"linked_to": "msg_root"},
            )

        ids = {m["id"] for m in resp.json()}
        assert ids == {"msg_r1", "msg_r2"}
