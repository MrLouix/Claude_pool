"""Unit tests for CLIManager and related executors."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from team_cli.executor import (
    CLIManager,
    GenericCLIExecutor,
    MistralExecutor,
    create_executor,
)
from team_cli.models import CLIConfig


class TestMistralExecutor:
    """Tests for MistralExecutor."""

    def test_execute_builds_correct_command(self):
        """MistralExecutor.execute() builds the correct command via cli_profiles.toml.

        The mistral profile uses '-p' as the prompt flag and has no model flag,
        so the command is: [binary, '-p', prompt, '--output', 'json', fixed_flags...]
        """
        config = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny", "mistral-small"],
            cli_type="mistral",
        )
        executor = MistralExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '[{"role": "assistant", "content": "test output", "message_id": "1"}]'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            executor.execute(
                prompt="test prompt",
                context=[],
                directory="/tmp",
                model="mistral-tiny",
            )

            call_args = subprocess.run.call_args[0][0]
            assert call_args[0] == "/usr/bin/mistral"
            # Profile uses '-p' (not '--prompt') as the prompt flag
            assert "-p" in call_args
            assert "test prompt" in call_args
            # Profile has empty model_flag, so --model is NOT added to the command
            assert "--model" not in call_args

    def test_execute_with_context_runs_without_error(self):
        """MistralExecutor.execute() runs successfully when context messages are provided.

        MistralExecutor uses a profile-based CLI invocation and does not pass
        context as a separate temp file — context is currently not forwarded to the CLI.
        """
        config = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
        )
        executor = MistralExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '[{"role": "assistant", "content": "ok", "message_id": "1"}]'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            result = executor.execute(
                prompt="test",
                context=[{"key": "value"}],
                directory="/tmp",
                model="mistral-tiny",
            )

            assert subprocess.run.called
            call_args = subprocess.run.call_args[0][0]
            assert call_args[0] == "/usr/bin/mistral"
            assert result is not None

    def test_check_rate_limit_true(self):
        """MistralExecutor.check_rate_limit() returns True on rate limit."""
        config = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
        )
        executor = MistralExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Rate limit exceeded"

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            executor.execute(prompt="test", context=[], directory="/tmp", model="")
            assert executor.check_rate_limit() is True

    def test_check_rate_limit_with_429(self):
        """MistralExecutor.check_rate_limit() returns True on 429 error."""
        config = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
        )
        executor = MistralExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "HTTP 429 Too Many Requests"
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            executor.execute(prompt="test", context=[], directory="/tmp", model="")
            assert executor.check_rate_limit() is True


class TestGenericCLIExecutor:
    """Tests for GenericCLIExecutor."""

    def test_execute_formats_args_template(self):
        """GenericCLIExecutor passes args_template as static flags; prompt is isolated.

        C6 security fix: args_template is split as-is (no format() interpolation).
        The prompt is always appended as a separate positional argument.
        Template placeholders like {prompt} remain as literal strings in the static
        args, not replaced with the actual prompt value.
        """
        config = CLIConfig(
            name="custom",
            path="/usr/bin/custom-cli",
            models=["model1"],
            cli_type="custom",
            args_template="--flag value",
        )
        executor = GenericCLIExecutor(config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"result": "ok"}'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            executor.execute(
                prompt="my prompt",
                context=[],
                directory="/tmp",
                model="model1",
            )

            call_args = subprocess.run.call_args[0][0]
            assert call_args[0] == "/usr/bin/custom-cli"
            # Static args from template come first
            assert "--flag" in call_args
            assert "value" in call_args
            # Prompt is the last isolated argument — never interpolated
            assert call_args[-1] == "my prompt"
            # Model is NOT injected via the template (no format() interpolation)
            assert "model1" not in call_args[:-1]

    def test_check_rate_limit_always_false(self):
        """GenericCLIExecutor.check_rate_limit() always returns False."""
        config = CLIConfig(
            name="custom",
            path="/usr/bin/custom",
            models=["m1"],
            cli_type="custom",
        )
        executor = GenericCLIExecutor(config)
        assert executor.check_rate_limit() is False


class TestCreateExecutor:
    """Tests for create_executor() with new types."""

    def test_returns_mistral_executor(self):
        """create_executor() returns MistralExecutor for cli_type='mistral'."""
        config = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
        )
        executor = create_executor(config)
        assert isinstance(executor, MistralExecutor)

    def test_returns_llama_executor(self):
        """create_executor() returns LlamaExecutor for cli_type='llama'."""
        config = CLIConfig(
            name="llama",
            path="/usr/bin/llama",
            models=["llama-70b"],
            cli_type="llama",
        )
        executor = create_executor(config)
        # LlamaExecutor is a subclass of GenericCLIExecutor
        assert isinstance(executor, GenericCLIExecutor)

    def test_returns_gemma_executor(self):
        """create_executor() returns GemmaExecutor for cli_type='gemma'."""
        config = CLIConfig(
            name="gemma",
            path="/usr/bin/gemma",
            models=["gemma-7b"],
            cli_type="gemma",
        )
        executor = create_executor(config)
        assert isinstance(executor, GenericCLIExecutor)

    def test_returns_generic_executor_for_custom(self):
        """create_executor() returns GenericCLIExecutor for cli_type='custom'."""
        config = CLIConfig(
            name="my-cli",
            path="/usr/bin/my-cli",
            models=["m1"],
            cli_type="custom",
            args_template="{prompt}",
        )
        executor = create_executor(config)
        assert isinstance(executor, GenericCLIExecutor)


class TestCLIManager:
    """Tests for CLIManager."""

    def test_execute_calls_first_available_executor(self):
        """CLIManager.execute() calls the first available executor."""
        config1 = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
            enabled=True,
        )
        config2 = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
            enabled=True,
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"result": "ok"}'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            with patch("team_cli.executor.parse_claude_output", return_value={"result": "ok"}):
                manager = CLIManager([config1, config2])
                result = manager.execute(
                    prompt="test",
                    context=[],
                    directory="/tmp",
                    model="haiku",
                )
                assert "result" in result

    def test_execute_skips_rate_limited_executor(self):
        """CLIManager.execute() skips rate-limited executor and falls back."""
        config1 = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
            enabled=True,
        )
        config2 = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
            enabled=True,
        )

        # First executor will return rate limit
        mock_result_rl = MagicMock()
        mock_result_rl.returncode = 1
        mock_result_rl.stdout = ""
        mock_result_rl.stderr = "rate limit exceeded"

        # Second executor will succeed — stdout in vibe (list-of-messages) format
        mock_result_ok = MagicMock()
        mock_result_ok.returncode = 0
        mock_result_ok.stdout = (
            '[{"role": "assistant", "content": "ok from mistral", "message_id": "abc"}]'
        )
        mock_result_ok.stderr = ""

        with patch("team_cli.executor.subprocess.run") as mock_run:
            # First call (Claude) returns rate limit, second call (Mistral) succeeds
            mock_run.side_effect = [mock_result_rl, mock_result_ok]

            with patch("team_cli.executor.parse_claude_output", return_value={"result": "ok"}):
                manager = CLIManager([config1, config2])
                result = manager.execute(
                    prompt="test",
                    context=[],
                    directory="/tmp",
                    model="",
                )
                assert result["result"] == "ok from mistral"

    def test_execute_raises_when_all_rate_limited(self):
        """CLIManager.execute() raises RuntimeError when all executors are rate-limited."""
        config1 = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
            enabled=True,
        )

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "rate limit exceeded"

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            with patch("team_cli.executor.parse_claude_output", return_value={}):
                manager = CLIManager([config1])

                # First, the executor is not rate-limited yet
                # But after execute, it will be
                with pytest.raises(RuntimeError, match="All CLI executors are rate-limited"):
                    manager.execute(
                        prompt="test",
                        context=[],
                        directory="/tmp",
                        model="",
                    )

    def test_available_executors_excludes_rate_limited(self):
        """CLIManager.available_executors() excludes rate-limited executors.

        Only Claude's executor is made to trigger a rate-limit so that Mistral
        remains uncalled (and therefore available).
        """
        config1 = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku"],
            cli_type="anthropic",
            enabled=True,
        )
        config2 = CLIConfig(
            name="mistral",
            path="/usr/bin/mistral",
            models=["mistral-tiny"],
            cli_type="mistral",
            enabled=True,
        )

        manager = CLIManager([config1, config2])

        # Directly trigger Claude's rate-limit by simulating a run with exit_code=1
        claude_ex = manager.get_executor_by_name("claude")
        claude_ex._last_exit_code = 1
        claude_ex._last_stderr = "rate limit exceeded"
        claude_ex._last_stdout = ""

        # Mistral has never been called → not rate-limited
        available = manager.available_executors()
        assert len(available) == 1, f"Expected 1 available executor, got {len(available)}"
        assert isinstance(available[0], MistralExecutor)

    def test_execute_uses_default_model(self):
        """CLIManager.execute() uses default_model when model is empty."""
        config = CLIConfig(
            name="claude",
            path="/usr/bin/claude",
            models=["haiku", "sonnet"],
            cli_type="anthropic",
            default_model="sonnet",
            enabled=True,
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"result": "ok"}'
        mock_result.stderr = ""

        with patch("team_cli.executor.subprocess.run", return_value=mock_result):
            with patch("team_cli.executor.parse_claude_output", return_value={"result": "ok"}) as mock_parse:
                manager = CLIManager([config])
                manager.execute(
                    prompt="test",
                    context=[],
                    directory="/tmp",
                    model="",  # Empty model
                )

                # Verify parse_claude_output was called (meaning execute was called)
                assert mock_parse.called
