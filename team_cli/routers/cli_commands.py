"""CLI commands settings endpoints — GET/PUT list and POST test."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException

from ..api_models import (
    CliCommandResponse,
    CliCommandTestInput,
    CliCommandTestResult,
    CliCommandUpdate,
)
from ..database import DatabaseManager

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    def _db() -> DatabaseManager:
        return DatabaseManager(server.pool_file)

    def _row_to_response(row: dict) -> CliCommandResponse:
        raw_models = row.get("models", "[]")
        try:
            models_list: list[str] = json.loads(raw_models) if isinstance(raw_models, str) else list(raw_models)
        except (json.JSONDecodeError, ValueError):
            models_list = []
        return CliCommandResponse(
            id=row["id"],
            name=row["name"],
            binary=row["binary"],
            args_template=row["args_template"],
            resume_template=row.get("resume_template"),
            model_flag=row.get("model_flag"),
            models=models_list,
            default_model=row.get("default_model"),
            enabled=bool(row.get("enabled", True)),
            priority_requests=int(row.get("priority_requests", 100)),
            priority_subtasks=int(row.get("priority_subtasks", 100)),
            parser=str(row.get("parser", "claude_json")),
        )

    @router.get("/api/settings/cli-commands")
    async def list_cli_commands() -> list[CliCommandResponse]:
        """Return all CLI commands ordered by priority_requests ASC."""
        db = _db()
        rows = await db.get_all_cli_commands()
        return [_row_to_response(r) for r in rows]

    @router.put("/api/settings/cli-commands")
    async def replace_cli_commands(
        commands: list[CliCommandUpdate],
    ) -> list[CliCommandResponse]:
        """Replace the full ordered CLI command list (upsert all, delete removed)."""
        db = _db()
        existing_rows = await db.get_all_cli_commands()
        existing_ids = {r["id"] for r in existing_rows}
        new_ids = {c.id for c in commands}

        # Delete commands that were removed from the list
        for removed_id in existing_ids - new_ids:
            await db.delete_cli_command(removed_id)

        # Upsert all provided commands
        for cmd in commands:
            await db.upsert_cli_command({
                "id": cmd.id,
                "name": cmd.name,
                "binary": cmd.binary,
                "args_template": cmd.args_template,
                "resume_template": cmd.resume_template,
                "model_flag": cmd.model_flag,
                "models": json.dumps(cmd.models),
                "default_model": cmd.default_model,
                "enabled": cmd.enabled,
                "priority_requests": cmd.priority_requests,
                "priority_subtasks": cmd.priority_subtasks,
                "parser": cmd.parser,
            })

        rows = await db.get_all_cli_commands()
        return [_row_to_response(r) for r in rows]

    @router.post("/api/settings/cli-commands/test")
    async def test_cli_command(body: CliCommandTestInput) -> CliCommandTestResult:
        """Run `<binary> --version` (timeout 5 s) and return {success, output}."""
        db = _db()
        row = await db.get_cli_command(body.id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"CLI command {body.id!r} not found")

        binary = row["binary"]
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            output = (stdout + stderr).decode("utf-8", errors="replace").strip()
            success = proc.returncode == 0
        except asyncio.TimeoutError:
            return CliCommandTestResult(success=False, output="Timed out after 5 seconds")
        except FileNotFoundError:
            return CliCommandTestResult(success=False, output=f"Binary not found: {binary!r}")
        except Exception as e:
            return CliCommandTestResult(success=False, output=str(e))

        return CliCommandTestResult(success=success, output=output)

    return router
