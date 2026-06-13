"""Tests for Step 5 — real-time WebSocket message_created events and store logic.

Server-side: verifies the WS broadcast payload is correct.
Client-side store: verifies store.js handles message_created events correctly
(via regex on the JS source, since we have no JS test runner).
"""
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState
from team_cli.storage import save_pool

_STORE_JS  = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "store.js"
_CHAT_JS   = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "views" / "chat.js"
_WS_JS     = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "ws.js"
_ROUTER_JS = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "router.js"


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


# ---------------------------------------------------------------------------
# Server-side: WS broadcast on POST /api/chats/{id}/messages
# ---------------------------------------------------------------------------

class TestWsBroadcastOnMessageCreate:
    def test_broadcast_sent_on_message_post(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        broadcasts = []
        with _make_api(pf) as (client, server):
            orig = server._broadcast_event
            async def _capture(ev): broadcasts.append(ev); await orig(ev)
            server._broadcast_event = _capture

            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "hello"})

        mc_events = [b for b in broadcasts if b.get("event") == "message_created"]
        assert mc_events, "POST /api/chats/{id}/messages must broadcast a message_created event"

    def test_broadcast_includes_chat_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        broadcasts = []
        with _make_api(pf) as (client, server):
            orig = server._broadcast_event
            async def _capture(ev): broadcasts.append(ev); await orig(ev)
            server._broadcast_event = _capture

            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

        mc = next(b for b in broadcasts if b.get("event") == "message_created")
        assert mc["data"]["chat_id"] == cid

    def test_broadcast_includes_role(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        broadcasts = []
        with _make_api(pf) as (client, server):
            orig = server._broadcast_event
            async def _capture(ev): broadcasts.append(ev); await orig(ev)
            server._broadcast_event = _capture

            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "q"})

        mc = next(b for b in broadcasts if b.get("event") == "message_created")
        assert "role" in mc["data"], "broadcast data must include 'role'"
        assert mc["data"]["role"] == "user"

    def test_broadcast_includes_message_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        broadcasts = []
        with _make_api(pf) as (client, server):
            orig = server._broadcast_event
            async def _capture(ev): broadcasts.append(ev); await orig(ev)
            server._broadcast_event = _capture

            pid = _create_project(client)
            cid = _create_chat(client, pid)
            resp = client.post(f"/api/chats/{cid}/messages", json={"content": "q"})
            msg_id = resp.json()["id"]

        mc = next(b for b in broadcasts if b.get("event") == "message_created")
        assert mc["data"]["message_id"] == msg_id

    def test_broadcast_includes_task_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        broadcasts = []
        with _make_api(pf) as (client, server):
            orig = server._broadcast_event
            async def _capture(ev): broadcasts.append(ev); await orig(ev)
            server._broadcast_event = _capture

            pid = _create_project(client)
            cid = _create_chat(client, pid)
            client.post(f"/api/chats/{cid}/messages", json={"content": "q"})

        mc = next(b for b in broadcasts if b.get("event") == "message_created")
        assert "task_id" in mc["data"], "broadcast data must include 'task_id'"


# ---------------------------------------------------------------------------
# Client-side: store.js handles message_created events
# ---------------------------------------------------------------------------

class TestStoreMessageCreatedHandler:
    def test_store_handles_message_created_event(self):
        src = _STORE_JS.read_text(encoding="utf-8")
        assert "message_created" in src, (
            "store.js must handle 'message_created' event in applyWsEvent"
        )

    def test_store_notifies_message_created(self):
        src = _STORE_JS.read_text(encoding="utf-8")
        # Must call _notify with 'message_created' topic
        assert "_notify('message_created'" in src or '_notify("message_created"' in src, (
            "store.js must call _notify('message_created', ...) so views can subscribe"
        )

    def test_store_exports_subscribe(self):
        src = _STORE_JS.read_text(encoding="utf-8")
        assert "export function subscribe" in src, (
            "store.js must export a subscribe() function"
        )

    def test_store_exports_apply_ws_event(self):
        src = _STORE_JS.read_text(encoding="utf-8")
        assert "export function applyWsEvent" in src, (
            "store.js must export applyWsEvent()"
        )


# ---------------------------------------------------------------------------
# Client-side: ws.js emits pool:* custom DOM events
# ---------------------------------------------------------------------------

class TestWsClientEventEmission:
    def test_ws_emits_custom_pool_events(self):
        src = _WS_JS.read_text(encoding="utf-8")
        assert "pool:" in src or "_emit" in src, (
            "ws.js must emit pool:* custom DOM events"
        )

    def test_ws_uses_custom_event(self):
        src = _WS_JS.read_text(encoding="utf-8")
        assert "CustomEvent" in src, (
            "ws.js must dispatch CustomEvent objects"
        )

    def test_ws_reconnects_on_close(self):
        src = _WS_JS.read_text(encoding="utf-8")
        assert "reconnect" in src.lower() or "scheduleReconnect" in src, (
            "ws.js must implement reconnect logic"
        )


# ---------------------------------------------------------------------------
# Client-side: router.js wires WS events to store
# ---------------------------------------------------------------------------

class TestRouterWsWiring:
    def test_router_wires_message_created_to_store(self):
        src = _ROUTER_JS.read_text(encoding="utf-8")
        assert "pool:message_created" in src, (
            "router.js must listen for pool:message_created and forward to applyWsEvent"
        )

    def test_router_calls_apply_ws_event(self):
        src = _ROUTER_JS.read_text(encoding="utf-8")
        assert "applyWsEvent" in src, (
            "router.js must call applyWsEvent() to update store on WS events"
        )


# ---------------------------------------------------------------------------
# Client-side: chat.js reacts to WS events
# ---------------------------------------------------------------------------

class TestChatViewWsIntegration:
    def test_chat_listens_to_ws_message_created(self):
        src = _CHAT_JS.read_text(encoding="utf-8")
        assert "pool:message_created" in src, (
            "chat.js must listen to pool:message_created DOM events"
        )

    def test_chat_filters_by_chat_id(self):
        src = _CHAT_JS.read_text(encoding="utf-8")
        assert "chat_id" in src and "_chatId" in src, (
            "chat.js must filter incoming WS events by the current chat_id"
        )

    def test_chat_clears_running_on_assistant_message(self):
        src = _CHAT_JS.read_text(encoding="utf-8")
        assert "setRunning" in src or "_setRunning" in src, (
            "chat.js must call _setRunning(false) when a non-user message arrives"
        )

    def test_chat_removes_listener_on_cleanup(self):
        src = _CHAT_JS.read_text(encoding="utf-8")
        assert "removeEventListener" in src, (
            "chat.js must remove WS event listener in _cleanup() to prevent leaks"
        )
