"""Chat routes — hybrid: legacy bucket chats + v2 project chats."""

import logging
import uuid as _uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..api_helpers import _generate_task_id, _task_to_message, _validate_directory
from ..api_models import (
    ChatCreateInput,
    ChatResponse,
    ChatUpdate,
    MessageCreate,
    MessageInput,
    MessageResponse,
    MessagesPageResponse,
    V2ChatResponse,
    V2MessageResponse,
)
from ..database import DatabaseManager
from ..models import Bucket, Message, Task

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    def _db() -> DatabaseManager:
        return DatabaseManager(server.pool_file)

    # ── Legacy bucket helpers ─────────────────────────────────────

    async def _handle_legacy_get_messages(chat_id: str) -> list[MessageResponse]:
        tasks = sorted(
            (t for t in server.executor.pool.tasks if t.bucket_id == chat_id),
            key=lambda t: (t.priority, t.created_at),
        )
        return [_task_to_message(t) for t in tasks]

    async def _handle_legacy_post_message(
        chat_id: str, message_input: MessageCreate
    ) -> MessageResponse:
        bucket = server.executor.pool.buckets.get(chat_id)
        if not bucket:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

        task_id = _generate_task_id()
        directory = Path(bucket.directory) if bucket.directory else Path.cwd()

        args: list[str] = []
        if message_input.model:
            args.extend(["--model", message_input.model])
        if message_input.effort:
            args.extend(["--effort", message_input.effort])

        new_task = Task(
            id=task_id,
            prompt=message_input.content,
            directory=directory,
            args=args,
            bucket_id=chat_id,
            priority=message_input.priority,
        )
        server.executor.pool.tasks.append(new_task)
        server.executor._save_state()

        msg = _task_to_message(new_task)
        await server._broadcast_event(
            {"event": "chat_message", "chat_id": chat_id, "message": msg.model_dump()}
        )
        await server._broadcast_pool_status()
        return msg

    # ── Legacy /api/chats (kept unchanged) ────────────────────────

    @router.get("/api/chats")
    async def list_chats() -> list[ChatResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        result = []
        for bid, bucket in server.executor.pool.buckets.items():
            if bucket.type != "chat":
                continue
            bucket_tasks = [t for t in server.executor.pool.tasks if t.bucket_id == bid]
            message_count = len(bucket_tasks)
            last_activity = max((t.created_at for t in bucket_tasks), default=None)
            dir_tasks = [
                t
                for t in server.executor.pool.tasks
                if t.bucket_id == bid and t.status == "success" and t.json_output
            ]
            dir_tasks.sort(key=lambda t: t.created_at, reverse=True)
            session_usage = (
                dir_tasks[0].json_output.get("session_usage_percent") if dir_tasks else None
            )
            result.append(
                ChatResponse(
                    id=bid,
                    label=bucket.label,
                    directory=bucket.directory,
                    created_at=bucket.created_at,
                    message_count=message_count,
                    last_activity=last_activity,
                    session_usage_percent=session_usage,
                )
            )
        result.sort(key=lambda c: c.created_at, reverse=True)
        return result

    @router.post("/api/chats", status_code=201)
    async def create_chat(chat_input: ChatCreateInput) -> ChatResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        _validate_directory(chat_input.directory)

        label = chat_input.label or Path(chat_input.directory).name
        bucket_id = f"chat_{_uuid.uuid4().hex[:8]}"
        bucket = Bucket(
            id=bucket_id,
            type="chat",
            label=label,
            directory=chat_input.directory,
            created_at=datetime.now().isoformat(),
        )
        server.executor.pool.buckets[bucket_id] = bucket
        server.executor._save_state()

        await server._broadcast_event({"event": "chat_created", "chat": bucket.to_dict()})

        return ChatResponse(
            id=bucket_id,
            label=bucket.label,
            directory=bucket.directory,
            created_at=bucket.created_at,
            message_count=0,
            last_activity=None,
        )

    # ── v2 PATCH (new — only v2 chats support rename/reorder) ────

    @router.patch("/api/chats/{chat_id}")
    async def patch_chat(chat_id: str, update: ChatUpdate) -> V2ChatResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        row = await db.get_chat(chat_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

        if update.label is not None:
            row["label"] = update.label
        if update.position is not None:
            row["position"] = update.position

        await db.upsert_chat(row)
        return V2ChatResponse(
            id=row["id"],
            project_id=row["project_id"],
            label=row["label"],
            position=row["position"],
            created_at=row["created_at"],
        )

    # ── DELETE /api/chats/{id} — hybrid ──────────────────────────

    @router.delete("/api/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        db = _db()
        v2_row = await db.get_chat(chat_id)

        if v2_row is not None:
            # v2 chat: delete from DB (cascade removes messages); tasks keep chat_id
            await db.delete_chat(chat_id)
            await server._broadcast_event({"event": "chat_deleted", "id": chat_id})
            return {"deleted": True, "chat_id": chat_id}

        # Legacy bucket chat
        if chat_id not in server.executor.pool.buckets:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
        try:
            deleted_tasks = server.executor.delete_bucket(chat_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await server._broadcast_event(
            {"event": "chat_deleted", "id": chat_id, "deleted_tasks": deleted_tasks}
        )
        await server._broadcast_pool_status()
        return {"deleted_tasks": deleted_tasks}

    # ── GET /api/chats/{id}/messages — hybrid ────────────────────

    @router.get("/api/chats/{chat_id}/messages")
    async def get_messages(
        chat_id: str,
        thread_root_id: str | None = Query(default=None),
        limit: int | None = Query(default=None),
        before: str | None = Query(default=None),
        paginate: bool = Query(default=False),
    ) -> MessagesPageResponse | list[V2MessageResponse] | list[MessageResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        db = _db()
        v2_row = await db.get_chat(chat_id)

        if v2_row is not None:
            if paginate:
                fetch_limit = limit if limit is not None else 50
                rows = await db.get_messages_for_chat(
                    chat_id,
                    thread_root_id=thread_root_id,
                    limit=fetch_limit + 1,
                    before_id=before,
                )
                has_more = len(rows) > fetch_limit
                items = rows[:fetch_limit]
                return MessagesPageResponse(
                    items=[
                        V2MessageResponse(
                            id=r["id"],
                            chat_id=r["chat_id"],
                            thread_root_id=r.get("thread_root_id"),
                            role=r["role"],
                            content=r["content"],
                            task_id=r.get("task_id"),
                            created_at=r["created_at"],
                        )
                        for r in items
                    ],
                    has_more=has_more,
                )
            rows = await db.get_messages_for_chat(
                chat_id,
                thread_root_id=thread_root_id,
                limit=limit,
                before_id=before,
            )
            return [
                V2MessageResponse(
                    id=r["id"],
                    chat_id=r["chat_id"],
                    thread_root_id=r.get("thread_root_id"),
                    role=r["role"],
                    content=r["content"],
                    task_id=r.get("task_id"),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

        # Legacy bucket chat
        if chat_id not in server.executor.pool.buckets:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
        return await _handle_legacy_get_messages(chat_id)

    # ── POST /api/chats/{id}/messages — hybrid ───────────────────

    @router.post("/api/chats/{chat_id}/messages", status_code=201)
    async def create_message(
        chat_id: str, message_input: MessageCreate
    ) -> V2MessageResponse | MessageResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        db = _db()
        v2_row = await db.get_chat(chat_id)

        if v2_row is not None:
            return await _handle_v2_post_message(chat_id, v2_row, message_input, db)

        # Legacy bucket fallback
        if chat_id not in server.executor.pool.buckets:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
        return await _handle_legacy_post_message(chat_id, message_input)

    async def _handle_v2_post_message(
        chat_id: str,
        chat_row: dict,
        message_input: MessageCreate,
        db: DatabaseManager,
    ) -> V2MessageResponse:
        project_id = chat_row["project_id"]
        proj_row = await db.get_project(project_id)
        if proj_row is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        directory = Path(proj_row["directory"])

        # Persist user message
        msg_id = f"msg_{_uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        msg_dict = {
            "id": msg_id,
            "chat_id": chat_id,
            "thread_root_id": message_input.thread_root_id,
            "role": "user",
            "content": message_input.content,
            "task_id": None,
            "created_at": now,
        }
        await db.upsert_message(msg_dict)

        # Build task args from cli_id if provided
        args: list[str] = []
        if message_input.model:
            args.extend(["--model", message_input.model])

        # Create and enqueue Task with v2 fields
        task_id = _generate_task_id()
        new_task = Task(
            id=task_id,
            prompt=message_input.content,
            directory=directory,
            args=args,
            bucket_id=chat_id,
            project_id=project_id,
            chat_id=chat_id,
            parent_message_id=message_input.thread_root_id,
            kind="request",
            model=message_input.model or "",
        )

        # Link message → task
        msg_dict["task_id"] = task_id
        await db.upsert_message(msg_dict)

        server.executor.pool.tasks.append(new_task)
        server.executor._save_state()

        await server._broadcast_event(
            {
                "event": "message_created",
                "data": {
                    "message_id": msg_id,
                    "chat_id": chat_id,
                    "thread_root_id": message_input.thread_root_id,
                    "role": "user",
                    "task_id": task_id,
                },
            }
        )
        await server._broadcast_pool_status()

        return V2MessageResponse(
            id=msg_id,
            chat_id=chat_id,
            thread_root_id=message_input.thread_root_id,
            role="user",
            content=message_input.content,
            task_id=task_id,
            created_at=now,
        )

    return router
