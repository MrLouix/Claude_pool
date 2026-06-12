"""Unit tests for the multi_step_planner generator and utilities (Step 4)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from team_cli.skills.multi_step_planner.generator import PlanGenerator
from team_cli.skills.multi_step_planner.models import StepPlan, StepTask
from team_cli.skills.multi_step_planner.utils import (
    MAX_PROMPT_LENGTH,
    _strip_code_fences,
    generate_id,
    now_utc,
    validate_and_parse_plan_json,
    validate_prompt_length,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_steps(n: int) -> list[dict]:
    return [
        {"id": i, "description": f"Step {i}", "prompt": f"Do step {i} in detail"}
        for i in range(1, n + 1)
    ]


def _valid_plan_json(n: int = 3) -> str:
    return json.dumps({"steps": _make_steps(n)})


def _mock_process(stdout: bytes, returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    """Return a mock asyncio subprocess process."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


def _patch_subprocess(proc: MagicMock):
    """Context manager patching asyncio.create_subprocess_exec in generator module."""
    return patch(
        "team_cli.skills.multi_step_planner.generator.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    )


# ---------------------------------------------------------------------------
# generate_id
# ---------------------------------------------------------------------------

class TestGenerateId:
    def test_returns_string(self):
        assert isinstance(generate_id(), str)

    def test_returns_unique_ids(self):
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100

    def test_looks_like_uuid(self):
        uid = generate_id()
        assert len(uid) == 36
        assert uid.count("-") == 4


# ---------------------------------------------------------------------------
# now_utc
# ---------------------------------------------------------------------------

class TestNowUtc:
    def test_returns_datetime(self):
        from datetime import datetime
        assert isinstance(now_utc(), datetime)

    def test_is_timezone_aware(self):
        import datetime as dt
        assert now_utc().tzinfo is not None
        assert now_utc().tzinfo == dt.UTC


# ---------------------------------------------------------------------------
# validate_prompt_length
# ---------------------------------------------------------------------------

class TestValidatePromptLength:
    def test_accepts_prompt_at_limit(self):
        validate_prompt_length("x" * MAX_PROMPT_LENGTH)  # must not raise

    def test_accepts_short_prompt(self):
        validate_prompt_length("Hello world")

    def test_accepts_empty_string(self):
        validate_prompt_length("")

    def test_rejects_prompt_over_limit(self):
        with pytest.raises(ValueError, match="too long"):
            validate_prompt_length("x" * (MAX_PROMPT_LENGTH + 1))

    def test_error_message_contains_length(self):
        length = MAX_PROMPT_LENGTH + 500
        with pytest.raises(ValueError, match=str(length)):
            validate_prompt_length("x" * length)

    def test_error_message_contains_max(self):
        with pytest.raises(ValueError, match=str(MAX_PROMPT_LENGTH)):
            validate_prompt_length("x" * (MAX_PROMPT_LENGTH + 1))


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------

class TestStripCodeFences:
    def test_strips_json_fence(self):
        text = "```json\n{\"key\": 1}\n```"
        assert _strip_code_fences(text) == '{"key": 1}'

    def test_strips_plain_fence(self):
        text = "```\n{\"key\": 1}\n```"
        assert _strip_code_fences(text) == '{"key": 1}'

    def test_no_fence_unchanged(self):
        text = '{"key": 1}'
        assert _strip_code_fences(text) == text

    def test_partial_fence_unchanged(self):
        text = "```json\n{\"key\": 1}"
        assert _strip_code_fences(text) == text

    def test_multiline_content_preserved(self):
        inner = '{\n  "steps": []\n}'
        text = f"```json\n{inner}\n```"
        assert _strip_code_fences(text) == inner


# ---------------------------------------------------------------------------
# validate_and_parse_plan_json — valid inputs
# ---------------------------------------------------------------------------

class TestValidateAndParsePlanJsonValid:
    def test_parses_3_steps(self):
        result = validate_and_parse_plan_json(_valid_plan_json(3))
        assert len(result["steps"]) == 3

    def test_parses_8_steps(self):
        result = validate_and_parse_plan_json(_valid_plan_json(8))
        assert len(result["steps"]) == 8

    def test_returns_dict(self):
        result = validate_and_parse_plan_json(_valid_plan_json(3))
        assert isinstance(result, dict)

    def test_steps_list_present(self):
        result = validate_and_parse_plan_json(_valid_plan_json(5))
        assert "steps" in result
        assert isinstance(result["steps"], list)

    def test_strips_markdown_json_fence(self):
        raw = "```json\n" + _valid_plan_json(3) + "\n```"
        result = validate_and_parse_plan_json(raw)
        assert len(result["steps"]) == 3

    def test_strips_plain_markdown_fence(self):
        raw = "```\n" + _valid_plan_json(4) + "\n```"
        result = validate_and_parse_plan_json(raw)
        assert len(result["steps"]) == 4

    def test_step_fields_preserved(self):
        result = validate_and_parse_plan_json(_valid_plan_json(3))
        step = result["steps"][0]
        assert step["id"] == 1
        assert step["description"] == "Step 1"
        assert step["prompt"] == "Do step 1 in detail"


# ---------------------------------------------------------------------------
# validate_and_parse_plan_json — invalid inputs
# ---------------------------------------------------------------------------

class TestValidateAndParsePlanJsonInvalid:
    def test_rejects_2_steps(self):
        with pytest.raises(ValueError, match="at least 3"):
            validate_and_parse_plan_json(_valid_plan_json(2))

    def test_rejects_1_step(self):
        with pytest.raises(ValueError, match="at least 3"):
            validate_and_parse_plan_json(_valid_plan_json(1))

    def test_rejects_9_steps(self):
        with pytest.raises(ValueError, match="at most 8"):
            validate_and_parse_plan_json(_valid_plan_json(9))

    def test_rejects_0_steps(self):
        with pytest.raises(ValueError, match="at least 3"):
            validate_and_parse_plan_json(json.dumps({"steps": []}))

    def test_rejects_malformed_json(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_and_parse_plan_json("{not valid json")

    def test_rejects_json_array_at_top_level(self):
        with pytest.raises(ValueError, match="JSON object"):
            validate_and_parse_plan_json(json.dumps(_make_steps(3)))

    def test_rejects_missing_steps_key(self):
        with pytest.raises(ValueError, match='"steps"'):
            validate_and_parse_plan_json(json.dumps({"result": "ok"}))

    def test_rejects_steps_not_a_list(self):
        with pytest.raises(ValueError, match='"steps" must be a list'):
            validate_and_parse_plan_json(json.dumps({"steps": "bad"}))

    def test_rejects_step_missing_description(self):
        steps = _make_steps(3)
        del steps[0]["description"]
        with pytest.raises(ValueError, match='"description"'):
            validate_and_parse_plan_json(json.dumps({"steps": steps}))

    def test_rejects_step_missing_prompt(self):
        steps = _make_steps(3)
        del steps[1]["prompt"]
        with pytest.raises(ValueError, match='"prompt"'):
            validate_and_parse_plan_json(json.dumps({"steps": steps}))

    def test_rejects_step_missing_id(self):
        steps = _make_steps(3)
        del steps[0]["id"]
        with pytest.raises(ValueError, match='"id"'):
            validate_and_parse_plan_json(json.dumps({"steps": steps}))

    def test_rejects_empty_description(self):
        steps = _make_steps(3)
        steps[0]["description"] = "   "
        with pytest.raises(ValueError, match='"description"'):
            validate_and_parse_plan_json(json.dumps({"steps": steps}))

    def test_rejects_empty_prompt(self):
        steps = _make_steps(3)
        steps[0]["prompt"] = ""
        with pytest.raises(ValueError, match='"prompt"'):
            validate_and_parse_plan_json(json.dumps({"steps": steps}))

    def test_rejects_step_not_a_dict(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            validate_and_parse_plan_json(json.dumps({"steps": ["bad", "bad2", "bad3"]}))


# ---------------------------------------------------------------------------
# PlanGenerator.generate — subprocess mocking
# ---------------------------------------------------------------------------

class TestPlanGeneratorGenerate:
    """All tests mock asyncio.create_subprocess_exec to avoid real CLI calls."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_step_plan(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            result = self._run(gen.generate("Build an API", "proj-1", "msg-1"))
        assert isinstance(result, StepPlan)

    def test_plan_has_correct_project_and_message_ids(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "proj-XY", "msg-ZZ"))
        assert plan.project_id == "proj-XY"
        assert plan.message_id == "msg-ZZ"

    def test_plan_status_is_pending(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "proj-1", "msg-1"))
        assert plan.status == "pending"

    def test_plan_has_n_steps(self):
        for n in (3, 5, 8):
            proc = _mock_process(stdout=_valid_plan_json(n).encode())
            gen = PlanGenerator()
            with _patch_subprocess(proc):
                plan = self._run(gen.generate("Build an API", "p", "m"))
            assert len(plan.steps) == n, f"Expected {n} steps, got {len(plan.steps)}"

    def test_steps_are_step_task_objects(self):
        proc = _mock_process(stdout=_valid_plan_json(4).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "p", "m"))
        assert all(isinstance(s, StepTask) for s in plan.steps)

    def test_step_tasks_have_pending_status(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "p", "m"))
        assert all(s.status == "pending" for s in plan.steps)

    def test_step_tasks_reference_plan_id(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "p", "m"))
        assert all(s.plan_id == plan.id for s in plan.steps)

    def test_step_numbers_match_json_ids(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "p", "m"))
        assert [s.step_number for s in plan.steps] == [1, 2, 3]

    def test_accepts_markdown_fenced_json(self):
        fenced = "```json\n" + _valid_plan_json(3) + "\n```"
        proc = _mock_process(stdout=fenced.encode())
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            plan = self._run(gen.generate("Build an API", "p", "m"))
        assert len(plan.steps) == 3

    def test_cli_called_with_model_arg(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator(cli_path="claude", model="claude-opus-4-7")
        mock_exec = AsyncMock(return_value=proc)
        with patch(
            "team_cli.skills.multi_step_planner.generator.asyncio.create_subprocess_exec",
            new=mock_exec,
        ):
            self._run(gen.generate("Build an API", "p", "m"))
        call_args = mock_exec.call_args[0]
        assert "--model" in call_args
        model_idx = list(call_args).index("--model")
        assert call_args[model_idx + 1] == "claude-opus-4-7"

    def test_cli_called_with_custom_cli_path(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator(cli_path="/usr/local/bin/my-cli")
        mock_exec = AsyncMock(return_value=proc)
        with patch(
            "team_cli.skills.multi_step_planner.generator.asyncio.create_subprocess_exec",
            new=mock_exec,
        ):
            self._run(gen.generate("Build an API", "p", "m"))
        first_arg = mock_exec.call_args[0][0]
        assert first_arg == "/usr/local/bin/my-cli"

    def test_raises_runtime_error_on_nonzero_exit(self):
        proc = _mock_process(stdout=b"", returncode=1, stderr=b"rate limit exceeded")
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            with pytest.raises(RuntimeError, match="exit"):
                self._run(gen.generate("Build an API", "p", "m"))

    def test_runtime_error_includes_exit_code(self):
        proc = _mock_process(stdout=b"", returncode=2, stderr=b"fatal error")
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            with pytest.raises(RuntimeError, match="2"):
                self._run(gen.generate("Build an API", "p", "m"))

    def test_raises_runtime_error_when_no_stdout(self):
        proc = _mock_process(stdout=b"", returncode=0, stderr=b"nothing")
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            with pytest.raises(RuntimeError, match="no output"):
                self._run(gen.generate("Build an API", "p", "m"))

    def test_raises_value_error_on_invalid_json_output(self):
        proc = _mock_process(stdout=b"{bad json", returncode=0)
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            with pytest.raises(ValueError, match="Invalid JSON"):
                self._run(gen.generate("Build an API", "p", "m"))

    def test_raises_value_error_on_wrong_step_count(self):
        proc = _mock_process(stdout=_valid_plan_json(1).encode(), returncode=0)
        gen = PlanGenerator()
        with _patch_subprocess(proc):
            with pytest.raises(ValueError, match="at least 3"):
                self._run(gen.generate("Build an API", "p", "m"))

    def test_raises_value_error_on_prompt_too_long(self):
        gen = PlanGenerator()
        long_prompt = "x" * (MAX_PROMPT_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            self._run(gen.generate(long_prompt, "p", "m"))

    def test_prompt_too_long_does_not_call_subprocess(self):
        mock_exec = AsyncMock()
        gen = PlanGenerator()
        with patch(
            "team_cli.skills.multi_step_planner.generator.asyncio.create_subprocess_exec",
            new=mock_exec,
        ):
            with pytest.raises(ValueError):
                self._run(gen.generate("x" * (MAX_PROMPT_LENGTH + 1), "p", "m"))
        mock_exec.assert_not_called()

    def test_plan_description_is_user_request(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        request = "Create a user authentication system"
        with _patch_subprocess(proc):
            plan = self._run(gen.generate(request, "p", "m"))
        assert plan.description == request

    def test_plan_description_truncated_at_500_chars(self):
        proc = _mock_process(stdout=_valid_plan_json(3).encode())
        gen = PlanGenerator()
        long_request = "Build an API " * 50  # > 500 chars
        with _patch_subprocess(proc):
            plan = self._run(gen.generate(long_request, "p", "m"))
        assert len(plan.description) == 500

    def test_timeout_raises_runtime_error(self):
        """Simulate asyncio.TimeoutError from asyncio.wait_for."""
        # proc.communicate is called again in the except block for cleanup — let it succeed.
        proc = MagicMock()
        proc.returncode = None
        proc.kill = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))

        gen = PlanGenerator()
        with patch(
            "team_cli.skills.multi_step_planner.generator.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ), patch(
            "team_cli.skills.multi_step_planner.generator.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                self._run(gen.generate("Build an API", "p", "m"))
