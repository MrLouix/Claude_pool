"""End-to-end tests."""

import json
from pathlib import Path

import pytest

from claude_pool.models import Task
from claude_pool.storage import load_pool, save_pool


@pytest.fixture
def e2e_pool_file(tmp_path: Path) -> Path:
    """Create a test pool file for e2e tests."""
    return tmp_path / "e2e_pool.json"


def test_full_cycle_save_load(e2e_pool_file: Path):
    """Test complete save/load cycle."""
    # Create tasks
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

    # Save to file
    save_pool(e2e_pool_file, tasks)

    # Verify file exists and is valid JSON
    assert e2e_pool_file.exists()
    content = json.loads(e2e_pool_file.read_text())
    assert isinstance(content, list)
    assert len(content) == 2

    # Load from file
    loaded_tasks = load_pool(e2e_pool_file)

    # Verify all data preserved
    assert len(loaded_tasks) == 2
    assert loaded_tasks[0].id == "e2e_001"
    assert loaded_tasks[0].status == "pending"
    assert loaded_tasks[1].id == "e2e_002"
    assert loaded_tasks[1].status == "success"
    assert loaded_tasks[1].json_output["tokens_used"] == 1000


def test_pool_modification_persistence(e2e_pool_file: Path):
    """Test that modifications are persisted correctly."""
    # Initial tasks
    tasks = [
        Task(id="mod_001", prompt="Task 1", directory=Path("/tmp")),
        Task(id="mod_002", prompt="Task 2", directory=Path("/tmp")),
        Task(id="mod_003", prompt="Task 3", directory=Path("/tmp")),
    ]

    save_pool(e2e_pool_file, tasks)

    # Modify: mark one as success, delete one
    loaded = load_pool(e2e_pool_file)
    loaded[0].status = "success"
    loaded[0].exit_code = 0
    del loaded[1]  # Delete middle task

    save_pool(e2e_pool_file, loaded)

    # Reload and verify
    final = load_pool(e2e_pool_file)
    assert len(final) == 2
    assert final[0].id == "mod_001"
    assert final[0].status == "success"
    assert final[1].id == "mod_003"


def test_empty_pool(e2e_pool_file: Path):
    """Test handling of empty pool."""
    save_pool(e2e_pool_file, [])

    loaded = load_pool(e2e_pool_file)
    assert loaded == []


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

    save_pool(e2e_pool_file, tasks)
    loaded = load_pool(e2e_pool_file)

    assert "caractères spéciaux" in loaded[0].prompt
    assert "🎉" in loaded[0].prompt
    assert loaded[0].json_output["result"] == "Résultat avec émojis 🚀"


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

    save_pool(e2e_pool_file, tasks)
    loaded = load_pool(e2e_pool_file)

    assert len(loaded[0].json_output["code_blocks"]) == 2
    assert loaded[0].json_output["code_blocks"][0]["language"] == "python"
    assert loaded[0].json_output["tokens_used"] == 2500
