"""Tests for API layer with DB-backed storage (step 4/5)."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.database import DatabaseManager
from team_cli.models import PoolState, Task
from team_cli.storage import save_pool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


from contextlib import contextmanager


@contextmanager
def _make_api(pool_file: Path):
    """Yield a (TestClient, ApiServer) pair with run_pool stubbed."""
    from unittest.mock import AsyncMock
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


def _seed_db(pool_file: Path, tasks: list[Task]) -> None:
    async def _run() -> None:
        db = DatabaseManager(pool_file)
        await db.init()
        for t in tasks:
            await db.upsert_task(t.to_dict())

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# test_get_pool_returns_tasks_from_db
# ---------------------------------------------------------------------------


def test_get_pool_returns_tasks_from_db(tmp_path: Path) -> None:
    """GET /api/tasks returns tasks that were seeded directly into the DB."""
    pool_file = tmp_path / "pool.db"
    task_a = Task(id="task_a", prompt="Task A", directory=Path("/tmp"))
    task_b = Task(id="task_b", prompt="Task B", directory=Path("/tmp"))

    state = PoolState(tasks=[task_a, task_b], pool_file=pool_file)
    save_pool(state)

    with _make_api(pool_file) as (client, _):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        ids = {t["id"] for t in resp.json()}
        assert "task_a" in ids
        assert "task_b" in ids


# ---------------------------------------------------------------------------
# test_post_task_persists_to_db
# ---------------------------------------------------------------------------


def test_post_task_persists_to_db(tmp_path: Path) -> None:
    """POST /api/tasks creates a task that is readable via DatabaseManager."""
    pool_file = tmp_path / "pool.db"
    state = PoolState(tasks=[], pool_file=pool_file)
    save_pool(state)

    with _make_api(pool_file) as (client, _server):
        resp = client.post(
            "/api/tasks",
            json={"prompt": "Do something", "directory": str(tmp_path)},
        )
        assert resp.status_code == 200
        task_id = resp.json()["id"]

    # Verify directly via DatabaseManager
    async def _check() -> bool:
        db = DatabaseManager(pool_file)
        await db.init()
        row = await db.get_task(task_id)
        return row is not None and row["prompt"] == "Do something"

    assert asyncio.run(_check())


# ---------------------------------------------------------------------------
# test_get_providers_available
# ---------------------------------------------------------------------------


def test_get_providers_available(tmp_path: Path) -> None:
    """GET /api/providers returns at least 'claude' when shutil.which finds it."""
    pool_file = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pool_file))

    def _fake_which(cmd: str) -> str | None:
        return "/usr/bin/claude" if cmd == "claude" else None

    with patch("team_cli.api.shutil.which", side_effect=_fake_which):
        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/providers")
            assert resp.status_code == 200
            providers = {p["name"]: p["available"] for p in resp.json()}
            assert "claude" in providers
            assert providers["claude"] is True


# ---------------------------------------------------------------------------
# test_pool_file_coercion
# ---------------------------------------------------------------------------


def test_pool_file_coercion(tmp_path: Path) -> None:
    """ApiServer silently coerces a .json path to .db at startup."""
    json_path = tmp_path / "pool.json"
    db_path = tmp_path / "pool.db"

    # Pre-create an empty DB at the .db path so load_pool succeeds
    save_pool(PoolState(tasks=[], pool_file=db_path))

    from unittest.mock import AsyncMock
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(json_path)  # pass .json path
        # Internal pool_file must have been coerced to .db
        assert server.pool_file.suffix == ".db"
        assert server.pool_file == db_path
