"""Tests for GET /api/tasks filters and DELETE /api/tasks purge (Step 8)."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState, Task
from team_cli.storage import save_pool


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


def _add_task(server, status: str, task_id: str, project_id: str | None = None,
              kind: str = "request") -> Task:
    task = Task(
        id=task_id,
        prompt="test",
        directory=Path("/tmp"),
        status=status,
        project_id=project_id,
        kind=kind,
    )
    server.executor.pool.tasks.append(task)
    return task


class TestGetTasksStatusFilter:
    def test_status_running_returns_only_running(self, tmp_path: Path) -> None:
        """GET /api/tasks?status=running returns only running tasks."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "running", "t_run")
            _add_task(server, "pending", "t_pend")
            _add_task(server, "success", "t_done")

            resp = client.get("/api/tasks?status=running")

        assert resp.status_code == 200
        data = resp.json()
        assert all(t["status"] == "running" for t in data)
        ids = [t["id"] for t in data]
        assert "t_run" in ids
        assert "t_pend" not in ids
        assert "t_done" not in ids

    def test_status_completed_returns_success_tasks(self, tmp_path: Path) -> None:
        """GET /api/tasks?status=completed maps to internal 'success' status."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "success", "t_ok")
            _add_task(server, "failed", "t_fail")

            resp = client.get("/api/tasks?status=completed")

        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()]
        assert "t_ok" in ids
        assert "t_fail" not in ids

    def test_no_filter_returns_all(self, tmp_path: Path) -> None:
        """GET /api/tasks with no filters returns all tasks."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "pending", "t1")
            _add_task(server, "running", "t2")
            _add_task(server, "success", "t3")

            resp = client.get("/api/tasks")

        ids = [t["id"] for t in resp.json()]
        assert "t1" in ids
        assert "t2" in ids
        assert "t3" in ids


class TestGetTasksProjectFilter:
    def test_project_id_filter_returns_only_that_project(self, tmp_path: Path) -> None:
        """GET /api/tasks?project_id=X returns only tasks for that project."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "pending", "t_proj_a", project_id="proj_a")
            _add_task(server, "pending", "t_proj_b", project_id="proj_b")
            _add_task(server, "pending", "t_no_proj")

            resp = client.get("/api/tasks?project_id=proj_a")

        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()]
        assert "t_proj_a" in ids
        assert "t_proj_b" not in ids
        assert "t_no_proj" not in ids

    def test_project_id_returns_empty_when_no_match(self, tmp_path: Path) -> None:
        """GET /api/tasks?project_id=nonexistent returns empty list."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "pending", "t_other", project_id="other")

            resp = client.get("/api/tasks?project_id=nonexistent")

        assert resp.status_code == 200
        assert resp.json() == []


class TestGetTasksKindFilter:
    def test_kind_subtask_filter(self, tmp_path: Path) -> None:
        """GET /api/tasks?kind=subtask returns only subtask-kind tasks."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "pending", "t_req", kind="request")
            _add_task(server, "pending", "t_sub", kind="subtask")

            resp = client.get("/api/tasks?kind=subtask")

        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()]
        assert "t_sub" in ids
        assert "t_req" not in ids


class TestDeleteTasksCompletedPurge:
    def test_delete_completed_removes_success_tasks(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=completed removes tasks with internal status 'success'."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "success", "t_done_1")
            _add_task(server, "success", "t_done_2")
            _add_task(server, "failed",  "t_fail")

            resp = client.delete("/api/tasks?status=completed")

        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

    def test_delete_completed_does_not_remove_other_statuses(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=completed leaves non-success tasks untouched."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "success", "t_done")
            _add_task(server, "failed",  "t_fail")
            _add_task(server, "pending", "t_pend")

            client.delete("/api/tasks?status=completed")
            remaining = [t.id for t in server.executor.pool.tasks]

        assert "t_fail" in remaining
        assert "t_pend" in remaining
        assert "t_done" not in remaining


class TestDeleteTasksRejected:
    def test_delete_running_returns_400(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=running must return 400 or 422."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "running", "t_run")
            resp = client.delete("/api/tasks?status=running")

        assert resp.status_code in (400, 422)

    def test_delete_pending_returns_400(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=pending must return 400 or 422."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            resp = client.delete("/api/tasks?status=pending")

        assert resp.status_code in (400, 422)
