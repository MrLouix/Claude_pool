"""Tests for multi-CLI fallback routing in TaskExecutor._handle_rate_limit."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from team_cli.models import CliCommand, PoolState, Task
from team_cli.pool_driver import TaskExecutor
from team_cli.storage import save_pool


def _cli(id: str, priority_requests: int = 100, enabled: bool = True) -> CliCommand:
    return CliCommand(
        id=id,
        name=id,
        binary=id,
        args_template='["-p","{prompt}"]',
        priority_requests=priority_requests,
        enabled=enabled,
    )


def _task(id: str = "t1") -> Task:
    return Task(id=id, prompt="do work", directory=Path("/tmp"))


def _executor(tmp_path: Path) -> TaskExecutor:
    pf = tmp_path / "pool.db"
    save_pool(PoolState(pool_file=pf))
    return TaskExecutor(pf, install_signal_handlers=False)


# ---------------------------------------------------------------------------
# _handle_rate_limit: CLI 1 rate-limited → reroute to CLI 2
# ---------------------------------------------------------------------------

class TestHandleRateLimitFallback:
    def test_task_rerouted_to_next_cli(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1", priority_requests=1)
        cli2 = _cli("cli2", priority_requests=2)

        ex._handle_rate_limit(task, cli1, [cli1, cli2])

        assert task.cli_id == "cli2"
        assert task.status == "pending"

    def test_rerouted_from_set_to_current(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1", priority_requests=1)
        cli2 = _cli("cli2", priority_requests=2)

        ex._handle_rate_limit(task, cli1, [cli1, cli2])

        assert task.rerouted_from == "cli1"
        assert task.rerouted_to == "cli2"

    def test_no_pool_suspension_when_fallback_available(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1", priority_requests=1)
        cli2 = _cli("cli2", priority_requests=2)

        ex._handle_rate_limit(task, cli1, [cli1, cli2])

        assert not ex.pool.is_suspended

    def test_task_status_pending_after_reroute(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1", priority_requests=1)
        cli2 = _cli("cli2", priority_requests=2)

        ex._handle_rate_limit(task, cli1, [cli1, cli2])

        assert task.status == "pending"


# ---------------------------------------------------------------------------
# _handle_rate_limit: all CLIs exhausted → pool suspended
# ---------------------------------------------------------------------------

class TestHandleRateLimitSuspend:
    def test_pool_suspended_when_no_fallback(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1")

        ex._handle_rate_limit(task, cli1, [cli1])

        assert ex.pool.is_suspended

    def test_task_status_rate_limit_retry_when_suspended(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1")

        ex._handle_rate_limit(task, cli1, [cli1])

        assert task.status == "rate_limit_retry"

    def test_pool_suspended_when_no_cli_info(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()

        ex._handle_rate_limit(task, None, [])

        assert ex.pool.is_suspended

    def test_reroute_picks_next_by_priority(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1", priority_requests=1)
        cli2 = _cli("cli2", priority_requests=2)
        cli3 = _cli("cli3", priority_requests=3)

        ex._handle_rate_limit(task, cli1, [cli1, cli2, cli3])

        # Next after cli1 should be cli2 (lowest priority after excluding cli1)
        assert task.cli_id == "cli2"
        assert not ex.pool.is_suspended

    def test_disabled_cli_not_used_as_fallback(self, tmp_path: Path) -> None:
        ex = _executor(tmp_path)
        task = _task()
        cli1 = _cli("cli1", priority_requests=1)
        cli_disabled = _cli("cli2", priority_requests=2, enabled=False)

        ex._handle_rate_limit(task, cli1, [cli1, cli_disabled])

        assert ex.pool.is_suspended
        assert task.status == "rate_limit_retry"


# ---------------------------------------------------------------------------
# execute_task integration: rate-limit with fallback (mocked subprocess)
# ---------------------------------------------------------------------------

class TestExecuteTaskFallbackIntegration:
    @pytest.mark.asyncio
    async def test_rate_limit_reroutes_task_to_next_cli(self, tmp_path: Path) -> None:
        """When CLI 1 returns exit_code=1 with rate-limit text and CLI 2 exists,
        the task should be re-queued with cli_id='cli2' rather than suspending."""
        pf = tmp_path / "pool.db"
        save_pool(PoolState(pool_file=pf))
        ex = TaskExecutor(pf, install_signal_handlers=False)

        cli1 = _cli("cli1", priority_requests=1)
        cli2 = _cli("cli2", priority_requests=2)

        task = _task()
        ex.pool.tasks.append(task)

        rate_limit_output = b'{"type":"result","result":"rate limit exceeded"}'

        with (
            patch.object(ex, "_load_cli_commands", new=AsyncMock(return_value=[cli1, cli2])),
            patch("asyncio.create_subprocess_exec") as mock_proc,
        ):
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(rate_limit_output, b""))
            proc.returncode = 1
            mock_proc.return_value = proc

            await ex.execute_task(task)

        assert task.cli_id == "cli2"
        assert task.status == "pending"
        assert task.rerouted_from == "cli1"
        assert not ex.pool.is_suspended

    @pytest.mark.asyncio
    async def test_rate_limit_suspends_when_only_one_cli(self, tmp_path: Path) -> None:
        """When there is only one CLI and it rate-limits, the pool should suspend."""
        pf = tmp_path / "pool.db"
        save_pool(PoolState(pool_file=pf))
        ex = TaskExecutor(pf, install_signal_handlers=False)

        cli1 = _cli("cli1", priority_requests=1)
        task = _task()
        ex.pool.tasks.append(task)

        rate_limit_output = b'{"type":"result","result":"rate limit exceeded"}'

        with (
            patch.object(ex, "_load_cli_commands", new=AsyncMock(return_value=[cli1])),
            patch("asyncio.create_subprocess_exec") as mock_proc,
        ):
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(rate_limit_output, b""))
            proc.returncode = 1
            mock_proc.return_value = proc

            await ex.execute_task(task)

        assert ex.pool.is_suspended
        assert task.status == "rate_limit_retry"
