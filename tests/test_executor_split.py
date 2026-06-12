"""Unit tests for the executor module split.

Verifies that:
- cli_executors.py, pool_driver.py, signal_handler.py are importable independently
- executor.py re-exports all expected symbols
- signal_handler.install_handlers() wires SIGINT/SIGTERM
- pool_driver.TaskExecutor uses CLIManager from cli_executors
"""

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestCliExecutorsModule:
    """cli_executors.py is importable and exposes the expected public API."""

    def test_importable(self):
        from team_cli.cli_executors import (
            _RATE_LIMIT_PATTERNS,
            MAX_RETRIES,
        )
        assert MAX_RETRIES == 5
        assert isinstance(_RATE_LIMIT_PATTERNS, tuple)
        assert len(_RATE_LIMIT_PATTERNS) > 0

    def test_create_executor_anthropic(self):
        from team_cli.cli_executors import ClaudeExecutor, create_executor
        from team_cli.models import CLIConfig

        cfg = CLIConfig(name="claude", path="/usr/bin/claude", models=["sonnet"], cli_type="anthropic")
        exc = create_executor(cfg)
        assert isinstance(exc, ClaudeExecutor)

    def test_create_executor_mistral(self):
        from team_cli.cli_executors import MistralExecutor, create_executor
        from team_cli.models import CLIConfig

        cfg = CLIConfig(name="mistral", path="/usr/bin/mistral", models=["tiny"], cli_type="mistral")
        exc = create_executor(cfg)
        assert isinstance(exc, MistralExecutor)

    def test_create_executor_custom(self):
        from team_cli.cli_executors import GenericCLIExecutor, create_executor
        from team_cli.models import CLIConfig

        cfg = CLIConfig(name="custom", path="/custom/cli", models=[], cli_type="custom")
        exc = create_executor(cfg)
        assert isinstance(exc, GenericCLIExecutor)

    def test_cli_manager_empty_configs(self):
        from team_cli.cli_executors import CLIManager

        mgr = CLIManager([])
        assert mgr._executors == []
        assert mgr.available_executors() == []

    def test_cli_manager_get_executor_by_name(self):
        from team_cli.cli_executors import CLIManager
        from team_cli.models import CLIConfig

        cfg = CLIConfig(name="claude", path="claude", models=["sonnet"], cli_type="anthropic")
        mgr = CLIManager([cfg])
        exc = mgr.get_executor_by_name("claude")
        assert exc is not None
        assert exc.config.name == "claude"

    def test_cli_manager_get_executor_by_name_missing(self):
        from team_cli.cli_executors import CLIManager

        mgr = CLIManager([])
        assert mgr.get_executor_by_name("nonexistent") is None

    def test_truncate_context_messages_under_limit(self):
        from team_cli.cli_executors import truncate_context_messages

        msgs = [{"role": "user", "content": str(i)} for i in range(2)]
        result = truncate_context_messages(msgs, max_count=3)
        assert result == msgs

    def test_truncate_context_messages_over_limit(self):
        from team_cli.cli_executors import truncate_context_messages

        msgs = [{"role": "user", "content": str(i)} for i in range(5)]
        result = truncate_context_messages(msgs, max_count=3)
        assert len(result) == 3
        assert result == msgs[-3:]


class TestPoolDriverModule:
    """pool_driver.py is importable and exposes TaskExecutor and execute_message."""

    def test_importable(self):
        from team_cli.pool_driver import _meta_hash, execute_message
        assert callable(execute_message)
        assert callable(_meta_hash)

    def test_meta_hash_stable(self):
        from team_cli.models import PoolState
        from team_cli.pool_driver import _meta_hash

        pool = PoolState(pool_file=Path("pool.db"))
        h1 = _meta_hash(pool)
        h2 = _meta_hash(pool)
        assert h1 == h2

    def test_meta_hash_changes_on_retry_count(self):
        from team_cli.models import PoolState
        from team_cli.pool_driver import _meta_hash

        pool = PoolState(pool_file=Path("pool.db"))
        h_before = _meta_hash(pool)
        pool.retry_count = 3
        h_after = _meta_hash(pool)
        assert h_before != h_after

    def test_task_executor_uses_cli_executors_clim(self):
        """TaskExecutor._cli_manager is a CLIManager from cli_executors."""
        from team_cli.cli_executors import CLIManager
        from team_cli.pool_driver import TaskExecutor

        exc = TaskExecutor(Path("pool.db"), install_signal_handlers=False)
        assert isinstance(exc.cli_manager, CLIManager)

    def test_task_executor_accepts_cli_manager(self):
        from team_cli.cli_executors import CLIManager
        from team_cli.models import CLIConfig
        from team_cli.pool_driver import TaskExecutor

        cfg = CLIConfig(name="claude", path="claude", models=[], cli_type="anthropic")
        mgr = CLIManager([cfg])
        exc = TaskExecutor(Path("pool.db"), install_signal_handlers=False, cli_manager=mgr)
        assert exc.cli_manager is mgr


class TestSignalHandlerModule:
    """signal_handler.py is importable and correctly wires signals."""

    def test_importable(self):
        from team_cli.signal_handler import install_handlers
        assert callable(install_handlers)

    def test_install_handlers_wires_sigint(self):
        from team_cli.signal_handler import install_handlers

        mock_executor = MagicMock()
        with patch("team_cli.signal_handler.signal.signal") as mock_signal:
            install_handlers(mock_executor)
            calls = {c.args[0] for c in mock_signal.call_args_list}
            assert signal.SIGINT in calls

    def test_install_handlers_wires_sigterm(self):
        from team_cli.signal_handler import install_handlers

        mock_executor = MagicMock()
        with patch("team_cli.signal_handler.signal.signal") as mock_signal:
            install_handlers(mock_executor)
            calls = {c.args[0] for c in mock_signal.call_args_list}
            assert signal.SIGTERM in calls

    def test_handle_signal_sets_should_stop(self):
        from team_cli.pool_driver import TaskExecutor

        exc = TaskExecutor(Path("pool.db"), install_signal_handlers=False)
        exc._handle_signal(signal.SIGINT, None)
        assert exc.should_stop is True


class TestExecutorShim:
    """executor.py re-exports all expected symbols from cli_executors and pool_driver."""

    def test_all_symbols_importable_from_shim(self):
        from team_cli.executor import (
            MAX_RETRIES,
        )
        assert MAX_RETRIES == 5

    def test_shim_clim_is_same_class_as_direct(self):
        from team_cli.cli_executors import CLIManager as DirectCLIManager
        from team_cli.executor import CLIManager as ShimCLIManager

        assert ShimCLIManager is DirectCLIManager

    def test_shim_task_executor_is_same_class_as_direct(self):
        from team_cli.executor import TaskExecutor as ShimTE
        from team_cli.pool_driver import TaskExecutor as DirectTE

        assert ShimTE is DirectTE
