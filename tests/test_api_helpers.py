"""Unit tests for api.py helper functions and api_models.py."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from team_cli.api import _compute_pool_status, _generate_task_id, _is_allowed_path
from team_cli.api_models import (
    MessageInput,
    ProjectEntry,
    ProjectInput,
    TaskInput,
    TaskPatchInput,
    _validate_priority,
)
from team_cli.models import PoolState, Task

# ── _is_allowed_path ──────────────────────────────────────────────


def test_is_allowed_home_path():
    assert _is_allowed_path(Path("/home/user/project")) is True


def test_is_allowed_mnt_path():
    assert _is_allowed_path(Path("/mnt/c/Users")) is True


def test_is_disallowed_etc():
    assert _is_allowed_path(Path("/etc/passwd")) is False


def test_is_disallowed_tmp():
    assert _is_allowed_path(Path("/tmp/work")) is False


def test_is_disallowed_root():
    assert _is_allowed_path(Path("/")) is False


# ── _generate_task_id ─────────────────────────────────────────────


def test_generate_task_id_format():
    task_id = _generate_task_id()
    assert task_id.startswith("task_")
    parts = task_id.split("_")
    # task_YYYYMMDD_HHMMSS_<8hex>  → 4 parts after split on _
    assert len(parts) == 4
    assert len(parts[3]) == 8  # 8 hex chars


def test_generate_task_id_unique():
    ids = {_generate_task_id() for _ in range(50)}
    assert len(ids) == 50


# ── _validate_priority ────────────────────────────────────────────


def test_validate_priority_accepts_1_through_5():
    for i in range(1, 6):
        assert _validate_priority(i) == i


def test_validate_priority_rejects_0():
    with pytest.raises(ValueError, match="priority"):
        _validate_priority(0)


def test_validate_priority_rejects_6():
    with pytest.raises(ValueError, match="priority"):
        _validate_priority(6)


# ── ProjectEntry and ProjectInput ────────────────────────────────


def test_project_entry_has_required_fields():
    p = ProjectEntry(id="proj_1", name="foo", directory="/home/x", created_at="2026-01-01T00:00:00")
    assert p.name == "foo"
    assert p.id == "proj_1"


def test_project_input_has_required_fields():
    p = ProjectInput(name="bar", directory="/home/x")
    assert p.name == "bar"


# ── TaskInput priority validator ──────────────────────────────────


def test_task_input_priority_default():
    assert TaskInput(prompt="p").priority == 2


def test_task_input_priority_1():
    assert TaskInput(prompt="p", priority=1).priority == 1


def test_task_input_priority_invalid():
    with pytest.raises(ValidationError):
        TaskInput(prompt="p", priority=6)


# ── MessageInput priority validator ──────────────────────────────


def test_message_input_priority_default():
    assert MessageInput(prompt="p").priority == 2


def test_message_input_priority_invalid():
    with pytest.raises(ValidationError):
        MessageInput(prompt="p", priority=0)


# ── TaskPatchInput priority validator ────────────────────────────


def test_task_patch_input_priority_none_is_allowed():
    assert TaskPatchInput(priority=None).priority is None


def test_task_patch_input_priority_invalid():
    with pytest.raises(ValidationError):
        TaskPatchInput(priority=6)


# ── _compute_pool_status ─────────────────────────────────────────


def _make_pool(tasks: list[Task], suspended_until=None, retry_count: int = 0) -> PoolState:
    pool = PoolState(tasks=tasks, pool_file=Path("pool.json"))
    pool.suspended_until = suspended_until
    pool.retry_count = retry_count
    return pool


def _task(status: str, json_output=None) -> Task:
    return Task(id="t", prompt="p", directory=Path("/tmp"), status=status, json_output=json_output)


def test_compute_status_waiting_when_no_tasks():
    pool = _make_pool([])
    s = _compute_pool_status(pool)
    assert s.claude_status == "waiting request"
    assert s.total_tasks == 0
    assert s.pool_suspended is False


def test_compute_status_running_when_pending():
    pool = _make_pool([_task("pending")])
    s = _compute_pool_status(pool)
    assert s.claude_status == "running"
    assert s.pending_tasks == 1


def test_compute_status_running_when_running():
    pool = _make_pool([_task("running")])
    s = _compute_pool_status(pool)
    assert s.claude_status == "running"
    assert s.running_tasks == 1


def test_compute_status_rate_limit_by_task():
    pool = _make_pool([_task("rate_limit_retry", {"result": "hit your limit"})])
    s = _compute_pool_status(pool)
    assert s.claude_status == "rate_limit"
    assert s.rate_limit_result == "hit your limit"


def test_compute_status_rate_limit_no_json_output():
    t = _task("rate_limit_retry")
    t.json_output = None
    pool = _make_pool([t])
    s = _compute_pool_status(pool)
    assert s.claude_status == "rate_limit"
    assert s.rate_limit_result == "Rate limit detected"


def test_compute_status_suspended():
    pool = _make_pool([], suspended_until=datetime.now() + timedelta(hours=1))
    s = _compute_pool_status(pool)
    assert s.claude_status == "rate_limit"
    assert s.pool_suspended is True
    assert s.suspension_remaining > 0


def test_compute_status_counts_all_statuses():
    tasks = [
        _task("pending"),
        _task("running"),
        _task("success"),
        _task("failed"),
        _task("skipped"),
    ]
    s = _compute_pool_status(_make_pool(tasks))
    assert s.total_tasks == 5
    assert s.pending_tasks == 1
    assert s.running_tasks == 1
    assert s.completed_tasks == 1
    assert s.failed_tasks == 1
    assert s.skipped_tasks == 1


def test_compute_status_retry_count_propagated():
    pool = _make_pool([], retry_count=3)
    s = _compute_pool_status(pool)
    assert s.retry_count == 3
