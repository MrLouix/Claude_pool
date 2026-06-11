"""FastAPI web server for TeamCLI with WebSocket support."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .api_helpers import (
    _compute_pool_status,
    _generate_task_id,
    _is_allowed_path,
    _validate_directory,
    _task_to_message,
)
import shutil  # noqa: F401 — kept for backward compat: tests patch team_cli.api.shutil.which

from .executor import CLIManager, NoCLIAvailableError, TaskExecutor, execute_message  # noqa: F401 — re-exported for test patches
from .api_models import TaskInput, TaskPatchInput, MessageInput  # noqa: F401 — re-exported for test patches
from .priority_engine import calculate_priority  # noqa: F401 — re-exported for test patches
from .models import Task
from .cli_detector import detect_clis
from .config import load_cli_configs

# Re-export helpers so existing imports like `from team_cli.api import _compute_pool_status` work.
__all__ = [
    "_compute_pool_status",
    "_generate_task_id",
    "_is_allowed_path",
    "_validate_directory",
    "_task_to_message",
]

logger = logging.getLogger(__name__)


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

        _cors_raw = os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        )
        allowed_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.frontend_path = Path(__file__).parent / "frontend"
        if self.frontend_path.exists():
            self.app.mount("/static", StaticFiles(directory=str(self.frontend_path)), name="static")

        @self.app.get("/favicon.ico")
        async def favicon():
            favicon_path = self.frontend_path / "favicon.ico"
            if favicon_path.exists():
                return FileResponse(favicon_path)
            return Response(status_code=204)

        # Legacy github_url → directory mapping (loaded from ~/.claude-pool/projects.json)
        self._projects_dir = Path.home() / ".claude-pool"
        self._projects_dir.mkdir(exist_ok=True)
        self._projects_file = self._projects_dir / "projects.json"
        self._projects: list[dict[str, str]] = []
        self._load_projects()

        self._setup_routes()

    # ── Legacy project store (github_url → directory) ─────────────

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
        from .routers.tasks import create_router as create_tasks_router
        from .routers.pools import create_router as create_pools_router
        from .routers.chats import create_router as create_chats_router
        from .routers.projects import create_router as create_projects_router
        from .routers.skills import create_router as create_skills_router
        from .routers.admin import create_router as create_admin_router

        @self.app.get("/")
        async def root():
            frontend_path = Path(__file__).parent / "frontend" / "index.html"
            if frontend_path.exists():
                return HTMLResponse(content=frontend_path.read_text(encoding="utf-8"))
            return {"message": "TeamCLI API"}

        self.app.include_router(create_pools_router(self))
        self.app.include_router(create_tasks_router(self))
        self.app.include_router(create_chats_router(self))
        self.app.include_router(create_projects_router(self))
        self.app.include_router(create_skills_router(self))
        self.app.include_router(create_admin_router(self))

        # ── WebSocket ─────────────────────────────────────────────

        @self.app.websocket("/ws/events")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.ws_clients.add(websocket)
            try:
                if self.executor:
                    self.executor.check_pool_updates()
                    status = _compute_pool_status(self.executor.pool)
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

    # ── Multi-Step Planner background helpers ─────────────────────

    async def _execute_plan_background(self, plan: object) -> None:
        """Run plan execution in background and broadcast step/completion events."""
        from .skills.multi_step_planner.executor import StepTaskExecutor

        async def broadcast_fn(event: str, data: dict) -> None:
            await self._broadcast_event({"event": event, "data": data})

        executor = StepTaskExecutor(db_path=self.pool_file)
        result = await executor.execute_plan(plan, broadcast_fn=broadcast_fn)

        await self._broadcast_event({
            "event": "plan_completed",
            "data": {
                "plan_id": result.id,
                "status": result.status,
                "final_evaluation": result.final_evaluation,
            },
        })

    async def _execute_step_background(self, plan: object, step: object) -> None:
        """Execute a single step in background, then check plan completion."""
        from .skills.multi_step_planner.executor import StepTaskExecutor
        from .storage import load_step_plan as _load_plan

        executor = StepTaskExecutor(db_path=self.pool_file)
        updated = await executor.execute_step(step)

        await self._broadcast_event({
            "event": "step_task_updated",
            "data": {
                "task_id": updated.id,
                "plan_id": updated.plan_id,
                "step_number": updated.step_number,
                "description": updated.description,
                "status": updated.status,
                "cli_used": updated.cli_used,
                "duration_ms": updated.duration_ms,
            },
        })

        await executor._check_plan_completion(plan)

        reloaded = await asyncio.to_thread(_load_plan, plan.id, self.pool_file)
        if reloaded and reloaded.status in ("completed", "failed"):
            await self._broadcast_event({
                "event": "plan_completed",
                "data": {
                    "plan_id": reloaded.id,
                    "status": reloaded.status,
                    "final_evaluation": reloaded.final_evaluation,
                },
            })

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
