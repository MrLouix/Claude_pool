"""Tests for automatic subtask spawning in TaskExecutor (Step 6 Part A)."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from team_cli.executor import TaskExecutor
from team_cli.models import CliCommand, PoolState, Task
from team_cli.pool_driver import MAX_SUBTASKS_PER_TASK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cli_command(cid: str = "cli_1") -> CliCommand:
    return CliCommand(
        id=cid,
        name="Test CLI",
        binary="echo",
        args_template='["-p", "{prompt}"]',
        models=["claude-3"],
        default_model="claude-3",
        enabled=True,
        priority_requests=1,
        priority_subtasks=1,
        parser="claude_json",
    )


def _make_stdout(result_text: str = "done", subtasks: list[dict] | None = None) -> bytes:
    data: dict = {
        "result": result_text,
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 0,
        "session_usage_percent": 0.0,
    }
    if subtasks is not None:
        data["result"] = result_text + " " + json.dumps({"subtasks": subtasks})
    return json.dumps(data).encode()


def _make_task(
    task_id: str = "task_parent_001",
    kind: str = "request",
    parent_task_id: str | None = None,
    project_id: str | None = "proj_1",
    chat_id: str | None = "chat_1",
    parent_message_id: str | None = "msg_1",
) -> Task:
    return Task(
        id=task_id,
        prompt="Do something",
        directory=Path("/tmp"),
        kind=kind,
        parent_task_id=parent_task_id,
        project_id=project_id,
        chat_id=chat_id,
        parent_message_id=parent_message_id,
    )


async def _run_execute_task(
    executor: TaskExecutor,
    task: Task,
    stdout: bytes,
    exit_code: int = 0,
    cli_commands: list | None = None,
) -> None:
    """Run execute_task with a mocked subprocess and optional CLI commands."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(stdout, b""))
    mock_proc.returncode = exit_code

    with patch(
        "team_cli.pool_driver.TaskExecutor._load_cli_commands",
        new=AsyncMock(return_value=cli_commands or [_make_cli_command()]),
    ), patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_proc),
    ), patch(
        "team_cli.pool_driver.TaskExecutor._save_state",
    ), patch(
        "team_cli.pool_driver.TaskExecutor._notify_update",
    ):
        await executor.execute_task(task)


# ---------------------------------------------------------------------------
# 1. completed_request_task_spawns_subtasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_request_task_spawns_subtasks(tmp_path: Path) -> None:
    """A completed kind='request' task with subtasks in its output spawns child tasks."""
    pf = tmp_path / "pool.db"
    executor = TaskExecutor(pf, install_signal_handlers=False)

    subtask_specs = [{"prompt": "p1"}, {"prompt": "p2", "model": "claude-3"}]
    task = _make_task()
    executor.pool.tasks.append(task)

    stdout = _make_stdout(subtasks=subtask_specs)
    await _run_execute_task(executor, task, stdout)

    spawned = [t for t in executor.pool.tasks if t.kind == "subtask"]
    assert len(spawned) == 2
    prompts = {t.prompt for t in spawned}
    assert prompts == {"p1", "p2"}


# ---------------------------------------------------------------------------
# 2. subtask_cannot_spawn_sub_subtasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subtask_cannot_spawn_sub_subtasks(tmp_path: Path) -> None:
    """A task with parent_task_id set (already a subtask) must NOT spawn further subtasks."""
    pf = tmp_path / "pool.db"
    executor = TaskExecutor(pf, install_signal_handlers=False)

    task = _make_task(kind="subtask", parent_task_id="task_grandparent")
    executor.pool.tasks.append(task)

    stdout = _make_stdout(subtasks=[{"prompt": "sub-sub"}])
    await _run_execute_task(executor, task, stdout)

    new_subtasks = [t for t in executor.pool.tasks if t.kind == "subtask" and t.id != task.id]
    assert len(new_subtasks) == 0


# ---------------------------------------------------------------------------
# 3. max_subtasks_cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_subtasks_cap(tmp_path: Path) -> None:
    """Only MAX_SUBTASKS_PER_TASK subtasks are spawned even if output has more."""
    pf = tmp_path / "pool.db"
    executor = TaskExecutor(pf, install_signal_handlers=False)

    task = _make_task()
    executor.pool.tasks.append(task)

    over_limit = [{"prompt": f"task_{i}"} for i in range(15)]
    stdout = _make_stdout(subtasks=over_limit)
    await _run_execute_task(executor, task, stdout)

    spawned = [t for t in executor.pool.tasks if t.kind == "subtask"]
    assert len(spawned) == MAX_SUBTASKS_PER_TASK


# ---------------------------------------------------------------------------
# 4. empty_subtasks_no_spawn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_subtasks_no_spawn(tmp_path: Path) -> None:
    """A task whose output has subtasks=[] spawns nothing."""
    pf = tmp_path / "pool.db"
    executor = TaskExecutor(pf, install_signal_handlers=False)

    task = _make_task()
    executor.pool.tasks.append(task)

    # No subtasks block in output at all
    stdout = _make_stdout()
    await _run_execute_task(executor, task, stdout)

    spawned = [t for t in executor.pool.tasks if t.kind == "subtask"]
    assert len(spawned) == 0


# ---------------------------------------------------------------------------
# 5. spawned_subtasks_inherit_project_and_chat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawned_subtasks_inherit_project_and_chat(tmp_path: Path) -> None:
    """Spawned subtasks inherit project_id, chat_id, and parent_message_id."""
    pf = tmp_path / "pool.db"
    executor = TaskExecutor(pf, install_signal_handlers=False)

    task = _make_task(project_id="proj_abc", chat_id="chat_xyz", parent_message_id="msg_999")
    executor.pool.tasks.append(task)

    stdout = _make_stdout(subtasks=[{"prompt": "inherit test"}])
    await _run_execute_task(executor, task, stdout)

    spawned = [t for t in executor.pool.tasks if t.kind == "subtask"]
    assert len(spawned) == 1
    s = spawned[0]
    assert s.project_id == "proj_abc"
    assert s.chat_id == "chat_xyz"
    assert s.parent_message_id == "msg_999"
    assert s.parent_task_id == task.id


# ---------------------------------------------------------------------------
# 6. spawned_subtask_fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawned_subtask_directory_matches_parent(tmp_path: Path) -> None:
    """Spawned subtasks run in the same directory as their parent task."""
    pf = tmp_path / "pool.db"
    executor = TaskExecutor(pf, install_signal_handlers=False)

    work_dir = Path("/tmp/myproject")
    task = Task(
        id="task_dir_parent",
        prompt="parent",
        directory=work_dir,
        kind="request",
        project_id="p1",
    )
    executor.pool.tasks.append(task)

    stdout = _make_stdout(subtasks=[{"prompt": "check dir"}])
    await _run_execute_task(executor, task, stdout)

    spawned = [t for t in executor.pool.tasks if t.kind == "subtask"]
    assert spawned[0].directory == work_dir
