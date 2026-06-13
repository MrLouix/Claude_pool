"""Tests for v2 project-chat CRUD endpoints."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState
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


def _create_project(client: TestClient, name: str = "Proj") -> str:
    resp = client.post(
        "/api/projects",
        json={"name": name, "directory": str(Path.home())},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_chat(client: TestClient, project_id: str, label: str = "Chat") -> dict:
    resp = client.post(
        f"/api/projects/{project_id}/chats",
        json={"label": label},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create chat
# ---------------------------------------------------------------------------

class TestCreateChat:
    def test_returns_201(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            resp = client.post(f"/api/projects/{pid}/chats", json={"label": "New Chat"})
        assert resp.status_code == 201

    def test_response_has_required_fields(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            data = _create_chat(client, pid, "My Chat")
        for field in ("id", "project_id", "label", "position", "created_at"):
            assert field in data, f"missing field: {field}"

    def test_project_id_matches(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            data = _create_chat(client, pid)
        assert data["project_id"] == pid

    def test_unknown_project_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post("/api/projects/proj_nope/chats", json={"label": "x"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Ordering / position
# ---------------------------------------------------------------------------

class TestChatOrdering:
    def test_first_chat_has_position_zero(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            data = _create_chat(client, pid, "First")
        assert data["position"] == 0

    def test_second_chat_has_position_one(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            _create_chat(client, pid, "First")
            data = _create_chat(client, pid, "Second")
        assert data["position"] == 1

    def test_list_ordered_by_position(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            _create_chat(client, pid, "A")
            _create_chat(client, pid, "B")
            _create_chat(client, pid, "C")
            chats = client.get(f"/api/projects/{pid}/chats").json()
        positions = [c["position"] for c in chats]
        assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# List chats for project
# ---------------------------------------------------------------------------

class TestListChats:
    def test_empty_list_for_new_project(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            chats = client.get(f"/api/projects/{pid}/chats").json()
        assert chats == []

    def test_created_chat_appears_in_list(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            _create_chat(client, pid, "Visible Chat")
            chats = client.get(f"/api/projects/{pid}/chats").json()
        assert any(c["label"] == "Visible Chat" for c in chats)

    def test_unknown_project_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/projects/proj_nope/chats")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH chat
# ---------------------------------------------------------------------------

class TestPatchChat:
    def test_rename_chat(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid, "Old Label")["id"]
            resp = client.patch(f"/api/chats/{cid}", json={"label": "New Label"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "New Label"

    def test_reorder_chat(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)["id"]
            resp = client.patch(f"/api/chats/{cid}", json={"position": 99})
        assert resp.json()["position"] == 99

    def test_patch_unknown_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.patch("/api/chats/chat_nope", json={"label": "x"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE chat (v2)
# ---------------------------------------------------------------------------

class TestDeleteV2Chat:
    def test_delete_returns_200(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)["id"]
            resp = client.delete(f"/api/chats/{cid}")
        assert resp.status_code == 200

    def test_chat_gone_after_delete(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)["id"]
            client.delete(f"/api/chats/{cid}")
            chats = client.get(f"/api/projects/{pid}/chats").json()
        assert not any(c["id"] == cid for c in chats)

    def test_delete_unknown_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.delete("/api/chats/chat_nope_nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Legacy /api/chats still work
# ---------------------------------------------------------------------------

class TestLegacyChatsUnchanged:
    def test_get_chats_returns_200(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/chats")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_post_legacy_chat_returns_201(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "Legacy Chat"},
            )
        assert resp.status_code == 201

    def test_delete_legacy_chat(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            cid = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "To Delete"},
            ).json()["id"]
            resp = client.delete(f"/api/chats/{cid}")
        assert resp.status_code == 200
