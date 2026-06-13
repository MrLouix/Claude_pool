"""Tests for PUT /api/settings/cli-commands — priority order, removal, idempotency."""

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
            yield client


def _pool(tmp_path: Path) -> Path:
    pf = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pf))
    return pf


def _base_cmd(id: str, name: str, priority_requests: int = 100) -> dict:
    return {
        "id": id,
        "name": name,
        "binary": id,
        "args_template": '["-p","{prompt}"]',
        "resume_template": None,
        "model_flag": None,
        "models": [],
        "default_model": None,
        "enabled": True,
        "priority_requests": priority_requests,
        "priority_subtasks": priority_requests,
        "parser": "plain",
    }


class TestPutUpdatesPriorityOrder:
    def test_put_updates_priority_order(self, tmp_path: Path) -> None:
        """PUT two commands with swapped priority_requests → GET confirms new order."""
        pf = _pool(tmp_path)
        with _make_api(pf) as client:
            cmd_a = _base_cmd("cmd_a", "Alpha", priority_requests=1)
            cmd_b = _base_cmd("cmd_b", "Beta", priority_requests=2)
            client.put("/api/settings/cli-commands", json=[cmd_a, cmd_b])

            # Swap priorities
            cmd_a["priority_requests"] = 10
            cmd_b["priority_requests"] = 1
            client.put("/api/settings/cli-commands", json=[cmd_a, cmd_b])

            result = client.get("/api/settings/cli-commands").json()

        ordered_ids = [c["id"] for c in result if c["id"] in ("cmd_a", "cmd_b")]
        assert ordered_ids == ["cmd_b", "cmd_a"], (
            f"Expected cmd_b first (priority 1), got: {ordered_ids}"
        )


class TestPutRemovesUnlistedCommand:
    def test_put_removes_unlisted_command(self, tmp_path: Path) -> None:
        """PUT with only one of two existing commands → GET returns only that one."""
        pf = _pool(tmp_path)
        with _make_api(pf) as client:
            client.put("/api/settings/cli-commands", json=[
                _base_cmd("keep_me", "Keep"),
                _base_cmd("remove_me", "Remove"),
            ])

            # PUT with only 'keep_me'
            client.put("/api/settings/cli-commands", json=[_base_cmd("keep_me", "Keep")])

            result = client.get("/api/settings/cli-commands").json()

        ids = [c["id"] for c in result]
        assert "keep_me" in ids
        assert "remove_me" not in ids


class TestPutIdempotent:
    def test_put_idempotent(self, tmp_path: Path) -> None:
        """PUT same list twice → GET returns identical list."""
        pf = _pool(tmp_path)
        with _make_api(pf) as client:
            payload = [_base_cmd("idm_a", "IdmA", 1), _base_cmd("idm_b", "IdmB", 2)]
            client.put("/api/settings/cli-commands", json=payload)
            client.put("/api/settings/cli-commands", json=payload)

            result = client.get("/api/settings/cli-commands").json()

        matching = [c for c in result if c["id"] in ("idm_a", "idm_b")]
        assert len(matching) == 2
        assert matching[0]["id"] == "idm_a"
        assert matching[1]["id"] == "idm_b"


class TestPutReturnsUpdatedList:
    def test_put_returns_updated_list(self, tmp_path: Path) -> None:
        """PUT response body contains the full updated list."""
        pf = _pool(tmp_path)
        with _make_api(pf) as client:
            payload = [_base_cmd("ret_a", "RetA")]
            resp = client.put("/api/settings/cli-commands", json=payload)

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert any(c["id"] == "ret_a" for c in body), (
            "PUT response must include the newly upserted command"
        )
