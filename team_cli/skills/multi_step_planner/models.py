"""Pydantic models for the Multi-Step Coding Planner skill."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class StepTask(BaseModel):
    id: str
    plan_id: str
    step_number: int
    description: str
    prompt: str
    status: Literal["pending", "running", "rate_limit", "success", "failed"]
    cli_used: str | None = None
    model_used: str | None = None
    output: str | None = None
    error: str | None = None
    tokens_used: int | None = None
    duration_ms: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> StepTask:
        """Construct a StepTask from a SQLite row dict."""
        return cls(
            id=str(row["id"]),
            plan_id=str(row["plan_id"]),
            step_number=int(row["step_number"]),
            description=str(row["description"]),
            prompt=str(row["prompt"]),
            status=row["status"],
            cli_used=row.get("cli_used"),
            model_used=row.get("model_used"),
            output=row.get("output"),
            error=row.get("error"),
            tokens_used=int(row["tokens_used"]) if row.get("tokens_used") is not None else None,
            duration_ms=int(row["duration_ms"]) if row.get("duration_ms") is not None else None,
            created_at=_parse_dt(row["created_at"]),
            started_at=_parse_dt(row["started_at"]) if row.get("started_at") else None,
            completed_at=_parse_dt(row["completed_at"]) if row.get("completed_at") else None,
        )


class StepPlan(BaseModel):
    id: str
    project_id: str
    message_id: str
    description: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None = None
    steps: list[StepTask] = []
    final_evaluation: dict[str, Any] | None = None

    @classmethod
    def from_db_row(cls, row: dict[str, Any], steps: list[StepTask] | None = None) -> StepPlan:
        """Construct a StepPlan from a SQLite row dict.

        Args:
            row: Raw database row.
            steps: Pre-loaded StepTask list. Pass None or omit to get an empty list.
        """
        final_eval: dict[str, Any] | None = None
        raw_eval = row.get("final_evaluation")
        if isinstance(raw_eval, str):
            try:
                final_eval = json.loads(raw_eval)
            except (json.JSONDecodeError, ValueError):
                final_eval = None
        elif isinstance(raw_eval, dict):
            final_eval = raw_eval

        return cls(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            message_id=str(row["message_id"]),
            description=str(row["description"]),
            status=row["status"],
            created_at=_parse_dt(row["created_at"]),
            completed_at=_parse_dt(row["completed_at"]) if row.get("completed_at") else None,
            steps=steps if steps is not None else [],
            final_evaluation=final_eval,
        )


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO-format datetime string or return a datetime as-is."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
