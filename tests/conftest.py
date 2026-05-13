"""Pytest configuration and shared fixtures for tests."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

from claude_pool.executor import TaskExecutor
from claude_pool.models import PoolState, Task


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file."""
    return tmp_path / "test_pool.json"


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task."""
    return Task(
        id="task_20260513_100000_aaaaaaaa",
        prompt="Test task prompt",
        directory=Path("/tmp"),
        args=["--model", "haiku", "--effort", "low"],
        status="pending",
    )


@pytest.fixture
def multiple_tasks() -> list[Task]:
    """Create multiple tasks with different statuses."""
    return [
        Task(
            id="task_20260513_100000_aaaaaaaa",
            prompt="First task",
            directory=Path("/tmp"),
            args=["--model", "haiku"],
            status="pending",
        ),
        Task(
            id="task_20260513_100100_bbbbbbbb",
            prompt="Second task",
            directory=Path("/home"),
            args=["--model", "sonnet"],
            status="running",
        ),
        Task(
            id="task_20260513_100200_cccccccc",
            prompt="Third task - successfully completed",
            directory=Path("/opt"),
            args=["--effort", "high"],
            status="success",
            exit_code=0,
            duration_ms=5000,
            json_output={"result": "Task completed", "tokens_used": 1000},
        ),
        Task(
            id="task_20260513_100300_dddddddd",
            prompt="Fourth task - failed",
            directory=Path("/var"),
            args=[],
            status="failed",
            exit_code=1,
            duration_ms=2000,
            json_output={"error": "Something went wrong"},
        ),
    ]


@pytest.fixture
def pool_file_with_tasks(temp_pool_file: Path, multiple_tasks: list[Task]) -> Path:
    """Create a pool file with test tasks."""
    pool_data = {
        "pool_retry_count": 0,
        "pool_suspended_until": None,
        "tasks": [task.to_dict() for task in multiple_tasks],
    }

    with open(temp_pool_file, "w") as f:
        json.dump(pool_data, f)

    return temp_pool_file


@pytest.fixture
def empty_pool_file(temp_pool_file: Path) -> Path:
    """Create an empty pool file."""
    pool_data = {
        "pool_retry_count": 0,
        "pool_suspended_until": None,
        "tasks": [],
    }

    with open(temp_pool_file, "w") as f:
        json.dump(pool_data, f)

    return temp_pool_file


@pytest.fixture
def mock_executor(temp_pool_file: Path, multiple_tasks: list[Task]) -> MagicMock:
    """Create a mock TaskExecutor."""
    executor = MagicMock(spec=TaskExecutor)
    executor.pool_file = temp_pool_file
    executor.paused = False
    executor.should_stop = False
    executor.current_task = None
    executor.on_task_update = None

    # Create a real PoolState with test tasks
    pool = PoolState(tasks=multiple_tasks, pool_file=temp_pool_file)
    executor.pool = pool

    # Mock async methods
    executor.load_tasks = AsyncMock()
    executor.run_pool = AsyncMock()
    executor.execute_task = AsyncMock()

    # Mock sync methods
    executor.pause = MagicMock()
    executor.resume = MagicMock()
    executor.delete_task = MagicMock(return_value=True)
    executor._save_state = MagicMock()

    return executor


@pytest.fixture
def mock_executor_empty(temp_pool_file: Path) -> MagicMock:
    """Create a mock TaskExecutor with no tasks."""
    executor = MagicMock(spec=TaskExecutor)
    executor.pool_file = temp_pool_file
    executor.paused = False
    executor.should_stop = False
    executor.current_task = None
    executor.on_task_update = None

    pool = PoolState(tasks=[], pool_file=temp_pool_file)
    executor.pool = pool

    executor.load_tasks = AsyncMock()
    executor.run_pool = AsyncMock()
    executor.execute_task = AsyncMock()
    executor.pause = MagicMock()
    executor.resume = MagicMock()
    executor.delete_task = MagicMock(return_value=True)
    executor._save_state = MagicMock()

    return executor
