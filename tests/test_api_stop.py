"""Tests for POST /api/tasks/{task_id}/stop endpoint."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from claude_pool.api import ApiServer
from claude_pool.models import PoolState, Task
from claude_pool.storage import save_pool


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def pool_file(tmp_path: Path) -> Path:
    state = PoolState(pool_file=tmp_path / "pool.json")
    save_pool(state)
    return tmp_path / "pool.json"


@pytest.fixture
def api(pool_file: Path):
    """ApiServer with run_pool and signal.signal stubbed."""
    with (
        patch("claude_pool.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("claude_pool.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


def _add_task(server: ApiServer, status: str = "pending") -> Task:
    task = Task(
        id=f"task_{len(server.executor.pool.tasks):04d}",
        prompt="test prompt",
        directory=Path.home(),
        status=status,
    )
    server.executor.pool.tasks.append(task)
    server.executor._save_state()
    return task


# ── POST /api/tasks/{task_id}/stop ────────────────────────────────────────────


def test_stop_task_503_no_executor(pool_file: Path):
    """Returns 503 when executor is not initialized."""
    with (
        patch("claude_pool.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("claude_pool.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            # Lifespan has already run and set executor; null it out to simulate 503
            server.executor = None
            r = client.post("/api/tasks/any-id/stop")
    assert r.status_code == 503
    assert "Executor not initialized" in r.json()["detail"]


def test_stop_task_404_unknown_id(api):
    """Returns 404 when task_id does not exist in the pool."""
    client, _ = api
    r = client.post("/api/tasks/no-such-id/stop")
    assert r.status_code == 404
    assert "no-such-id" in r.json()["detail"]


def test_stop_task_400_wrong_status_pending(api):
    """Returns 400 when task is pending (not running)."""
    client, server = api
    task = _add_task(server, status="pending")
    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 400
    assert "pending" in r.json()["detail"]


def test_stop_task_400_wrong_status_success(api):
    """Returns 400 when task is already succeeded."""
    client, server = api
    task = _add_task(server, status="success")
    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 400
    assert "success" in r.json()["detail"]


def test_stop_task_400_wrong_status_failed(api):
    """Returns 400 when task has already failed."""
    client, server = api
    task = _add_task(server, status="failed")
    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 400


def test_stop_task_200_running(api):
    """Returns 200 with status=stopped when task is running."""
    client, server = api
    task = _add_task(server, status="running")

    # stop_task sets task.status = "stopped" as a side effect
    async def _fake_stop(task_id: str) -> bool:
        t = next(t for t in server.executor.pool.tasks if t.id == task_id)
        t.status = "stopped"
        return True

    server.executor.stop_task = _fake_stop

    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == task.id
    assert body["status"] == "stopped"


def test_stop_task_200_response_fields(api):
    """Response contains all expected TaskResponse fields."""
    client, server = api
    task = _add_task(server, status="running")

    async def _fake_stop(task_id: str) -> bool:
        t = next(t for t in server.executor.pool.tasks if t.id == task_id)
        t.status = "stopped"
        return True

    server.executor.stop_task = _fake_stop

    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 200
    body = r.json()
    for field in ("id", "prompt", "directory", "status", "retry_count", "bucket_id", "priority"):
        assert field in body, f"missing field: {field}"


def test_stop_task_broadcasts_event(api):
    """stop endpoint broadcasts a task_stopped WebSocket event."""
    client, server = api
    task = _add_task(server, status="running")

    broadcast_calls: list[dict] = []

    async def _capture_broadcast(event: dict) -> None:
        broadcast_calls.append(event)

    async def _fake_stop(task_id: str) -> bool:
        t = next(t for t in server.executor.pool.tasks if t.id == task_id)
        t.status = "stopped"
        return True

    server.executor.stop_task = _fake_stop
    server._broadcast_event = _capture_broadcast  # type: ignore[method-assign]

    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 200
    assert any(e.get("event") == "task_stopped" for e in broadcast_calls)


def test_stop_task_error_detail_contains_status(api):
    """400 detail message names the actual task status."""
    client, server = api
    task = _add_task(server, status="skipped")
    r = client.post(f"/api/tasks/{task.id}/stop")
    assert r.status_code == 400
    assert "skipped" in r.json()["detail"]
