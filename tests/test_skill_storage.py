"""Unit tests for the Step Plan / Step Task storage layer (Step 3)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from team_cli.database import DatabaseManager
from team_cli.models import Project, ProjectMessage
from team_cli.skills.multi_step_planner.models import StepPlan, StepTask
from team_cli.storage import (
    delete_step_plan,
    load_step_plan,
    load_step_plans_for_message,
    load_step_tasks_for_plan,
    save_project,
    save_project_message,
    save_step_plan,
    save_step_task,
    update_step_plan_status,
    update_step_task_status,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 6, 12, 0, 0)
NOW_ISO = NOW.isoformat()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Initialised SQLite DB with all tables and migrations applied."""
    path = tmp_path / "pool.db"
    asyncio.run(DatabaseManager(path).init())
    return path


@pytest.fixture
def seeded_db(db_path: Path) -> Path:
    """DB with a project and message pre-inserted (required by FK constraints)."""
    project = Project(
        id="proj-1",
        name="Test Project",
        directory="/tmp/test",
        created_at=NOW,
        default_cli="claude",
        allow_cli_switch=True,
    )
    save_project(db_path, project)

    message = ProjectMessage(
        id="msg-1",
        project_id="proj-1",
        content="Build a REST API",
        role="user",
        created_at=NOW,
    )
    save_project_message(db_path, message)
    return db_path


def _make_plan(plan_id: str = "plan-1", message_id: str = "msg-1") -> StepPlan:
    return StepPlan(
        id=plan_id,
        project_id="proj-1",
        message_id=message_id,
        description="Build a REST API with auth",
        status="pending",
        created_at=NOW,
    )


def _make_task(task_id: str, plan_id: str = "plan-1", step_number: int = 1) -> StepTask:
    return StepTask(
        id=task_id,
        plan_id=plan_id,
        step_number=step_number,
        description=f"Step {step_number}: do something",
        prompt=f"Prompt for step {step_number}",
        status="pending",
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# save_step_plan
# ---------------------------------------------------------------------------

class TestSaveStepPlan:
    def test_creates_row_in_db(self, seeded_db):
        plan = _make_plan()
        save_step_plan(plan, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        row = conn.execute("SELECT * FROM step_plans WHERE id = 'plan-1'").fetchone()
        conn.close()

        assert row is not None

    def test_stores_all_core_fields(self, seeded_db):
        plan = _make_plan()
        save_step_plan(plan, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM step_plans WHERE id = 'plan-1'").fetchone())
        conn.close()

        assert row["id"] == "plan-1"
        assert row["project_id"] == "proj-1"
        assert row["message_id"] == "msg-1"
        assert row["description"] == "Build a REST API with auth"
        assert row["status"] == "pending"
        assert row["created_at"] == NOW_ISO

    def test_upsert_overwrites_existing_row(self, seeded_db):
        plan = _make_plan()
        save_step_plan(plan, seeded_db)

        updated = plan.model_copy(update={"status": "running"})
        save_step_plan(updated, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        row = conn.execute("SELECT status FROM step_plans WHERE id = 'plan-1'").fetchone()
        conn.close()
        assert row[0] == "running"

    def test_stores_final_evaluation_as_json(self, seeded_db):
        plan = _make_plan()
        plan = plan.model_copy(update={"final_evaluation": {"success": True, "summary": "All good"}})
        save_step_plan(plan, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        raw = conn.execute("SELECT final_evaluation FROM step_plans WHERE id = 'plan-1'").fetchone()[0]
        conn.close()

        parsed = json.loads(raw)
        assert parsed["success"] is True
        assert parsed["summary"] == "All good"

    def test_completed_at_stored_as_iso_string(self, seeded_db):
        plan = _make_plan()
        plan = plan.model_copy(update={"completed_at": NOW, "status": "completed"})
        save_step_plan(plan, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        raw = conn.execute("SELECT completed_at FROM step_plans WHERE id = 'plan-1'").fetchone()[0]
        conn.close()
        assert raw == NOW_ISO


# ---------------------------------------------------------------------------
# load_step_plan
# ---------------------------------------------------------------------------

class TestLoadStepPlan:
    def test_returns_none_for_missing_plan(self, db_path):
        assert load_step_plan("nonexistent", db_path) is None

    def test_returns_step_plan_object(self, seeded_db):
        plan = _make_plan()
        save_step_plan(plan, seeded_db)

        loaded = load_step_plan("plan-1", seeded_db)

        assert loaded is not None
        assert isinstance(loaded, StepPlan)
        assert loaded.id == "plan-1"
        assert loaded.project_id == "proj-1"
        assert loaded.description == "Build a REST API with auth"
        assert loaded.status == "pending"

    def test_created_at_is_datetime(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        loaded = load_step_plan("plan-1", seeded_db)
        assert isinstance(loaded.created_at, datetime)
        assert loaded.created_at == NOW

    def test_loads_with_empty_steps_when_no_tasks(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        loaded = load_step_plan("plan-1", seeded_db)
        assert loaded.steps == []

    def test_loads_plan_with_step_tasks(self, seeded_db):
        plan = _make_plan()
        save_step_plan(plan, seeded_db)
        t1 = _make_task("t-1", step_number=1)
        t2 = _make_task("t-2", step_number=2)
        save_step_task(t1, seeded_db)
        save_step_task(t2, seeded_db)

        loaded = load_step_plan("plan-1", seeded_db)

        assert len(loaded.steps) == 2
        assert loaded.steps[0].id == "t-1"
        assert loaded.steps[1].id == "t-2"

    def test_steps_ordered_by_step_number(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        # Save out-of-order
        save_step_task(_make_task("t-3", step_number=3), seeded_db)
        save_step_task(_make_task("t-1", step_number=1), seeded_db)
        save_step_task(_make_task("t-2", step_number=2), seeded_db)

        loaded = load_step_plan("plan-1", seeded_db)
        numbers = [s.step_number for s in loaded.steps]
        assert numbers == [1, 2, 3]

    def test_final_evaluation_deserialised(self, seeded_db):
        payload = {"success": False, "summary": "Partial", "missing": ["auth"]}
        plan = _make_plan()
        plan = plan.model_copy(update={"final_evaluation": payload})
        save_step_plan(plan, seeded_db)

        loaded = load_step_plan("plan-1", seeded_db)
        assert loaded.final_evaluation == payload


# ---------------------------------------------------------------------------
# load_step_plans_for_message
# ---------------------------------------------------------------------------

class TestLoadStepPlansForMessage:
    def test_returns_empty_list_when_none_exist(self, seeded_db):
        assert load_step_plans_for_message("msg-1", seeded_db) == []

    def test_returns_plans_for_message(self, seeded_db):
        msg2 = ProjectMessage(
            id="msg-2", project_id="proj-1", content="Q2", role="user", created_at=NOW
        )
        save_project_message(seeded_db, msg2)

        save_step_plan(_make_plan("plan-1"), seeded_db)
        save_step_plan(_make_plan("plan-2"), seeded_db)
        save_step_plan(_make_plan("plan-X", message_id="msg-2"), seeded_db)

        plans = load_step_plans_for_message("msg-1", seeded_db)
        assert len(plans) == 2
        ids = {p.id for p in plans}
        assert ids == {"plan-1", "plan-2"}

    def test_does_not_include_other_message_plans(self, seeded_db):
        msg2 = ProjectMessage(
            id="msg-2", project_id="proj-1", content="Q", role="user", created_at=NOW
        )
        save_project_message(seeded_db, msg2)
        save_step_plan(_make_plan("plan-A", message_id="msg-2"), seeded_db)

        plans = load_step_plans_for_message("msg-1", seeded_db)
        assert plans == []


# ---------------------------------------------------------------------------
# update_step_plan_status
# ---------------------------------------------------------------------------

class TestUpdateStepPlanStatus:
    def test_updates_status(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        update_step_plan_status("plan-1", "running", seeded_db)

        loaded = load_step_plan("plan-1", seeded_db)
        assert loaded.status == "running"

    def test_updates_completed_at(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        update_step_plan_status("plan-1", "completed", seeded_db, completed_at=NOW)

        conn = sqlite3.connect(str(seeded_db))
        raw = conn.execute("SELECT completed_at FROM step_plans WHERE id='plan-1'").fetchone()[0]
        conn.close()
        assert raw == NOW_ISO

    def test_updates_final_evaluation_json_roundtrip(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        eval_data = {"success": True, "summary": "All steps passed", "suggestions": []}
        update_step_plan_status(
            "plan-1", "completed", seeded_db,
            completed_at=NOW, final_evaluation=eval_data
        )

        loaded = load_step_plan("plan-1", seeded_db)
        assert loaded.final_evaluation == eval_data

    def test_does_not_overwrite_existing_completed_at_when_none(self, seeded_db):
        plan = _make_plan()
        plan = plan.model_copy(update={"completed_at": NOW, "status": "completed"})
        save_step_plan(plan, seeded_db)

        # Update status only — completed_at should stay
        update_step_plan_status("plan-1", "failed", seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        raw = conn.execute("SELECT completed_at FROM step_plans WHERE id='plan-1'").fetchone()[0]
        conn.close()
        assert raw == NOW_ISO  # unchanged


# ---------------------------------------------------------------------------
# delete_step_plan
# ---------------------------------------------------------------------------

class TestDeleteStepPlan:
    def test_removes_plan_row(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        delete_step_plan("plan-1", seeded_db)

        assert load_step_plan("plan-1", seeded_db) is None

    def test_removes_associated_step_tasks(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)
        save_step_task(_make_task("t-2", step_number=2), seeded_db)

        delete_step_plan("plan-1", seeded_db)

        remaining = load_step_tasks_for_plan("plan-1", seeded_db)
        assert remaining == []

    def test_does_not_affect_other_plans(self, seeded_db):
        msg2 = ProjectMessage(
            id="msg-2", project_id="proj-1", content="Q", role="user", created_at=NOW
        )
        save_project_message(seeded_db, msg2)
        save_step_plan(_make_plan("plan-1"), seeded_db)
        save_step_plan(_make_plan("plan-2", message_id="msg-2"), seeded_db)

        delete_step_plan("plan-1", seeded_db)

        assert load_step_plan("plan-2", seeded_db) is not None

    def test_delete_nonexistent_is_silent(self, db_path):
        delete_step_plan("ghost-plan", db_path)  # must not raise


# ---------------------------------------------------------------------------
# save_step_task
# ---------------------------------------------------------------------------

class TestSaveStepTask:
    def test_creates_row_in_db(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        row = conn.execute("SELECT * FROM step_tasks WHERE id = 't-1'").fetchone()
        conn.close()
        assert row is not None

    def test_stores_all_required_fields(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1", step_number=3), seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM step_tasks WHERE id='t-1'").fetchone())
        conn.close()

        assert row["id"] == "t-1"
        assert row["plan_id"] == "plan-1"
        assert row["step_number"] == 3
        assert row["status"] == "pending"
        assert row["created_at"] == NOW_ISO

    def test_stores_optional_fields(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        task = _make_task("t-1")
        task = task.model_copy(update={
            "cli_used": "claude",
            "model_used": "claude-sonnet-4-6",
            "output": "Done!",
            "tokens_used": 512,
            "duration_ms": 3000,
            "status": "success",
            "started_at": NOW,
            "completed_at": NOW,
        })
        save_step_task(task, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM step_tasks WHERE id='t-1'").fetchone())
        conn.close()

        assert row["cli_used"] == "claude"
        assert row["model_used"] == "claude-sonnet-4-6"
        assert row["output"] == "Done!"
        assert row["tokens_used"] == 512
        assert row["duration_ms"] == 3000
        assert row["started_at"] == NOW_ISO
        assert row["completed_at"] == NOW_ISO

    def test_upsert_overwrites_existing_row(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        updated = _make_task("t-1")
        updated = updated.model_copy(update={"status": "success", "output": "result"})
        save_step_task(updated, seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        row = conn.execute("SELECT status, output FROM step_tasks WHERE id='t-1'").fetchone()
        conn.close()
        assert row[0] == "success"
        assert row[1] == "result"


# ---------------------------------------------------------------------------
# load_step_tasks_for_plan
# ---------------------------------------------------------------------------

class TestLoadStepTasksForPlan:
    def test_returns_empty_list_when_none(self, seeded_db):
        assert load_step_tasks_for_plan("plan-1", seeded_db) == []

    def test_returns_step_task_objects(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1", step_number=1), seeded_db)

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert len(tasks) == 1
        assert isinstance(tasks[0], StepTask)
        assert tasks[0].id == "t-1"

    def test_ordered_by_step_number_ascending(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        # Insert deliberately out of order
        save_step_task(_make_task("t-3", step_number=3), seeded_db)
        save_step_task(_make_task("t-1", step_number=1), seeded_db)
        save_step_task(_make_task("t-2", step_number=2), seeded_db)

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert [t.step_number for t in tasks] == [1, 2, 3]
        assert [t.id for t in tasks] == ["t-1", "t-2", "t-3"]

    def test_does_not_return_tasks_of_other_plan(self, seeded_db):
        msg2 = ProjectMessage(
            id="msg-2", project_id="proj-1", content="Q", role="user", created_at=NOW
        )
        save_project_message(seeded_db, msg2)
        save_step_plan(_make_plan("plan-1"), seeded_db)
        save_step_plan(_make_plan("plan-2", message_id="msg-2"), seeded_db)

        save_step_task(_make_task("t-A", plan_id="plan-1", step_number=1), seeded_db)
        save_step_task(_make_task("t-B", plan_id="plan-2", step_number=1), seeded_db)

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert len(tasks) == 1
        assert tasks[0].id == "t-A"

    def test_created_at_is_datetime(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert isinstance(tasks[0].created_at, datetime)
        assert tasks[0].created_at == NOW


# ---------------------------------------------------------------------------
# update_step_task_status
# ---------------------------------------------------------------------------

class TestUpdateStepTaskStatus:
    def test_updates_status(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        update_step_task_status("t-1", "running", seeded_db)

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert tasks[0].status == "running"

    def test_updates_only_provided_fields(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        task = _make_task("t-1")
        task = task.model_copy(update={"cli_used": "original-cli", "output": "original-out"})
        save_step_task(task, seeded_db)

        # Update status only — other fields must be unchanged
        update_step_task_status("t-1", "running", seeded_db)

        conn = sqlite3.connect(str(seeded_db))
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM step_tasks WHERE id='t-1'").fetchone())
        conn.close()
        assert row["status"] == "running"
        assert row["cli_used"] == "original-cli"
        assert row["output"] == "original-out"

    def test_updates_multiple_kwargs(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        update_step_task_status(
            "t-1", "success", seeded_db,
            cli_used="claude",
            model_used="claude-sonnet-4-6",
            output="Task done",
            tokens_used=300,
            duration_ms=5000,
            started_at=NOW,
            completed_at=NOW,
        )

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        t = tasks[0]
        assert t.status == "success"
        assert t.cli_used == "claude"
        assert t.model_used == "claude-sonnet-4-6"
        assert t.output == "Task done"
        assert t.tokens_used == 300
        assert t.duration_ms == 5000
        assert t.started_at == NOW
        assert t.completed_at == NOW

    def test_datetime_kwargs_serialised_correctly(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        update_step_task_status("t-1", "running", seeded_db, started_at=NOW)

        conn = sqlite3.connect(str(seeded_db))
        raw = conn.execute("SELECT started_at FROM step_tasks WHERE id='t-1'").fetchone()[0]
        conn.close()
        assert raw == NOW_ISO

    def test_error_field_updated(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        update_step_task_status("t-1", "failed", seeded_db, error="CLI returned exit code 2")

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert tasks[0].error == "CLI returned exit code 2"

    def test_unknown_kwargs_are_ignored(self, seeded_db):
        save_step_plan(_make_plan(), seeded_db)
        save_step_task(_make_task("t-1"), seeded_db)

        # Should not raise, unknown key is silently dropped
        update_step_task_status("t-1", "running", seeded_db, nonexistent_field="oops")
