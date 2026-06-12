"""Tests for executor bug fixes: C1 (stop_task), C2 (exit_code), C3 (backoff).

Uses real subprocesses via tiny fake-claude shell scripts — no mocks.
"""

import asyncio
import json
import stat
import textwrap
from pathlib import Path

import pytest

from team_cli.executor import (
    MistralExecutor,
    TaskExecutor,
)
from team_cli.models import CLIConfig, Task
from team_cli.parser import parse_claude_output

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_claude(tmp_path: Path, exit_code: int, stdout_json: dict) -> Path:
    """Write a Python script that prints *stdout_json* and exits with *exit_code*.

    Using repr() to embed the dict avoids shell and string-escaping issues.
    """
    script = tmp_path / "fake_claude"
    script.write_text(
        f"#!/usr/bin/env python3\nimport sys, json\n"
        f"print(json.dumps({repr(stdout_json)}))\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _success_output() -> dict:
    return {"type": "result", "result": "Hello from fake claude", "usage": {"input_tokens": 10}}


def _rate_limit_output() -> dict:
    return {
        "type": "result",
        "result": "rate limit exceeded — too many requests",
        "usage": {},
    }


def _make_task(tmp_path: Path, task_id: str = "t1") -> Task:
    return Task(id=task_id, prompt="test prompt", directory=tmp_path, args=[])


def _make_executor(tmp_path: Path, fake_claude: Path) -> TaskExecutor:
    """Build a TaskExecutor wired to *fake_claude* with signal handlers off."""
    CLIConfig(
        name="claude",
        path=str(fake_claude),
        models=["sonnet"],
        cli_type="anthropic",
    )
    executor = TaskExecutor(
        tmp_path / "pool.db",
        install_signal_handlers=False,
    )
    return executor


# ---------------------------------------------------------------------------
# C2 – exit code is captured correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_code_zero_marks_success(tmp_path: Path) -> None:
    """exit_code 0 → task.status == 'success', task.exit_code == 0."""
    fake = _make_fake_claude(tmp_path, 0, _success_output())
    executor = _make_executor(tmp_path, fake)
    task = _make_task(tmp_path)
    # Override _build_command to use our fake binary
    executor._build_command = lambda t, s: [str(fake), "-p", t.prompt, "--output-format", "json"]

    await executor.execute_task(task)

    assert task.exit_code == 0, f"Expected 0, got {task.exit_code}"
    assert task.status == "success", f"Expected success, got {task.status}"


@pytest.mark.asyncio
async def test_exit_code_two_marks_failed(tmp_path: Path) -> None:
    """exit_code >= 2 → task.status == 'failed', task.exit_code == 2."""
    fake = _make_fake_claude(tmp_path, 2, {"result": "hard error"})
    executor = _make_executor(tmp_path, fake)
    task = _make_task(tmp_path)
    executor._build_command = lambda t, s: [str(fake), "-p", t.prompt]

    await executor.execute_task(task)

    assert task.exit_code == 2, f"Expected 2, got {task.exit_code}"
    assert task.status == "failed", f"Expected failed, got {task.status}"


@pytest.mark.asyncio
async def test_exit_code_one_with_rate_limit_message(tmp_path: Path) -> None:
    """exit_code 1 + rate-limit message → task.status == 'rate_limit_retry'."""
    fake = _make_fake_claude(tmp_path, 1, _rate_limit_output())
    executor = _make_executor(tmp_path, fake)
    task = _make_task(tmp_path)
    executor._build_command = lambda t, s: [str(fake), "-p", t.prompt]

    await executor.execute_task(task)

    assert task.exit_code == 1, f"Expected 1, got {task.exit_code}"
    assert task.status == "rate_limit_retry", f"Expected rate_limit_retry, got {task.status}"


# ---------------------------------------------------------------------------
# C1 – _running_processes is populated during execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_running_process_registered_during_execution(tmp_path: Path) -> None:
    """The process is in _running_processes while the task is running."""
    # A script that sleeps long enough for us to observe the registry
    sleep_script = tmp_path / "slow_fake_claude"
    sleep_script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            sleep 5
            echo '{json.dumps(_success_output())}'
            exit 0
            """
        )
    )
    sleep_script.chmod(sleep_script.stat().st_mode | stat.S_IEXEC)

    executor = _make_executor(tmp_path, sleep_script)
    task = _make_task(tmp_path)
    executor._build_command = lambda t, s: [str(sleep_script)]

    observed_pids: list[int] = []

    async def _probe() -> None:
        # Give the subprocess a moment to start
        await asyncio.sleep(0.3)
        proc = executor._running_processes.get(task.id)
        if proc is not None:
            observed_pids.append(proc.pid)
        # Cancel the task so the test doesn't hang
        executor.should_stop = True
        proc = executor._running_processes.get(task.id)
        if proc:
            proc.kill()

    await asyncio.gather(
        executor.execute_task(task),
        _probe(),
        return_exceptions=True,
    )

    assert observed_pids, "Process was never registered in _running_processes"
    assert observed_pids[0] > 0


@pytest.mark.asyncio
async def test_running_process_removed_after_execution(tmp_path: Path) -> None:
    """The process entry is cleaned up from _running_processes after the task completes."""
    fake = _make_fake_claude(tmp_path, 0, _success_output())
    executor = _make_executor(tmp_path, fake)
    task = _make_task(tmp_path)
    executor._build_command = lambda t, s: [str(fake), "-p", t.prompt]

    await executor.execute_task(task)

    assert task.id not in executor._running_processes


@pytest.mark.asyncio
async def test_stop_task_signals_running_process(tmp_path: Path) -> None:
    """stop_task() terminates a long-running subprocess and sets status=stopped."""
    sleep_script = tmp_path / "long_task"
    sleep_script.write_text("#!/bin/sh\nsleep 30\n")
    sleep_script.chmod(sleep_script.stat().st_mode | stat.S_IEXEC)

    executor = _make_executor(tmp_path, sleep_script)
    task = _make_task(tmp_path)
    # stop_task() looks up the task in pool.tasks — must be registered
    executor.pool.tasks.append(task)
    executor._build_command = lambda t, s: [str(sleep_script)]

    stop_result: list[bool] = []

    async def _stopper() -> None:
        await asyncio.sleep(0.4)
        result = await executor.stop_task(task.id)
        stop_result.append(result)

    await asyncio.gather(
        executor.execute_task(task),
        _stopper(),
        return_exceptions=True,
    )

    assert stop_result == [True], "stop_task() should return True for a running task"
    assert task.status == "stopped", f"Expected stopped, got {task.status}"


# ---------------------------------------------------------------------------
# C3 – Fixed 30-minute retry interval (no exponential backoff, no max retries)
# ---------------------------------------------------------------------------


def test_rate_limit_fixed_delay(tmp_path: Path) -> None:
    """Rate-limit suspension is always exactly 1800 seconds (30 min), regardless of retry count."""
    executor = TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)

    for retry_count in [0, 1, 5, 10]:
        executor.pool.retry_count = retry_count
        task = _make_task(tmp_path, f"t{retry_count}")
        task.status = "rate_limit_retry"
        task.exit_code = 1
        task.json_output = {}
        executor._on_rate_limit_detected(task)
        assert task.status == "rate_limit_retry"
        remaining = executor.pool.suspension_remaining
        assert abs(remaining - 1800) < 2, (
            f"retry_count={retry_count}: expected ~1800s, got {remaining:.1f}s"
        )
        executor.pool.suspended_until = None


def test_rate_limit_no_exhaustion(tmp_path: Path) -> None:
    """Rate-limited tasks are never permanently failed — retries are unbounded."""
    executor = TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)
    executor.pool.retry_count = 100  # far beyond the old MAX_RETRIES
    task = _make_task(tmp_path)
    task.json_output = {}
    executor._on_rate_limit_detected(task)

    assert task.status == "rate_limit_retry", (
        f"Expected rate_limit_retry (not failed), got {task.status}"
    )
    assert executor.pool.is_suspended


def test_rate_limit_retry_count_increments(tmp_path: Path) -> None:
    """pool.retry_count increments on each rate-limit event."""
    executor = TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)
    for expected in range(1, 6):
        task = _make_task(tmp_path, f"t{expected}")
        task.json_output = {}
        executor._on_rate_limit_detected(task)
        assert executor.pool.retry_count == expected
        executor.pool.suspended_until = None  # reset so next call doesn't exit early


# ---------------------------------------------------------------------------
# Quick wins
# ---------------------------------------------------------------------------


def test_build_command_includes_structured_output(tmp_path: Path) -> None:
    """_build_command must include --structured-output."""
    executor = TaskExecutor(tmp_path / "pool.db", install_signal_handlers=False)
    task = _make_task(tmp_path)
    cmd = executor._build_command(task, None)
    assert "--structured-output" in cmd


def test_parse_claude_output_strips_reasoning() -> None:
    """parse_claude_output must remove the reasoning field."""
    raw = json.dumps(
        {
            "type": "result",
            "result": "Hello",
            "reasoning": "step1: ...",
            "usage": {"input_tokens": 5},
        }
    ).encode()
    parsed = parse_claude_output(raw)
    assert "reasoning" not in parsed
    assert parsed["result"] == "Hello"


def test_parse_claude_output_strips_reasoning_legacy() -> None:
    """Reasoning is stripped from legacy format too."""
    raw = json.dumps(
        {
            "result": "Hello",
            "reasoning": "thinking...",
            "tokens_used": 10,
        }
    ).encode()
    parsed = parse_claude_output(raw)
    assert "reasoning" not in parsed


# ---------------------------------------------------------------------------
# Mistral rate-limit detection fix
# ---------------------------------------------------------------------------


def test_mistral_check_rate_limit_exit_code_zero_returns_false() -> None:
    """exit_code 0 should never be a rate limit, even if output contains 'rate'."""
    cfg = CLIConfig(name="mistral", path="mistral", models=[], cli_type="mistral")
    ex = MistralExecutor(cfg)
    ex._last_exit_code = 0
    ex._last_stdout = "rate limit info in stdout"
    ex._last_stderr = ""
    assert ex.check_rate_limit() is False


def test_mistral_check_rate_limit_exit_code_one_with_pattern() -> None:
    """exit_code 1 + rate-limit keyword → True."""
    cfg = CLIConfig(name="mistral", path="mistral", models=[], cli_type="mistral")
    ex = MistralExecutor(cfg)
    ex._last_exit_code = 1
    ex._last_stdout = "Error: rate limit exceeded"
    ex._last_stderr = ""
    assert ex.check_rate_limit() is True


def test_mistral_check_rate_limit_exit_code_two_returns_false() -> None:
    """exit_code 2 (hard failure) is NOT a rate limit."""
    cfg = CLIConfig(name="mistral", path="mistral", models=[], cli_type="mistral")
    ex = MistralExecutor(cfg)
    ex._last_exit_code = 2
    ex._last_stdout = "429 too many requests"
    ex._last_stderr = ""
    assert ex.check_rate_limit() is False


def test_mistral_check_rate_limit_exit_code_one_with_429() -> None:
    """exit_code 1 + 429 in output → True."""
    cfg = CLIConfig(name="mistral", path="mistral", models=[], cli_type="mistral")
    ex = MistralExecutor(cfg)
    ex._last_exit_code = 1
    ex._last_stdout = ""
    ex._last_stderr = "HTTP 429"
    assert ex.check_rate_limit() is True
