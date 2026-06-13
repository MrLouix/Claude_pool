"""Plan generator for the Multi-Step Coding Planner skill.

Calls the configured AI CLI to decompose a user request into 3-8 executable steps,
then returns an unsaved StepPlan with its StepTask list populated.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from team_cli.cli_executors import build_claude_cmd
from .models import StepPlan, StepTask
from .utils import (
    generate_id,
    now_utc,
    validate_and_parse_plan_json,
    validate_prompt_length,
)

logger = logging.getLogger(__name__)

_GENERATION_TIMEOUT = 30.0  # seconds

_SYSTEM_PROMPT_TEMPLATE = """\
You are a software development expert. The user wants to accomplish the following task:
"{user_request}"

Strict rules:
1. Decompose this task into exactly 3 to 8 steps (no fewer, no more).
2. Each step must be a precise, actionable objective that can be completed by a single AI CLI call.
3. Write each step as a direct instruction (e.g. "Create a Python User class with SQLAlchemy...").

Output format: Return ONLY a valid JSON object with the following structure (no markdown, no explanation):
{{
  "steps": [
    {{"id": 1, "description": "[short description]", "prompt": "[detailed instruction]"}},
    ...
  ]
}}"""


class PlanGenerator:
    """Calls an AI CLI to generate a step-by-step coding plan from a user request.

    The returned StepPlan is not persisted — the caller is responsible for
    saving it to the database via ``save_step_plan`` / ``save_step_task``.
    """

    def __init__(
        self,
        cli_path: str = "claude",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.cli_path = cli_path
        self.model = model

    async def generate(
        self,
        user_request: str,
        project_id: str,
        message_id: str,
    ) -> StepPlan:
        """Generate a StepPlan from *user_request*.

        Args:
            user_request: The user's description of what they want to build.
            project_id: ID of the owning project (stored on the plan).
            message_id: ID of the chat message that triggered this plan.

        Returns:
            A StepPlan (status=``"pending"``) with its ``steps`` list populated.
            Neither the plan nor its tasks are saved to the database.

        Raises:
            ValueError: If *user_request* is too long or the CLI returns invalid JSON.
            RuntimeError: If the CLI exits with a non-zero exit code or times out.
        """
        validate_prompt_length(user_request)

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(user_request=user_request)

        cmd = build_claude_cmd(self.cli_path, system_prompt, self.model)

        logger.info("[planner/generator] CLI command: %s", shlex.join(cmd))

        stdout_bytes, stderr_bytes = await self._run_cli(cmd)

        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        logger.info("[planner/generator] stdout=%r stderr=%r", stdout_text[:2000], stderr_text[:500])
        if not stdout_text:
            raise RuntimeError(
                f"CLI returned no output. stderr: {stderr_text!r}"
            )

        plan_data = validate_and_parse_plan_json(stdout_text)

        return self._build_plan(plan_data, project_id, message_id, user_request)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_cli(self, cmd: list[str]) -> tuple[bytes, bytes]:
        """Spawn *cmd* and return (stdout, stderr) bytes.

        Raises:
            RuntimeError: On non-zero exit code or timeout.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_GENERATION_TIMEOUT,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(
                f"Plan generation timed out after {_GENERATION_TIMEOUT:.0f} seconds"
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"CLI exited with code {proc.returncode}. stderr: {stderr_text!r}"
            )

        return stdout, stderr

    def _build_plan(
        self,
        plan_data: dict[str, Any],
        project_id: str,
        message_id: str,
        user_request: str,
    ) -> StepPlan:
        """Construct a StepPlan (and its StepTask list) from validated plan_data."""
        plan_id = generate_id()
        created = now_utc()

        steps: list[StepTask] = []
        for raw_step in plan_data["steps"]:
            task = StepTask(
                id=generate_id(),
                plan_id=plan_id,
                step_number=int(raw_step["id"]),
                description=str(raw_step["description"]),
                prompt=str(raw_step["prompt"]),
                status="pending",
                created_at=created,
            )
            steps.append(task)

        return StepPlan(
            id=plan_id,
            project_id=project_id,
            message_id=message_id,
            description=user_request[:500],  # store a truncated version as description
            status="pending",
            created_at=created,
            steps=steps,
        )
