"""CLI command resolution and command building for multi-CLI routing."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CliCommand, Task

logger = logging.getLogger(__name__)


class NoCLICommandError(Exception):
    """Raised when no enabled CLI command is available for routing."""


def resolve_command(
    kind: str,
    requested_cli_id: str | None,
    cli_commands: list[CliCommand],
) -> CliCommand:
    """Return the first CliCommand in the routing chain for a task.

    If *requested_cli_id* is provided and points to an enabled command it is
    promoted to the front of the chain.  The rest of the chain is ordered by
    priority_requests (kind='request') or priority_subtasks (kind='subtask'),
    then by id as a tiebreaker.

    Raises NoCLICommandError when no enabled command is available.
    """
    chain = resolve_command_chain(kind, requested_cli_id, cli_commands)
    if not chain:
        raise NoCLICommandError("No enabled CLI commands available")
    return chain[0]


def resolve_command_chain(
    kind: str,
    requested_cli_id: str | None,
    cli_commands: list[CliCommand],
    exclude_ids: list[str] | None = None,
) -> list[CliCommand]:
    """Return the full ordered routing chain, optionally skipping some CLIs.

    *exclude_ids* is used for fallback: pass the id of the CLI that just
    rate-limited to get the next candidate without it.
    """
    exclude = set(exclude_ids or [])
    enabled = [c for c in cli_commands if c.enabled and c.id not in exclude]

    if kind == "subtask":
        chain = sorted(enabled, key=lambda c: (c.priority_subtasks, c.id))
    else:
        chain = sorted(enabled, key=lambda c: (c.priority_requests, c.id))

    if requested_cli_id and requested_cli_id not in exclude:
        requested = next((c for c in chain if c.id == requested_cli_id), None)
        if requested is not None:
            chain = [requested] + [c for c in chain if c.id != requested_cli_id]

    return chain


def build_command(task: Task, cli_command: CliCommand) -> list[str]:
    """Build the full argv list for a task using a CliCommand template.

    Steps:
    1. Parse args_template (JSON list) and substitute {prompt}.
    2. If task.session_id and resume_template exist: parse resume_template,
       substitute {session_id}, and insert the resume args after the binary.
    3. If task.model and model_flag are set: append [model_flag, task.model].

    Returns the complete argv list starting with the binary name.
    """
    try:
        template_args: list[str] = json.loads(cli_command.args_template)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse args_template for CLI %s", cli_command.id)
        template_args = ["{prompt}"]

    main_args = [arg.replace("{prompt}", task.prompt) for arg in template_args]

    resume_args: list[str] = []
    if task.session_id and cli_command.resume_template:
        try:
            rt: list[str] = json.loads(cli_command.resume_template)
            resume_args = [arg.replace("{session_id}", task.session_id) for arg in rt]
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse resume_template for CLI %s", cli_command.id)

    cmd = [cli_command.binary] + resume_args + main_args

    if task.model and cli_command.model_flag:
        cmd.extend([cli_command.model_flag, task.model])

    return cmd
