"""Tests for GET/PUT /api/settings (Step 7 — settings KV store)."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState
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


class TestSettingsDefaults:
    def test_get_returns_seeded_defaults(self, tmp_path: Path) -> None:
        """GET /api/settings returns the seeded default keys."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("max_subtasks_per_task") == "10"
        assert data.get("auto_decompose") == "true"


class TestSettingsUpdate:
    def test_put_updates_value(self, tmp_path: Path) -> None:
        """PUT /api/settings updates a key and returns the full settings dict."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.put("/api/settings", json={"max_subtasks_per_task": "5"})
        assert resp.status_code == 200
        assert resp.json()["max_subtasks_per_task"] == "5"

    def test_put_adds_new_key(self, tmp_path: Path) -> None:
        """PUT /api/settings can add a new arbitrary key."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.put("/api/settings", json={"my_custom_key": "hello"})
        assert resp.status_code == 200
        assert resp.json()["my_custom_key"] == "hello"


class TestSettingsMerge:
    def test_put_merges_not_replaces(self, tmp_path: Path) -> None:
        """PUT /api/settings merges into existing settings, not replaces."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            # Update one key
            client.put("/api/settings", json={"max_subtasks_per_task": "3"})
            # Other default keys must still be present
            resp = client.get("/api/settings")
        data = resp.json()
        assert data["max_subtasks_per_task"] == "3"
        assert "auto_decompose" in data, "PUT must not delete unrelated keys"
