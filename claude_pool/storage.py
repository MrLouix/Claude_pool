"""Storage functions for loading and saving task pools."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import MAIN_BUCKET_LABEL, Bucket, PoolState, Task

logger = logging.getLogger(__name__)

# Tasks older than this threshold are eligible for automatic cleanup.
_DEFAULT_CLEANUP_AGE_HOURS = 48

# Active statuses that are never removed by cleanup regardless of age.
# Terminal statuses (success, failed, skipped, stopped) are intentionally
# excluded — they are eligible for 48-hour automatic cleanup.
_ACTIVE_STATUSES = frozenset({"pending", "running", "rate_limit_retry"})


def _apply_migrations(raw_data: Any) -> tuple[dict[str, Any], bool]:
    """Upgrade pool data to the current v2 format in-memory.

    Returns ``(data_dict, needs_save)`` where ``needs_save`` is True when the
    file should be rewritten on disk (i.e. it was in an older format).

    Handles:
    - v0: bare task list → wrapped v1 dict
    - v1: dict without a ``buckets`` key → v2 needs saving
    - v2: dict with ``buckets`` key → no migration needed
    """
    if isinstance(raw_data, list):
        # v0 → v1: promote bare task array to wrapped dict
        return {
            "pool_retry_count": 0,
            "pool_suspended_until": None,
            "tasks": raw_data,
        }, True
    if not isinstance(raw_data, dict):
        raise ValueError("Pool file must contain a JSON object or array")
    # v1 → v2: dict exists but lacks the buckets key
    return raw_data, "buckets" not in raw_data


def _load_buckets(raw_buckets: Any) -> dict[str, Bucket]:
    """Parse a raw buckets mapping and guarantee the 'main' bucket exists."""
    buckets: dict[str, Bucket] = {}
    if raw_buckets and isinstance(raw_buckets, dict):
        for bid, bdata in raw_buckets.items():
            if isinstance(bdata, dict):
                bdata = dict(bdata)
                bdata.setdefault("id", bid)
                buckets[bid] = Bucket.from_dict(bdata)
    if "main" not in buckets:
        buckets["main"] = Bucket(id="main", type="cli", label=MAIN_BUCKET_LABEL)
    return buckets


def _ensure_unique_id(item: dict[str, Any], existing_ids: set[str]) -> None:
    """Assign a unique task ID to *item*, modifying it in-place.

    Generates a new ID when one is missing; appends a short random suffix when
    the existing ID collides with a previously seen one.
    """
    if "id" not in item or not item["id"]:
        item["id"] = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    while item["id"] in existing_ids:
        item["id"] = f"{item['id']}_{uuid.uuid4().hex[:4]}"
    existing_ids.add(item["id"])


def _load_tasks(tasks_raw: list[Any]) -> list[Task]:
    """Validate and deserialise a raw task list.

    Raises:
        ValueError: if any item is not a dict.
        KeyError: if a required field (prompt, directory) is missing.
    """
    tasks: list[Task] = []
    existing_ids: set[str] = set()

    for item in tasks_raw:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid task data: {item}")
        if "prompt" not in item:
            raise KeyError(f"Missing required field 'prompt' in task: {item}")
        if "directory" not in item:
            raise KeyError(f"Missing required field 'directory' in task: {item}")

        _ensure_unique_id(item, existing_ids)
        tasks.append(Task.from_dict(item))

    return tasks


def load_pool(pool_file: Path) -> PoolState:
    """Load tasks and pool state from a JSON pool file.

    Supports both the wrapped format (dict with 'tasks' key) and the legacy
    bare-array format for backward compatibility.

    If the file doesn't exist or is empty, initialises it with an empty pool.

    Args:
        pool_file: Path to the pool.json file

    Returns:
        PoolState object containing tasks and pool metadata

    Raises:
        json.JSONDecodeError: If pool file contains invalid JSON
    """
    if not pool_file.exists():
        logger.info(f"Pool file not found, creating new empty pool: {pool_file}")
        state = PoolState(pool_file=pool_file)
        save_pool(state)
        return state

    content = pool_file.read_text(encoding="utf-8").strip()

    if not content:
        logger.info(f"Pool file is empty, initialising: {pool_file}")
        state = PoolState(pool_file=pool_file)
        save_pool(state)
        return state

    raw_data = json.loads(content)
    data, needs_save = _apply_migrations(raw_data)

    suspended_until_raw = data.get("pool_suspended_until")
    suspended_until = (
        datetime.fromisoformat(suspended_until_raw) if suspended_until_raw else None
    )

    state = PoolState(
        retry_count=int(data.get("pool_retry_count", 0)),
        suspended_until=suspended_until,
        tasks=_load_tasks(data.get("tasks", [])),
        pool_file=pool_file,
        buckets=_load_buckets(data.get("buckets", {})),
    )

    if needs_save:
        logger.info(f"Migrating pool file to v2 format: {pool_file}")
        save_pool(state)

    return state


def save_pool(state: PoolState) -> None:
    """Save pool state to a JSON file.

    Args:
        state: PoolState object to save
    """
    state.pool_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "pool_retry_count": state.retry_count,
        "pool_suspended_until": (
            state.suspended_until.isoformat() if state.suspended_until else None
        ),
        "buckets": {bid: b.to_dict() for bid, b in state.buckets.items()},
        "tasks": [task.to_dict() for task in state.tasks],
    }
    state.pool_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _should_keep_task(task: Task, cutoff_time: datetime) -> bool:
    """Return True when a task should be retained during cleanup.

    Active tasks (pending / running / rate_limit_retry) are always kept.
    Finished tasks are kept only when younger than the cutoff.
    """
    if task.status in _ACTIVE_STATUSES:
        return True
    return datetime.fromisoformat(task.created_at) > cutoff_time


def cleanup_old_tasks(state: PoolState, max_age_hours: int = _DEFAULT_CLEANUP_AGE_HOURS) -> int:
    """Remove finished tasks older than *max_age_hours* (default: 48 h).

    Only tasks with status ``success``, ``failed``, or ``skipped`` are
    eligible for removal.  Active tasks (pending / running / rate_limit_retry)
    are never removed regardless of age.

    Side-effect: writes the updated pool to disk when at least one task is
    removed.

    Args:
        state: PoolState object to clean
        max_age_hours: Maximum age in hours before a finished task is removed

    Returns:
        Number of tasks removed
    """
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    initial_count = len(state.tasks)

    state.tasks = [t for t in state.tasks if _should_keep_task(t, cutoff_time)]

    removed_count = initial_count - len(state.tasks)
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} old tasks (older than {max_age_hours}h)")
        save_pool(state)

    return removed_count
