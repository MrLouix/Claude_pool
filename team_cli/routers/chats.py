"""Chat bucket and message routes."""

import logging
import uuid as _uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..api_helpers import _generate_task_id, _task_to_message, _validate_directory
from ..api_models import ChatCreateInput, ChatResponse, MessageInput, MessageResponse
from ..models import Bucket, Task

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

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
                t for t in server.executor.pool.tasks
                if t.bucket_id == bid and t.status == "success" and t.json_output
            ]
            dir_tasks.sort(key=lambda t: t.created_at, reverse=True)
            session_usage = (
                dir_tasks[0].json_output.get("session_usage_percent")
                if dir_tasks else None
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

    @router.delete("/api/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
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

    @router.get("/api/chats/{chat_id}/messages")
    async def get_messages(chat_id: str) -> list[MessageResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        if chat_id not in server.executor.pool.buckets:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
        tasks = sorted(
            (t for t in server.executor.pool.tasks if t.bucket_id == chat_id),
            key=lambda t: (t.priority, t.created_at),
        )
        return [_task_to_message(t) for t in tasks]

    @router.post("/api/chats/{chat_id}/messages", status_code=201)
    async def create_message(chat_id: str, message_input: MessageInput) -> MessageResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
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
            prompt=message_input.prompt,
            directory=directory,
            args=args,
            bucket_id=chat_id,
            priority=message_input.priority,
        )
        server.executor.pool.tasks.append(new_task)
        server.executor._save_state()

        msg = _task_to_message(new_task)
        await server._broadcast_event(
            {
                "event": "chat_message",
                "chat_id": chat_id,
                "message": msg.model_dump(),
            }
        )
        await server._broadcast_pool_status()
        return msg

    return router
