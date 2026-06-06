"""Unit tests for StepPlan, StepTask Pydantic models and ProjectMessage extensions."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from team_cli.skills.multi_step_planner.models import StepPlan, StepTask, _parse_dt
from team_cli.models import ProjectMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 6, 12, 0, 0)
NOW_ISO = NOW.isoformat()


def _task_row(**overrides) -> dict:
    base = {
        "id": "task-1",
        "plan_id": "plan-1",
        "step_number": 1,
        "description": "Create the User model",
        "prompt": "Create a Python User class...",
        "status": "pending",
        "cli_used": None,
        "model_used": None,
        "output": None,
        "error": None,
        "tokens_used": None,
        "duration_ms": None,
        "created_at": NOW_ISO,
        "started_at": None,
        "completed_at": None,
    }
    return {**base, **overrides}


def _plan_row(**overrides) -> dict:
    base = {
        "id": "plan-1",
        "project_id": "proj-1",
        "message_id": "msg-1",
        "description": "Build a REST API",
        "status": "pending",
        "created_at": NOW_ISO,
        "completed_at": None,
        "final_evaluation": None,
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# StepTask — direct instantiation
# ---------------------------------------------------------------------------

class TestStepTaskInstantiation:
    def test_minimal_required_fields(self):
        t = StepTask(
            id="t1",
            plan_id="p1",
            step_number=1,
            description="desc",
            prompt="do something",
            status="pending",
            created_at=NOW,
        )
        assert t.id == "t1"
        assert t.status == "pending"

    def test_optional_fields_default_to_none(self):
        t = StepTask(
            id="t1", plan_id="p1", step_number=1,
            description="d", prompt="p", status="pending", created_at=NOW,
        )
        assert t.cli_used is None
        assert t.model_used is None
        assert t.output is None
        assert t.error is None
        assert t.tokens_used is None
        assert t.duration_ms is None
        assert t.started_at is None
        assert t.completed_at is None

    def test_all_valid_statuses_accepted(self):
        for status in ("pending", "running", "rate_limit", "success", "failed"):
            t = StepTask(
                id="t1", plan_id="p1", step_number=1,
                description="d", prompt="p", status=status, created_at=NOW,
            )
            assert t.status == status

    def test_invalid_status_raises_validation_error(self):
        with pytest.raises(ValidationError):
            StepTask(
                id="t1", plan_id="p1", step_number=1,
                description="d", prompt="p", status="unknown", created_at=NOW,
            )

    def test_full_fields_accepted(self):
        t = StepTask(
            id="t1", plan_id="p1", step_number=2,
            description="Implement CRUD", prompt="Create endpoints...",
            status="success", cli_used="claude", model_used="claude-sonnet-4-6",
            output="Done!", error=None, tokens_used=500, duration_ms=12000,
            created_at=NOW, started_at=NOW, completed_at=NOW,
        )
        assert t.tokens_used == 500
        assert t.cli_used == "claude"


# ---------------------------------------------------------------------------
# StepTask — from_db_row
# ---------------------------------------------------------------------------

class TestStepTaskFromDbRow:
    def test_basic_row_maps_correctly(self):
        t = StepTask.from_db_row(_task_row())
        assert t.id == "task-1"
        assert t.plan_id == "plan-1"
        assert t.step_number == 1
        assert t.description == "Create the User model"
        assert t.status == "pending"

    def test_created_at_parsed_from_iso_string(self):
        t = StepTask.from_db_row(_task_row(created_at=NOW_ISO))
        assert t.created_at == NOW

    def test_started_at_and_completed_at_parsed(self):
        t = StepTask.from_db_row(_task_row(started_at=NOW_ISO, completed_at=NOW_ISO))
        assert t.started_at == NOW
        assert t.completed_at == NOW

    def test_none_started_at_stays_none(self):
        t = StepTask.from_db_row(_task_row(started_at=None))
        assert t.started_at is None

    def test_tokens_used_coerced_to_int(self):
        t = StepTask.from_db_row(_task_row(tokens_used=1234))
        assert t.tokens_used == 1234

    def test_tokens_used_none_stays_none(self):
        t = StepTask.from_db_row(_task_row(tokens_used=None))
        assert t.tokens_used is None

    def test_duration_ms_coerced_to_int(self):
        t = StepTask.from_db_row(_task_row(duration_ms=9876))
        assert t.duration_ms == 9876

    def test_output_and_error_preserved(self):
        t = StepTask.from_db_row(_task_row(output="result text", error="some error"))
        assert t.output == "result text"
        assert t.error == "some error"

    def test_cli_used_and_model_used_preserved(self):
        t = StepTask.from_db_row(_task_row(cli_used="claude", model_used="claude-sonnet-4-6"))
        assert t.cli_used == "claude"
        assert t.model_used == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# StepPlan — direct instantiation
# ---------------------------------------------------------------------------

class TestStepPlanInstantiation:
    def test_minimal_required_fields(self):
        p = StepPlan(
            id="p1", project_id="proj-1", message_id="msg-1",
            description="Build API", status="pending", created_at=NOW,
        )
        assert p.id == "p1"
        assert p.status == "pending"

    def test_steps_default_to_empty_list(self):
        p = StepPlan(
            id="p1", project_id="proj-1", message_id="msg-1",
            description="Build API", status="pending", created_at=NOW,
        )
        assert p.steps == []

    def test_completed_at_defaults_to_none(self):
        p = StepPlan(
            id="p1", project_id="proj-1", message_id="msg-1",
            description="Build API", status="pending", created_at=NOW,
        )
        assert p.completed_at is None

    def test_final_evaluation_defaults_to_none(self):
        p = StepPlan(
            id="p1", project_id="proj-1", message_id="msg-1",
            description="Build API", status="pending", created_at=NOW,
        )
        assert p.final_evaluation is None

    def test_all_valid_statuses_accepted(self):
        for status in ("pending", "running", "completed", "failed"):
            p = StepPlan(
                id="p1", project_id="proj-1", message_id="msg-1",
                description="d", status=status, created_at=NOW,
            )
            assert p.status == status

    def test_invalid_status_raises_validation_error(self):
        with pytest.raises(ValidationError):
            StepPlan(
                id="p1", project_id="proj-1", message_id="msg-1",
                description="d", status="not_valid", created_at=NOW,
            )

    def test_steps_list_accepted(self):
        task = StepTask(
            id="t1", plan_id="p1", step_number=1,
            description="d", prompt="p", status="pending", created_at=NOW,
        )
        p = StepPlan(
            id="p1", project_id="proj-1", message_id="msg-1",
            description="d", status="running", created_at=NOW, steps=[task],
        )
        assert len(p.steps) == 1
        assert p.steps[0].id == "t1"

    def test_final_evaluation_dict_accepted(self):
        p = StepPlan(
            id="p1", project_id="proj-1", message_id="msg-1",
            description="d", status="completed", created_at=NOW,
            final_evaluation={"success": True, "summary": "All good"},
        )
        assert p.final_evaluation["success"] is True


# ---------------------------------------------------------------------------
# StepPlan — from_db_row
# ---------------------------------------------------------------------------

class TestStepPlanFromDbRow:
    def test_basic_row_maps_correctly(self):
        p = StepPlan.from_db_row(_plan_row())
        assert p.id == "plan-1"
        assert p.project_id == "proj-1"
        assert p.message_id == "msg-1"
        assert p.description == "Build a REST API"
        assert p.status == "pending"

    def test_created_at_parsed_from_iso_string(self):
        p = StepPlan.from_db_row(_plan_row(created_at=NOW_ISO))
        assert p.created_at == NOW

    def test_completed_at_parsed_when_present(self):
        p = StepPlan.from_db_row(_plan_row(completed_at=NOW_ISO))
        assert p.completed_at == NOW

    def test_completed_at_none_when_missing(self):
        p = StepPlan.from_db_row(_plan_row(completed_at=None))
        assert p.completed_at is None

    def test_final_evaluation_parsed_from_json_string(self):
        payload = {"success": False, "summary": "Incomplete", "missing": ["auth"]}
        p = StepPlan.from_db_row(_plan_row(final_evaluation=json.dumps(payload)))
        assert p.final_evaluation == payload

    def test_final_evaluation_accepted_as_dict(self):
        payload = {"success": True, "summary": "Done"}
        p = StepPlan.from_db_row(_plan_row(final_evaluation=payload))
        assert p.final_evaluation == payload

    def test_final_evaluation_none_when_null(self):
        p = StepPlan.from_db_row(_plan_row(final_evaluation=None))
        assert p.final_evaluation is None

    def test_final_evaluation_none_on_malformed_json(self):
        p = StepPlan.from_db_row(_plan_row(final_evaluation="{invalid json"))
        assert p.final_evaluation is None

    def test_steps_empty_by_default(self):
        p = StepPlan.from_db_row(_plan_row())
        assert p.steps == []

    def test_steps_injected_via_parameter(self):
        task = StepTask.from_db_row(_task_row())
        p = StepPlan.from_db_row(_plan_row(), steps=[task])
        assert len(p.steps) == 1
        assert p.steps[0].id == "task-1"


# ---------------------------------------------------------------------------
# _parse_dt helper
# ---------------------------------------------------------------------------

class TestParseDt:
    def test_parses_iso_string(self):
        dt = _parse_dt("2026-06-06T12:00:00")
        assert dt == datetime(2026, 6, 6, 12, 0, 0)

    def test_returns_datetime_unchanged(self):
        dt = _parse_dt(NOW)
        assert dt is NOW

    def test_parses_iso_with_timezone(self):
        s = "2026-06-06T12:00:00+00:00"
        dt = _parse_dt(s)
        assert dt.year == 2026 and dt.month == 6 and dt.day == 6


# ---------------------------------------------------------------------------
# ProjectMessage — new fields
# ---------------------------------------------------------------------------

class TestProjectMessageNewFields:
    def _make_msg(self, **overrides) -> ProjectMessage:
        base = {
            "id": "msg-1",
            "project_id": "proj-1",
            "content": "Hello",
            "role": "user",
        }
        return ProjectMessage(**{**base, **overrides})

    def test_is_step_task_defaults_to_false(self):
        msg = self._make_msg()
        assert msg.is_step_task is False

    def test_step_task_id_defaults_to_none(self):
        msg = self._make_msg()
        assert msg.step_task_id is None

    def test_is_step_task_can_be_set_true(self):
        msg = self._make_msg(is_step_task=True, step_task_id="st-42")
        assert msg.is_step_task is True
        assert msg.step_task_id == "st-42"

    def test_existing_fields_unaffected(self):
        msg = self._make_msg(cli_used="claude", priority=1)
        assert msg.cli_used == "claude"
        assert msg.priority == 1
        assert msg.linked_message_id is None

    def test_from_dict_without_new_fields_uses_defaults(self):
        data = {
            "id": "msg-1",
            "project_id": "proj-1",
            "content": "Hi",
            "role": "assistant",
            "created_at": NOW_ISO,
        }
        msg = ProjectMessage.from_dict(data)
        assert msg.is_step_task is False
        assert msg.step_task_id is None

    def test_from_dict_with_new_fields(self):
        data = {
            "id": "msg-1",
            "project_id": "proj-1",
            "content": "Hi",
            "role": "assistant",
            "created_at": NOW_ISO,
            "is_step_task": True,
            "step_task_id": "st-99",
        }
        msg = ProjectMessage.from_dict(data)
        assert msg.is_step_task is True
        assert msg.step_task_id == "st-99"

    def test_to_dict_includes_new_fields(self):
        msg = self._make_msg(is_step_task=True, step_task_id="st-7")
        d = msg.to_dict()
        assert d["is_step_task"] is True
        assert d["step_task_id"] == "st-7"

    def test_to_dict_includes_defaults_for_new_fields(self):
        msg = self._make_msg()
        d = msg.to_dict()
        assert "is_step_task" in d
        assert d["is_step_task"] is False
        assert "step_task_id" in d
        assert d["step_task_id"] is None
