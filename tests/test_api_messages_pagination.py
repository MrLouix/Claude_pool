"""Tests for Step 5 — paginated GET /api/chats/{id}/messages?paginate=true."""
import time
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


def _create_project(client: TestClient) -> str:
    return client.post(
        "/api/projects", json={"name": "P", "directory": str(Path.home())}
    ).json()["id"]


def _create_chat(client: TestClient, project_id: str) -> str:
    return client.post(
        f"/api/projects/{project_id}/chats", json={"label": "C"}
    ).json()["id"]


def _post_message(client: TestClient, chat_id: str, content: str) -> dict:
    """Post a message and introduce a small sleep so created_at values differ."""
    resp = client.post(f"/api/chats/{chat_id}/messages", json={"content": content})
    assert resp.status_code == 201, resp.text
    time.sleep(0.02)  # ensure monotonically increasing created_at
    return resp.json()


# ---------------------------------------------------------------------------
# ?paginate=true — basic response shape
# ---------------------------------------------------------------------------

class TestPaginateQueryParam:
    def test_paginate_true_returns_object(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            resp = client.get(f"/api/chats/{cid}/messages?paginate=true")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict), "Expected object response when paginate=true"

    def test_paginate_response_has_items_key(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.get(f"/api/chats/{cid}/messages?paginate=true").json()
        assert "items" in data, "Paginated response must have 'items' key"

    def test_paginate_response_has_has_more_key(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.get(f"/api/chats/{cid}/messages?paginate=true").json()
        assert "has_more" in data, "Paginated response must have 'has_more' key"

    def test_paginate_items_is_list(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.get(f"/api/chats/{cid}/messages?paginate=true").json()
        assert isinstance(data["items"], list)

    def test_paginate_has_more_is_bool(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.get(f"/api/chats/{cid}/messages?paginate=true").json()
        assert isinstance(data["has_more"], bool)

    def test_without_paginate_still_returns_list(self, tmp_path: Path) -> None:
        """?paginate=true is opt-in; default must remain a list for backward compat."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            result = client.get(f"/api/chats/{cid}/messages").json()
        assert isinstance(result, list), "Default (no paginate param) must return a list"


# ---------------------------------------------------------------------------
# has_more flag
# ---------------------------------------------------------------------------

class TestHasMoreFlag:
    def test_has_more_false_when_fewer_than_limit(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            for i in range(3):
                _post_message(client, cid, f"msg {i}")
            data = client.get(f"/api/chats/{cid}/messages?paginate=true&limit=10").json()
        assert data["has_more"] is False

    def test_has_more_true_when_more_exist(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            for i in range(5):
                _post_message(client, cid, f"msg {i}")
            data = client.get(f"/api/chats/{cid}/messages?paginate=true&limit=2").json()
        assert data["has_more"] is True, "has_more should be True when more messages exist"

    def test_has_more_false_at_exact_limit(self, tmp_path: Path) -> None:
        """Exactly 'limit' messages in DB — no more pages."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            for i in range(3):
                _post_message(client, cid, f"msg {i}")
            data = client.get(f"/api/chats/{cid}/messages?paginate=true&limit=3").json()
        assert data["has_more"] is False

    def test_items_capped_at_limit(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            for i in range(5):
                _post_message(client, cid, f"msg {i}")
            data = client.get(f"/api/chats/{cid}/messages?paginate=true&limit=2").json()
        assert len(data["items"]) == 2

    def test_empty_chat_has_more_false(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.get(f"/api/chats/{cid}/messages?paginate=true").json()
        assert data["has_more"] is False
        assert data["items"] == []


# ---------------------------------------------------------------------------
# ?before= cursor pagination
# ---------------------------------------------------------------------------

class TestBeforeCursor:
    def test_before_returns_earlier_messages(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            m1 = _post_message(client, cid, "first")
            m2 = _post_message(client, cid, "second")
            m3 = _post_message(client, cid, "third")
            data = client.get(
                f"/api/chats/{cid}/messages?paginate=true&before={m3['id']}"
            ).json()
        ids = [m["id"] for m in data["items"]]
        assert m3["id"] not in ids, "before cursor should exclude the referenced message"
        assert m1["id"] in ids or m2["id"] in ids, "Earlier messages must be included"

    def test_before_excludes_message_and_newer(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            _post_message(client, cid, "first")
            m2 = _post_message(client, cid, "second")
            m3 = _post_message(client, cid, "third")
            data = client.get(
                f"/api/chats/{cid}/messages?paginate=true&before={m2['id']}"
            ).json()
        ids = [m["id"] for m in data["items"]]
        assert m2["id"] not in ids
        assert m3["id"] not in ids

    def test_before_with_limit_and_has_more(self, tmp_path: Path) -> None:
        """5 messages total; request limit=2&before=msg5 → 2 results, has_more=True."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msgs = [_post_message(client, cid, f"msg {i}") for i in range(5)]
            last_id = msgs[-1]["id"]
            data = client.get(
                f"/api/chats/{cid}/messages?paginate=true&limit=2&before={last_id}"
            ).json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True

    def test_before_first_message_returns_empty(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            m1 = _post_message(client, cid, "only")
            data = client.get(
                f"/api/chats/{cid}/messages?paginate=true&before={m1['id']}"
            ).json()
        assert data["items"] == []
        assert data["has_more"] is False
