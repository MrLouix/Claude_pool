"""Unit tests for StepTaskExecutor and PlanEvaluator (Step 5)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from team_cli.database import DatabaseManager
from team_cli.models import Project, ProjectMessage
from team_cli.skills.multi_step_planner.evaluator import PlanEvaluator
from team_cli.skills.multi_step_planner.executor import StepTaskExecutor
from team_cli.skills.multi_step_planner.models import StepPlan, StepTask
from team_cli.storage import (
    load_step_plan,
    load_step_tasks_for_plan,
    save_project,
    save_project_message,
    save_step_plan,
    save_step_task,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "pool.db"
    asyncio.run(DatabaseManager(path).init())
    return path


@pytest.fixture
def seeded_db(db_path: Path) -> Path:
    """DB with a project + message so FK constraints are satisfied."""
    save_project(db_path, Project(
        id="proj-1", name="Test", directory="/tmp", created_at=NOW,
    ))
    save_project_message(db_path, ProjectMessage(
        id="msg-1", project_id="proj-1", content="Build API", role="user", created_at=NOW,
    ))
    return db_path


def _make_plan(db_path: Path, plan_id: str = "plan-1") -> StepPlan:
    plan = StepPlan(
        id=plan_id,
        project_id="proj-1",
        message_id="msg-1",
        description="Build a REST API",
        status="pending",
        created_at=NOW,
    )
    save_step_plan(plan, db_path)
    return plan


def _make_task(
    db_path: Path,
    task_id: str,
    plan_id: str = "plan-1",
    step_number: int = 1,
    status: str = "pending",
) -> StepTask:
    task = StepTask(
        id=task_id,
        plan_id=plan_id,
        step_number=step_number,
        description=f"Step {step_number}",
        prompt=f"Do step {step_number}",
        status=status,
        created_at=NOW,
    )
    save_step_task(task, db_path)
    return task


def _mock_proc(stdout: bytes, returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


def _patch_subprocess(proc: MagicMock, module: str = "executor"):
    """Patch asyncio.create_subprocess_exec in the given skill module."""
    target = f"team_cli.skills.multi_step_planner.{module}.asyncio.create_subprocess_exec"
    return patch(target, new=AsyncMock(return_value=proc))


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# StepTaskExecutor.execute_step — success
# ---------------------------------------------------------------------------

class TestExecuteStepSuccess:
    def test_returns_step_task_object(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1", step_number=1)
        proc = _mock_proc(stdout=b'{"result": "done"}', returncode=0)

        executor = StepTaskExecutor(db_path=seeded_db)
        with _patch_subprocess(proc):
            result = _run(executor.execute_step(task))

        assert isinstance(result, StepTask)

    def test_status_is_success_on_exit_0(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b'{"result": "done"}', returncode=0)

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.status == "success"

    def test_output_stored_on_success(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b'{"result": "created user.py"}', returncode=0)

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.output is not None
        assert "created user.py" in result.output

    def test_duration_ms_populated(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"ok", returncode=0)

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    def test_cli_used_and_model_populated(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"ok", returncode=0)

        executor = StepTaskExecutor(seeded_db, cli_path="claude", model="claude-sonnet-4-6")
        with _patch_subprocess(proc):
            result = _run(executor.execute_step(task))

        assert result.cli_used == "claude"
        assert result.model_used == "claude-sonnet-4-6"

    def test_db_updated_to_success(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"output text", returncode=0)

        with _patch_subprocess(proc):
            _run(StepTaskExecutor(seeded_db).execute_step(task))

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert tasks[0].status == "success"

    def test_started_at_and_completed_at_set(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"ok", returncode=0)

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.started_at is not None
        assert result.completed_at is not None


# ---------------------------------------------------------------------------
# StepTaskExecutor.execute_step — failure
# ---------------------------------------------------------------------------

class TestExecuteStepFailure:
    def test_status_is_failed_on_exit_2(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"", returncode=2, stderr=b"fatal error")

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.status == "failed"

    def test_status_is_failed_on_exit_minus1(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"", returncode=-1, stderr=b"killed")

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.status == "failed"

    def test_error_stored_on_failure(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"", returncode=2, stderr=b"syntax error on line 3")

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.error is not None
        assert "syntax error" in result.error

    def test_db_updated_to_failed(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"", returncode=3, stderr=b"error")

        with _patch_subprocess(proc):
            _run(StepTaskExecutor(seeded_db).execute_step(task))

        tasks = load_step_tasks_for_plan("plan-1", seeded_db)
        assert tasks[0].status == "failed"


# ---------------------------------------------------------------------------
# StepTaskExecutor.execute_step — rate_limit
# ---------------------------------------------------------------------------

class TestExecuteStepRateLimit:
    def test_status_is_rate_limit_on_exit_1_with_pattern(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(
            stdout=b"", returncode=1, stderr=b"You've hit your rate limit"
        )

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.status == "rate_limit"

    def test_status_is_rate_limit_for_various_patterns(self, seeded_db):
        patterns = [
            b"rate limit exceeded",
            b"too many requests",
            b"quota exceeded",
            b"session limit reached",
        ]
        for stderr_msg in patterns:
            plan_id = f"plan-{stderr_msg[:4].hex()}"
            # Need separate plan per iteration to avoid FK issues with same message
            plan = StepPlan(
                id=plan_id, project_id="proj-1", message_id="msg-1",
                description="d", status="pending", created_at=NOW,
            )
            save_step_plan(plan, seeded_db)
            task = StepTask(
                id=f"t-{plan_id}", plan_id=plan_id, step_number=1,
                description="d", prompt="p", status="pending", created_at=NOW,
            )
            save_step_task(task, seeded_db)
            proc = _mock_proc(stdout=b"", returncode=1, stderr=stderr_msg)
            with _patch_subprocess(proc):
                result = _run(StepTaskExecutor(seeded_db).execute_step(task))
            assert result.status == "rate_limit", f"Expected rate_limit for {stderr_msg}"

    def test_status_is_failed_on_exit_1_without_rate_limit(self, seeded_db):
        _make_plan(seeded_db)
        task = _make_task(seeded_db, "t-1")
        proc = _mock_proc(stdout=b"", returncode=1, stderr=b"internal server error")

        with _patch_subprocess(proc):
            result = _run(StepTaskExecutor(seeded_db).execute_step(task))

        assert result.status == "failed"


# ---------------------------------------------------------------------------
# StepTaskExecutor._check_plan_completion
# ---------------------------------------------------------------------------

class TestCheckPlanCompletion:
    def test_triggers_evaluation_when_all_steps_terminal(self, seeded_db):
        plan = _make_plan(seeded_db)
        _make_task(seeded_db, "t-1", step_number=1, status="success")
        _make_task(seeded_db, "t-2", step_number=2, status="failed")

        # Patch the evaluator so no real CLI is called
        eval_result = {"success": False, "summary": "Partial"}
        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(return_value=eval_result)

        _run(executor._check_plan_completion(plan))

        reloaded = load_step_plan("plan-1", seeded_db)
        assert reloaded.status in ("completed", "failed")

    def test_does_not_trigger_evaluation_when_step_pending(self, seeded_db):
        plan = _make_plan(seeded_db)
        _make_task(seeded_db, "t-1", step_number=1, status="success")
        _make_task(seeded_db, "t-2", step_number=2, status="pending")

        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(return_value={"success": True, "summary": "ok"})

        _run(executor._check_plan_completion(plan))

        # evaluate must NOT have been called
        executor._evaluator.evaluate.assert_not_called()

    def test_does_not_trigger_evaluation_when_step_running(self, seeded_db):
        plan = _make_plan(seeded_db)
        _make_task(seeded_db, "t-1", step_number=1, status="success")
        _make_task(seeded_db, "t-2", step_number=2, status="running")

        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(return_value={"success": True, "summary": "ok"})

        _run(executor._check_plan_completion(plan))
        executor._evaluator.evaluate.assert_not_called()

    def test_plan_status_completed_when_all_succeed(self, seeded_db):
        plan = _make_plan(seeded_db)
        _make_task(seeded_db, "t-1", step_number=1, status="success")
        _make_task(seeded_db, "t-2", step_number=2, status="success")

        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": True, "summary": "All good"}
        )

        _run(executor._check_plan_completion(plan))

        reloaded = load_step_plan("plan-1", seeded_db)
        assert reloaded.status == "completed"

    def test_plan_status_failed_when_any_step_failed(self, seeded_db):
        plan = _make_plan(seeded_db)
        _make_task(seeded_db, "t-1", step_number=1, status="success")
        _make_task(seeded_db, "t-2", step_number=2, status="failed")

        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": False, "summary": "Step 2 failed"}
        )

        _run(executor._check_plan_completion(plan))

        reloaded = load_step_plan("plan-1", seeded_db)
        assert reloaded.status == "failed"

    def test_noop_when_no_tasks(self, seeded_db):
        plan = _make_plan(seeded_db)  # no tasks saved

        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock()

        _run(executor._check_plan_completion(plan))
        executor._evaluator.evaluate.assert_not_called()

    def test_final_evaluation_stored_in_db(self, seeded_db):
        plan = _make_plan(seeded_db)
        _make_task(seeded_db, "t-1", step_number=1, status="success")

        eval_data = {"success": True, "summary": "Done", "missing": [], "suggestions": []}
        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(return_value=eval_data)

        _run(executor._check_plan_completion(plan))

        reloaded = load_step_plan("plan-1", seeded_db)
        assert reloaded.final_evaluation == eval_data


# ---------------------------------------------------------------------------
# StepTaskExecutor.execute_plan
# ---------------------------------------------------------------------------

class TestExecutePlan:
    def _make_full_plan(self, seeded_db: Path) -> StepPlan:
        plan = _make_plan(seeded_db)
        t1 = _make_task(seeded_db, "t-1", step_number=1)
        t2 = _make_task(seeded_db, "t-2", step_number=2)
        return plan.model_copy(update={"steps": [t1, t2]})

    def test_returns_step_plan(self, seeded_db):
        plan = self._make_full_plan(seeded_db)
        proc = _mock_proc(stdout=b"ok", returncode=0)
        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": True, "summary": "done"}
        )

        with _patch_subprocess(proc):
            result = _run(executor.execute_plan(plan))

        assert isinstance(result, StepPlan)

    def test_plan_status_running_at_start(self, seeded_db):
        plan = _make_plan(seeded_db)
        plan = plan.model_copy(update={"steps": [_make_task(seeded_db, "t-1")]})
        _mock_proc(stdout=b"ok", returncode=0)

        status_snapshots: list[str] = []

        async def mock_exec_step(task):
            # Snapshot plan status mid-execution
            reloaded = load_step_plan("plan-1", seeded_db)
            status_snapshots.append(reloaded.status if reloaded else "?")
            return task.model_copy(update={"status": "success"})

        executor = StepTaskExecutor(seeded_db)
        executor.execute_step = mock_exec_step
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": True, "summary": "done"}
        )

        _run(executor.execute_plan(plan))
        assert "running" in status_snapshots

    def test_broadcast_fn_called_after_each_step(self, seeded_db):
        plan = self._make_full_plan(seeded_db)
        events: list[tuple[str, dict]] = []

        def broadcast(event, data):
            events.append((event, data))

        proc = _mock_proc(stdout=b"ok", returncode=0)
        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": True, "summary": "done"}
        )

        with _patch_subprocess(proc):
            _run(executor.execute_plan(plan, broadcast_fn=broadcast))

        step_events = [e for e in events if e[0] == "step_task_updated"]
        assert len(step_events) == 2

    def test_async_broadcast_fn_is_awaited(self, seeded_db):
        plan = _make_plan(seeded_db)
        plan = plan.model_copy(update={"steps": [_make_task(seeded_db, "t-1")]})
        called: list[bool] = []

        async def async_broadcast(event, data):
            called.append(True)

        proc = _mock_proc(stdout=b"ok", returncode=0)
        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": True, "summary": "done"}
        )

        with _patch_subprocess(proc):
            _run(executor.execute_plan(plan, broadcast_fn=async_broadcast))

        assert len(called) == 1

    def test_steps_executed_in_order(self, seeded_db):
        plan = _make_plan(seeded_db)
        t1 = _make_task(seeded_db, "t-1", step_number=1)
        t2 = _make_task(seeded_db, "t-2", step_number=2)
        t3 = _make_task(seeded_db, "t-3", step_number=3)
        # Put steps in reverse order to verify sorting
        plan = plan.model_copy(update={"steps": [t3, t1, t2]})

        executed_order: list[int] = []

        async def mock_exec(task: StepTask) -> StepTask:
            executed_order.append(task.step_number)
            return task.model_copy(update={"status": "success"})

        executor = StepTaskExecutor(seeded_db)
        executor.execute_step = mock_exec
        executor._evaluator.evaluate = AsyncMock(
            return_value={"success": True, "summary": "ok"}
        )

        _run(executor.execute_plan(plan))
        assert executed_order == [1, 2, 3]


# ---------------------------------------------------------------------------
# PlanEvaluator.evaluate
# ---------------------------------------------------------------------------

class TestPlanEvaluatorEvaluate:
    def _make_plan_and_steps(self) -> tuple[StepPlan, list[StepTask]]:
        plan = StepPlan(
            id="plan-1", project_id="proj-1", message_id="msg-1",
            description="Build a REST API", status="running", created_at=NOW,
        )
        steps = [
            StepTask(
                id="t-1", plan_id="plan-1", step_number=1,
                description="Step 1", prompt="Do step 1",
                status="success", output="Created user.py",
                created_at=NOW,
            ),
            StepTask(
                id="t-2", plan_id="plan-1", step_number=2,
                description="Step 2", prompt="Do step 2",
                status="failed", error="ImportError: no module named xyz",
                created_at=NOW,
            ),
        ]
        return plan, steps

    def _patch_eval_subprocess(self, proc: MagicMock):
        return patch(
            "team_cli.skills.multi_step_planner.evaluator.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        )

    def test_returns_dict_on_valid_response(self):
        plan, steps = self._make_plan_and_steps()
        payload = {"success": False, "summary": "Step 2 failed", "missing": ["auth"], "suggestions": []}
        proc = _mock_proc(stdout=json.dumps(payload).encode(), returncode=0)

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            result = _run(evaluator.evaluate(plan, steps))

        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["summary"] == "Step 2 failed"

    def test_success_true_response(self):
        plan, steps = self._make_plan_and_steps()
        payload = {"success": True, "summary": "All steps passed", "missing": [], "suggestions": []}
        proc = _mock_proc(stdout=json.dumps(payload).encode(), returncode=0)

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            result = _run(evaluator.evaluate(plan, steps))

        assert result["success"] is True

    def test_accepts_markdown_fenced_json(self):
        plan, steps = self._make_plan_and_steps()
        payload = {"success": True, "summary": "Done"}
        fenced = f"```json\n{json.dumps(payload)}\n```"
        proc = _mock_proc(stdout=fenced.encode(), returncode=0)

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            result = _run(evaluator.evaluate(plan, steps))

        assert result["success"] is True

    def test_raises_value_error_on_malformed_json(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(stdout=b"{bad json", returncode=0)

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            with pytest.raises(ValueError, match="Invalid evaluation JSON"):
                _run(evaluator.evaluate(plan, steps))

    def test_raises_value_error_on_missing_success_field(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(stdout=json.dumps({"summary": "ok"}).encode(), returncode=0)

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            with pytest.raises(ValueError, match='"success"'):
                _run(evaluator.evaluate(plan, steps))

    def test_raises_value_error_on_missing_summary_field(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(stdout=json.dumps({"success": True}).encode(), returncode=0)

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            with pytest.raises(ValueError, match='"summary"'):
                _run(evaluator.evaluate(plan, steps))

    def test_raises_value_error_when_success_not_bool(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(
            stdout=json.dumps({"success": "yes", "summary": "ok"}).encode(),
            returncode=0,
        )

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            with pytest.raises(ValueError, match='"success"'):
                _run(evaluator.evaluate(plan, steps))

    def test_raises_runtime_error_on_nonzero_exit(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(stdout=b"", returncode=1, stderr=b"error")

        evaluator = PlanEvaluator()
        with self._patch_eval_subprocess(proc):
            with pytest.raises(RuntimeError, match="exit"):
                _run(evaluator.evaluate(plan, steps))

    def test_prompt_contains_plan_description(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(
            stdout=json.dumps({"success": True, "summary": "done"}).encode(),
            returncode=0,
        )
        mock_exec = AsyncMock(return_value=proc)

        evaluator = PlanEvaluator()
        with patch(
            "team_cli.skills.multi_step_planner.evaluator.asyncio.create_subprocess_exec",
            new=mock_exec,
        ):
            _run(evaluator.evaluate(plan, steps))

        # The prompt (third positional arg after cli and "-p") should contain the description
        call_args = mock_exec.call_args[0]
        prompt_arg = call_args[2]  # cli_path, "-p", <prompt>, ...
        assert "Build a REST API" in prompt_arg

    def test_prompt_includes_step_results(self):
        plan, steps = self._make_plan_and_steps()
        proc = _mock_proc(
            stdout=json.dumps({"success": True, "summary": "done"}).encode(),
            returncode=0,
        )
        mock_exec = AsyncMock(return_value=proc)

        evaluator = PlanEvaluator()
        with patch(
            "team_cli.skills.multi_step_planner.evaluator.asyncio.create_subprocess_exec",
            new=mock_exec,
        ):
            _run(evaluator.evaluate(plan, steps))

        call_args = mock_exec.call_args[0]
        prompt_arg = call_args[2]
        assert "Created user.py" in prompt_arg
        assert "ImportError" in prompt_arg

    def test_evaluation_failure_logged_gracefully_in_executor(self, seeded_db):
        """_trigger_global_evaluation should not propagate evaluation errors."""
        plan = _make_plan(seeded_db)
        steps = [_make_task(seeded_db, "t-1", status="success")]

        executor = StepTaskExecutor(seeded_db)
        executor._evaluator.evaluate = AsyncMock(side_effect=RuntimeError("CLI down"))

        # Should not raise
        _run(executor._trigger_global_evaluation(plan, steps))
