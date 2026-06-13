"""Tests for v2 chat message endpoints."""

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


def _create_project(client: TestClient, name: str = "P") -> str:
    return client.post(
        "/api/projects", json={"name": name, "directory": str(Path.home())}
    ).json()["id"]


def _create_chat(client: TestClient, project_id: str, label: str = "C") -> str:
    return client.post(
        f"/api/projects/{project_id}/chats", json={"label": label}
    ).json()["id"]


# ---------------------------------------------------------------------------
# POST /api/chats/{id}/messages — v2 path
# ---------------------------------------------------------------------------

class TestPostV2Message:
    def test_returns_201(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            resp = client.post(f"/api/chats/{cid}/messages", json={"content": "hello"})
        assert resp.status_code == 201

    def test_returns_user_message(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.post(
                f"/api/chats/{cid}/messages", json={"content": "hello"}
            ).json()
        assert data["role"] == "user"
        assert data["content"] == "hello"
        assert data["chat_id"] == cid

    def test_response_has_required_fields(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            data = client.post(
                f"/api/chats/{cid}/messages", json={"content": "hi"}
            ).json()
        for field in ("id", "chat_id", "role", "content", "created_at"):
            assert field in data, f"missing field: {field}"

    def test_task_enqueued_in_pool(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "do something"})
            tasks = [t for t in server.executor.pool.tasks if t.chat_id == cid]
        assert len(tasks) == 1
        assert tasks[0].prompt == "do something"

    def test_task_has_v2_fields(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "work"})
            tasks = [t for t in server.executor.pool.tasks if t.chat_id == cid]
        assert tasks[0].project_id == pid
        assert tasks[0].chat_id == cid
        assert tasks[0].kind == "request"

    def test_task_status_is_pending(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "run"})
            tasks = [t for t in server.executor.pool.tasks if t.chat_id == cid]
        assert tasks[0].status == "pending"

    def test_model_forwarded_to_task(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(
                f"/api/chats/{cid}/messages",
                json={"content": "run", "model": "opus"},
            )
            tasks = [t for t in server.executor.pool.tasks if t.chat_id == cid]
        assert tasks[0].model == "opus"

    def test_thread_root_id_sets_parent_message_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_msg_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root"}
            ).json()["id"]
            client.post(
                f"/api/chats/{cid}/messages",
                json={"content": "reply", "thread_root_id": root_msg_id},
            )
            tasks = [t for t in server.executor.pool.tasks if t.chat_id == cid]
        reply_task = next(t for t in tasks if t.prompt == "reply")
        assert reply_task.parent_message_id == root_msg_id

    def test_unknown_chat_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.post("/api/chats/chat_nope/messages", json={"content": "x"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/chats/{id}/messages — v2 path
# ---------------------------------------------------------------------------

class TestGetV2Messages:
    def test_returns_empty_list_initially(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msgs = client.get(f"/api/chats/{cid}/messages").json()
        assert msgs == []

    def test_posted_message_appears_in_get(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "visible"})
            msgs = client.get(f"/api/chats/{cid}/messages").json()
        assert any(m["content"] == "visible" for m in msgs)

    def test_main_thread_excludes_replies(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root"}
            ).json()["id"]
            client.post(
                f"/api/chats/{cid}/messages",
                json={"content": "reply", "thread_root_id": root_id},
            )
            main_msgs = client.get(f"/api/chats/{cid}/messages").json()
        assert all(m.get("thread_root_id") is None for m in main_msgs)

    def test_thread_root_id_query_returns_replies(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root"}
            ).json()["id"]
            client.post(
                f"/api/chats/{cid}/messages",
                json={"content": "reply", "thread_root_id": root_id},
            )
            replies = client.get(
                f"/api/chats/{cid}/messages?thread_root_id={root_id}"
            ).json()
        assert len(replies) == 1
        assert replies[0]["content"] == "reply"

    def test_limit_param_caps_results(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            for i in range(5):
                client.post(f"/api/chats/{cid}/messages", json={"content": f"msg {i}"})
            msgs = client.get(f"/api/chats/{cid}/messages?limit=3").json()
        assert len(msgs) <= 3

    def test_before_param_excludes_newer_messages(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "first"})
            mid2 = client.post(
                f"/api/chats/{cid}/messages", json={"content": "second"}
            ).json()["id"]
            msgs = client.get(f"/api/chats/{cid}/messages?before={mid2}").json()
        ids = [m["id"] for m in msgs]
        assert mid2 not in ids

    def test_unknown_chat_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/chats/chat_nope/messages")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/messages/{id}/thread
# ---------------------------------------------------------------------------

class TestGetThread:
    def test_returns_root_message(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root msg"}
            ).json()["id"]
            data = client.get(f"/api/messages/{root_id}/thread").json()
        assert data["root"]["id"] == root_id
        assert data["root"]["content"] == "root msg"

    def test_thread_has_required_keys(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root"}
            ).json()["id"]
            data = client.get(f"/api/messages/{root_id}/thread").json()
        for key in ("root", "subtasks", "messages"):
            assert key in data, f"missing key: {key}"

    def test_subtasks_contains_matching_pool_task(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root"}
            ).json()["id"]
            # Manually mark the task's parent_message_id for subtask test
            tasks = [t for t in server.executor.pool.tasks if t.chat_id == cid]
            tasks[0].parent_message_id = root_id
            data = client.get(f"/api/messages/{root_id}/thread").json()
        assert any(s["parent_message_id"] == root_id for s in data["subtasks"])

    def test_reply_messages_in_thread(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            root_id = client.post(
                f"/api/chats/{cid}/messages", json={"content": "root"}
            ).json()["id"]
            client.post(
                f"/api/chats/{cid}/messages",
                json={"content": "reply", "thread_root_id": root_id},
            )
            data = client.get(f"/api/messages/{root_id}/thread").json()
        assert any(m["content"] == "reply" for m in data["messages"])

    def test_unknown_message_gives_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/messages/msg_nope/thread")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Legacy POST /api/chats/{id}/messages still works
# ---------------------------------------------------------------------------

class TestLegacyChatMessages:
    def test_legacy_prompt_field_accepted(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            cid = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "Legacy"},
            ).json()["id"]
            resp = client.post(
                f"/api/chats/{cid}/messages",
                json={"prompt": "old style prompt"},
            )
        assert resp.status_code == 201

    def test_legacy_get_messages_still_works(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            cid = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "Legacy"},
            ).json()["id"]
            client.post(f"/api/chats/{cid}/messages", json={"prompt": "legacy msg"})
            resp = client.get(f"/api/chats/{cid}/messages")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
