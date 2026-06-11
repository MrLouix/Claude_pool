"""Shared helper functions used by api.py and the router modules."""

import logging
import platform
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .api_models import MessageResponse, PoolStatusResponse
from .models import PoolState, Task

logger = logging.getLogger(__name__)


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


def _compute_pool_status(pool: PoolState) -> PoolStatusResponse:
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
