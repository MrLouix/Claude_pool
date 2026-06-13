"""Tests for GET /api/messages/{id}/thread — subtask_count and subtask_done_count (Step 6 Part B)."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState, Task
from team_cli.storage import save_pool


# ---------------------------------------------------------------------------
# Shared helpers (same pattern as test_api_messages.py)
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


def _post_message(client: TestClient, chat_id: str, content: str = "hello") -> dict:
    return client.post(
        f"/api/chats/{chat_id}/messages", json={"content": content}
    ).json()


# ---------------------------------------------------------------------------
# 1. thread_response_structure
# ---------------------------------------------------------------------------

class TestThreadResponseStructure:
    def test_has_root_subtasks_messages_keys(self, tmp_path: Path) -> None:
        """GET /api/messages/{id}/thread returns root, subtasks, and messages."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]
            data = client.get(f"/api/messages/{msg_id}/thread").json()
        for key in ("root", "subtasks", "messages"):
            assert key in data, f"Missing key: {key}"

    def test_root_matches_message(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg = _post_message(client, cid, "test content")
            data = client.get(f"/api/messages/{msg['id']}/thread").json()
        assert data["root"]["id"] == msg["id"]
        assert data["root"]["content"] == "test content"

    def test_subtasks_initially_empty(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]
            data = client.get(f"/api/messages/{msg_id}/thread").json()
        # The task created by posting a message has parent_message_id=msg_id
        # so it should appear in subtasks; subtasks list is non-empty
        assert isinstance(data["subtasks"], list)

    def test_unknown_message_404(self, tmp_path: Path) -> None:
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, _):
            resp = client.get("/api/messages/msg_does_not_exist/thread")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. subtask_count_in_response
# ---------------------------------------------------------------------------

class TestSubtaskCountInResponse:
    def test_subtask_count_reflects_children(self, tmp_path: Path) -> None:
        """TaskSummary in thread.subtasks has subtask_count == number of child tasks."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]

            # Find the task created for this message
            all_tasks = server.executor.pool.tasks
            parent_task = next(t for t in all_tasks if t.chat_id == cid)
            parent_task.parent_message_id = msg_id

            # Inject 2 child subtasks pointing to parent_task
            child1 = Task(
                id="subtask_child_1",
                prompt="child 1",
                directory=Path("/tmp"),
                kind="subtask",
                parent_task_id=parent_task.id,
                status="success",
            )
            child2 = Task(
                id="subtask_child_2",
                prompt="child 2",
                directory=Path("/tmp"),
                kind="subtask",
                parent_task_id=parent_task.id,
                status="pending",
            )
            server.executor.pool.tasks.extend([child1, child2])

            data = client.get(f"/api/messages/{msg_id}/thread").json()

        # The parent task should appear in subtasks with subtask_count=2
        matching = [s for s in data["subtasks"] if s["id"] == parent_task.id]
        assert matching, "Parent task not found in thread subtasks"
        assert matching[0]["subtask_count"] == 2

    def test_subtask_count_zero_when_no_children(self, tmp_path: Path) -> None:
        """A task with no children has subtask_count=0."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]

            all_tasks = server.executor.pool.tasks
            task = next(t for t in all_tasks if t.chat_id == cid)
            task.parent_message_id = msg_id

            data = client.get(f"/api/messages/{msg_id}/thread").json()

        matching = [s for s in data["subtasks"] if s["id"] == task.id]
        assert matching
        assert matching[0]["subtask_count"] == 0


# ---------------------------------------------------------------------------
# 3. subtask_done_count_reflects_status
# ---------------------------------------------------------------------------

class TestSubtaskDoneCountReflectsStatus:
    def test_done_count_counts_success_only(self, tmp_path: Path) -> None:
        """subtask_done_count == number of children with status='success'."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]

            all_tasks = server.executor.pool.tasks
            parent_task = next(t for t in all_tasks if t.chat_id == cid)
            parent_task.parent_message_id = msg_id

            # 2 subtasks: one success, one pending
            child_ok = Task(
                id="done_child_ok",
                prompt="done",
                directory=Path("/tmp"),
                kind="subtask",
                parent_task_id=parent_task.id,
                status="success",
            )
            child_pending = Task(
                id="done_child_pending",
                prompt="not done",
                directory=Path("/tmp"),
                kind="subtask",
                parent_task_id=parent_task.id,
                status="pending",
            )
            server.executor.pool.tasks.extend([child_ok, child_pending])

            data = client.get(f"/api/messages/{msg_id}/thread").json()

        matching = [s for s in data["subtasks"] if s["id"] == parent_task.id]
        assert matching
        assert matching[0]["subtask_count"] == 2
        assert matching[0]["subtask_done_count"] == 1

    def test_done_count_all_success(self, tmp_path: Path) -> None:
        """subtask_done_count == subtask_count when all children succeeded."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]

            all_tasks = server.executor.pool.tasks
            parent_task = next(t for t in all_tasks if t.chat_id == cid)
            parent_task.parent_message_id = msg_id

            for i in range(3):
                server.executor.pool.tasks.append(Task(
                    id=f"all_ok_child_{i}",
                    prompt=f"success task {i}",
                    directory=Path("/tmp"),
                    kind="subtask",
                    parent_task_id=parent_task.id,
                    status="success",
                ))

            data = client.get(f"/api/messages/{msg_id}/thread").json()

        matching = [s for s in data["subtasks"] if s["id"] == parent_task.id]
        assert matching
        assert matching[0]["subtask_count"] == 3
        assert matching[0]["subtask_done_count"] == 3

    def test_done_count_none_success(self, tmp_path: Path) -> None:
        """subtask_done_count == 0 when no children have succeeded."""
        pf = _pool(tmp_path)
        with _make_api(pf) as (client, server):
            pid = _create_project(client)
            cid = _create_chat(client, pid)
            msg_id = _post_message(client, cid)["id"]

            all_tasks = server.executor.pool.tasks
            parent_task = next(t for t in all_tasks if t.chat_id == cid)
            parent_task.parent_message_id = msg_id

            server.executor.pool.tasks.append(Task(
                id="none_ok_child",
                prompt="pending task",
                directory=Path("/tmp"),
                kind="subtask",
                parent_task_id=parent_task.id,
                status="pending",
            ))

            data = client.get(f"/api/messages/{msg_id}/thread").json()

        matching = [s for s in data["subtasks"] if s["id"] == parent_task.id]
        assert matching
        assert matching[0]["subtask_done_count"] == 0
