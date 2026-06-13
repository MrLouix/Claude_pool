"""Tests for enriched WebSocket event payloads (v2 fields)."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState, Task
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


def _v2_task(project_id: str = "proj_abc", chat_id: str = "chat_xyz") -> Task:
    return Task(
        id="task_ws_00000000_aaaa",
        prompt="do something",
        directory=Path.home(),
        project_id=project_id,
        chat_id=chat_id,
        parent_message_id="msg_parent",
        parent_task_id=None,
        kind="request",
    )


# ---------------------------------------------------------------------------
# task_updated event includes v2 fields
# ---------------------------------------------------------------------------

class TestTaskUpdatedV2Fields:
    def test_event_contains_project_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        received: list[dict] = []
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()  # consume pool_status
                task = _v2_task()
                server._on_task_update(task)
                msg = ws.receive_json()
        assert msg["task"]["project_id"] == "proj_abc"

    def test_event_contains_chat_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = _v2_task()
                server._on_task_update(task)
                msg = ws.receive_json()
        assert msg["task"]["chat_id"] == "chat_xyz"

    def test_event_contains_parent_message_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = _v2_task()
                server._on_task_update(task)
                msg = ws.receive_json()
        assert msg["task"]["parent_message_id"] == "msg_parent"

    def test_event_contains_parent_task_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = _v2_task()
                server._on_task_update(task)
                msg = ws.receive_json()
        assert "parent_task_id" in msg["task"]

    def test_event_is_task_updated(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = _v2_task()
                server._on_task_update(task)
                msg = ws.receive_json()
        assert msg["event"] == "task_updated"

    def test_legacy_fields_still_present(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = _v2_task()
                server._on_task_update(task)
                msg = ws.receive_json()
        for field in ("id", "prompt", "status", "bucket_id"):
            assert field in msg["task"], f"legacy field missing: {field}"

    def test_null_v2_fields_when_not_set(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = Task(
                    id="task_ws_plain_0000",
                    prompt="plain",
                    directory=Path.home(),
                )
                server._on_task_update(task)
                msg = ws.receive_json()
        assert msg["task"]["project_id"] is None
        assert msg["task"]["chat_id"] is None


# ---------------------------------------------------------------------------
# message_created event emitted after successful v2 task
# ---------------------------------------------------------------------------

class TestMessageCreatedEvent:
    def test_message_created_emitted_on_success(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()  # pool_status
                task = Task(
                    id="task_ws_success",
                    prompt="work",
                    directory=Path.home(),
                    chat_id="chat_xyz",
                    project_id="proj_abc",
                    status="success",
                    json_output={"result": "done"},
                )
                server._on_task_update(task)
                # First event: task_updated
                task_event = ws.receive_json()
                assert task_event["event"] == "task_updated"
                # Second event: message_created (async, may need a moment)
                msg_event = ws.receive_json()
        assert msg_event["event"] == "message_created"
        assert msg_event["data"]["chat_id"] == "chat_xyz"
        assert msg_event["data"]["role"] == "assistant"

    def test_message_created_not_emitted_without_chat_id(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
                task = Task(
                    id="task_ws_no_chat",
                    prompt="work",
                    directory=Path.home(),
                    status="success",
                    json_output={"result": "done"},
                )
                # No chat_id → no message_created event
                server._on_task_update(task)
                task_event = ws.receive_json()
        assert task_event["event"] == "task_updated"
        # No more events should be queued
