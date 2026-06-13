"""Tests for v2 project CRUD endpoints."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState, Task
from team_cli.storage import save_pool


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


def _pool(tmp_path: Path) -> Path:
    pf = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pf))
    return pf


def _create_project(client: TestClient, name: str = "Test Project") -> dict:
    resp = client.post(
        "/api/projects",
        json={"name": name, "directory": str(Path.home())},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreateProject:
    def test_returns_201(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post(
                "/api/projects",
                json={"name": "Alpha", "directory": str(Path.home())},
            )
        assert resp.status_code == 201

    def test_response_has_required_fields(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = _create_project(client, "Beta")
        for field in ("id", "name", "directory", "created_at", "archived", "active_task_count"):
            assert field in data, f"missing field: {field}"

    def test_id_starts_with_proj(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = _create_project(client, "Gamma")
        assert data["id"].startswith("proj_")

    def test_archived_defaults_false(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = _create_project(client, "Delta")
        assert data["archived"] is False

    def test_active_task_count_zero_on_create(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = _create_project(client)
        assert data["active_task_count"] == 0

    def test_directory_outside_allowlist_gives_403(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post(
                "/api/projects",
                json={"name": "Bad", "directory": "/etc"},
            )
        assert resp.status_code == 403

    def test_git_remote_explicitly_stored(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post(
                "/api/projects",
                json={
                    "name": "Repo",
                    "directory": str(Path.home()),
                    "git_remote": "https://github.com/example/repo.git",
                },
            )
        assert resp.json()["git_remote"] == "https://github.com/example/repo.git"

    def test_backward_compat_default_cli_accepted(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post(
                "/api/projects",
                json={"name": "Compat", "directory": str(Path.home()), "default_cli": "claude"},
            )
        assert resp.status_code == 201
        assert resp.json()["default_cli"] == "claude"


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestGetProject:
    def test_returns_200_for_existing(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)["id"]
            resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == pid

    def test_returns_404_for_unknown(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/projects/proj_does_not_exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListProjects:
    def test_returns_list(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_created_project_appears_in_list(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            _create_project(client, "Visible")
            projects = client.get("/api/projects").json()
        assert any(p["name"] == "Visible" for p in projects)

    def test_archived_projects_excluded(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client, "To Archive")["id"]
            client.patch(f"/api/projects/{pid}", json={"archived": True})
            projects = client.get("/api/projects").json()
        assert not any(p["id"] == pid for p in projects)

    def test_multiple_projects_ordered_newest_first(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            _create_project(client, "First")
            _create_project(client, "Second")
            projects = client.get("/api/projects").json()
        assert projects[0]["created_at"] >= projects[-1]["created_at"]


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------

class TestUpdateProject:
    def test_rename(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client, "Old Name")["id"]
            resp = client.patch(f"/api/projects/{pid}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_set_git_remote(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)["id"]
            resp = client.patch(
                f"/api/projects/{pid}",
                json={"git_remote": "https://github.com/x/y.git"},
            )
        assert resp.json()["git_remote"] == "https://github.com/x/y.git"

    def test_archive(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)["id"]
            resp = client.patch(f"/api/projects/{pid}", json={"archived": True})
        assert resp.json()["archived"] is True

    def test_patch_unknown_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.patch("/api/projects/proj_nope", json={"name": "X"})
        assert resp.status_code == 404

    def test_backward_compat_default_cli_patch(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)["id"]
            resp = client.patch(
                f"/api/projects/{pid}",
                json={"default_cli": "hermes", "allow_cli_switch": False},
            )
        data = resp.json()
        assert data["default_cli"] == "hermes"
        assert data["allow_cli_switch"] is False


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteProject:
    def test_returns_200(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)["id"]
            resp = client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 200

    def test_project_gone_after_delete(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)["id"]
            client.delete(f"/api/projects/{pid}")
            resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 404

    def test_delete_unknown_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.delete("/api/projects/proj_nope")
        assert resp.status_code == 404

    def test_tasks_reassigned_to_null_on_delete(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)["id"]
            # Inject a task belonging to this project
            task = Task(
                id="task_test_0000_aaaaaaaa",
                prompt="do work",
                directory=Path.home(),
                project_id=pid,
            )
            server.executor.pool.tasks.append(task)
            client.delete(f"/api/projects/{pid}")
            # Task should still exist but project_id nulled
            remaining = [t for t in server.executor.pool.tasks if t.id == task.id]
        assert len(remaining) == 1
        assert remaining[0].project_id is None
