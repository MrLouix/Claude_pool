"""Tests for Risk Mitigation Step 1: Standardized CLI output normalization."""

from unittest.mock import MagicMock, patch

import pytest

from team_cli.executor import (
    BaseCLIExecutor,
    ClaudeExecutor,
    CLIManager,
    GemmaExecutor,
    GenericCLIExecutor,
    LlamaExecutor,
    MistralExecutor,
    NormalizedOutput,
)
from team_cli.models import CLIConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(name: str = "test-cli", cli_type: str = "anthropic") -> CLIConfig:
    return CLIConfig(
        name=name,
        path="/usr/bin/fake-cli",
        models=["model-1"],
        cli_type=cli_type,
        default_model="model-1",
    )


def _claude_exec(name: str = "claude") -> ClaudeExecutor:
    return ClaudeExecutor(_config(name=name, cli_type="anthropic"))


def _mistral_exec(name: str = "mistral") -> MistralExecutor:
    return MistralExecutor(_config(name=name, cli_type="mistral"))


def _generic_exec(name: str = "generic") -> GenericCLIExecutor:
    return GenericCLIExecutor(_config(name=name, cli_type="custom"))


# ---------------------------------------------------------------------------
# NormalizedOutput TypedDict structure
# ---------------------------------------------------------------------------

class TestNormalizedOutputShape:
    def test_normalized_output_importable(self):
        assert NormalizedOutput is not None

    def test_normalized_output_is_typeddict(self):
        from typing import get_type_hints
        hints = get_type_hints(NormalizedOutput)
        assert "content" in hints
        assert "model" in hints
        assert "cli_name" in hints
        assert "tokens_used" in hints
        assert "duration_ms" in hints
        assert "raw" in hints

    def test_can_construct_as_dict(self):
        out = NormalizedOutput(
            content="hello",
            model="claude-3",
            cli_name="claude",
            tokens_used=100,
            duration_ms=500,
            raw={"result": "hello"},
        )
        assert out["content"] == "hello"
        assert out["cli_name"] == "claude"
        assert out["raw"] == {"result": "hello"}

    def test_optional_fields_can_be_none(self):
        out = NormalizedOutput(
            content="",
            model=None,
            cli_name="cli",
            tokens_used=None,
            duration_ms=None,
            raw={},
        )
        assert out["model"] is None
        assert out["tokens_used"] is None
        assert out["duration_ms"] is None


# ---------------------------------------------------------------------------
# ClaudeExecutor.normalize_output
# ---------------------------------------------------------------------------

class TestClaudeNormalizeOutput:
    def test_extracts_content_from_result_field(self):
        exec_ = _claude_exec()
        raw = {"result": "This is the answer", "tokens_used": 42}
        norm = exec_.normalize_output(raw)
        assert norm["content"] == "This is the answer"

    def test_sets_cli_name_from_config(self):
        exec_ = _claude_exec(name="my-claude")
        norm = exec_.normalize_output({"result": "hi"})
        assert norm["cli_name"] == "my-claude"

    def test_extracts_tokens_used(self):
        exec_ = _claude_exec()
        raw = {"result": "ans", "tokens_used": 1234}
        norm = exec_.normalize_output(raw)
        assert norm["tokens_used"] == 1234

    def test_tokens_used_zero_becomes_none(self):
        exec_ = _claude_exec()
        raw = {"result": "ans", "tokens_used": 0}
        norm = exec_.normalize_output(raw)
        assert norm["tokens_used"] is None

    def test_tokens_used_absent_is_none(self):
        exec_ = _claude_exec()
        norm = exec_.normalize_output({"result": "ans"})
        assert norm["tokens_used"] is None

    def test_model_absent_is_none(self):
        exec_ = _claude_exec()
        norm = exec_.normalize_output({"result": "hi"})
        assert norm["model"] is None

    def test_model_extracted_when_present(self):
        exec_ = _claude_exec()
        raw = {"result": "hi", "model": "claude-opus-4"}
        norm = exec_.normalize_output(raw)
        assert norm["model"] == "claude-opus-4"

    def test_duration_ms_absent_is_none(self):
        exec_ = _claude_exec()
        norm = exec_.normalize_output({"result": "hi"})
        assert norm["duration_ms"] is None

    def test_raw_preserves_original_dict(self):
        exec_ = _claude_exec()
        original = {"result": "hi", "tokens_used": 10, "session_id": "sess_abc"}
        norm = exec_.normalize_output(original)
        assert norm["raw"]["session_id"] == "sess_abc"
        assert norm["raw"]["tokens_used"] == 10

    def test_raw_is_a_copy_not_same_reference(self):
        exec_ = _claude_exec()
        original = {"result": "hi"}
        norm = exec_.normalize_output(original)
        assert norm["raw"] is not original

    def test_realistic_claude_response(self):
        exec_ = _claude_exec(name="claude")
        raw = {
            "result": "Here is the fixed code:\n```python\nprint('hello')\n```",
            "tokens_used": 512,
            "session_usage_percent": 4.5,
            "code_blocks": [{"language": "python", "filename": "main.py", "content": "print('hello')"}],
            "files_changed": ["main.py"],
            "session_id": "sess_xyz789",
        }
        norm = exec_.normalize_output(raw)
        assert "fixed code" in norm["content"]
        assert norm["tokens_used"] == 512
        assert norm["cli_name"] == "claude"
        assert norm["raw"]["session_id"] == "sess_xyz789"
        assert norm["raw"]["code_blocks"][0]["language"] == "python"


# ---------------------------------------------------------------------------
# MistralExecutor.normalize_output
# ---------------------------------------------------------------------------

class TestMistralNormalizeOutput:
    def test_extracts_content_from_result(self):
        exec_ = _mistral_exec()
        norm = exec_.normalize_output({"result": "Mistral says hi"})
        assert norm["content"] == "Mistral says hi"

    def test_falls_back_to_content_field(self):
        exec_ = _mistral_exec()
        norm = exec_.normalize_output({"content": "alt content"})
        assert norm["content"] == "alt content"

    def test_extracts_tokens_from_usage_dict(self):
        exec_ = _mistral_exec()
        raw = {"result": "hi", "usage": {"total_tokens": 99}}
        norm = exec_.normalize_output(raw)
        assert norm["tokens_used"] == 99

    def test_extracts_tokens_from_top_level(self):
        exec_ = _mistral_exec()
        raw = {"result": "hi", "tokens_used": 77}
        norm = exec_.normalize_output(raw)
        assert norm["tokens_used"] == 77

    def test_tokens_none_when_absent(self):
        exec_ = _mistral_exec()
        norm = exec_.normalize_output({"result": "hi"})
        assert norm["tokens_used"] is None

    def test_model_extracted(self):
        exec_ = _mistral_exec()
        raw = {"result": "hi", "model": "mistral-large"}
        norm = exec_.normalize_output(raw)
        assert norm["model"] == "mistral-large"

    def test_cli_name_set(self):
        exec_ = _mistral_exec(name="mistral-prod")
        norm = exec_.normalize_output({"result": "hi"})
        assert norm["cli_name"] == "mistral-prod"

    def test_raw_preserved(self):
        exec_ = _mistral_exec()
        original = {"result": "hi", "extra": "data"}
        norm = exec_.normalize_output(original)
        assert norm["raw"]["extra"] == "data"


# ---------------------------------------------------------------------------
# GenericCLIExecutor.normalize_output (also covers LlamaExecutor, GemmaExecutor)
# ---------------------------------------------------------------------------

class TestGenericNormalizeOutput:
    def test_extracts_content_from_result(self):
        exec_ = _generic_exec()
        norm = exec_.normalize_output({"result": "generic output"})
        assert norm["content"] == "generic output"

    def test_falls_back_to_content_field(self):
        exec_ = _generic_exec()
        norm = exec_.normalize_output({"content": "content field"})
        assert norm["content"] == "content field"

    def test_falls_back_to_output_field(self):
        exec_ = _generic_exec()
        norm = exec_.normalize_output({"output": "output field"})
        assert norm["content"] == "output field"

    def test_empty_content_when_no_known_field(self):
        exec_ = _generic_exec()
        norm = exec_.normalize_output({"unknown_key": "value"})
        assert norm["content"] == ""

    def test_minimal_output_no_tokens(self):
        exec_ = _generic_exec()
        norm = exec_.normalize_output({"result": "minimal"})
        assert norm["tokens_used"] is None
        assert norm["duration_ms"] is None
        assert norm["model"] is None

    def test_tokens_extracted_when_present(self):
        exec_ = _generic_exec()
        norm = exec_.normalize_output({"result": "hi", "tokens_used": 55})
        assert norm["tokens_used"] == 55

    def test_cli_name_set(self):
        exec_ = _generic_exec(name="my-llama")
        norm = exec_.normalize_output({"result": "hi"})
        assert norm["cli_name"] == "my-llama"

    def test_raw_preserved_unchanged(self):
        exec_ = _generic_exec()
        original = {"result": "hi", "exit_code": 0, "extra": [1, 2, 3]}
        norm = exec_.normalize_output(original)
        assert norm["raw"] == original

    def test_raw_is_copy(self):
        exec_ = _generic_exec()
        original = {"result": "hi"}
        norm = exec_.normalize_output(original)
        original["result"] = "mutated"
        assert norm["raw"]["result"] == "hi"

    def test_llama_executor_inherits_normalize(self):
        llama = LlamaExecutor(_config(name="llama", cli_type="llama"))
        norm = llama.normalize_output({"result": "llama says hi"})
        assert norm["content"] == "llama says hi"
        assert norm["cli_name"] == "llama"

    def test_gemma_executor_inherits_normalize(self):
        gemma = GemmaExecutor(_config(name="gemma", cli_type="gemma"))
        norm = gemma.normalize_output({"result": "gemma says hi"})
        assert norm["content"] == "gemma says hi"
        assert norm["cli_name"] == "gemma"


# ---------------------------------------------------------------------------
# BaseCLIExecutor.execute() — merges raw + normalized, calls normalize_output
# ---------------------------------------------------------------------------

class TestBaseExecuteMerge:
    """Test the concrete execute() method on BaseCLIExecutor via a real subclass."""

    def _patched_exec(self, raw_return: dict, name: str = "test") -> ClaudeExecutor:
        exec_ = _claude_exec(name=name)
        exec_._run_raw = MagicMock(return_value=raw_return)
        return exec_

    def test_execute_calls_run_raw(self):
        exec_ = self._patched_exec({"result": "hi"})
        exec_.execute("p", [], "/tmp", "m")
        exec_._run_raw.assert_called_once_with("p", [], "/tmp", "m")

    def test_execute_returns_content_field(self):
        exec_ = self._patched_exec({"result": "hello world"})
        result = exec_.execute("p", [], "/tmp", "m")
        assert result["content"] == "hello world"

    def test_execute_returns_cli_name(self):
        exec_ = self._patched_exec({"result": "hi"}, name="claude-test")
        result = exec_.execute("p", [], "/tmp", "m")
        assert result["cli_name"] == "claude-test"

    def test_execute_returns_raw_field(self):
        raw = {"result": "hi", "session_id": "sess_123"}
        exec_ = self._patched_exec(raw)
        result = exec_.execute("p", [], "/tmp", "m")
        assert result["raw"]["session_id"] == "sess_123"

    def test_execute_preserves_raw_keys_for_backward_compat(self):
        raw = {
            "result": "hi",
            "tokens_used": 100,
            "session_id": "sess_abc",
            "session_usage_percent": 5.0,
            "code_blocks": [],
        }
        exec_ = self._patched_exec(raw)
        result = exec_.execute("p", [], "/tmp", "m")
        assert result["session_id"] == "sess_abc"
        assert result["session_usage_percent"] == 5.0
        assert result["code_blocks"] == []

    def test_execute_does_not_lose_parse_error_flag(self):
        raw = {"result": "error", "parse_error": True}
        exec_ = self._patched_exec(raw)
        result = exec_.execute("p", [], "/tmp", "m")
        assert result.get("parse_error") is True

    def test_normalized_tokens_override_raw_zero(self):
        # tokens_used=100 in raw → normalized has 100, result should have 100
        raw = {"result": "hi", "tokens_used": 100}
        exec_ = self._patched_exec(raw)
        result = exec_.execute("p", [], "/tmp", "m")
        assert result["tokens_used"] == 100

    def test_missing_optional_fields_do_not_raise(self):
        # No tokens, no model, no duration
        exec_ = self._patched_exec({"result": "ok"})
        result = exec_.execute("p", [], "/tmp", "m")
        assert "content" in result
        assert "cli_name" in result
        assert "raw" in result


# ---------------------------------------------------------------------------
# CLIManager.execute() — result has normalized fields
# ---------------------------------------------------------------------------

class TestCLIManagerNormalizedResult:
    def _manager_with_mock_exec(self, raw_return: dict, name: str = "mgr-cli") -> CLIManager:
        config = _config(name=name)
        mgr = CLIManager([config])
        mock_exec = MagicMock(spec=ClaudeExecutor)
        mock_exec.config = config
        mock_exec.check_rate_limit.return_value = False
        # execute() on the mock should call the real base logic, so we patch _run_raw
        # instead. Use a real ClaudeExecutor and patch its _run_raw.
        real_exec = _claude_exec(name=name)
        real_exec._run_raw = MagicMock(return_value=raw_return)
        mgr._executors = [real_exec]
        return mgr

    def test_result_has_content_field(self):
        mgr = self._manager_with_mock_exec({"result": "manager output"})
        result = mgr.execute("prompt", [], "/tmp", "model")
        assert "content" in result
        assert result["content"] == "manager output"

    def test_result_has_cli_name_field(self):
        mgr = self._manager_with_mock_exec({"result": "hi"}, name="my-cli")
        result = mgr.execute("prompt", [], "/tmp", "model")
        assert result["cli_name"] == "my-cli"

    def test_result_has_raw_field(self):
        mgr = self._manager_with_mock_exec({"result": "hi", "extra": "value"})
        result = mgr.execute("prompt", [], "/tmp", "model")
        assert "raw" in result
        assert result["raw"]["extra"] == "value"

    def test_no_key_error_for_missing_optional_fields(self):
        mgr = self._manager_with_mock_exec({"result": "minimal"})
        result = mgr.execute("prompt", [], "/tmp", "model")
        # These should either be present or safely accessed via .get()
        _ = result.get("tokens_used")
        _ = result.get("model")
        _ = result.get("duration_ms")


# ---------------------------------------------------------------------------
# execute_message — cli_used set from cli_name
# ---------------------------------------------------------------------------

class TestExecuteMessageCliUsed:
    def test_cli_used_set_from_cli_name(self):
        import inspect

        import team_cli.executor as mod
        src = inspect.getsource(mod.execute_message)
        assert 'result["cli_used"] = result.get("cli_name"' in src

    def test_execute_message_returns_cli_used(self):
        import asyncio

        from team_cli.executor import execute_message
        from team_cli.models import Project, ProjectMessage

        project = Project(
            id="proj_1", name="Test", directory="/tmp",
            default_cli="test-cli", allow_cli_switch=False,
        )
        message = ProjectMessage(
            id="msg_1", project_id="proj_1", content="hello", role="user",
        )
        raw = {"result": "response", "tokens_used": 50}
        real_exec = _claude_exec(name="test-cli")
        real_exec._run_raw = MagicMock(return_value=raw)
        real_exec.check_rate_limit = MagicMock(return_value=False)

        mgr = CLIManager([])
        mgr._executors = [real_exec]

        with patch("team_cli.executor.build_context", return_value=[]):
            result = asyncio.run(
                execute_message(message, project, mgr, "/tmp/test.db")
            )

        assert result["cli_used"] == "test-cli"
        assert result["cli_name"] == "test-cli"
        assert result["cli_used"] == result["cli_name"]

    def test_execute_message_result_has_content(self):
        import asyncio

        from team_cli.executor import execute_message
        from team_cli.models import Project, ProjectMessage

        project = Project(
            id="proj_1", name="Test", directory="/tmp",
            default_cli="test-cli", allow_cli_switch=False,
        )
        message = ProjectMessage(
            id="msg_1", project_id="proj_1", content="hello", role="user",
        )
        real_exec = _claude_exec(name="test-cli")
        real_exec._run_raw = MagicMock(return_value={"result": "the answer"})
        real_exec.check_rate_limit = MagicMock(return_value=False)

        mgr = CLIManager([])
        mgr._executors = [real_exec]

        with patch("team_cli.executor.build_context", return_value=[]):
            result = asyncio.run(
                execute_message(message, project, mgr, "/tmp/test.db")
            )

        assert result["content"] == "the answer"


# ---------------------------------------------------------------------------
# abstract method enforcement
# ---------------------------------------------------------------------------

class TestAbstractMethodEnforcement:
    def test_cannot_instantiate_base_without_run_raw(self):
        with pytest.raises(TypeError):
            class Incomplete(BaseCLIExecutor):
                def check_rate_limit(self): return False
                def normalize_output(self, raw): return NormalizedOutput(
                    content="", model=None, cli_name="x",
                    tokens_used=None, duration_ms=None, raw={}
                )
            Incomplete(_config())

    def test_cannot_instantiate_base_without_normalize_output(self):
        with pytest.raises(TypeError):
            class Incomplete(BaseCLIExecutor):
                def _run_raw(self, p, c, d, m): return {}
                def check_rate_limit(self): return False
            Incomplete(_config())

    def test_full_implementation_is_instantiable(self):
        class Full(BaseCLIExecutor):
            def _run_raw(self, p, c, d, m): return {"result": "hi"}
            def normalize_output(self, raw): return NormalizedOutput(
                content=raw.get("result", ""), model=None, cli_name=self.config.name,
                tokens_used=None, duration_ms=None, raw=dict(raw)
            )
            def format_context(self, messages): return ""
            def check_rate_limit(self): return False

        obj = Full(_config())
        assert obj is not None
        result = obj.execute("p", [], "/tmp", "m")
        assert result["content"] == "hi"
        assert result["cli_name"] == "test-cli"
