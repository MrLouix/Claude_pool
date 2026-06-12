"""StepTask executor for the Multi-Step Coding Planner skill.

Runs each StepTask sequentially against the configured AI CLI, persists
status changes to the database, and triggers global evaluation once all
steps reach a terminal state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from team_cli.executor import _RATE_LIMIT_PATTERNS
from team_cli.storage import (
    load_step_tasks_for_plan,
    update_step_plan_status,
    update_step_task_status,
)

from .evaluator import PlanEvaluator
from .models import StepPlan, StepTask
from .utils import now_utc

logger = logging.getLogger(__name__)

_STEP_TIMEOUT = 30 * 60  # 30 minutes per step

_TERMINAL_STATUSES = frozenset({"success", "failed"})


class StepTaskExecutor:
    """Executes each StepTask via CLI, persists results, and drives plan evaluation."""

    def __init__(
        self,
        db_path: str | Path,
        cli_path: str = "claude",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.db_path = Path(db_path)
        self.cli_path = cli_path
        self.model = model
        self._evaluator = PlanEvaluator(cli_path=cli_path, model=model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_step(self, task: StepTask) -> StepTask:
        """Run a single StepTask and persist its result.

        Args:
            task: The task to execute.

        Returns:
            The updated task (with final status, output/error, duration).
        """
        started_at = now_utc()
        await asyncio.to_thread(
            update_step_task_status,
            task.id, "running", self.db_path,
            started_at=started_at,
        )

        cmd = [
            self.cli_path,
            "-p",
            task.prompt,
            "--output-format",
            "json",
            "--structured-output",
            "--model",
            self.model,
        ]

        t0 = time.monotonic()
        stdout_text = ""
        stderr_text = ""
        exit_code: int | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=_STEP_TIMEOUT,
                )
                exit_code = proc.returncode
                stdout_text = stdout_b.decode("utf-8", errors="replace")
                stderr_text = stderr_b.decode("utf-8", errors="replace")
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                exit_code = -1
                stderr_text = f"Task timed out after {_STEP_TIMEOUT // 60} minutes"
        except Exception as exc:
            exit_code = -1
            stderr_text = f"Execution error: {exc}"

        duration_ms = int((time.monotonic() - t0) * 1000)
        completed_at = now_utc()
        status = self._classify(exit_code, stdout_text, stderr_text)

        if status == "success":
            await asyncio.to_thread(
                update_step_task_status,
                task.id, "success", self.db_path,
                output=stdout_text or None,
                duration_ms=duration_ms,
                completed_at=completed_at,
                cli_used=self.cli_path,
                model_used=self.model,
            )
        else:
            await asyncio.to_thread(
                update_step_task_status,
                task.id, status, self.db_path,
                error=stderr_text or stdout_text or None,
                duration_ms=duration_ms,
                completed_at=completed_at,
                cli_used=self.cli_path,
                model_used=self.model,
            )

        return task.model_copy(update={
            "status": status,
            "output": stdout_text or None if status == "success" else None,
            "error": stderr_text or stdout_text or None if status != "success" else None,
            "duration_ms": duration_ms,
            "started_at": started_at,
            "completed_at": completed_at,
            "cli_used": self.cli_path,
            "model_used": self.model,
        })

    async def execute_plan(
        self,
        plan: StepPlan,
        broadcast_fn: Callable[..., Any] | None = None,
    ) -> StepPlan:
        """Execute all steps of *plan* sequentially and trigger completion checks.

        Args:
            plan: The plan whose steps will be executed.
            broadcast_fn: Optional callable invoked after each step with
                ``(event_type: str, data: dict)``.  May be a plain function
                or a coroutine function.

        Returns:
            The reloaded StepPlan after all steps and evaluation are done.
        """
        await asyncio.to_thread(
            update_step_plan_status,
            plan.id, "running", self.db_path,
        )

        sorted_steps = sorted(plan.steps, key=lambda s: s.step_number)

        for step in sorted_steps:
            updated = await self.execute_step(step)
            await self._broadcast(broadcast_fn, "step_task_updated", {
                "task_id": updated.id,
                "plan_id": updated.plan_id,
                "step_number": updated.step_number,
                "description": updated.description,
                "status": updated.status,
                "cli_used": updated.cli_used,
                "duration_ms": updated.duration_ms,
            })

        await self._check_plan_completion(plan)

        from team_cli.storage import load_step_plan
        reloaded = await asyncio.to_thread(load_step_plan, plan.id, self.db_path)
        return reloaded if reloaded is not None else plan

    # ------------------------------------------------------------------
    # Completion / evaluation
    # ------------------------------------------------------------------

    async def _check_plan_completion(self, plan: StepPlan) -> None:
        """Inspect DB task statuses and trigger evaluation if all are terminal."""
        steps = await asyncio.to_thread(
            load_step_tasks_for_plan, plan.id, self.db_path
        )

        if not steps:
            return

        all_terminal = all(s.status in _TERMINAL_STATUSES for s in steps)
        if not all_terminal:
            return

        await self._trigger_global_evaluation(plan, steps)

        any_failed = any(s.status == "failed" for s in steps)
        final_status = "failed" if any_failed else "completed"

        await asyncio.to_thread(
            update_step_plan_status,
            plan.id, final_status, self.db_path,
            completed_at=now_utc(),
        )

    async def _trigger_global_evaluation(
        self, plan: StepPlan, steps: list[StepTask]
    ) -> None:
        """Call PlanEvaluator and persist the result; log on failure."""
        try:
            evaluation = await self._evaluator.evaluate(plan, steps)
        except Exception as exc:
            logger.warning("Plan evaluation failed for %s: %s", plan.id, exc)
            evaluation = {
                "success": False,
                "summary": f"Evaluation failed: {exc}",
            }

        await asyncio.to_thread(
            update_step_plan_status,
            plan.id, "running", self.db_path,
            final_evaluation=evaluation,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(exit_code: int | None, stdout: str, stderr: str) -> str:
        """Map CLI exit code + output to a StepTask status string."""
        if exit_code == 0:
            return "success"
        if exit_code == 1:
            combined = (stdout + stderr).lower()
            if any(p in combined for p in _RATE_LIMIT_PATTERNS):
                return "rate_limit"
        return "failed"

    @staticmethod
    async def _broadcast(
        fn: Callable[..., Any] | None,
        event: str,
        data: dict[str, Any],
    ) -> None:
        """Call *fn(event, data)*, awaiting it if it is a coroutine function."""
        if fn is None:
            return
        result = fn(event, data)
        if asyncio.iscoroutine(result):
            await result
