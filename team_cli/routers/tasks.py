"""Task CRUD and lifecycle routes."""

import logging
from copy import deepcopy
from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..api_helpers import _generate_task_id, _validate_directory
from ..api_models import TaskDetailResponse, TaskInput, TaskPatchInput, TaskResponse
from ..models import Task

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    # "completed" is the external alias for internal status "success"
    _STATUS_ALIAS = {"completed": "success"}

    @router.get("/api/tasks")
    async def get_tasks(
        status: str | None = None,
        project_id: str | None = None,
        kind: str | None = None,
    ) -> list[TaskResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        tasks = server.executor.pool.tasks
        if status:
            internal = _STATUS_ALIAS.get(status, status)
            tasks = [t for t in tasks if t.status == internal]
        if project_id:
            tasks = [t for t in tasks if t.project_id == project_id]
        if kind:
            tasks = [t for t in tasks if t.kind == kind]
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

    @router.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> TaskDetailResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
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

    @router.post("/api/tasks")
    async def create_task(task_input: TaskInput) -> TaskResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        directory = task_input.directory
        if not directory and task_input.github_url:
            directory = server._resolve_directory(task_input.github_url)
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

        resolved = _validate_directory(directory)

        task_id = _generate_task_id()
        args = list(task_input.args)
        if task_input.model:
            args.extend(["--model", task_input.model])
        if task_input.effort:
            args.extend(["--effort", task_input.effort])

        new_task = Task(
            id=task_id,
            prompt=task_input.prompt,
            directory=resolved,
            args=args,
            status="pending",
            priority=task_input.priority,
        )
        server.executor.pool.tasks.append(new_task)
        server.executor._save_state()

        await server._broadcast_event(
            {
                "event": "task_created",
                "task": {
                    "id": new_task.id,
                    "prompt": new_task.prompt,
                    "status": new_task.status,
                },
            }
        )
        await server._broadcast_pool_status()

        return TaskResponse(
            id=new_task.id,
            prompt=new_task.prompt,
            directory=str(new_task.directory),
            status=new_task.status,
            retry_count=0,
            bucket_id=new_task.bucket_id,
            priority=new_task.priority,
            created_at=new_task.created_at,
        )

    @router.post("/api/tasks/{task_id}/retry")
    async def retry_task(task_id: str) -> TaskResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
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
        server.executor._save_state()
        await server._broadcast_event(
            {
                "event": "task_updated",
                "task": {"id": task.id, "status": task.status, "retry_count": task.retry_count},
            }
        )
        await server._broadcast_pool_status()
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
            created_at=task.created_at,
        )

    @router.post("/api/tasks/{task_id}/skip")
    async def skip_task(task_id: str) -> TaskResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        if task.status not in ("pending", "rate_limit_retry"):
            raise HTTPException(
                status_code=400, detail=f"Cannot skip task in {task.status} status"
            )
        task.status = "skipped"
        server.executor._save_state()
        await server._broadcast_event(
            {"event": "task_skipped", "task": {"id": task.id, "status": "skipped"}}
        )
        await server._broadcast_pool_status()
        return TaskResponse(
            id=task.id,
            prompt=task.prompt,
            directory=str(task.directory),
            status="skipped",
            retry_count=task.retry_count,
            bucket_id=task.bucket_id,
            priority=task.priority,
            created_at=task.created_at,
        )

    @router.post("/api/tasks/{task_id}/stop")
    async def stop_task(task_id: str) -> TaskResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        if task.status != "running":
            raise HTTPException(
                status_code=400, detail=f"Cannot stop task in {task.status} status"
            )
        await server.executor.stop_task(task_id)
        await server._broadcast_event(
            {"event": "task_stopped", "task": {"id": task.id, "status": "stopped"}}
        )
        await server._broadcast_pool_status()
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
            created_at=task.created_at,
        )

    @router.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str) -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        server.executor.pool.tasks.remove(task)
        server.executor._save_state()
        await server._broadcast_event(
            {"event": "task_deleted", "task": {"id": task.id}}
        )
        await server._broadcast_pool_status()
        return {"status": "success", "id": task_id}

    @router.post("/api/tasks/{task_id}/duplicate")
    async def duplicate_task(task_id: str) -> TaskResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
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
        server.executor.pool.tasks.append(new_task)
        server.executor._save_state()
        await server._broadcast_event(
            {
                "event": "task_created",
                "task": {
                    "id": new_task.id,
                    "prompt": new_task.prompt,
                    "status": new_task.status,
                },
            }
        )
        await server._broadcast_pool_status()
        return TaskResponse(
            id=new_task.id,
            prompt=new_task.prompt,
            directory=str(new_task.directory),
            status=new_task.status,
            retry_count=0,
            bucket_id=new_task.bucket_id,
            priority=new_task.priority,
            created_at=new_task.created_at,
        )

    @router.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, patch: TaskPatchInput) -> TaskResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        task = next((t for t in server.executor.pool.tasks if t.id == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Handle status=skipped separately — returns 409 if not pending
        if patch.status == "skipped":
            if task.status != "pending":
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot skip task in {task.status} status",
                )
            task.status = "skipped"
            server.executor._save_state()
            await server._broadcast_event(
                {"event": "task_skipped", "task": {"id": task.id, "status": "skipped"}}
            )
            await server._broadcast_pool_status()
            return TaskResponse(
                id=task.id,
                prompt=task.prompt,
                directory=str(task.directory),
                status=task.status,
                retry_count=task.retry_count,
                bucket_id=task.bucket_id,
                priority=task.priority,
                created_at=task.created_at,
            )

        # All other field updates require pending status
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
        server.executor._save_state()
        await server._broadcast_event(
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
            created_at=task.created_at,
        )

    _PURGEABLE_STATUSES = {"success", "completed", "failed", "skipped"}

    @router.delete("/api/tasks")
    async def purge_tasks(status: str | None = None) -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        if not status:
            raise HTTPException(status_code=400, detail="'status' query parameter is required")
        if status not in _PURGEABLE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot purge tasks with status '{status}'. "
                       f"Allowed: completed, failed, skipped",
            )
        # "completed" is the external alias for internal "success"
        internal_status = _STATUS_ALIAS.get(status, status)
        from ..database import DatabaseManager
        db = DatabaseManager(server.pool_file)
        # Skip running tasks even if they somehow match
        to_remove = [
            t for t in server.executor.pool.tasks
            if t.status == internal_status and t.status != "running"
        ]
        for task in to_remove:
            server.executor.pool.tasks.remove(task)
            await db.delete_task(task.id)
        if to_remove:
            server.executor._save_state()
            await server._broadcast_pool_status()
        return {"deleted": len(to_remove)}

    return router
