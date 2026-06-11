"""Tests for the chat REST API (Step 3)."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import Bucket, PoolState, Task
from team_cli.storage import save_pool

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def pool_file(tmp_path: Path) -> Path:
    state = PoolState(pool_file=tmp_path / "pool.json")
    save_pool(state)
    return tmp_path / "pool.json"


@pytest.fixture
def api(pool_file: Path):
    """ApiServer with run_pool and signal.signal stubbed (TestClient runs in a thread)."""
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


# ── Helpers ───────────────────────────────────────────────────────


def _add_chat(server: ApiServer, label: str = "test-chat", directory: str | None = None) -> str:
    """Directly inject a chat bucket into the executor pool."""
    import uuid

    bucket_id = f"chat_{uuid.uuid4().hex[:8]}"
    server.executor.pool.buckets[bucket_id] = Bucket(
        id=bucket_id,
        type="chat",
        label=label,
        directory=directory or str(Path.home()),
    )
    server.executor._save_state()
    return bucket_id


def _add_task(
    server: ApiServer,
    bucket_id: str,
    prompt: str = "hello",
    status: str = "pending",
    created_at: str | None = None,
    json_output: dict | None = None,
    exit_code: int | None = None,
) -> Task:
    task = Task(
        id=f"task_{len(server.executor.pool.tasks):04d}",
        prompt=prompt,
        directory=Path.home(),
        bucket_id=bucket_id,
        status=status,
        json_output=json_output,
        exit_code=exit_code,
        created_at=created_at or datetime.now().isoformat(),
    )
    server.executor.pool.tasks.append(task)
    server.executor._save_state()
    return task


# ── GET /api/chats ────────────────────────────────────────────────


def test_list_chats_empty(api):
    client, _ = api
    r = client.get("/api/chats")
    assert r.status_code == 200
    assert r.json() == []


def test_list_chats_excludes_main_bucket(api):
    client, server = api
    # Only 'main' bucket exists by default
    r = client.get("/api/chats")
    assert r.status_code == 200
    assert all(c["id"] != "main" for c in r.json())


def test_list_chats_returns_chat_buckets(api):
    client, server = api
    bid = _add_chat(server, label="My Chat")
    r = client.get("/api/chats")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert bid in ids


def test_list_chats_message_count_and_last_activity(api):
    client, server = api
    bid = _add_chat(server)
    t1 = _add_task(server, bid, created_at="2026-01-01T10:00:00")
    t2 = _add_task(server, bid, created_at="2026-01-01T11:00:00")

    r = client.get("/api/chats")
    chat = next(c for c in r.json() if c["id"] == bid)
    assert chat["message_count"] == 2
    assert chat["last_activity"] == "2026-01-01T11:00:00"


# ── POST /api/chats ───────────────────────────────────────────────


def test_create_chat_happy_path(api):
    client, _ = api
    r = client.post("/api/chats", json={"directory": str(Path.home())})
    assert r.status_code == 201
    data = r.json()
    assert data["id"].startswith("chat_")
    assert data["label"] == Path.home().name
    assert data["directory"] == str(Path.home())
    assert data["message_count"] == 0
    assert data["last_activity"] is None


def test_create_chat_explicit_label(api):
    client, _ = api
    r = client.post("/api/chats", json={"directory": str(Path.home()), "label": "My Project"})
    assert r.status_code == 201
    assert r.json()["label"] == "My Project"


def test_create_chat_directory_outside_allowlist_gives_403(api):
    client, _ = api
    r = client.post("/api/chats", json={"directory": "/tmp/outside"})
    assert r.status_code == 403


def test_create_chat_directory_root_gives_403(api):
    client, _ = api
    r = client.post("/api/chats", json={"directory": "/etc"})
    assert r.status_code == 403


def test_create_chat_persists_bucket(api):
    client, server = api
    r = client.post("/api/chats", json={"directory": str(Path.home())})
    bid = r.json()["id"]
    assert bid in server.executor.pool.buckets
    assert server.executor.pool.buckets[bid].type == "chat"


# ── DELETE /api/chats/{chat_id} ───────────────────────────────────


def test_delete_chat_happy_path(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid)
    _add_task(server, bid)

    r = client.delete(f"/api/chats/{bid}")
    assert r.status_code == 200
    assert r.json()["deleted_tasks"] == 2
    assert bid not in server.executor.pool.buckets


def test_delete_chat_removes_tasks(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid)

    client.delete(f"/api/chats/{bid}")
    assert all(t.bucket_id != bid for t in server.executor.pool.tasks)


def test_delete_chat_main_gives_400(api):
    client, _ = api
    r = client.delete("/api/chats/main")
    assert r.status_code == 400


def test_delete_chat_nonexistent_gives_404(api):
    client, _ = api
    r = client.delete("/api/chats/chat_doesnotexist")
    assert r.status_code == 404


# ── GET /api/chats/{chat_id}/messages ────────────────────────────


def test_get_messages_empty(api):
    client, server = api
    bid = _add_chat(server)
    r = client.get(f"/api/chats/{bid}/messages")
    assert r.status_code == 200
    assert r.json() == []


def test_get_messages_chronological_order(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, prompt="third", created_at="2026-01-01T12:00:00")
    _add_task(server, bid, prompt="first", created_at="2026-01-01T10:00:00")
    _add_task(server, bid, prompt="second", created_at="2026-01-01T11:00:00")

    r = client.get(f"/api/chats/{bid}/messages")
    prompts = [m["content"] for m in r.json()]
    assert prompts == ["first", "second", "third"]


def test_get_messages_unknown_chat_gives_404(api):
    client, _ = api
    r = client.get("/api/chats/chat_unknown/messages")
    assert r.status_code == 404


def test_get_messages_assistant_response_pending(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, status="pending")

    msgs = client.get(f"/api/chats/{bid}/messages").json()
    assert msgs[0]["assistant_response"] is None
    assert msgs[0]["role"] == "user"


def test_get_messages_assistant_response_running(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, status="running")

    msgs = client.get(f"/api/chats/{bid}/messages").json()
    assert msgs[0]["assistant_response"] is None


def test_get_messages_assistant_response_success(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(
        server, bid, status="success", json_output={"result": "Here is the answer."}, exit_code=0
    )

    msgs = client.get(f"/api/chats/{bid}/messages").json()
    assert msgs[0]["assistant_response"] == "Here is the answer."
    assert msgs[0]["status"] == "success"


def test_get_messages_assistant_response_failed(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, status="failed", exit_code=2)

    msgs = client.get(f"/api/chats/{bid}/messages").json()
    assert msgs[0]["assistant_response"] is not None
    assert "2" in msgs[0]["assistant_response"]  # exit code present


def test_get_messages_content_equals_prompt(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, prompt="Explain the codebase")

    msgs = client.get(f"/api/chats/{bid}/messages").json()
    assert msgs[0]["content"] == "Explain the codebase"


def test_get_messages_filters_by_bucket(api):
    client, server = api
    bid1 = _add_chat(server, label="chat1")
    bid2 = _add_chat(server, label="chat2")
    _add_task(server, bid1, prompt="for chat1")
    _add_task(server, bid2, prompt="for chat2")

    msgs = client.get(f"/api/chats/{bid1}/messages").json()
    assert len(msgs) == 1
    assert msgs[0]["content"] == "for chat1"


# ── POST /api/chats/{chat_id}/messages ────────────────────────────


def test_post_message_creates_task_in_correct_bucket(api):
    client, server = api
    bid = _add_chat(server)

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "Hello Claude"})
    assert r.status_code == 201
    data = r.json()
    assert data["content"] == "Hello Claude"
    assert data["role"] == "user"
    assert data["status"] == "pending"
    assert data["assistant_response"] is None

    task = next(t for t in server.executor.pool.tasks if t.id == data["id"])
    assert task.bucket_id == bid


def test_post_message_uses_bucket_directory(api):
    client, server = api
    bid = _add_chat(server, directory=str(Path.home()))

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "hi"})
    assert r.status_code == 201
    task_id = r.json()["id"]

    task = next(t for t in server.executor.pool.tasks if t.id == task_id)
    assert str(task.directory) == str(Path.home())


def test_post_message_with_model_arg(api):
    client, server = api
    bid = _add_chat(server)

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "hi", "model": "claude-opus-4-7"})
    assert r.status_code == 201
    task_id = r.json()["id"]
    task = next(t for t in server.executor.pool.tasks if t.id == task_id)
    assert "--model" in task.args
    assert "claude-opus-4-7" in task.args


def test_post_message_with_effort_arg(api):
    client, server = api
    bid = _add_chat(server)

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "hi", "effort": "high"})
    assert r.status_code == 201
    task_id = r.json()["id"]
    task = next(t for t in server.executor.pool.tasks if t.id == task_id)
    assert "--effort" in task.args
    assert "high" in task.args


def test_post_message_with_model_and_effort(api):
    client, server = api
    bid = _add_chat(server)

    r = client.post(
        f"/api/chats/{bid}/messages",
        json={"prompt": "hi", "model": "claude-haiku-4-5-20251001", "effort": "low"},
    )
    assert r.status_code == 201
    task_id = r.json()["id"]
    task = next(t for t in server.executor.pool.tasks if t.id == task_id)
    assert "--model" in task.args
    assert "--effort" in task.args


def test_post_message_unknown_chat_gives_404(api):
    client, _ = api
    r = client.post("/api/chats/chat_ghost/messages", json={"prompt": "hi"})
    assert r.status_code == 404


# ── GET /api/status & POST /api/pool/instant-retry ────────────────


def test_get_status_waiting_request(api):
    client, server = api
    # Initially no tasks exist, so it should be "waiting request"
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["claude_status"] == "waiting request"
    assert data["rate_limit_result"] is None


def test_get_status_running(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, status="running")
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["claude_status"] == "running"
    assert data["rate_limit_result"] is None


def test_get_status_pending(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(server, bid, status="pending")
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["claude_status"] == "running"
    assert data["rate_limit_result"] is None


def test_get_status_rate_limit_by_task(api):
    client, server = api
    bid = _add_chat(server)
    _add_task(
        server,
        bid,
        status="rate_limit_retry",
        json_output={"result": "You've hit your limit · resets 2:30pm (Europe/Paris)"},
    )
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["claude_status"] == "rate_limit"
    assert data["rate_limit_result"] == "You've hit your limit · resets 2:30pm (Europe/Paris)"


def test_get_status_rate_limit_by_suspended(api):
    client, server = api
    server.executor.pool.suspended_until = datetime.now() + timedelta(hours=1)
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["claude_status"] == "rate_limit"


def test_post_instant_retry(api):
    client, server = api
    # Suspend pool
    server.executor.pool.suspended_until = datetime.now() + timedelta(hours=1)
    assert server.executor.pool.is_suspended is True

    # Call instant-retry
    r = client.post("/api/pool/instant-retry")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert server.executor.pool.suspended_until is None
    assert server.executor.pool.is_suspended is False


# ── POST /api/tasks — priority ────────────────────────────────────────────────


def test_post_task_with_priority_1(api):
    """POST /api/tasks with priority=1 creates a task with priority=1."""
    client, server = api
    r = client.post(
        "/api/tasks",
        json={"prompt": "High priority task", "directory": str(Path.home()), "priority": 1},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["priority"] == 1
    task = next(t for t in server.executor.pool.tasks if t.id == data["id"])
    assert task.priority == 1


def test_post_task_default_priority_is_2(api):
    """POST /api/tasks without priority defaults to 2."""
    client, server = api
    r = client.post(
        "/api/tasks",
        json={"prompt": "Normal task", "directory": str(Path.home())},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["priority"] == 2
    task = next(t for t in server.executor.pool.tasks if t.id == data["id"])
    assert task.priority == 2


def test_post_task_priority_6_returns_422(api):
    """POST /api/tasks with priority=6 returns 422 Unprocessable Entity."""
    client, _ = api
    r = client.post(
        "/api/tasks",
        json={"prompt": "Bad priority", "directory": str(Path.home()), "priority": 6},
    )
    assert r.status_code == 422


def test_post_task_priority_0_returns_422(api):
    """POST /api/tasks with priority=0 returns 422."""
    client, _ = api
    r = client.post(
        "/api/tasks",
        json={"prompt": "Bad priority", "directory": str(Path.home()), "priority": 0},
    )
    assert r.status_code == 422


# ── GET /api/tasks — priority ─────────────────────────────────────────────────


def test_get_tasks_includes_priority(api):
    """GET /api/tasks response includes priority field."""
    client, server = api
    bid = _add_chat(server)
    task = _add_task(server, bid, prompt="check priority")
    task.priority = 3
    server.executor._save_state()

    r = client.get("/api/tasks")
    assert r.status_code == 200
    tasks = r.json()
    match = next((t for t in tasks if t["id"] == task.id), None)
    assert match is not None
    assert match["priority"] == 3


def test_get_task_detail_includes_priority(api):
    """GET /api/tasks/{id} response includes priority field."""
    client, server = api
    bid = _add_chat(server)
    task = _add_task(server, bid)
    task.priority = 1
    server.executor._save_state()

    r = client.get(f"/api/tasks/{task.id}")
    assert r.status_code == 200
    assert r.json()["priority"] == 1


# ── PATCH /api/tasks/{id} — priority ─────────────────────────────────────────


def test_patch_task_priority_3(api):
    """PATCH /api/tasks/{id} with priority=3 updates the task."""
    client, server = api
    bid = _add_chat(server)
    task = _add_task(server, bid, status="pending")

    r = client.patch(f"/api/tasks/{task.id}", json={"priority": 3})
    assert r.status_code == 200
    assert r.json()["priority"] == 3
    assert task.priority == 3


def test_patch_task_priority_0_returns_422(api):
    """PATCH /api/tasks/{id} with priority=0 returns 422."""
    client, server = api
    bid = _add_chat(server)
    task = _add_task(server, bid, status="pending")

    r = client.patch(f"/api/tasks/{task.id}", json={"priority": 0})
    assert r.status_code == 422


def test_patch_task_priority_6_returns_422(api):
    """PATCH /api/tasks/{id} with priority=6 returns 422."""
    client, server = api
    bid = _add_chat(server)
    task = _add_task(server, bid, status="pending")

    r = client.patch(f"/api/tasks/{task.id}", json={"priority": 6})
    assert r.status_code == 422


# ── POST /api/chats/{id}/messages — priority ──────────────────────────────────


def test_post_message_with_priority_1(api):
    """POST /api/chats/{id}/messages with priority=1 creates a task with priority=1."""
    client, server = api
    bid = _add_chat(server)

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "urgent", "priority": 1})
    assert r.status_code == 201
    task_id = r.json()["id"]
    task = next(t for t in server.executor.pool.tasks if t.id == task_id)
    assert task.priority == 1


def test_post_message_default_priority_is_2(api):
    """POST /api/chats/{id}/messages without priority defaults to 2."""
    client, server = api
    bid = _add_chat(server)

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "normal"})
    assert r.status_code == 201
    task_id = r.json()["id"]
    task = next(t for t in server.executor.pool.tasks if t.id == task_id)
    assert task.priority == 2


def test_post_message_priority_6_returns_422(api):
    """POST /api/chats/{id}/messages with priority=6 returns 422."""
    client, server = api
    bid = _add_chat(server)

    r = client.post(f"/api/chats/{bid}/messages", json={"prompt": "bad", "priority": 6})
    assert r.status_code == 422
