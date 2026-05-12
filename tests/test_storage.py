"""Tests for storage functions."""

import json
from pathlib import Path

import pytest

from claude_pool.models import Task
from claude_pool.storage import load_pool, save_pool


@pytest.fixture
def temp_pool_file(tmp_path: Path) -> Path:
    """Create a temporary pool file path."""
    return tmp_path / "test_pool.json"


@pytest.fixture
def sample_pool_data() -> list[dict]:
    """Sample pool data for testing."""
    return [
        {
            "id": "task_001",
            "prompt": "Fix login bug",
            "directory": "/home/user/project",
            "args": ["--model", "sonnet-4"],
            "status": "pending",
            "exit_code": None,
            "duration_ms": None,
            "json_output": None,
            "retry_count": 0,
        },
        {
            "id": "task_002",
            "prompt": "Review code",
            "directory": "/home/user/project",
            "args": [],
            "status": "success",
            "exit_code": 0,
            "duration_ms": 5000,
            "json_output": {"result": "Code reviewed"},
            "retry_count": 0,
        },
    ]


def test_save_pool(temp_pool_file: Path):
    """Test saving tasks to a pool file."""
    tasks = [
        Task(
            id="task_001",
            prompt="Test task",
            directory=Path("/tmp/test"),
            args=["--verbose"],
        ),
        Task(
            id="task_002",
            prompt="Another task",
            directory=Path("/tmp/test2"),
            status="success",
            exit_code=0,
        ),
    ]

    save_pool(temp_pool_file, tasks)

    assert temp_pool_file.exists()

    # Verify JSON content
    content = json.loads(temp_pool_file.read_text())
    assert isinstance(content, list)
    assert len(content) == 2
    assert content[0]["id"] == "task_001"
    assert content[1]["status"] == "success"


def test_load_pool(temp_pool_file: Path, sample_pool_data: list[dict]):
    """Test loading tasks from a pool file."""
    temp_pool_file.write_text(json.dumps(sample_pool_data, indent=2))

    tasks = load_pool(temp_pool_file)

    assert len(tasks) == 2
    assert tasks[0].id == "task_001"
    assert tasks[0].prompt == "Fix login bug"
    assert tasks[0].status == "pending"
    assert tasks[1].id == "task_002"
    assert tasks[1].status == "success"
    assert tasks[1].exit_code == 0


def test_load_pool_file_not_found(temp_pool_file: Path):
    """Test loading from non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_pool(temp_pool_file)


def test_load_pool_invalid_json(temp_pool_file: Path):
    """Test loading invalid JSON raises JSONDecodeError."""
    temp_pool_file.write_text("invalid json {")

    with pytest.raises(json.JSONDecodeError):
        load_pool(temp_pool_file)


def test_load_pool_not_array(temp_pool_file: Path):
    """Test loading non-array JSON raises ValueError."""
    temp_pool_file.write_text('{"id": "task_001"}')

    with pytest.raises(ValueError, match="must contain a JSON array"):
        load_pool(temp_pool_file)


def test_load_pool_missing_required_field(temp_pool_file: Path):
    """Test loading task with missing required field raises KeyError."""
    invalid_data = [
        {
            "id": "task_001",
            # Missing "prompt" and "directory"
        }
    ]
    temp_pool_file.write_text(json.dumps(invalid_data))

    with pytest.raises(KeyError, match="Missing required field"):
        load_pool(temp_pool_file)


def test_save_load_roundtrip(temp_pool_file: Path):
    """Test that saving and loading preserves all task data."""
    original_tasks = [
        Task(
            id="task_001",
            prompt="Roundtrip test",
            directory=Path("/home/user/app"),
            args=["--test", "--verbose"],
            status="running",
            exit_code=None,
            duration_ms=None,
            json_output=None,
            retry_count=1,
        ),
        Task(
            id="task_002",
            prompt="Completed task",
            directory=Path("/opt/service"),
            args=[],
            status="success",
            exit_code=0,
            duration_ms=8500,
            json_output={"result": "Success", "tokens_used": 1500},
            retry_count=0,
        ),
    ]

    save_pool(temp_pool_file, original_tasks)
    loaded_tasks = load_pool(temp_pool_file)

    assert len(loaded_tasks) == len(original_tasks)

    for original, loaded in zip(original_tasks, loaded_tasks):
        assert loaded.id == original.id
        assert loaded.prompt == original.prompt
        assert loaded.directory == original.directory
        assert loaded.args == original.args
        assert loaded.status == original.status
        assert loaded.exit_code == original.exit_code
        assert loaded.duration_ms == original.duration_ms
        assert loaded.json_output == original.json_output
        assert loaded.retry_count == original.retry_count


def test_save_pool_creates_parent_directory(tmp_path: Path):
    """Test that save_pool creates parent directories if they don't exist."""
    nested_file = tmp_path / "subdir" / "nested" / "pool.json"

    tasks = [Task(id="task_001", prompt="Test", directory=Path("/tmp"))]
    save_pool(nested_file, tasks)

    assert nested_file.exists()
    assert nested_file.parent.exists()
