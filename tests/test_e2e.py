"""End-to-end tests."""

from pathlib import Path

import pytest

from claude_pool.models import PoolState, Task
from claude_pool.storage import load_pool, save_pool


@pytest.fixture
def e2e_pool_file(tmp_path: Path) -> Path:
    """Pool file path for e2e tests (storage layer uses .db extension internally)."""
    return tmp_path / "e2e_pool.db"


def test_full_cycle_save_load(e2e_pool_file: Path):
    """Test complete save/load cycle."""
    tasks = [
        Task(
            id="e2e_001",
            prompt="Test task 1",
            directory=Path("/tmp"),
            args=["--verbose"],
        ),
        Task(
            id="e2e_002",
            prompt="Test task 2",
            directory=Path("/home/user"),
            status="success",
            exit_code=0,
            duration_ms=5000,
            json_output={
                "result": "Success",
                "tokens_used": 1000,
                "session_usage_percent": 20.0,
            },
        ),
    ]

    state = PoolState(tasks=tasks, pool_file=e2e_pool_file)
    save_pool(state)

    # Verify the SQLite database file was created
    assert e2e_pool_file.exists()

    loaded_state = load_pool(e2e_pool_file)

    assert len(loaded_state.tasks) == 2
    assert loaded_state.tasks[0].id == "e2e_001"
    assert loaded_state.tasks[0].status == "pending"
    assert loaded_state.tasks[1].id == "e2e_002"
    assert loaded_state.tasks[1].status == "success"
    assert loaded_state.tasks[1].json_output["tokens_used"] == 1000


def test_pool_modification_persistence(e2e_pool_file: Path):
    """Test that modifications are persisted correctly."""
    # Initial tasks
    tasks = [
        Task(id="mod_001", prompt="Task 1", directory=Path("/tmp")),
        Task(id="mod_002", prompt="Task 2", directory=Path("/tmp")),
        Task(id="mod_003", prompt="Task 3", directory=Path("/tmp")),
    ]

    state = PoolState(tasks=tasks, pool_file=e2e_pool_file)
    save_pool(state)

    # Modify: mark one as success, delete one
    loaded = load_pool(e2e_pool_file)
    loaded.tasks[0].status = "success"
    loaded.tasks[0].exit_code = 0
    del loaded.tasks[1]  # Delete middle task

    save_pool(loaded)

    # Reload and verify
    final = load_pool(e2e_pool_file)
    assert len(final.tasks) == 2
    assert final.tasks[0].id == "mod_001"
    assert final.tasks[0].status == "success"
    assert final.tasks[1].id == "mod_003"


def test_empty_pool(e2e_pool_file: Path):
    """Test handling of empty pool."""
    state = PoolState(tasks=[], pool_file=e2e_pool_file)
    save_pool(state)

    loaded = load_pool(e2e_pool_file)
    assert loaded.tasks == []


def test_unicode_handling(e2e_pool_file: Path):
    """Test that Unicode characters are preserved."""
    tasks = [
        Task(
            id="unicode_001",
            prompt="Tâche avec des caractères spéciaux: é à ç 中文 🎉",
            directory=Path("/tmp"),
            json_output={"result": "Résultat avec émojis 🚀"},
        )
    ]

    state = PoolState(tasks=tasks, pool_file=e2e_pool_file)
    save_pool(state)
    loaded = load_pool(e2e_pool_file)

    assert "caractères spéciaux" in loaded.tasks[0].prompt
    assert "🎉" in loaded.tasks[0].prompt
    assert loaded.tasks[0].json_output["result"] == "Résultat avec émojis 🚀"


def test_complex_json_output(e2e_pool_file: Path):
    """Test handling of complex JSON output structures."""
    complex_output = {
        "result": "Complex task completed",
        "code_blocks": [
            {
                "language": "python",
                "filename": "test.py",
                "content": "def hello():\n    print('world')",
            },
            {
                "language": "javascript",
                "filename": "test.js",
                "content": "console.log('hello');",
            },
        ],
        "files_changed": ["/path/to/file1.py", "/path/to/file2.js"],
        "tokens_used": 2500,
        "session_usage_percent": 45.8,
    }

    tasks = [
        Task(
            id="complex_001",
            prompt="Complex task",
            directory=Path("/tmp"),
            json_output=complex_output,
        )
    ]

    state = PoolState(tasks=tasks, pool_file=e2e_pool_file)
    save_pool(state)
    loaded = load_pool(e2e_pool_file)

    assert len(loaded.tasks[0].json_output["code_blocks"]) == 2
    assert loaded.tasks[0].json_output["code_blocks"][0]["language"] == "python"
    assert loaded.tasks[0].json_output["tokens_used"] == 2500


def test_pool_metadata_preservation(e2e_pool_file: Path):
    """Test that pool metadata (retry_count, suspended_until) is preserved."""
    from datetime import datetime, timedelta

    tasks = [
        Task(id="meta_001", prompt="Test", directory=Path("/tmp")),
    ]
    suspended_time = datetime.now() + timedelta(minutes=30)
    state = PoolState(
        retry_count=3,
        suspended_until=suspended_time,
        tasks=tasks,
        pool_file=e2e_pool_file,
    )
    save_pool(state)

    loaded = load_pool(e2e_pool_file)
    assert loaded.retry_count == 3
    assert loaded.suspended_until is not None
    assert loaded.is_suspended
