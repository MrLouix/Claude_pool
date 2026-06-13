"""v2 message-level routes."""

import logging

from fastapi import APIRouter, HTTPException

from ..api_models import TaskSummary, ThreadResponse, V2MessageResponse
from ..database import DatabaseManager

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    def _db() -> DatabaseManager:
        return DatabaseManager(server.pool_file)

    @router.get("/api/messages/{message_id}/thread")
    async def get_thread(message_id: str) -> ThreadResponse:
        """Return the root message, all tasks whose parent_message_id=message_id,
        and all reply messages (thread_root_id=message_id)."""
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        db = _db()
        root_row = await db.get_message(message_id)
        if root_row is None:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        root = V2MessageResponse(
            id=root_row["id"],
            chat_id=root_row["chat_id"],
            thread_root_id=root_row.get("thread_root_id"),
            role=root_row["role"],
            content=root_row["content"],
            task_id=root_row.get("task_id"),
            created_at=root_row["created_at"],
        )

        # Subtasks: pool tasks whose parent_message_id == message_id
        all_tasks = server.executor.pool.tasks

        def _subtask_counts(task_id: str) -> tuple[int, int]:
            children = [t for t in all_tasks if t.parent_task_id == task_id]
            return len(children), sum(1 for t in children if t.status == "success")

        subtasks = [
            TaskSummary(
                id=t.id,
                status=t.status,
                prompt=t.prompt[:200],
                created_at=t.created_at,
                parent_message_id=t.parent_message_id,
                parent_task_id=t.parent_task_id,
                kind=t.kind,
                subtask_count=_subtask_counts(t.id)[0],
                subtask_done_count=_subtask_counts(t.id)[1],
            )
            for t in all_tasks
            if t.parent_message_id == message_id
        ]

        # Thread reply messages
        reply_rows = await db.get_messages_for_chat(
            root_row["chat_id"],
            thread_root_id=message_id,
        )
        messages = [
            V2MessageResponse(
                id=r["id"],
                chat_id=r["chat_id"],
                thread_root_id=r.get("thread_root_id"),
                role=r["role"],
                content=r["content"],
                task_id=r.get("task_id"),
                created_at=r["created_at"],
            )
            for r in reply_rows
        ]

        return ThreadResponse(root=root, subtasks=subtasks, messages=messages)

    return router
