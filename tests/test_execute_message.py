"""Unit tests for execute_message() — Phase 3 Step 2."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from team_cli.executor import (
    CLIManager,
    NoCLIAvailableError,
    execute_message,
)
from team_cli.models import CLIConfig, Project, ProjectMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(default_cli: str | None = None, allow_cli_switch: bool = True) -> Project:
    return Project(
        id="proj-1",
        name="Test Project",
        directory="/tmp/test",
        default_cli=default_cli,
        allow_cli_switch=allow_cli_switch,
    )


def _make_message(linked_message_id: str | None = None) -> ProjectMessage:
    return ProjectMessage(
        id="msg-1",
        project_id="proj-1",
        content="Hello, world!",
        role="user",
        linked_message_id=linked_message_id,
    )


def _make_executor(name: str, rate_limited: bool = False, result: dict | None = None) -> MagicMock:
    config = CLIConfig(
        name=name,
        path=f"/usr/bin/{name}",
        models=["model1"],
        cli_type="custom",
        enabled=True,
    )
    executor = MagicMock()
    executor.config = config
    executor.check_rate_limit.return_value = rate_limited
    executor.execute.return_value = result or {"result": f"ok from {name}"}
    executor.format_context.return_value = ""
    return executor


def _make_manager(*executors) -> CLIManager:
    manager = CLIManager.__new__(CLIManager)
    manager._executors = list(executors)
    return manager


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExecuteMessageSuccess:
    def test_successful_execution_on_first_try(self):
        ex = _make_executor("claude", result={"result": "answer"})
        manager = _make_manager(ex)
        project = _make_project()
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            result = _run(execute_message(message, project, manager, "/tmp/pool.db"))

        assert result["result"] == "answer"
        assert result["cli_used"] == "claude"

    def test_cli_used_field_set_to_executor_name(self):
        ex = _make_executor("hermes", result={"result": "hermes output"})
        manager = _make_manager(ex)
        project = _make_project()
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            result = _run(execute_message(message, project, manager, "/tmp/pool.db"))

        assert result["cli_used"] == "hermes"

    def test_model_parameter_passed_through(self):
        ex = _make_executor("claude")
        manager = _make_manager(ex)
        project = _make_project()
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            _run(execute_message(message, project, manager, "/tmp/pool.db", model="opus"))

        ex.execute.assert_called_once()
        call_kwargs = ex.execute.call_args
        assert call_kwargs[1].get("model") == "opus" or call_kwargs[0][3] == "opus"

    def test_empty_model_passed_as_empty_string(self):
        ex = _make_executor("claude")
        manager = _make_manager(ex)
        project = _make_project()
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            _run(execute_message(message, project, manager, "/tmp/pool.db", model=None))

        ex.execute.assert_called_once()
        call_kwargs = ex.execute.call_args
        passed_model = call_kwargs[1].get("model", call_kwargs[0][3] if call_kwargs[0] else "")
        assert passed_model == ""


class TestExecuteMessageContext:
    def test_context_built_from_build_context(self):
        ex = _make_executor("claude")
        manager = _make_manager(ex)
        project = _make_project()
        message = _make_message(linked_message_id="prev-msg-1")
        fake_context = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "reply"}]

        with patch("team_cli.executor.build_context", return_value=fake_context) as mock_bc:
            _run(execute_message(message, project, manager, "/tmp/pool.db"))

        mock_bc.assert_called_once()
        # Verify context was passed to executor
        ex.execute.assert_called_once()
        passed_context = ex.execute.call_args[1].get("context", ex.execute.call_args[0][1] if ex.execute.call_args[0] else [])
        assert passed_context == fake_context

    def test_build_context_called_with_correct_args(self):
        ex = _make_executor("claude")
        manager = _make_manager(ex)
        project = _make_project()
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]) as mock_bc:
            _run(execute_message(message, project, manager, "/tmp/pool.db"))

        mock_bc.assert_called_once()
        args = mock_bc.call_args[0]
        assert args[0] is message


class TestExecuteMessageDefaultCLI:
    def test_uses_default_cli_when_specified(self):
        ex_claude = _make_executor("claude")
        ex_hermes = _make_executor("hermes")
        manager = _make_manager(ex_claude, ex_hermes)
        project = _make_project(default_cli="hermes")
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            result = _run(execute_message(message, project, manager, "/tmp/pool.db"))

        assert result["cli_used"] == "hermes"
        ex_hermes.execute.assert_called_once()
        ex_claude.execute.assert_not_called()

    def test_falls_back_when_default_cli_not_found(self):
        ex = _make_executor("claude")
        manager = _make_manager(ex)
        project = _make_project(default_cli="missing-cli", allow_cli_switch=True)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            result = _run(execute_message(message, project, manager, "/tmp/pool.db"))

        assert result["cli_used"] == "claude"

    def test_raises_when_default_cli_missing_and_no_switch(self):
        ex = _make_executor("claude")
        manager = _make_manager(ex)
        project = _make_project(default_cli="missing-cli", allow_cli_switch=False)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            with pytest.raises(NoCLIAvailableError, match="missing-cli"):
                _run(execute_message(message, project, manager, "/tmp/pool.db"))

    def test_raises_when_default_cli_rate_limited_and_no_switch(self):
        ex = _make_executor("claude", rate_limited=True)
        manager = _make_manager(ex)
        project = _make_project(default_cli="claude", allow_cli_switch=False)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            with pytest.raises(NoCLIAvailableError):
                _run(execute_message(message, project, manager, "/tmp/pool.db"))


class TestExecuteMessageRateLimitSwitching:
    def test_switches_cli_on_rate_limit_when_allowed(self):
        ex1 = _make_executor("claude")
        ex1.check_rate_limit.side_effect = [False, True]  # ok before execute, rate-limited after
        ex1.execute.return_value = {"result": "rate limited response"}

        ex2 = _make_executor("hermes", result={"result": "hermes answer"})

        manager = _make_manager(ex1, ex2)
        project = _make_project(allow_cli_switch=True)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            result = _run(execute_message(message, project, manager, "/tmp/pool.db"))

        assert result["cli_used"] == "hermes"
        assert result["result"] == "hermes answer"

    def test_raises_when_rate_limited_and_switch_disabled(self):
        ex = _make_executor("claude")
        ex.check_rate_limit.side_effect = [False, True]  # rate-limited after execute
        ex.execute.return_value = {"result": "limited"}

        manager = _make_manager(ex)
        project = _make_project(allow_cli_switch=False)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            with pytest.raises(RuntimeError, match="rate-limited"):
                _run(execute_message(message, project, manager, "/tmp/pool.db"))

    def test_raises_no_cli_available_when_all_exhausted(self):
        ex1 = _make_executor("claude")
        ex1.check_rate_limit.side_effect = [False, True]
        ex1.execute.return_value = {"result": "limited"}

        ex2 = _make_executor("hermes")
        ex2.check_rate_limit.side_effect = [False, True]
        ex2.execute.return_value = {"result": "also limited"}

        manager = _make_manager(ex1, ex2)
        project = _make_project(allow_cli_switch=True)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            with pytest.raises(NoCLIAvailableError, match="All CLIs are rate-limited"):
                _run(execute_message(message, project, manager, "/tmp/pool.db"))

    def test_raises_no_cli_available_when_no_executors(self):
        manager = _make_manager()
        project = _make_project()
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            with pytest.raises(NoCLIAvailableError):
                _run(execute_message(message, project, manager, "/tmp/pool.db"))

    def test_tried_clis_excluded_on_each_retry(self):
        ex1 = _make_executor("claude")
        ex1.check_rate_limit.side_effect = [False, True]
        ex1.execute.return_value = {"result": "limited"}

        ex2 = _make_executor("hermes")
        ex2.check_rate_limit.side_effect = [False, False]  # succeeds
        ex2.execute.return_value = {"result": "hermes ok"}

        ex3 = _make_executor("openai")

        manager = _make_manager(ex1, ex2, ex3)
        project = _make_project(allow_cli_switch=True)
        message = _make_message()

        with patch("team_cli.executor.build_context", return_value=[]):
            result = _run(execute_message(message, project, manager, "/tmp/pool.db"))

        assert result["cli_used"] == "hermes"
        # openai executor should never have been invoked
        ex3.execute.assert_not_called()
