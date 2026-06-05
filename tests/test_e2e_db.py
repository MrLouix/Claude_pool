"""End-to-end smoke tests for the SQLite-backed pool (step 5/5)."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from team_cli.database import DatabaseManager
from team_cli.executor import TaskExecutor
from team_cli.models import PoolState, Task
from team_cli.storage import cleanup_old_tasks, load_pool, save_pool


# ---------------------------------------------------------------------------
# test_full_pool_lifecycle
# ---------------------------------------------------------------------------


def test_full_pool_lifecycle(tmp_path: Path) -> None:
    """Complete lifecycle: init → load (empty) → save tasks → reload → cleanup."""
    pool_file = tmp_path / "pool.db"

    # 1. Create DB via DatabaseManager.init() (idempotent)
    asyncio.run(_init_db(pool_file))
    assert pool_file.exists()

    # 2. Instantiate executor, load tasks (empty pool — must not raise)
    with (
        patch("team_cli.executor.TaskExecutor.run_pool"),
        patch("team_cli.executor.signal.signal"),
    ):
        ex = TaskExecutor(pool_file, install_signal_handlers=False)
        asyncio.run(ex.load_tasks())

    assert ex.pool.tasks == []

    # 3. Save two pending tasks
    old_ts = (datetime.now() - timedelta(hours=72)).isoformat()
    task_a = Task(id="task_a", prompt="Task A", directory=Path("/tmp"), created_at=old_ts)
    task_b = Task(id="task_b", prompt="Task B", directory=Path("/tmp"))
    state = PoolState(tasks=[task_a, task_b], pool_file=pool_file)
    save_pool(state)

    # 4. Reload — both tasks present with correct fields
    loaded = load_pool(pool_file)
    assert len(loaded.tasks) == 2
    ids = {t.id for t in loaded.tasks}
    assert "task_a" in ids
    assert "task_b" in ids
    loaded_a = next(t for t in loaded.tasks if t.id == "task_a")
    assert loaded_a.prompt == "Task A"

    # 5. Cleanup: mark task_a as success (old) — should be removed
    loaded_a.status = "success"  # type: ignore[assignment]
    save_pool(loaded)
    removed = cleanup_old_tasks(loaded, max_age_hours=48)
    assert removed == 1
    remaining_ids = {t.id for t in loaded.tasks}
    assert "task_a" not in remaining_ids
    assert "task_b" in remaining_ids

    # 6. Verify DB file exists and no pool.json was created
    assert pool_file.exists()
    assert not (tmp_path / "pool.json").exists()


async def _init_db(pool_file: Path) -> None:
    db = DatabaseManager(pool_file)
    await db.init()


# ---------------------------------------------------------------------------
# test_migration_from_json_e2e
# ---------------------------------------------------------------------------


def test_migration_from_json_e2e(tmp_path: Path) -> None:
    """JSON → SQLite migration: load_pool on a .db path migrates pool.json automatically."""
    json_path = tmp_path / "pool.json"
    db_path = tmp_path / "pool.db"

    # 1. Write a minimal valid pool.json with one task
    pool_data = {
        "pool_retry_count": 0,
        "pool_suspended_until": None,
        "provider": "claude",
        "buckets": {
            "main": {
                "id": "main",
                "type": "cli",
                "label": "CLI / Dashboard",
                "created_at": "2025-01-01T00:00:00",
            }
        },
        "tasks": [
            {
                "id": "migrated_task",
                "prompt": "Migrated from JSON",
                "directory": "/tmp",
                "args": [],
                "status": "pending",
                "exit_code": None,
                "duration_ms": None,
                "json_output": None,
                "retry_count": 0,
                "created_at": "2025-06-01T10:00:00",
                "session_id": None,
                "bucket_id": "main",
                "priority": 2,
            }
        ],
    }
    json_path.write_text(json.dumps(pool_data), encoding="utf-8")

    # 2. Call load_pool pointing at .db path — triggers migration
    loaded = load_pool(db_path)

    # 3. pool.db created, pool.json renamed to .bak, original gone
    assert db_path.exists()
    assert (tmp_path / "pool.json.bak").exists()
    assert not json_path.exists()

    # 4. Task from original JSON is present
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].id == "migrated_task"
    assert loaded.tasks[0].prompt == "Migrated from JSON"
