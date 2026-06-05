"""Unit tests for Phase 3 Step 1: NoCLIAvailableError and CLIManager.get_next_available_cli."""

from unittest.mock import MagicMock

import pytest

from team_cli.executor import (
    BaseCLIExecutor,
    CLIManager,
    NoCLIAvailableError,
)
from team_cli.models import CLIConfig


def _make_executor(name: str, rate_limited: bool = False) -> BaseCLIExecutor:
    """Create a mock executor with the given name and rate-limit state."""
    config = CLIConfig(
        name=name,
        path=f"/usr/bin/{name}",
        models=["model1"],
        cli_type="custom",
        enabled=True,
    )
    executor = MagicMock(spec=BaseCLIExecutor)
    executor.config = config
    executor.check_rate_limit.return_value = rate_limited
    return executor


def _make_manager(*executors: BaseCLIExecutor) -> CLIManager:
    """Create a CLIManager whose _executors list is pre-populated."""
    manager = CLIManager.__new__(CLIManager)
    manager._executors = list(executors)
    return manager


class TestNoCLIAvailableError:
    def test_is_exception_subclass(self):
        assert issubclass(NoCLIAvailableError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(NoCLIAvailableError):
            raise NoCLIAvailableError("all CLIs exhausted")

    def test_message_preserved(self):
        try:
            raise NoCLIAvailableError("test message")
        except NoCLIAvailableError as exc:
            assert str(exc) == "test message"


class TestGetNextAvailableCLI:
    def test_returns_none_when_executor_list_empty(self):
        manager = _make_manager()
        assert manager.get_next_available_cli(exclude=[]) is None

    def test_returns_none_when_all_excluded(self):
        ex1 = _make_executor("claude")
        ex2 = _make_executor("hermes")
        manager = _make_manager(ex1, ex2)
        result = manager.get_next_available_cli(exclude=["claude", "hermes"])
        assert result is None

    def test_returns_none_when_all_rate_limited(self):
        ex1 = _make_executor("claude", rate_limited=True)
        ex2 = _make_executor("hermes", rate_limited=True)
        manager = _make_manager(ex1, ex2)
        result = manager.get_next_available_cli(exclude=[])
        assert result is None

    def test_skips_excluded_returns_non_excluded(self):
        ex1 = _make_executor("claude")
        ex2 = _make_executor("hermes")
        manager = _make_manager(ex1, ex2)
        result = manager.get_next_available_cli(exclude=["claude"])
        assert result is ex2

    def test_skips_rate_limited_returns_non_limited(self):
        ex1 = _make_executor("claude", rate_limited=True)
        ex2 = _make_executor("hermes", rate_limited=False)
        manager = _make_manager(ex1, ex2)
        result = manager.get_next_available_cli(exclude=[])
        assert result is ex2

    def test_returns_first_eligible_executor(self):
        ex1 = _make_executor("claude")
        ex2 = _make_executor("hermes")
        ex3 = _make_executor("openai")
        manager = _make_manager(ex1, ex2, ex3)
        result = manager.get_next_available_cli(exclude=[])
        assert result is ex1

    def test_returns_none_when_excluded_and_rate_limited_cover_all(self):
        ex1 = _make_executor("claude", rate_limited=True)
        ex2 = _make_executor("hermes", rate_limited=False)
        manager = _make_manager(ex1, ex2)
        result = manager.get_next_available_cli(exclude=["hermes"])
        assert result is None

    def test_exclude_empty_list_returns_first_available(self):
        ex1 = _make_executor("claude")
        manager = _make_manager(ex1)
        result = manager.get_next_available_cli(exclude=[])
        assert result is ex1

    def test_single_executor_excluded_returns_none(self):
        ex1 = _make_executor("claude")
        manager = _make_manager(ex1)
        result = manager.get_next_available_cli(exclude=["claude"])
        assert result is None
