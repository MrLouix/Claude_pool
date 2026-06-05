"""Unit tests for BaseCLIExecutor, ClaudeExecutor, and create_executor."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from team_cli.executor import BaseCLIExecutor, ClaudeExecutor, create_executor
from team_cli.models import CLIConfig


class TestClaudeExecutorGetModelList:
    """Tests for ClaudeExecutor.get_model_list()."""

    def test_returns_models_from_config(self):
        """ClaudeExecutor.get_model_list() returns the models from its CLIConfig."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku", "sonnet", "opus"],
            cli_type="anthropic",
        )
        executor = ClaudeExecutor(config)
        assert executor.get_model_list() == ["haiku", "sonnet", "opus"]


class TestClaudeExecutorExecute:
    """Tests for ClaudeExecutor.execute()."""

    def test_builds_correct_command(self):
        """ClaudeExecutor.execute() builds the correct subprocess command."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku", "sonnet", "opus"],
            cli_type="anthropic",
        )
        executor = ClaudeExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"result": "test"}'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result) as mock_run:
            with patch("team_cli.executor.parse_claude_output", return_value={"result": "parsed"}):
                result = executor.execute(
                    prompt="test prompt",
                    context=[],
                    directory="/tmp",
                    model="sonnet",
                )

                # Verify subprocess.run was called with correct args
                assert mock_run.called
                args = mock_run.call_args[0][0]  # First positional arg is cmd list
                assert args[0] == "/usr/bin/claude"
                assert "-p" in args
                assert "test prompt" in args
                assert "--output-format" in args
                assert "json" in args
                assert "--structured-output" in args
                assert "--model" in args
                assert "sonnet" in args

    def test_handles_timeout(self):
        """ClaudeExecutor.execute() handles subprocess timeout."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
        )
        executor = ClaudeExecutor(config)

        with patch("team_cli.executor.subprocess.run", side_effect=subprocess.TimeoutExpired(30 * 60, "test")):
            result = executor.execute(
                prompt="test",
                context=[],
                directory="/tmp",
                model="haiku",
            )

            assert "Task timed out after 30 minutes" in result["result"]
            assert executor.check_rate_limit() is False


class TestClaudeExecutorCheckRateLimit:
    """Tests for ClaudeExecutor.check_rate_limit()."""

    def test_returns_true_on_rate_limit_message(self):
        """ClaudeExecutor.check_rate_limit() returns True when last execution had rate limit."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
        )
        executor = ClaudeExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: rate limit exceeded"

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            with patch("team_cli.executor.parse_claude_output", return_value={}):
                executor.execute(
                    prompt="test",
                    context=[],
                    directory="/tmp",
                    model="haiku",
                )

                assert executor.check_rate_limit() is True

    def test_returns_false_on_success(self):
        """ClaudeExecutor.check_rate_limit() returns False when last execution succeeded."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
        )
        executor = ClaudeExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"result": "ok"}'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            with patch("team_cli.executor.parse_claude_output", return_value={"result": "ok"}):
                executor.execute(
                    prompt="test",
                    context=[],
                    directory="/tmp",
                    model="haiku",
                )

                assert executor.check_rate_limit() is False

    def test_returns_false_on_other_error(self):
        """ClaudeExecutor.check_rate_limit() returns False for non-rate-limit errors."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
        )
        executor = ClaudeExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: some other error"

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            with patch("team_cli.executor.parse_claude_output", return_value={}):
                executor.execute(
                    prompt="test",
                    context=[],
                    directory="/tmp",
                    model="haiku",
                )

                assert executor.check_rate_limit() is False


class TestCreateExecutor:
    """Tests for create_executor() factory function."""

    def test_returns_claude_executor_for_anthropic(self):
        """create_executor() returns a ClaudeExecutor for cli_type='anthropic'."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
        )
        executor = create_executor(config)
        assert isinstance(executor, ClaudeExecutor)
        assert isinstance(executor, BaseCLIExecutor)

    def test_raises_value_error_for_unknown_type(self):
        """create_executor() raises ValueError for unknown cli_type."""
        config = CLIConfig(
            name="unknown",
            path="/usr/bin/unknown",
            models=[],
            cli_type="unknown_type",
        )
        with pytest.raises(ValueError, match="Unsupported CLI type"):
            create_executor(config)
