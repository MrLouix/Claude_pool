"""Shared utilities for the Multi-Step Coding Planner skill."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

MAX_PROMPT_LENGTH = 10_000


def generate_id() -> str:
    """Return a new unique UUID string."""
    return str(uuid.uuid4())


def now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def validate_prompt_length(prompt: str) -> None:
    """Raise ValueError when *prompt* exceeds MAX_PROMPT_LENGTH characters."""
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(
            f"Prompt is too long ({len(prompt)} chars). "
            f"Maximum allowed is {MAX_PROMPT_LENGTH} characters."
        )


def validate_and_parse_plan_json(raw: str) -> dict[str, Any]:
    """Parse and validate the JSON plan returned by the CLI.

    Accepts raw text that may be wrapped in markdown code fences
    (```json ... ``` or ``` ... ```).

    Expected structure::

        {
          "steps": [
            {"id": 1, "description": "...", "prompt": "..."},
            ...
          ]
        }

    Enforces between 3 and 8 steps (inclusive).

    Raises:
        ValueError: On malformed JSON, wrong structure, or step count violations.
    """
    cleaned = _strip_code_fences(raw.strip())

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from CLI: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    if "steps" not in data:
        raise ValueError('JSON is missing required key "steps"')

    steps = data["steps"]
    if not isinstance(steps, list):
        raise ValueError(f'"steps" must be a list, got {type(steps).__name__}')

    if len(steps) < 3:
        raise ValueError(
            f"Plan must have at least 3 steps, got {len(steps)}"
        )
    if len(steps) > 8:
        raise ValueError(
            f"Plan must have at most 8 steps, got {len(steps)}"
        )

    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} is not a JSON object")
        for field in ("id", "description", "prompt"):
            if field not in step:
                raise ValueError(f'Step {i} is missing required field "{field}"')
        if not isinstance(step["description"], str) or not step["description"].strip():
            raise ValueError(f'Step {i} "description" must be a non-empty string')
        if not isinstance(step["prompt"], str) or not step["prompt"].strip():
            raise ValueError(f'Step {i} "prompt" must be a non-empty string')

    return data


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n(.*?)\n```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _strip_code_fences(text: str) -> str:
    """Remove surrounding markdown code fences if present."""
    m = _CODE_FENCE_RE.match(text)
    return m.group(1) if m else text
