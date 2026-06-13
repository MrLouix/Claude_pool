"""Tests for GET/PUT /api/settings/cli-commands and POST /api/settings/cli-commands/test."""

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


# ---------------------------------------------------------------------------
# GET /api/settings/cli-commands
# ---------------------------------------------------------------------------

class TestGetCliCommands:
    def test_returns_200(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/settings/cli-commands")
        assert resp.status_code == 200

    def test_returns_list(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = client.get("/api/settings/cli-commands").json()
        assert isinstance(data, list)

    def test_default_claude_command_present(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = client.get("/api/settings/cli-commands").json()
        assert any(c["id"] == "claude" for c in data)

    def test_response_has_required_fields(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = client.get("/api/settings/cli-commands").json()
        required = ("id", "name", "binary", "args_template", "enabled", "priority_requests",
                    "priority_subtasks", "parser")
        for field in required:
            assert field in data[0], f"missing field: {field}"

    def test_default_claude_parser_is_claude_json(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            data = client.get("/api/settings/cli-commands").json()
        claude = next(c for c in data if c["id"] == "claude")
        assert claude["parser"] == "claude_json"


# ---------------------------------------------------------------------------
# PUT /api/settings/cli-commands
# ---------------------------------------------------------------------------

class TestPutCliCommands:
    def test_returns_200(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            existing = client.get("/api/settings/cli-commands").json()
            resp = client.put("/api/settings/cli-commands", json=existing)
        assert resp.status_code == 200

    def test_upsert_new_command(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            existing = client.get("/api/settings/cli-commands").json()
            new_cmd = {
                "id": "llm2",
                "name": "LLM2",
                "binary": "llm2",
                "args_template": '["{prompt}"]',
                "parser": "plain",
                "enabled": True,
                "priority_requests": 50,
                "priority_subtasks": 50,
                "models": [],
            }
            resp = client.put("/api/settings/cli-commands", json=existing + [new_cmd])
            result = resp.json()
        assert any(c["id"] == "llm2" for c in result)

    def test_delete_removed_command(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            # Add extra command
            new_cmd = {
                "id": "to_delete",
                "name": "ToDel",
                "binary": "td",
                "args_template": '["{prompt}"]',
                "parser": "plain",
                "enabled": True,
                "priority_requests": 99,
                "priority_subtasks": 99,
                "models": [],
            }
            client.put("/api/settings/cli-commands",
                       json=[c for c in client.get("/api/settings/cli-commands").json()] + [new_cmd])
            # Remove it
            remaining = [c for c in client.get("/api/settings/cli-commands").json()
                         if c["id"] != "to_delete"]
            resp = client.put("/api/settings/cli-commands", json=remaining)
        assert not any(c["id"] == "to_delete" for c in resp.json())

    def test_parser_field_persisted(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            existing = client.get("/api/settings/cli-commands").json()
            for c in existing:
                if c["id"] == "claude":
                    c["parser"] = "plain"
            client.put("/api/settings/cli-commands", json=existing)
            data = client.get("/api/settings/cli-commands").json()
        claude = next(c for c in data if c["id"] == "claude")
        assert claude["parser"] == "plain"

    def test_update_priority(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            existing = client.get("/api/settings/cli-commands").json()
            for c in existing:
                if c["id"] == "claude":
                    c["priority_requests"] = 42
            resp = client.put("/api/settings/cli-commands", json=existing)
        claude = next(c for c in resp.json() if c["id"] == "claude")
        assert claude["priority_requests"] == 42


# ---------------------------------------------------------------------------
# POST /api/settings/cli-commands/test
# ---------------------------------------------------------------------------

class TestPostCliCommandTest:
    def test_returns_200(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            with patch("asyncio.create_subprocess_exec") as mock_proc:
                proc = AsyncMock()
                proc.communicate = AsyncMock(return_value=(b"claude 1.0", b""))
                proc.returncode = 0
                mock_proc.return_value = proc
                resp = client.post("/api/settings/cli-commands/test", json={"id": "claude"})
        assert resp.status_code == 200

    def test_success_true_on_zero_exit(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            with patch("asyncio.create_subprocess_exec") as mock_proc:
                proc = AsyncMock()
                proc.communicate = AsyncMock(return_value=(b"v1.2.3", b""))
                proc.returncode = 0
                mock_proc.return_value = proc
                data = client.post("/api/settings/cli-commands/test", json={"id": "claude"}).json()
        assert data["success"] is True
        assert "v1.2.3" in data["output"]

    def test_success_false_on_nonzero_exit(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            with patch("asyncio.create_subprocess_exec") as mock_proc:
                proc = AsyncMock()
                proc.communicate = AsyncMock(return_value=(b"", b"error"))
                proc.returncode = 1
                mock_proc.return_value = proc
                data = client.post("/api/settings/cli-commands/test", json={"id": "claude"}).json()
        assert data["success"] is False

    def test_unknown_id_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post("/api/settings/cli-commands/test", json={"id": "nonexistent"})
        assert resp.status_code == 404

    def test_file_not_found_returns_failure(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("not found")):
                data = client.post("/api/settings/cli-commands/test", json={"id": "claude"}).json()
        assert data["success"] is False
        assert "not found" in data["output"].lower() or "binary" in data["output"].lower()

    def test_response_has_success_and_output(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            with patch("asyncio.create_subprocess_exec") as mock_proc:
                proc = AsyncMock()
                proc.communicate = AsyncMock(return_value=(b"ok", b""))
                proc.returncode = 0
                mock_proc.return_value = proc
                data = client.post("/api/settings/cli-commands/test", json={"id": "claude"}).json()
        assert "success" in data
        assert "output" in data
