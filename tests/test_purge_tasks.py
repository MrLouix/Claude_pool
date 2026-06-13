"""Tests for DELETE /api/tasks?status=X purge endpoint (Step 7 Part B)."""

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


class TestPurgeCompleted:
    def test_purge_success_tasks(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=success removes success tasks and returns count."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "success", "t_done_1")
            _add_task(server, "success", "t_done_2")
            _add_task(server, "failed", "t_fail_1")

            resp = client.delete("/api/tasks?status=success")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

    def test_purge_failed_tasks(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=failed removes failed tasks and returns count."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "failed", "t_fail_2")
            _add_task(server, "success", "t_done_3")

            resp = client.delete("/api/tasks?status=failed")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1


class TestPurgeRejected:
    def test_reject_purge_running(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=running must return 400."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "running", "t_run_1")
            resp = client.delete("/api/tasks?status=running")
        assert resp.status_code == 400

    def test_reject_purge_pending(self, tmp_path: Path) -> None:
        """DELETE /api/tasks?status=pending must return 400."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            _add_task(server, "pending", "t_pend_1")
            resp = client.delete("/api/tasks?status=pending")
        assert resp.status_code == 400


class TestPurgeCount:
    def test_returns_deleted_count(self, tmp_path: Path) -> None:
        """Response body contains the number of deleted tasks."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            for i in range(4):
                _add_task(server, "skipped", f"t_skip_{i}")

            resp = client.delete("/api/tasks?status=skipped")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 4

    def test_returns_zero_when_no_matching_tasks(self, tmp_path: Path) -> None:
        """Returns deleted=0 when no tasks match the given status."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.delete("/api/tasks?status=failed")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0
