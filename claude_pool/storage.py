"""Storage functions for loading and saving task pools."""

import json
from pathlib import Path

from .models import Task


def load_pool(pool_file: Path) -> list[Task]:
    """Load tasks from a JSON pool file.

    Args:
        pool_file: Path to the pool.json file

    Returns:
        List of Task objects

    Raises:
        FileNotFoundError: If pool file doesn't exist
        json.JSONDecodeError: If pool file contains invalid JSON
        KeyError: If required fields are missing
    """
    if not pool_file.exists():
        raise FileNotFoundError(f"Pool file not found: {pool_file}")

    content = pool_file.read_text(encoding="utf-8")
    raw_data = json.loads(content)

    if not isinstance(raw_data, list):
        raise ValueError("Pool file must contain a JSON array")

    tasks = []
    for item in raw_data:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid task data: {item}")

        # Validate required fields
        required_fields = ["id", "prompt", "directory"]
        for field in required_fields:
            if field not in item:
                raise KeyError(
                    f"Missing required field '{field}' in task: {item.get('id', 'unknown')}"
                )

        tasks.append(Task.from_dict(item))

    return tasks


def save_pool(pool_file: Path, tasks: list[Task]) -> None:
    """Save tasks to a JSON pool file.

    Args:
        pool_file: Path to the pool.json file
        tasks: List of Task objects to save
    """
    # Ensure parent directory exists
    pool_file.parent.mkdir(parents=True, exist_ok=True)

    data = [task.to_dict() for task in tasks]
    content = json.dumps(data, indent=2, ensure_ascii=False)
    pool_file.write_text(content, encoding="utf-8")
