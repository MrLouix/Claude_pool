"""Tests for per-CLI context formatting and truncation (Risk Mitigation Step 2)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from team_cli.executor import (
    CLIManager,
    ClaudeExecutor,
    GenericCLIExecutor,
    LlamaExecutor,
    MistralExecutor,
    truncate_context_messages,
)
from team_cli.models import CLIConfig, Project, ProjectMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claude_config(name: str = "claude") -> CLIConfig:
    return CLIConfig(
        name=name,
        path="/usr/bin/claude",
        models=["claude-3-opus"],
        cli_type="anthropic",
        default_model="claude-3-opus",
    )


def _generic_config(name: str = "generic") -> CLIConfig:
    return CLIConfig(
        name=name,
        path="/usr/bin/generic-ai",
        models=["model-1"],
        cli_type="custom",
        default_model="model-1",
    )


def _mistral_config(name: str = "mistral") -> CLIConfig:
    return CLIConfig(
        name=name,
        path="/usr/bin/mistral",
        models=["mistral-large"],
        cli_type="mistral",
        default_model="mistral-large",
    )


def _llama_config(name: str = "llama") -> CLIConfig:
    return CLIConfig(
        name=name,
        path="/usr/bin/llama",
        models=["llama-3"],
        cli_type="llama",
        default_model="llama-3",
    )


# ---------------------------------------------------------------------------
# truncate_context_messages
# ---------------------------------------------------------------------------

class TestTruncateContextMessages:
    def test_returns_last_three_of_five(self):
        msgs = [
            {"role": "user", "content": f"msg{i}"} for i in range(5)
        ]
        result = truncate_context_messages(msgs)
        assert result == msgs[-3:]
        assert result[0]["content"] == "msg2"

    def test_returns_all_when_fewer_than_max(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        result = truncate_context_messages(msgs)
        assert result == msgs

    def test_returns_all_when_exactly_max(self):
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(3)]
        assert truncate_context_messages(msgs) == msgs

    def test_empty_list(self):
        assert truncate_context_messages([]) == []

    def test_custom_max_count(self):
        msgs = [{"role": "user", "content": str(i)} for i in range(10)]
        result = truncate_context_messages(msgs, max_count=5)
        assert len(result) == 5
        assert result == msgs[-5:]

    def test_max_count_one(self):
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        result = truncate_context_messages(msgs, max_count=1)
        assert result == [{"role": "assistant", "content": "b"}]


# ---------------------------------------------------------------------------
# ClaudeExecutor.format_context
# ---------------------------------------------------------------------------

class TestClaudeExecutorFormatContext:
    def setup_method(self):
        self.executor = ClaudeExecutor(_claude_config())

    def test_empty_list_returns_empty_string(self):
        assert self.executor.format_context([]) == ""

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        result = self.executor.format_context(msgs)
        assert result == "Human: Hello\n"

    def test_single_assistant_message(self):
        msgs = [{"role": "assistant", "content": "Hi there"}]
        result = self.executor.format_context(msgs)
        assert result == "Assistant: Hi there\n"

    def test_three_messages_produces_correct_human_assistant_format(self):
        msgs = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "Give me an example."},
        ]
        result = self.executor.format_context(msgs)
        assert result == (
            "Human: What is Python?\n"
            "Assistant: Python is a programming language.\n"
            "Human: Give me an example.\n"
        )

    def test_ends_with_newline(self):
        msgs = [{"role": "user", "content": "test"}]
        assert self.executor.format_context(msgs).endswith("\n")

    def test_user_role_maps_to_human(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = self.executor.format_context(msgs)
        assert result.startswith("Human:")

    def test_assistant_role_maps_to_assistant(self):
        msgs = [{"role": "assistant", "content": "hello"}]
        result = self.executor.format_context(msgs)
        assert result.startswith("Assistant:")

    def test_two_messages_alternating(self):
        msgs = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ]
        result = self.executor.format_context(msgs)
        lines = result.strip().split("\n")
        assert lines[0] == "Human: Question"
        assert lines[1] == "Assistant: Answer"


# ---------------------------------------------------------------------------
# GenericCLIExecutor.format_context
# ---------------------------------------------------------------------------

class TestGenericCLIExecutorFormatContext:
    def setup_method(self):
        self.executor = GenericCLIExecutor(_generic_config())

    def test_empty_list_returns_empty_string(self):
        assert self.executor.format_context([]) == ""

    def test_two_messages_produces_readable_block(self):
        msgs = [
            {"role": "user", "content": "Tell me about ML."},
            {"role": "assistant", "content": "ML is machine learning."},
        ]
        result = self.executor.format_context(msgs)
        assert result.startswith("[Previous conversation:]")
        assert "User: Tell me about ML." in result
        assert "AI: ML is machine learning." in result
        assert result.rstrip("\n").endswith("[End of context]")

    def test_three_messages(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        result = self.executor.format_context(msgs)
        lines = result.strip().split("\n")
        assert lines[0] == "[Previous conversation:]"
        assert lines[1] == "User: a"
        assert lines[2] == "AI: b"
        assert lines[3] == "User: c"
        assert lines[4] == "[End of context]"

    def test_ends_with_newline(self):
        msgs = [{"role": "user", "content": "hi"}]
        assert self.executor.format_context(msgs).endswith("\n")

    def test_user_role_maps_to_user(self):
        msgs = [{"role": "user", "content": "x"}]
        assert "User: x" in self.executor.format_context(msgs)

    def test_assistant_role_maps_to_ai(self):
        msgs = [{"role": "assistant", "content": "y"}]
        assert "AI: y" in self.executor.format_context(msgs)


# ---------------------------------------------------------------------------
# MistralExecutor.format_context — same readable block format
# ---------------------------------------------------------------------------

class TestMistralExecutorFormatContext:
    def setup_method(self):
        self.executor = MistralExecutor(_mistral_config())

    def test_empty_list_returns_empty_string(self):
        assert self.executor.format_context([]) == ""

    def test_uses_readable_block_format(self):
        msgs = [
            {"role": "user", "content": "foo"},
            {"role": "assistant", "content": "bar"},
        ]
        result = self.executor.format_context(msgs)
        assert "[Previous conversation:]" in result
        assert "User: foo" in result
        assert "AI: bar" in result
        assert "[End of context]" in result


# ---------------------------------------------------------------------------
# LlamaExecutor.format_context — inherits GenericCLIExecutor
# ---------------------------------------------------------------------------

class TestLlamaExecutorFormatContext:
    def setup_method(self):
        self.executor = LlamaExecutor(_llama_config())

    def test_empty_returns_empty(self):
        assert self.executor.format_context([]) == ""

    def test_uses_readable_block_format(self):
        msgs = [{"role": "user", "content": "test"}]
        result = self.executor.format_context(msgs)
        assert "[Previous conversation:]" in result
        assert "[End of context]" in result


# ---------------------------------------------------------------------------
# execute_message prepends formatted context to prompt
# ---------------------------------------------------------------------------

class TestExecuteMessageContextPrepend:
    """Verify execute_message builds full_prompt = format_context() + message.content."""

    def _make_project(self, default_cli: str = "mock-cli") -> Project:
        return Project(
            id="proj_1",
            name="Test Project",
            directory="/tmp",
            default_cli=default_cli,
            allow_cli_switch=False,
        )

    def _make_message(self, content: str = "What is 2+2?") -> ProjectMessage:
        return ProjectMessage(
            id="msg_1",
            project_id="proj_1",
            content=content,
            role="user",
        )

    @pytest.mark.asyncio
    async def test_prepends_formatted_context_to_prompt(self):
        from team_cli.executor import execute_message

        project = self._make_project()
        message = self._make_message("What is 2+2?")
        context_messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]

        received_prompt: list[str] = []

        mock_exec = MagicMock()
        mock_exec.config = MagicMock()
        mock_exec.config.name = "mock-cli"
        mock_exec.check_rate_limit.return_value = False
        mock_exec.format_context.return_value = (
            "[Previous conversation:]\nUser: Hi\nAI: Hello!\n[End of context]\n"
        )
        mock_exec.execute.side_effect = lambda prompt, **kw: (
            received_prompt.append(prompt) or {"result": "4", "cli_name": "mock-cli"}
        )

        mock_manager = MagicMock(spec=CLIManager)
        mock_manager.get_executor_by_name.return_value = mock_exec
        mock_manager.get_next_available_cli.return_value = mock_exec

        with patch(
            "team_cli.executor.build_context",
            return_value=context_messages,
        ):
            result = await execute_message(
                message=message,
                project=project,
                cli_manager=mock_manager,
                db_path="/tmp/test.db",
            )

        assert len(received_prompt) == 1
        prompt = received_prompt[0]
        assert "[Previous conversation:]" in prompt
        assert "User: Hi" in prompt
        assert "AI: Hello!" in prompt
        assert "[End of context]" in prompt
        assert prompt.endswith("What is 2+2?")

    @pytest.mark.asyncio
    async def test_empty_context_uses_plain_prompt(self):
        from team_cli.executor import execute_message

        project = self._make_project()
        message = self._make_message("Simple question")

        received_prompt: list[str] = []

        mock_exec = MagicMock()
        mock_exec.config = MagicMock()
        mock_exec.config.name = "mock-cli"
        mock_exec.check_rate_limit.return_value = False
        mock_exec.format_context.return_value = ""
        mock_exec.execute.side_effect = lambda prompt, **kw: (
            received_prompt.append(prompt) or {"result": "ok", "cli_name": "mock-cli"}
        )

        mock_manager = MagicMock(spec=CLIManager)
        mock_manager.get_executor_by_name.return_value = mock_exec
        mock_manager.get_next_available_cli.return_value = mock_exec

        with patch("team_cli.executor.build_context", return_value=[]):
            await execute_message(
                message=message,
                project=project,
                cli_manager=mock_manager,
                db_path="/tmp/test.db",
            )

        assert received_prompt[0] == "Simple question"

    @pytest.mark.asyncio
    async def test_context_truncated_to_three_before_formatting(self):
        from team_cli.executor import execute_message

        project = self._make_project()
        message = self._make_message("Final question")

        five_messages = [
            {"role": "user", "content": f"msg{i}"} for i in range(5)
        ]

        received_context: list[list] = []

        mock_exec = MagicMock()
        mock_exec.config = MagicMock()
        mock_exec.config.name = "mock-cli"
        mock_exec.check_rate_limit.return_value = False
        mock_exec.format_context.side_effect = lambda msgs: (
            received_context.append(msgs) or ""
        )
        mock_exec.execute.return_value = {"result": "ok", "cli_name": "mock-cli"}

        mock_manager = MagicMock(spec=CLIManager)
        mock_manager.get_executor_by_name.return_value = mock_exec
        mock_manager.get_next_available_cli.return_value = mock_exec

        with patch("team_cli.executor.build_context", return_value=five_messages):
            await execute_message(
                message=message,
                project=project,
                cli_manager=mock_manager,
                db_path="/tmp/test.db",
            )

        assert len(received_context[0]) == 3
        assert received_context[0] == five_messages[-3:]

    @pytest.mark.asyncio
    async def test_format_context_called_with_correct_executor(self):
        """Verify each executor's own format_context is used (not a global one)."""
        from team_cli.executor import execute_message

        project = Project(
            id="p", name="P", directory="/tmp",
            default_cli=None, allow_cli_switch=False,
        )
        message = self._make_message("test")

        mock_exec = MagicMock()
        mock_exec.config = MagicMock()
        mock_exec.config.name = "custom-cli"
        mock_exec.check_rate_limit.return_value = False
        mock_exec.format_context.return_value = "CUSTOM_FORMAT\n"
        received: list[str] = []
        mock_exec.execute.side_effect = lambda prompt, **kw: (
            received.append(prompt) or {"result": "ok", "cli_name": "custom-cli"}
        )

        mock_manager = MagicMock(spec=CLIManager)
        mock_manager.get_executor_by_name.return_value = None
        mock_manager.get_next_available_cli.return_value = mock_exec

        with patch(
            "team_cli.executor.build_context",
            return_value=[{"role": "user", "content": "prior"}],
        ):
            await execute_message(
                message=message,
                project=project,
                cli_manager=mock_manager,
                db_path="/tmp/test.db",
            )

        assert received[0].startswith("CUSTOM_FORMAT")
