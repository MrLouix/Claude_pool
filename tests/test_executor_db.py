"""Tests for DB-based change detection in TaskExecutor (step 3/5)."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from team_cli.database import DatabaseManager
from team_cli.executor import TaskExecutor, _meta_hash
from team_cli.models import PoolState, Task
from team_cli.storage import save_pool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(task_id: str, status: str = "pending") -> Task:
    return Task(
        id=task_id,
        prompt=f"Prompt for {task_id}",
        directory=Path("/tmp/project"),
        status=status,  # type: ignore[arg-type]
    )


def _executor(pool_file: Path) -> TaskExecutor:
    return TaskExecutor(pool_file, install_signal_handlers=False)


async def _seed_db(pool_file: Path, tasks: list[Task]) -> None:
    """Write tasks directly to DB using DatabaseManager (bypasses executor)."""
    db = DatabaseManager(pool_file)
    await db.init()
    for t in tasks:
        await db.upsert_task(t.to_dict())


# ---------------------------------------------------------------------------
# check_pool_updates — new task detection
# ---------------------------------------------------------------------------

def test_check_pool_updates_detects_new_task(tmp_path: Path) -> None:
    """A task added to the DB externally is picked up by check_pool_updates."""
    pool_file = tmp_path / "pool.db"
    task_a = _make_task("task_a")

    # Bootstrap DB with task_a and create executor that knows about task_a
    state = PoolState(tasks=[task_a], pool_file=pool_file)
    save_pool(state)

    ex = _executor(pool_file)
    ex.pool = state
    ex._last_known_task_ids = {"task_a"}
    ex._last_pool_meta_hash = _meta_hash(state)

    # Externally add task_b directly to DB
    task_b = _make_task("task_b")
    asyncio.run(_seed_db(pool_file, [task_b]))

    # check_pool_updates should detect task_b and merge it
    ex.check_pool_updates()

    ids = {t.id for t in ex.pool.tasks}
    assert "task_b" in ids


def test_check_pool_updates_calls_on_task_update_for_new_task(tmp_path: Path) -> None:
    """on_task_update callback is invoked for each newly detected task."""
    pool_file = tmp_path / "pool.db"
    task_a = _make_task("task_a")

    state = PoolState(tasks=[task_a], pool_file=pool_file)
    save_pool(state)

    callback = MagicMock()
    ex = _executor(pool_file)
    ex.pool = state
    ex.on_task_update = callback
    ex._last_known_task_ids = {"task_a"}
    ex._last_pool_meta_hash = _meta_hash(state)

    task_b = _make_task("task_b")
    asyncio.run(_seed_db(pool_file, [task_b]))

    ex.check_pool_updates()

    # Callback must have been called at least once with task_b
    called_ids = {call.args[0].id for call in callback.call_args_list}
    assert "task_b" in called_ids


def test_check_pool_updates_no_spurious_reload_after_save(tmp_path: Path) -> None:
    """After executor saves state, check_pool_updates must NOT trigger on_task_update."""
    pool_file = tmp_path / "pool.db"
    task = _make_task("task_x", status="success")

    ex = _executor(pool_file)
    callback = MagicMock()
    ex.on_task_update = callback
    ex.pool = PoolState(tasks=[task], pool_file=pool_file)

    # Simulate executor saving (stamps tracking hashes)
    ex._do_save()

    # Reset callback to isolate the check_pool_updates call
    callback.reset_mock()

    # No external change — callback must NOT be called
    ex.check_pool_updates()

    callback.assert_not_called()


def test_check_pool_updates_detects_pool_meta_change(tmp_path: Path) -> None:
    """A suspended_until change written externally to the DB is picked up."""
    pool_file = tmp_path / "pool.db"

    state = PoolState(tasks=[], pool_file=pool_file, retry_count=0)
    save_pool(state)

    ex = _executor(pool_file)
    ex.pool = state
    ex._last_known_task_ids = set()
    ex._last_pool_meta_hash = _meta_hash(state)

    # Externally update suspended_until in DB
    future_time = (datetime.now() + timedelta(hours=1)).isoformat()

    async def _update_meta() -> None:
        db = DatabaseManager(pool_file)
        await db.init()
        await db.set_pool_meta(
            retry_count=2,
            suspended_until=future_time,
            provider="claude",
        )

    asyncio.run(_update_meta())

    ex.check_pool_updates()

    assert ex.pool.retry_count == 2


def test_check_pool_updates_stamps_tracking_after_change(tmp_path: Path) -> None:
    """Tracking hashes are updated after detecting an external change."""
    pool_file = tmp_path / "pool.db"

    state = PoolState(tasks=[], pool_file=pool_file)
    save_pool(state)

    ex = _executor(pool_file)
    ex.pool = state
    ex._last_known_task_ids = set()
    ex._last_pool_meta_hash = ""  # Force change detection

    ex.check_pool_updates()

    # After detection the hashes must be non-empty
    assert ex._last_pool_meta_hash != ""


def test_check_pool_updates_no_change_leaves_hashes_unchanged(tmp_path: Path) -> None:
    """When nothing changes, tracking hashes are not mutated."""
    pool_file = tmp_path / "pool.db"
    task = _make_task("t1")

    state = PoolState(tasks=[task], pool_file=pool_file)
    save_pool(state)

    ex = _executor(pool_file)
    ex.pool = state
    ex._do_save()  # stamp hashes to match DB

    before_ids = frozenset(ex._last_known_task_ids)
    before_hash = ex._last_pool_meta_hash

    ex.check_pool_updates()  # nothing changed

    assert ex._last_known_task_ids == before_ids
    assert ex._last_pool_meta_hash == before_hash


# ---------------------------------------------------------------------------
# _meta_hash helper
# ---------------------------------------------------------------------------

def test_meta_hash_changes_on_retry_count() -> None:
    s1 = PoolState(retry_count=0)
    s2 = PoolState(retry_count=1)
    assert _meta_hash(s1) != _meta_hash(s2)


def test_meta_hash_changes_on_suspended_until() -> None:
    s1 = PoolState(suspended_until=None)
    s2 = PoolState(suspended_until=datetime.fromisoformat("2025-06-15T22:45:00"))
    assert _meta_hash(s1) != _meta_hash(s2)


def test_meta_hash_same_for_identical_state() -> None:
    s1 = PoolState(retry_count=2, suspended_until=None)
    s2 = PoolState(retry_count=2, suspended_until=None)
    assert _meta_hash(s1) == _meta_hash(s2)


# ---------------------------------------------------------------------------
# load_tasks stamps tracking hashes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_tasks_stamps_tracking_hashes(tmp_path: Path) -> None:
    """load_tasks() initialises tracking hashes so the first check_pool_updates
    call does not misidentify the initial DB state as an external change."""
    pool_file = tmp_path / "pool.db"
    task = _make_task("t_init")
    state = PoolState(tasks=[task], pool_file=pool_file)
    save_pool(state)

    callback = MagicMock()
    ex = _executor(pool_file)
    ex.on_task_update = callback

    await ex.load_tasks()

    # Hashes must be set after load
    assert "t_init" in ex._last_known_task_ids
    assert ex._last_pool_meta_hash != ""

    # First check_pool_updates must not fire callback (no external change)
    callback.reset_mock()
    ex.check_pool_updates()
    callback.assert_not_called()


# ---------------------------------------------------------------------------
# Executor init — no mtime attributes
# ---------------------------------------------------------------------------

def test_executor_has_no_mtime_attributes(tmp_path: Path) -> None:
    """Ensure legacy mtime tracking attributes are fully removed."""
    ex = _executor(tmp_path / "pool.db")
    assert not hasattr(ex, "last_pool_mtime")
    assert not hasattr(ex, "_last_save_mtime")


def test_executor_has_db_tracking_attributes(tmp_path: Path) -> None:
    ex = _executor(tmp_path / "pool.db")
    assert hasattr(ex, "_last_known_task_ids")
    assert hasattr(ex, "_last_pool_meta_hash")
    assert ex._last_known_task_ids == set()
    assert ex._last_pool_meta_hash == ""
