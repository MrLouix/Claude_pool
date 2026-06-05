"""FastAPI web server for TeamCLI with WebSocket support."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
import os
import platform
import shutil
import uuid as _uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .api_models import (
    ChatCreateInput,
    ChatResponse,
    CLIConfigResponse,
    MessageInput,
    MessageResponse,
    PoolStatusResponse,
    ProjectEntry,
    ProjectInput,
    TaskDetailResponse,
    TaskInput,
    TaskPatchInput,
    TaskResponse,
)
from .executor import TaskExecutor
from .models import Bucket, PoolState, Task
from .cli_detector import detect_clis
from .config import load_cli_configs

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────


def _is_allowed_path(resolved: Path) -> bool:
    """Return True when *resolved* is inside the platform-specific allow-list.

    On Linux/Mac: only /home and /mnt subtrees are permitted.
    On Windows: all paths are allowed.
    """
    if platform.system() == "Windows":
        return True
    s = str(resolved).replace("\\", "/")
    return s.startswith("/home") or s.startswith("/mnt")


def _generate_task_id() -> str:
    """Return a unique task identifier: task_YYYYMMDD_HHMMSS_<8hex>."""
    return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def _validate_directory(directory: str) -> Path:
    """Resolve and validate that a directory exists.

    On Linux, restricts to /home and /mnt.
    On Windows, allows any path.
    Raises HTTPException(404) if the path does not exist.
    """
    logger.info(f"_validate_directory called with: {directory!r}")
    directory = directory.replace("\\", "/")
    resolved = Path(directory).resolve()
    logger.info(f"Resolved path: {resolved}")
    if not _is_allowed_path(resolved):
        raise HTTPException(status_code=403, detail="Access denied: directory outside allow-list")
    if not resolved.is_dir():
        logger.error(f"Directory not found: {resolved} (original: {directory!r})")
        raise HTTPException(status_code=404, detail=f"Directory not found: {directory}")
    return resolved


def _compute_pool_status(pool: "PoolState") -> "PoolStatusResponse":
    """Build a PoolStatusResponse from *pool*.  Pure function — no side effects."""
    tasks = pool.tasks

    pending_count = sum(1 for t in tasks if t.status == "pending")
    running_count = sum(1 for t in tasks if t.status == "running")
    rate_limit_count = sum(1 for t in tasks if t.status == "rate_limit_retry")

    rate_limit_result = None
    if rate_limit_count > 0:
        rl_task = next((t for t in tasks if t.status == "rate_limit_retry"), None)
        if rl_task and rl_task.json_output:
            rate_limit_result = rl_task.json_output.get("result")
        elif rl_task:
            rate_limit_result = "Rate limit detected"

    if rate_limit_count > 0 or pool.is_suspended:
        claude_status = "rate_limit"
    elif running_count > 0 or pending_count > 0:
        claude_status = "running"
    else:
        claude_status = "waiting request"

    return PoolStatusResponse(
        total_tasks=len(tasks),
        pending_tasks=pending_count,
        running_tasks=running_count,
        completed_tasks=sum(1 for t in tasks if t.status == "success"),
        failed_tasks=sum(1 for t in tasks if t.status == "failed"),
        skipped_tasks=sum(1 for t in tasks if t.status == "skipped"),
        pool_suspended=pool.is_suspended,
        suspension_remaining=pool.suspension_remaining,
        retry_count=pool.retry_count,
        claude_status=claude_status,
        rate_limit_result=rate_limit_result,
    )


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
    """FastAPI server for TeamCLI."""

    def __init__(self, pool_file: Path):
        if pool_file.suffix == ".json":
            pool_file = pool_file.with_suffix(".db")
        self.pool_file = pool_file
        self.executor: Optional[TaskExecutor] = None

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Bootstrap CLIManager
            detected = detect_clis()
            custom = load_cli_configs()
            all_configs = {c.name: c for c in detected}
            all_configs.update({c.name: c for c in custom})
            cli_manager = CLIManager(list(all_configs.values()))
            
            if not cli_manager._executors:
                logger.warning("No CLI executors detected or configured. Tasks will fail until a valid CLI is available.")
            
            self.executor = TaskExecutor(
                self.pool_file, on_task_update=self._on_task_update, install_signal_handlers=False,
                cli_manager=cli_manager
            )
            await self.executor.load_tasks()
            asyncio.create_task(self.executor.run_pool())
            logger.info("API server started with task executor")
            yield
            if self.executor:
                self.executor.should_stop = True

        self.app = FastAPI(
            title="TeamCLI API",
            description="REST API for managing TeamCLI tasks",
            version="1.0.0",
            lifespan=lifespan,
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

        @self.app.get("/")
        async def root():
            frontend_path = Path(__file__).parent / "frontend" / "index.html"
            if frontend_path.exists():
                return HTMLResponse(content=frontend_path.read_text(encoding="utf-8"))
            return {"message": "TeamCLI API"}

        # ── Pool status ───────────────────────────────────────────

        @self.app.get("/api/status")
        async def get_status() -> PoolStatusResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            self.executor.check_pool_updates()
            return _compute_pool_status(self.executor.pool)

        # ── Providers ─────────────────────────────────────────────

        _PROVIDER_CLI = {
            "claude": "claude",
            "qwen": "qwen-coder",
            "opencode": "opencode",
            "mistral": "codestral",
        }

        @self.app.get("/api/providers")
        async def get_providers() -> list[dict]:
            return [
                {"name": name, "available": shutil.which(cli) is not None}
                for name, cli in _PROVIDER_CLI.items()
            ]

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
                    priority=t.priority,
                    created_at=t.created_at,
                )
                for t in tasks
            ]

        @self.app.get("/api/tasks/{task_id}")
        async def get_task(task_id: str) -> TaskDetailResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            return TaskDetailResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                exit_code=task.exit_code,
                duration_ms=task.duration_ms,
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
                args=task.args,
                json_output=task.json_output,
                created_at=task.created_at,
                priority=task.priority,
            )

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

            task_id = _generate_task_id()
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
                priority=task_input.priority,
            )
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()

            await self._broadcast_event(
                {
                    "event": "task_created",
                    "task": {
                        "id": new_task.id,
                        "prompt": new_task.prompt,
                        "status": new_task.status,
                    },
                }
            )
            await self._broadcast_pool_status()

            return TaskResponse(
                id=new_task.id,
                prompt=new_task.prompt,
                directory=str(new_task.directory),
                status=new_task.status,
                retry_count=0,
                bucket_id=new_task.bucket_id,
                priority=new_task.priority,
            )

        @self.app.post("/api/tasks/{task_id}/retry")
        async def retry_task(task_id: str) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            if task.status not in ("failed", "success", "skipped"):
                raise HTTPException(
                    status_code=400, detail=f"Cannot retry task in {task.status} status"
                )
            was_skipped = task.status == "skipped"
            task.status = "pending"
            task.exit_code = None
            task.duration_ms = None
            task.json_output = None
            if not was_skipped:
                task.retry_count += 1
            self.executor._save_state()
            await self._broadcast_event(
                {
                    "event": "task_updated",
                    "task": {"id": task.id, "status": task.status, "retry_count": task.retry_count},
                }
            )
            await self._broadcast_pool_status()
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                exit_code=task.exit_code,
                duration_ms=task.duration_ms,
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
                priority=task.priority,
            )

        @self.app.post("/api/tasks/{task_id}/skip")
        async def skip_task(task_id: str) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            if task.status not in ("pending", "rate_limit_retry"):
                raise HTTPException(
                    status_code=400, detail=f"Cannot skip task in {task.status} status"
                )
            task.status = "skipped"
            self.executor._save_state()
            await self._broadcast_event(
                {"event": "task_skipped", "task": {"id": task.id, "status": "skipped"}}
            )
            await self._broadcast_pool_status()
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status="skipped",
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
                priority=task.priority,
            )

        @self.app.post("/api/tasks/{task_id}/stop")
        async def stop_task(task_id: str) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            if task.status != "running":
                raise HTTPException(
                    status_code=400, detail=f"Cannot stop task in {task.status} status"
                )
            await self.executor.stop_task(task_id)
            await self._broadcast_event(
                {"event": "task_stopped", "task": {"id": task.id, "status": "stopped"}}
            )
            await self._broadcast_pool_status()
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                exit_code=task.exit_code,
                duration_ms=task.duration_ms,
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
                priority=task.priority,
            )

        @self.app.delete("/api/tasks/{task_id}")
        async def delete_task(task_id: str) -> dict:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            self.executor.pool.tasks.remove(task)
            self.executor._save_state()
            await self._broadcast_event(
                {"event": "task_deleted", "task": {"id": task.id}}
            )
            await self._broadcast_pool_status()
            return {"status": "success", "id": task_id}

        @self.app.post("/api/tasks/{task_id}/duplicate")
        async def duplicate_task(task_id: str) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            new_task = deepcopy(task)
            new_task.id = _generate_task_id()
            new_task.status = "pending"
            new_task.exit_code = None
            new_task.duration_ms = None
            new_task.json_output = None
            new_task.retry_count = 0
            new_task.created_at = datetime.now().isoformat()
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()
            await self._broadcast_event(
                {
                    "event": "task_created",
                    "task": {
                        "id": new_task.id,
                        "prompt": new_task.prompt,
                        "status": new_task.status,
                    },
                }
            )
            await self._broadcast_pool_status()
            return TaskResponse(
                id=new_task.id,
                prompt=new_task.prompt,
                directory=str(new_task.directory),
                status=new_task.status,
                retry_count=0,
                bucket_id=new_task.bucket_id,
                priority=new_task.priority,
            )

        @self.app.patch("/api/tasks/{task_id}")
        async def update_task(task_id: str, patch: TaskPatchInput) -> TaskResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            task = next((t for t in self.executor.pool.tasks if t.id == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            if task.status != "pending":
                raise HTTPException(
                    status_code=400, detail=f"Cannot update task in {task.status} status"
                )
            if patch.prompt is not None:
                task.prompt = patch.prompt
            if patch.priority is not None:
                task.priority = patch.priority
            if patch.model is not None or patch.effort is not None:
                new_args = list(task.args)
                if patch.model is not None:
                    if "--model" in new_args:
                        idx = new_args.index("--model")
                        new_args[idx + 1] = patch.model
                    else:
                        new_args.extend(["--model", patch.model])
                if patch.effort is not None:
                    if "--effort" in new_args:
                        idx = new_args.index("--effort")
                        new_args[idx + 1] = patch.effort
                    else:
                        new_args.extend(["--effort", patch.effort])
                task.args = new_args
            self.executor._save_state()
            await self._broadcast_event(
                {
                    "event": "task_updated",
                    "task": {
                        "id": task.id,
                        "status": task.status,
                        "prompt": task.prompt,
                        "retry_count": task.retry_count,
                        "bucket_id": task.bucket_id,
                    },
                }
            )
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
                priority=task.priority,
            )

        @self.app.post("/api/pool/instant-retry")
        async def instant_retry() -> dict:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            self.executor.pool.suspended_until = None
            self.executor._save_state()
            await self._broadcast_pool_status()
            logger.info("Instant retry requested: pool suspension cleared")
            return {
                "status": "success",
                "message": "Pool suspension cleared, retrying task immediately",
            }

        # ── Directories ───────────────────────────────────────────

        @self.app.get("/api/directories")
        async def list_directories(path: Optional[str] = None) -> dict:
            target = Path(path) if path else Path.home()
            try:
                resolved = target.resolve()
                s = str(resolved).replace("\\", "/")
                if not _is_allowed_path(resolved):
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
            parent_raw = str(resolved.parent)
            parent = parent_raw.replace("\\", "/") if resolved != Path(resolved.anchor) else None
            return {"current": s, "parent": parent, "entries": entries}

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

        # ── CLI Config ────────────────────────────────────────────

        @self.app.get("/api/clis")
        async def list_clis() -> list[CLIConfigResponse]:
            """Get list of configured CLIs (detected + custom)."""
            detected = detect_clis()
            custom = load_cli_configs()
            
            # Merge: custom overrides detected
            all_configs = {c.name: c for c in detected}
            all_configs.update({c.name: c for c in custom if c.enabled})
            
            return [
                CLIConfigResponse(
                    name=c.name,
                    path=c.path,
                    models=c.models,
                    cli_type=c.cli_type,
                    enabled=c.enabled,
                    default_model=c.default_model,
                )
                for c in all_configs.values()
            ]

        @self.app.get("/api/clis/detect")
        async def detect_clis_endpoint() -> list[CLIConfigResponse]:
            """Trigger fresh CLI detection and return results."""
            detected = detect_clis()
            return [
                CLIConfigResponse(
                    name=c.name,
                    path=c.path,
                    models=c.models,
                    cli_type=c.cli_type,
                    enabled=c.enabled,
                    default_model=c.default_model,
                )
                for c in detected
            ]

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
                dir_tasks = [
                    t for t in self.executor.pool.tasks
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
            await self._broadcast_event(
                {"event": "chat_deleted", "id": chat_id, "deleted_tasks": deleted_tasks}
            )
            await self._broadcast_pool_status()
            return {"deleted_tasks": deleted_tasks}

        @self.app.get("/api/chats/{chat_id}/messages")
        async def get_messages(chat_id: str) -> list[MessageResponse]:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            if chat_id not in self.executor.pool.buckets:
                raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")
            tasks = sorted(
                (t for t in self.executor.pool.tasks if t.bucket_id == chat_id),
                key=lambda t: (t.priority, t.created_at),
            )
            return [_task_to_message(t) for t in tasks]

        @self.app.post("/api/chats/{chat_id}/messages", status_code=201)
        async def create_message(chat_id: str, message_input: MessageInput) -> MessageResponse:
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")
            bucket = self.executor.pool.buckets.get(chat_id)
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
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()

            msg = _task_to_message(new_task)
            await self._broadcast_event(
                {
                    "event": "chat_message",
                    "chat_id": chat_id,
                    "message": msg.model_dump(),
                }
            )
            await self._broadcast_pool_status()
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
        asyncio.create_task(
            self._broadcast_event(
                {
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
                }
            )
        )
        asyncio.create_task(self._broadcast_pool_status())

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

    async def _broadcast_pool_status(self) -> None:
        if not self.executor:
            return
        self.executor.check_pool_updates()
        status = _compute_pool_status(self.executor.pool)
        await self._broadcast_event({"event": "pool_status", "data": status.model_dump()})


def create_app(pool_file: Path) -> FastAPI:
    return ApiServer(pool_file).app
