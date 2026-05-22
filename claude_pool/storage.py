"""Storage functions for loading and saving task pools."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .models import Bucket, PoolState, Task

logger = logging.getLogger(__name__)


def load_pool(pool_file: Path) -> PoolState:
    """Load tasks and pool state from a JSON pool file.

    Supports both the wrapped format (dict with 'tasks' key) and the legacy
    bare-array format for backward compatibility.

    If the file doesn't exist or is empty, initializes it with an empty pool.

    Args:
        pool_file: Path to the pool.json file

    Returns:
        PoolState object containing tasks and pool metadata

    Raises:
        json.JSONDecodeError: If pool file contains invalid JSON
    """
    # Initialize empty pool if file doesn't exist
    if not pool_file.exists():
        logger.info(f"Pool file not found, creating new empty pool: {pool_file}")
        state = PoolState(pool_file=pool_file)
        save_pool(state)
        return state

    content = pool_file.read_text(encoding="utf-8").strip()
    
    # Initialize empty pool if file is empty
    if not content:
        logger.info(f"Pool file is empty, initializing: {pool_file}")
        state = PoolState(pool_file=pool_file)
        save_pool(state)
        return state
    
    raw_data = json.loads(content)

    # Backward compatibility: legacy bare task array
    if isinstance(raw_data, list):
        raw_data = {
            "pool_retry_count": 0,
            "pool_suspended_until": None,
            "tasks": raw_data,
        }

    if not isinstance(raw_data, dict):
        raise ValueError("Pool file must contain a JSON object or array")

    tasks_raw = raw_data.get("tasks", [])

    tasks = []
    existing_ids = set()
    
    for item in tasks_raw:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid task data: {item}")

        # Validate and auto-complete task fields
        # Required: prompt and directory
        if "prompt" not in item:
            raise KeyError(f"Missing required field 'prompt' in task: {item}")
        if "directory" not in item:
            raise KeyError(f"Missing required field 'directory' in task: {item}")
        
        # Auto-generate unique ID if missing
        if "id" not in item or not item["id"]:
            # Generate unique ID based on timestamp and UUID
            new_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            item["id"] = new_id
        
        # Ensure ID is unique
        while item["id"] in existing_ids:
            item["id"] = f"{item['id']}_{uuid.uuid4().hex[:4]}"
        existing_ids.add(item["id"])
        
        # Auto-initialize optional fields with defaults if missing
        if "args" not in item:
            item["args"] = []
        if "status" not in item:
            item["status"] = "pending"
        if "exit_code" not in item:
            item["exit_code"] = None
        if "duration_ms" not in item:
            item["duration_ms"] = None
        if "json_output" not in item:
            item["json_output"] = None
        if "retry_count" not in item:
            item["retry_count"] = 0

        tasks.append(Task.from_dict(item))

    suspended_until_raw = raw_data.get("pool_suspended_until")
    if suspended_until_raw:
        suspended_until = datetime.fromisoformat(suspended_until_raw)
    else:
        suspended_until = None

    # Load buckets (v2) or migrate from v1 (no buckets key → default main bucket)
    raw_buckets = raw_data.get("buckets", {})
    buckets: dict[str, Bucket] = {}
    if raw_buckets and isinstance(raw_buckets, dict):
        for bid, bdata in raw_buckets.items():
            if isinstance(bdata, dict):
                bdata = dict(bdata)
                bdata.setdefault("id", bid)
                buckets[bid] = Bucket.from_dict(bdata)
    if "main" not in buckets:
        buckets["main"] = Bucket(id="main", type="cli", label="CLI / Dashboard")

    return PoolState(
        retry_count=int(raw_data.get("pool_retry_count", 0)),
        suspended_until=suspended_until,
        tasks=tasks,
        pool_file=pool_file,
        buckets=buckets,
    )


def save_pool(state: PoolState) -> None:
    """Save pool state to a JSON file.

    Args:
        state: PoolState object to save
    """
    # Ensure parent directory exists
    state.pool_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "pool_retry_count": state.retry_count,
        "pool_suspended_until": state.suspended_until.isoformat() if state.suspended_until else None,
        "buckets": {bid: b.to_dict() for bid, b in state.buckets.items()},
        "tasks": [task.to_dict() for task in state.tasks],
    }
    content = json.dumps(data, indent=2, ensure_ascii=False)
    state.pool_file.write_text(content, encoding="utf-8")


def cleanup_old_tasks(state: PoolState, max_age_hours: int = 48) -> int:
    """Remove completed/failed tasks older than max_age_hours.
    
    Only removes tasks with status: success, failed, or skipped.
    Pending and running tasks are never removed.
    
    Args:
        state: PoolState object to clean
        max_age_hours: Maximum age in hours (default: 48)
    
    Returns:
        Number of tasks removed
    """
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    initial_count = len(state.tasks)
    
    # Keep tasks that are:
    # - pending or running (regardless of age)
    # - OR created within the max_age window
    state.tasks = [
        task for task in state.tasks
        if task.status in ("pending", "running", "rate_limit_retry")
        or datetime.fromisoformat(task.created_at) > cutoff_time
    ]
    
    removed_count = initial_count - len(state.tasks)
    
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} old tasks (older than {max_age_hours}h)")
        save_pool(state)
    
    return removed_count
