"""Tests for PATCH /api/tasks/{id} status=skipped (Step 8)."""

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


def _add_task(server, status: str, task_id: str) -> Task:
    task = Task(id=task_id, prompt="test", directory=Path("/tmp"), status=status)
    server.executor.pool.tasks.append(task)
    return task


class TestPatchSkipPendingTask:
    def test_skip_pending_task_updates_status(self, tmp_path: Path) -> None:
        """PATCH /api/tasks/{id} {status: 'skipped'} on a pending task sets status to skipped."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "pending", "t_pend")
            resp = client.patch(f"/api/tasks/{task.id}", json={"status": "skipped"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_skip_pending_task_mutates_pool(self, tmp_path: Path) -> None:
        """PATCH skip on pending task updates the in-memory task object."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "pending", "t_mut")
            client.patch(f"/api/tasks/{task.id}", json={"status": "skipped"})
            assert task.status == "skipped"

    def test_skip_returns_task_response(self, tmp_path: Path) -> None:
        """PATCH skip response includes id and status fields."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "pending", "t_resp")
            resp = client.patch(f"/api/tasks/{task.id}", json={"status": "skipped"})

        body = resp.json()
        assert "id" in body
        assert body["id"] == "t_resp"
        assert body["status"] == "skipped"


class TestPatchSkipNonPendingTask:
    def test_skip_running_task_returns_409(self, tmp_path: Path) -> None:
        """PATCH status=skipped on a running task returns 409 Conflict."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "running", "t_run")
            resp = client.patch(f"/api/tasks/{task.id}", json={"status": "skipped"})

        assert resp.status_code == 409

    def test_skip_failed_task_returns_409(self, tmp_path: Path) -> None:
        """PATCH status=skipped on a failed task returns 409 Conflict."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "failed", "t_fail")
            resp = client.patch(f"/api/tasks/{task.id}", json={"status": "skipped"})

        assert resp.status_code == 409

    def test_skip_completed_task_returns_409(self, tmp_path: Path) -> None:
        """PATCH status=skipped on a completed (success) task returns 409 Conflict."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "success", "t_done")
            resp = client.patch(f"/api/tasks/{task.id}", json={"status": "skipped"})

        assert resp.status_code == 409

    def test_skip_nonexistent_task_returns_404(self, tmp_path: Path) -> None:
        """PATCH status=skipped on a missing task returns 404."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.patch("/api/tasks/no_such_task", json={"status": "skipped"})

        assert resp.status_code == 404

    def test_invalid_status_value_returns_422(self, tmp_path: Path) -> None:
        """PATCH with status='running' (not allowed) returns 422."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            task = _add_task(server, "pending", "t_inv")
            resp = client.patch(f"/api/tasks/{task.id}", json={"status": "running"})

        assert resp.status_code == 422
