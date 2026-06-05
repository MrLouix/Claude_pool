"""Tests for data models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from team_cli.models import MAIN_BUCKET_LABEL, Task, _coerce_int, _coerce_optional_int


def test_task_creation():
    """Test basic Task creation."""
    task = Task(
        id="task_001",
        prompt="Fix bug",
        directory=Path("/home/user/project"),
        args=["--model", "sonnet-4"],
    )

    assert task.id == "task_001"
    assert task.prompt == "Fix bug"
    assert task.directory == Path("/home/user/project")
    assert task.args == ["--model", "sonnet-4"]
    assert task.status == "pending"
    assert task.exit_code is None
    assert task.duration_ms is None
    assert task.json_output is None
    assert task.retry_count == 0


def test_task_from_dict_minimal():
    """Test Task creation from minimal dict."""
    data = {
        "id": "task_001",
        "prompt": "Fix bug",
        "directory": "/home/user/project",
    }

    task = Task.from_dict(data)

    assert task.id == "task_001"
    assert task.prompt == "Fix bug"
    assert task.directory == Path("/home/user/project")
    assert task.args == []
    assert task.status == "pending"


def test_task_from_dict_complete():
    """Test Task creation from complete dict."""
    data = {
        "id": "task_002",
        "prompt": "Review code",
        "directory": "/home/user/project",
        "args": ["--model", "opus-4"],
        "status": "success",
        "exit_code": 0,
        "duration_ms": 5000,
        "json_output": {"result": "Code reviewed"},
        "retry_count": 2,
    }

    task = Task.from_dict(data)

    assert task.id == "task_002"
    assert task.status == "success"
    assert task.exit_code == 0
    assert task.duration_ms == 5000
    assert task.json_output == {"result": "Code reviewed"}
    assert task.retry_count == 2


def test_task_to_dict():
    """Test Task serialization to dict."""
    task = Task(
        id="task_003",
        prompt="Deploy app",
        directory=Path("/opt/app"),
        args=["--verbose"],
        status="running",
        exit_code=None,
        duration_ms=None,
    )

    result = task.to_dict()

    assert result["id"] == "task_003"
    assert result["prompt"] == "Deploy app"
    assert result["directory"] == "/opt/app"
    assert result["args"] == ["--verbose"]
    assert result["status"] == "running"
    assert result["exit_code"] is None
    assert result["duration_ms"] is None


def test_task_roundtrip():
    """Test that from_dict(to_dict()) preserves all data."""
    original = Task(
        id="task_004",
        prompt="Test roundtrip",
        directory=Path("/tmp/test"),
        args=["--test"],
        status="failed",
        exit_code=1,
        duration_ms=3000,
        json_output={"error": "Something went wrong"},
        retry_count=3,
    )

    data = original.to_dict()
    restored = Task.from_dict(data)

    assert restored.id == original.id
    assert restored.prompt == original.prompt
    assert restored.directory == original.directory
    assert restored.args == original.args
    assert restored.status == original.status
    assert restored.exit_code == original.exit_code
    assert restored.duration_ms == original.duration_ms
    assert restored.json_output == original.json_output
    assert restored.retry_count == original.retry_count


# ── Priority tests ─────────────────────────────────────────────────────────────

def test_task_priority_defaults_to_2():
    task = Task(id="t1", prompt="p", directory=Path("/tmp"))
    assert task.priority == 2


def test_task_from_dict_priority_explicit():
    data = {"id": "t2", "prompt": "p", "directory": "/tmp", "priority": 1}
    task = Task.from_dict(data)
    assert task.priority == 1


def test_task_from_dict_priority_missing_defaults_to_2():
    """Loading a pool.json entry without a priority key yields priority=2."""
    data = {"id": "t3", "prompt": "p", "directory": "/tmp"}
    task = Task.from_dict(data)
    assert task.priority == 2


def test_task_to_dict_includes_priority():
    task = Task(id="t4", prompt="p", directory=Path("/tmp"), priority=3)
    d = task.to_dict()
    assert d["priority"] == 3


def test_task_roundtrip_preserves_priority():
    """Saving and reloading a task preserves its priority."""
    original = Task(id="t5", prompt="p", directory=Path("/tmp"), priority=1)
    restored = Task.from_dict(original.to_dict())
    assert restored.priority == 1


def test_task_input_priority_validation():
    """Pydantic TaskInput rejects priority values outside [1, 2, 3]."""
    from team_cli.api import TaskInput

    assert TaskInput(prompt="p", priority=1).priority == 1
    assert TaskInput(prompt="p", priority=2).priority == 2
    assert TaskInput(prompt="p", priority=3).priority == 3
    assert TaskInput(prompt="p").priority == 2  # default

    with pytest.raises(ValidationError):
        TaskInput(prompt="p", priority=0)
    with pytest.raises(ValidationError):
        TaskInput(prompt="p", priority=4)


def test_task_patch_input_priority_validation():
    """Pydantic TaskPatchInput rejects priority values outside [1, 2, 3]."""
    from team_cli.api import TaskPatchInput

    assert TaskPatchInput(priority=None).priority is None  # optional
    assert TaskPatchInput(priority=1).priority == 1

    with pytest.raises(ValidationError):
        TaskPatchInput(priority=5)


def test_message_input_priority_validation():
    """Pydantic MessageInput rejects priority values outside [1, 2, 3]."""
    from team_cli.api import MessageInput

    assert MessageInput(prompt="p").priority == 2  # default
    assert MessageInput(prompt="p", priority=3).priority == 3

    with pytest.raises(ValidationError):
        MessageInput(prompt="p", priority=0)


# ── Helper function tests ──────────────────────────────────────────────────────


def test_main_bucket_label_constant():
    assert MAIN_BUCKET_LABEL == "CLI / Dashboard"


def test_coerce_int_with_none_returns_default():
    assert _coerce_int(None, 0) == 0
    assert _coerce_int(None, 2) == 2


def test_coerce_int_with_value_converts_to_int():
    assert _coerce_int(5, 0) == 5
    assert _coerce_int("3", 0) == 3
    assert _coerce_int(1.9, 0) == 1


def test_coerce_int_default_not_used_when_value_present():
    assert _coerce_int(0, 99) == 0


def test_coerce_optional_int_with_none_returns_none():
    assert _coerce_optional_int(None) is None


def test_coerce_optional_int_with_value_converts_to_int():
    assert _coerce_optional_int(0) == 0
    assert _coerce_optional_int(42) == 42
    assert _coerce_optional_int("7") == 7


def test_task_from_dict_handles_explicit_null_retry_count():
    """Explicit null retry_count in JSON falls back to 0 via _coerce_int."""
    data = {"id": "t", "prompt": "p", "directory": "/tmp", "retry_count": None}
    task = Task.from_dict(data)
    assert task.retry_count == 0


def test_task_from_dict_handles_explicit_null_priority():
    """Explicit null priority in JSON falls back to 2 via _coerce_int."""
    data = {"id": "t", "prompt": "p", "directory": "/tmp", "priority": None}
    task = Task.from_dict(data)
    assert task.priority == 2


def test_task_from_dict_handles_explicit_null_exit_code():
    """Explicit null exit_code stays None via _coerce_optional_int."""
    data = {"id": "t", "prompt": "p", "directory": "/tmp", "exit_code": None}
    task = Task.from_dict(data)
    assert task.exit_code is None


def test_task_from_dict_handles_explicit_null_duration_ms():
    """Explicit null duration_ms stays None via _coerce_optional_int."""
    data = {"id": "t", "prompt": "p", "directory": "/tmp", "duration_ms": None}
    task = Task.from_dict(data)
    assert task.duration_ms is None


# ── stopped status ────────────────────────────────────────────────────────────


def test_task_accepts_stopped_status():
    task = Task(id="t", prompt="p", directory=Path("/tmp"), status="stopped")
    assert task.status == "stopped"


def test_task_from_dict_accepts_stopped_status():
    data = {"id": "t", "prompt": "p", "directory": "/tmp", "status": "stopped"}
    task = Task.from_dict(data)
    assert task.status == "stopped"


def test_task_to_dict_preserves_stopped_status():
    task = Task(id="t", prompt="p", directory=Path("/tmp"), status="stopped")
    assert task.to_dict()["status"] == "stopped"
