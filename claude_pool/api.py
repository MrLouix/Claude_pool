"""FastAPI web server for Claude Pool with WebSocket support."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .executor import TaskExecutor
from .models import Task

logger = logging.getLogger(__name__)


class TaskInput(BaseModel):
    """Input model for creating a task."""
    prompt: str
    directory: str
    args: list[str] = []
    model: Optional[str] = None
    effort: Optional[str] = None


class TaskResponse(BaseModel):
    """Response model for a task."""
    id: str
    prompt: str
    directory: str
    status: str
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0


class PoolStatusResponse(BaseModel):
    """Response model for pool status."""
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    pool_suspended: bool
    suspension_remaining: float = 0.0
    retry_count: int = 0


class ApiServer:
    """FastAPI server for Claude Pool."""

    def __init__(self, pool_file: Path):
        """Initialize the API server.

        Args:
            pool_file: Path to pool.json
        """
        self.pool_file = pool_file
        self.executor: Optional[TaskExecutor] = None
        self.app = FastAPI(
            title="Claude Pool API",
            description="REST API for managing Claude Pool tasks",
            version="1.0.0"
        )
        self.ws_clients: Set[WebSocket] = set()

        # Setup routes
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup API routes."""

        @self.app.on_event("startup")
        async def startup():
            """Initialize executor on startup."""
            self.executor = TaskExecutor(self.pool_file, on_task_update=self._on_task_update)
            await self.executor.load_tasks()

            # Start background task executor
            asyncio.create_task(self.executor.run_pool())
            logger.info("API server started with task executor")

        @self.app.on_event("shutdown")
        async def shutdown():
            """Cleanup on shutdown."""
            if self.executor:
                self.executor.should_stop = True
            logger.info("API server shut down")

        @self.app.get("/")
        async def root():
            """Return dashboard HTML."""
            frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
            if frontend_path.exists():
                return HTMLResponse(content=frontend_path.read_text())
            return {"message": "Claude Pool API"}

        @self.app.get("/api/status")
        async def get_status() -> PoolStatusResponse:
            """Get current pool status."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")

            pool = self.executor.pool
            tasks = pool.tasks

            pending = sum(1 for t in tasks if t.status == "pending")
            running = sum(1 for t in tasks if t.status == "running")
            completed = sum(1 for t in tasks if t.status == "success")
            failed = sum(1 for t in tasks if t.status == "failed")
            skipped = sum(1 for t in tasks if t.status == "skipped")

            return PoolStatusResponse(
                total_tasks=len(tasks),
                pending_tasks=pending,
                running_tasks=running,
                completed_tasks=completed,
                failed_tasks=failed,
                skipped_tasks=skipped,
                pool_suspended=pool.is_suspended,
                suspension_remaining=pool.suspension_remaining,
                retry_count=pool.retry_count,
            )

        @self.app.get("/api/tasks")
        async def get_tasks(status: Optional[str] = None) -> list[TaskResponse]:
            """Get all tasks, optionally filtered by status."""
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
                )
                for t in tasks
            ]

        @self.app.post("/api/tasks")
        async def create_task(task_input: TaskInput) -> TaskResponse:
            """Create a new task."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")

            # Generate task ID
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"

            # Build args list
            args = task_input.args.copy() if task_input.args else []
            if task_input.model:
                args.extend(["--model", task_input.model])
            if task_input.effort:
                args.extend(["--effort", task_input.effort])

            # Create task
            new_task = Task(
                id=task_id,
                prompt=task_input.prompt,
                directory=Path(task_input.directory),
                args=args,
                status="pending",
            )

            # Add to executor's pool
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()

            # Notify WebSocket clients
            await self._broadcast_event({
                "event": "task_created",
                "task": {
                    "id": new_task.id,
                    "prompt": new_task.prompt,
                    "status": new_task.status,
                }
            })

            return TaskResponse(
                id=new_task.id,
                prompt=new_task.prompt,
                directory=str(new_task.directory),
                status=new_task.status,
                retry_count=0,
            )

        @self.app.post("/api/tasks/{task_id}/retry")
        async def retry_task(task_id: str) -> TaskResponse:
            """Retry a task."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")

            # Find task
            task = None
            for t in self.executor.pool.tasks:
                if t.id == task_id:
                    task = t
                    break

            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

            if task.status not in ("failed", "success"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot retry task in {task.status} status"
                )

            # Reset task
            task.status = "pending"
            task.exit_code = None
            task.duration_ms = None
            task.json_output = None
            task.retry_count += 1

            self.executor._save_state()

            # Notify WebSocket clients
            await self._broadcast_event({
                "event": "task_updated",
                "task": {
                    "id": task.id,
                    "status": task.status,
                    "retry_count": task.retry_count,
                }
            })

            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                exit_code=task.exit_code,
                duration_ms=task.duration_ms,
                retry_count=task.retry_count,
            )

        @self.app.post("/api/tasks/{task_id}/skip")
        async def skip_task(task_id: str) -> TaskResponse:
            """Skip a running task."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Executor not initialized")

            # Find task
            task = None
            for t in self.executor.pool.tasks:
                if t.id == task_id:
                    task = t
                    break

            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

            # Check if it's the current task
            if self.executor.current_task and self.executor.current_task.id == task_id:
                self.executor.skip_current()
                logger.info(f"Skipped task {task_id} via API")

                # Notify WebSocket clients
                await self._broadcast_event({
                    "event": "task_skipped",
                    "task": {
                        "id": task.id,
                        "status": "skipped",
                    }
                })

                return TaskResponse(
                    id=task.id,
                    prompt=task.prompt,
                    directory=str(task.directory),
                    status="skipped",
                    retry_count=task.retry_count,
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Task is not currently running"
                )

        @self.app.websocket("/ws/events")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket endpoint for real-time task updates."""
            await websocket.accept()
            self.ws_clients.add(websocket)

            try:
                # Send initial pool status
                if self.executor:
                    status = await get_status()
                    await websocket.send_json({
                        "event": "pool_status",
                        "data": status.dict()
                    })

                # Keep connection alive and receive messages
                while True:
                    # Allow client to send ping/pong
                    data = await websocket.receive_text()
                    if data == "ping":
                        await websocket.send_text("pong")
            except WebSocketDisconnect:
                self.ws_clients.discard(websocket)
                logger.debug(f"WebSocket client disconnected")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.ws_clients.discard(websocket)

    def _on_task_update(self, task: Task) -> None:
        """Callback when a task is updated by executor.

        Args:
            task: Updated task
        """
        # Schedule broadcast of update
        asyncio.create_task(self._broadcast_event({
            "event": "task_updated",
            "task": {
                "id": task.id,
                "prompt": task.prompt[:50],
                "status": task.status,
                "exit_code": task.exit_code,
                "duration_ms": task.duration_ms,
                "retry_count": task.retry_count,
            }
        }))

    async def _broadcast_event(self, message: dict) -> None:
        """Broadcast an event to all connected WebSocket clients.

        Args:
            message: Event message to broadcast
        """
        if not self.ws_clients:
            return

        disconnected = set()
        for client in self.ws_clients:
            try:
                await client.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send WebSocket message: {e}")
                disconnected.add(client)

        # Remove disconnected clients
        self.ws_clients -= disconnected


def create_app(pool_file: Path) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        pool_file: Path to pool.json

    Returns:
        FastAPI application instance
    """
    api_server = ApiServer(pool_file)
    return api_server.app
