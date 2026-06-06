"""Global plan evaluator for the Multi-Step Coding Planner skill.

After all steps finish, PlanEvaluator calls the AI CLI with a summary of
every step's outcome and asks it to decide whether the original request was
fully resolved.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .models import StepPlan, StepTask
from .utils import _strip_code_fences

logger = logging.getLogger(__name__)

_EVALUATION_TIMEOUT = 30.0  # seconds

_EVALUATION_PROMPT_TEMPLATE = """\
Contexte :
- Besoin initial : {description}
- Résultats des étapes :
{step_results}

Mission : Évalue si le besoin initial a été complètement résolu.

Règles :
1. Sois critique et précis : ne valide pas si une étape essentielle a échoué.
2. Si résolu : success = true, summary = résumé clair.
3. Si non résolu : success = false, summary = explication, missing = liste des manquants, suggestions = actions correctives.

Retourne UNIQUEMENT un JSON valide :
{{"success": true/false, "summary": "[résumé en 1-2 phrases]", "missing": [...], "suggestions": [...]}}"""


class PlanEvaluator:
    """Calls an AI CLI to evaluate whether a plan's original goal was achieved."""

    def __init__(
        self,
        cli_path: str = "claude",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.cli_path = cli_path
        self.model = model

    async def evaluate(self, plan: StepPlan, steps: list[StepTask]) -> dict[str, Any]:
        """Ask the CLI to evaluate whether *plan*'s goal was fully accomplished.

        Args:
            plan: The completed StepPlan (used for its description).
            steps: All StepTask objects belonging to the plan.

        Returns:
            Parsed evaluation dict with at least ``"success"`` (bool) and
            ``"summary"`` (str) keys.

        Raises:
            ValueError: If the CLI returns malformed or invalid JSON.
            RuntimeError: If the CLI exits with a non-zero code or times out.
        """
        prompt = self._build_prompt(plan, steps)

        cmd = [
            self.cli_path,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--structured-output",
            "--model",
            self.model,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_EVALUATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(
                f"Plan evaluation timed out after {_EVALUATION_TIMEOUT:.0f} seconds"
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Evaluation CLI exited with code {proc.returncode}. stderr: {stderr_text!r}"
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        return self._parse_response(stdout_text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, plan: StepPlan, steps: list[StepTask]) -> str:
        sorted_steps = sorted(steps, key=lambda s: s.step_number)
        lines: list[str] = []
        for step in sorted_steps:
            if step.status == "success":
                outcome = f"Étape {step.step_number} (succès) : {step.output or '(no output)'}"
            else:
                outcome = f"Étape {step.step_number} (échec) : Erreur : {step.error or '(no error details)'}"
            lines.append(f"  {outcome}")
        step_results = "\n".join(lines)
        return _EVALUATION_PROMPT_TEMPLATE.format(
            description=plan.description,
            step_results=step_results,
        )

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse and validate the evaluation JSON response."""
        cleaned = _strip_code_fences(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid evaluation JSON from CLI: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Evaluation response must be a JSON object, got {type(data).__name__}"
            )
        if "success" not in data or not isinstance(data["success"], bool):
            raise ValueError(
                'Evaluation JSON missing required "success" boolean field'
            )
        if "summary" not in data or not isinstance(data["summary"], str):
            raise ValueError(
                'Evaluation JSON missing required "summary" string field'
            )

        return data
