"""Storage functions for loading and saving task pools."""

import json
from datetime import datetime
from pathlib import Path

from .models import PoolState, Task


def load_pool(pool_file: Path) -> PoolState:
    """Load tasks and pool state from a JSON pool file.

    Supports both the wrapped format (dict with 'tasks' key) and the legacy
    bare-array format for backward compatibility.

    Args:
        pool_file: Path to the pool.json file

    Returns:
        PoolState object containing tasks and pool metadata

    Raises:
        FileNotFoundError: If pool file doesn't exist
        json.JSONDecodeError: If pool file contains invalid JSON
    """
    if not pool_file.exists():
        raise FileNotFoundError(f"Pool file not found: {pool_file}")

    content = pool_file.read_text(encoding="utf-8")
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
    for item in tasks_raw:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid task data: {item}")

        required_fields = ["id", "prompt", "directory"]
        for field in required_fields:
            if field not in item:
                raise KeyError(
                    f"Missing required field '{field}' in task: {item.get('id', 'unknown')}"
                )

        tasks.append(Task.from_dict(item))

    suspended_until_raw = raw_data.get("pool_suspended_until")
    if suspended_until_raw:
        suspended_until = datetime.fromisoformat(suspended_until_raw)
    else:
        suspended_until = None

    return PoolState(
        retry_count=int(raw_data.get("pool_retry_count", 0)),
        suspended_until=suspended_until,
        tasks=tasks,
        pool_file=pool_file,
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
        "tasks": [task.to_dict() for task in state.tasks],
    }
    content = json.dumps(data, indent=2, ensure_ascii=False)
    state.pool_file.write_text(content, encoding="utf-8")
