"""FastAPI web server for Claude Pool with WebSocket support."""

import asyncio
import json
import logging
import os
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .executor import TaskExecutor
from .models import Bucket, Task

logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────

class ProjectEntry(BaseModel):
    name: str
    github_url: str
    directory: str


class ProjectInput(BaseModel):
    name: str
    github_url: str
    directory: str


class TaskInput(BaseModel):
    prompt: str
    directory: Optional[str] = None
    github_url: Optional[str] = None
    args: list[str] = []
    model: Optional[str] = None
    effort: Optional[str] = None


class TaskResponse(BaseModel):
    id: str
    prompt: str
    directory: str
    status: str
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0
    bucket_id: str = "main"


class PoolStatusResponse(BaseModel):
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    pool_suspended: bool
    suspension_remaining: float = 0.0
    retry_count: int = 0


class ChatCreateInput(BaseModel):
    """Input model for creating a chat bucket."""
    directory: str
    label: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for a chat bucket."""
    id: str
    label: str
    directory: Optional[str] = None
    created_at: str
    message_count: int = 0
    last_activity: Optional[str] = None


class MessageInput(BaseModel):
    """Input model for sending a chat message (creates a task)."""
    prompt: str
    model: Optional[str] = None
    effort: Optional[str] = None


class MessageResponse(BaseModel):
    """Response model for a chat message (task projected as chat turn)."""
    id: str
    role: str = "user"
    content: str
    created_at: str
    status: str
    assistant_response: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────

def _validate_directory(directory: str) -> Path:
    """Resolve and validate that a directory is inside the allow-list.

    Raises HTTPException(403) if outside /home or /mnt.
    Raises HTTPException(404) if the path does not exist.
    """
    resolved = Path(directory).resolve()
    s = str(resolved)
    if not s.startswith("/home") and not s.startswith("/mnt"):
        raise HTTPException(status_code=403, detail="Access denied: directory outside allow-list")
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    return resolved


def _task_to_message(task: Task) -> MessageResponse:
    """Project a Task onto MessageResponse."""
    if task.status in ("pending", "running", "rate_limit_retry"):
        assistant_response = None
    elif task.status == "success":
        assistant_response = task.json_output.get("result") if task.json_output else None
    else:  # failed, skipped
        if task.json_output and task.json_output.get("result"):
            assistant_response = task.json_output["result"]
        else:
            assistant_response = f"Error (exit code {task.exit_code})"

    return MessageResponse(
        id=task.id,
        role="user",
        content=task.prompt,
        created_at=task.created_at,
        status=task.status,
        assistant_response=assistant_response,
        exit_code=task.exit_code,
        duration_ms=task.duration_ms,
    )


# ── API server ────────────────────────────────────────────────────

class ApiServer:
    """FastAPI server for Claude Pool."""

    def __init__(self, pool_file: Path):
        self.pool_file = pool_file
        self.executor: Optional[TaskExecutor] = None
        self.app = FastAPI(
            title="Claude Pool API",
            description="REST API for managing Claude Pool tasks",
            version="1.0.0",
        )
        self.ws_clients: Set[WebSocket] = set()

        self._projects_dir = Path.home() / ".claude-pool"
        self._projects_dir.mkdir(exist_ok=True)
        self._projects_file = self._projects_dir / "projects.json"
        self._projects: list[dict[str, str]] = []
        self._load_projects()

        self._setup_routes()

    # ── Project store ─────────────────────────────────────────────

    def _load_projects(self) -> None:
        if self._projects_file.exists():
            try:
                data = json.loads(self._projects_file.read_text())
                self._projects = data.get("projects", [])
            except Exception as e:
                logger.error(f"Failed to load projects.json: {e}")
                self._projects = []
        else:
            self._projects = []

    def _save_projects(self) -> None:
        self._projects_file.write_text(
            json.dumps({"projects": self._projects}, indent=2, ensure_ascii=False)
        )

    def _resolve_directory(self, github_url: str) -> str | None:
        for p in self._projects:
            if p["github_url"].rstrip("/") == github_url.rstrip("/"):
                return p["directory"]
        return None

    def _setup_routes(self) -> None:

        @self.app.on_event("startup")
        async def startup():
            self.executor = TaskExecutor(self.pool_file, on_task_update=self._on_task_update)
            await self.executor.load_tasks()
            asyncio.create_task(self.executor.run_pool())
            logger.info("API server started with task executor")

        @self.app.on_event("shutdown")
        async def shutdown():
            if self.executor:
                self.executor.should_stop = True

        @self.app.get("/")
        async def root():
            frontend_path = Path(__file__).parent / "frontend" / "index.html"
            if frontend_path.exists():
                return HTMLResponse(content=frontend_path.read_text())
            return {"message": "Claude Pool API"}

        # ── Pool status ───────────────────────────────────────────

        @self.app.get("/api/status")
        async def get_status() -> PoolStatusResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            pool = self.executor.pool
            tasks = pool.tasks
            return PoolStatusResponse(
                total_tasks=len(tasks),
                pending_tasks=sum(1 for t in tasks if t.status == "pending"),
                running_tasks=sum(1 for t in tasks if t.status == "running"),
                completed_tasks=sum(1 for t in tasks if t.status == "success"),
                failed_tasks=sum(1 for t in tasks if t.status == "failed"),
                skipped_tasks=sum(1 for t in tasks if t.status == "skipped"),
                pool_suspended=pool.is_suspended,
                suspension_remaining=pool.suspension_remaining,
                retry_count=pool.retry_count,
            )

        # ── Tasks ─────────────────────────────────────────────────

        @self.app.get("/api/tasks")
        async def get_tasks(status: Optional[str] = None) -> list[TaskResponse]:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            tasks = self.executor.pool.tasks
            if status:
                tasks = [t for t in tasks if t.status == status]
            return [
                TaskResponse(
                    id=t.id,
                    prompt=t.prompt,
                    directory=str(t.directory),
                    status=t.status,
                    exit_code=t.exit_code,
                    duration_ms=t.duration_ms,
                    retry_count=t.retry_count,
                    bucket_id=t.bucket_id,
                )
                for t in tasks
            ]

        @self.app.post("/api/tasks")
        async def create_task(task_input: TaskInput) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")

            directory = task_input.directory
            if not directory and task_input.github_url:
                directory = self._resolve_directory(task_input.github_url)
                if not directory:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unknown GitHub URL: {task_input.github_url}. "
                        "Add a mapping via POST /api/projects first.",
                    )
            if not directory:
                raise HTTPException(
                    status_code=400,
                    detail="Either 'directory' or 'github_url' must be provided",
                )

            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
            args = list(task_input.args)
            if task_input.model:
                args.extend(["--model", task_input.model])
            if task_input.effort:
                args.extend(["--effort", task_input.effort])

            new_task = Task(
                id=task_id,
                prompt=task_input.prompt,
                directory=Path(directory),
                args=args,
                status="pending",
            )
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()

            await self._broadcast_event({
                "event": "task_created",
                "task": {"id": new_task.id, "prompt": new_task.prompt, "status": new_task.status},
            })

            return TaskResponse(
                id=new_task.id,
                prompt=new_task.prompt,
                directory=str(new_task.directory),
                status=new_task.status,
                retry_count=0,
                bucket_id=new_task.bucket_id,
            )

        @self.app.post("/api/tasks/{task_id}/retry")
        async def retry_task(task_id: str) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            if task.status not in ("failed", "success"):
                raise HTTPException(
                    status_code=400, detail=f"Cannot retry task in {task.status} status"
                )
            task.status = "pending"
            task.exit_code = None
            task.duration_ms = None
            task.json_output = None
            task.retry_count += 1
            self.executor._save_state()
            await self._broadcast_event({
                "event": "task_updated",
                "task": {"id": task.id, "status": task.status, "retry_count": task.retry_count},
            })
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                exit_code=task.exit_code,
                duration_ms=task.duration_ms,
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
            )

        @self.app.post("/api/tasks/{task_id}/skip")
        async def skip_task(task_id: str) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            if not (self.executor.current_task and self.executor.current_task.id == task_id):
                raise HTTPException(status_code=400, detail="Task is not currently running")
            self.executor.skip_current()
            await self._broadcast_event(
                {"event": "task_skipped", "task": {"id": task.id, "status": "skipped"}}
            )
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status="skipped",
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
            )

        # ── Directories ───────────────────────────────────────────

        @self.app.get("/api/directories")
        async def list_directories(path: Optional[str] = None) -> dict:
            target = Path(path) if path else Path.home()
            try:
                resolved = target.resolve()
                s = str(resolved)
                if not s.startswith("/home") and not s.startswith("/mnt"):
                    raise HTTPException(status_code=403, detail="Access denied")
            except HTTPException:
                raise
            if not resolved.is_dir():
                raise HTTPException(status_code=404, detail="Directory not found")
            entries = []
            try:
                for item in sorted(resolved.iterdir()):
                    if item.is_dir() and not item.name.startswith("."):
                        entries.append({"name": item.name, "type": "directory"})
            except PermissionError:
                raise HTTPException(status_code=403, detail="Permission denied")
            parent = str(resolved.parent) if resolved != Path(resolved.anchor) else None
            return {"current": str(resolved), "parent": parent, "entries": entries}

        # ── Projects ──────────────────────────────────────────────

        @self.app.get("/api/projects")
        async def list_projects() -> list[ProjectEntry]:
            return [ProjectEntry(**p) for p in self._projects]

        @self.app.post("/api/projects", status_code=201)
        async def create_project(proj: ProjectInput) -> ProjectEntry:
            for p in self._projects:
                if p["github_url"].rstrip("/") == proj.github_url.rstrip("/"):
                    raise HTTPException(
                        status_code=409,
                        detail=f"GitHub URL already mapped to {p['directory']}",
                    )
            entry = {"name": proj.name, "github_url": proj.github_url, "directory": proj.directory}
            self._projects.append(entry)
            self._save_projects()
            return ProjectEntry(**entry)

        @self.app.delete("/api/projects/{project_name}")
        async def delete_project(project_name: str) -> dict:
            before = len(self._projects)
            self._projects = [p for p in self._projects if p["name"] != project_name]
            if len(self._projects) == before:
                raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
            self._save_projects()
            return {"removed": project_name}

        @self.app.post("/api/projects/resolve")
        async def resolve_project(body: dict) -> dict:
            github_url = body.get("github_url", "")
            directory = self._resolve_directory(github_url)
            if not directory:
                return {"github_url": github_url, "directory": None, "found": False}
            return {"github_url": github_url, "directory": directory, "found": True}

        # ── Chats ─────────────────────────────────────────────────

        @self.app.get("/api/chats")
        async def list_chats() -> list[ChatResponse]:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            result = []
            for bid, bucket in self.executor.pool.buckets.items():
                if bucket.type != "chat":
                    continue
                bucket_tasks = [t for t in self.executor.pool.tasks if t.bucket_id == bid]
                message_count = len(bucket_tasks)
                last_activity = max((t.created_at for t in bucket_tasks), default=None)
                result.append(ChatResponse(
                    id=bid,
                    label=bucket.label,
                    directory=bucket.directory,
                    created_at=bucket.created_at,
                    message_count=message_count,
                    last_activity=last_activity,
                ))
            result.sort(key=lambda c: c.created_at, reverse=True)
            return result

        @self.app.post("/api/chats", status_code=201)
        async def create_chat(chat_input: ChatCreateInput) -> ChatResponse:
            if not self.executor:
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
            self.executor.pool.buckets[bucket_id] = bucket
            self.executor._save_state()

            await self._broadcast_event({"event": "chat_created", "chat": bucket.to_dict()})

            return ChatResponse(
                id=bucket_id,
                label=bucket.label,
                directory=bucket.directory,
                created_at=bucket.created_at,
                message_count=0,
                last_activity=None,
            )

        @self.app.delete("/api/chats/{chat_id}")
        async def delete_chat(chat_id: str) -> dict:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            if chat_id not in self.executor.pool.buckets:
                raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
            try:
                deleted_tasks = self.executor.delete_bucket(chat_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            await self._broadcast_event({"event": "chat_deleted", "id": chat_id, "deleted_tasks": deleted_tasks})
            return {"deleted_tasks": deleted_tasks}

        @self.app.get("/api/chats/{chat_id}/messages")
        async def get_messages(chat_id: str) -> list[MessageResponse]:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            if chat_id not in self.executor.pool.buckets:
                raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
            msgs = [
                _task_to_message(t)
                for t in self.executor.pool.tasks
                if t.bucket_id == chat_id
            ]
            msgs.sort(key=lambda m: m.created_at)
            return msgs

        @self.app.post("/api/chats/{chat_id}/messages", status_code=201)
        async def create_message(chat_id: str, message_input: MessageInput) -> MessageResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            bucket = self.executor.pool.buckets.get(chat_id)
            if not bucket:
                raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
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
            )
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()

            msg = _task_to_message(new_task)
            await self._broadcast_event({
                "event": "chat_message",
                "chat_id": chat_id,
                "message": msg.model_dump(),
            })
            return msg

        # ── WebSocket ─────────────────────────────────────────────

        @self.app.websocket("/ws/events")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.ws_clients.add(websocket)
            try:
                if self.executor:
                    status = await get_status()
                    await websocket.send_json({"event": "pool_status", "data": status.model_dump()})
                while True:
                    data = await websocket.receive_text()
                    if data == "ping":
                        await websocket.send_text("pong")
            except WebSocketDisconnect:
                self.ws_clients.discard(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.ws_clients.discard(websocket)

    def _on_task_update(self, task: Task) -> None:
        asyncio.create_task(self._broadcast_event({
            "event": "task_updated",
            "task": {
                "id": task.id,
                "prompt": task.prompt[:50],
                "status": task.status,
                "exit_code": task.exit_code,
                "duration_ms": task.duration_ms,
                "retry_count": task.retry_count,
                "bucket_id": task.bucket_id,
                "result": task.json_output.get("result") if task.json_output else None,
            },
        }))

    async def _broadcast_event(self, message: dict) -> None:
        if not self.ws_clients:
            return
        disconnected = set()
        for client in self.ws_clients:
            try:
                await client.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send WebSocket message: {e}")
                disconnected.add(client)
        self.ws_clients -= disconnected


def create_app(pool_file: Path) -> FastAPI:
    return ApiServer(pool_file).app
