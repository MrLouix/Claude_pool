"""Pool status, providers, directories, and CLI config routes."""

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from ..api_helpers import _compute_pool_status, _is_allowed_path
from ..api_models import CLIConfigResponse, PoolStatusResponse
from ..cli_detector import detect_clis
from ..config import load_cli_configs

logger = logging.getLogger(__name__)

_PROVIDER_CLI = {
    "claude": "claude",
    "qwen": "qwen-coder",
    "opencode": "opencode",
    "mistral": "codestral",
}


def create_router(server) -> APIRouter:
    router = APIRouter()

    @router.get("/api/status")
    async def get_status() -> PoolStatusResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        server.executor.check_pool_updates()
        return _compute_pool_status(server.executor.pool)

    @router.get("/api/providers")
    async def get_providers() -> list[dict]:
        return [
            {"name": name, "available": shutil.which(cli) is not None}
            for name, cli in _PROVIDER_CLI.items()
        ]

    @router.post("/api/pool/instant-retry")
    async def instant_retry() -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        server.executor.pool.suspended_until = None
        server.executor._save_state()
        await server._broadcast_pool_status()
        logger.info("Instant retry requested: pool suspension cleared")
        return {
            "status": "success",
            "message": "Pool suspension cleared, retrying task immediately",
        }

    @router.get("/api/directories")
    async def list_directories(path: Optional[str] = None) -> dict:
        target = Path(path) if path else Path.home()
        try:
            resolved = target.resolve()
            s = str(resolved).replace("\\", "/")
            if not _is_allowed_path(resolved):
                raise HTTPException(status_code=403, detail="Access denied")
        except HTTPException:
            raise
        if not resolved.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")
        entries = []
        try:
            for item in sorted(resolved.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    entries.append({"name": item.name, "type": "directory"})
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")
        parent_raw = str(resolved.parent)
        parent = parent_raw.replace("\\", "/") if resolved != Path(resolved.anchor) else None
        return {"current": s, "parent": parent, "entries": entries}

    @router.get("/api/clis")
    async def list_clis() -> list[CLIConfigResponse]:
        """Get list of configured CLIs (detected + custom)."""
        detected = detect_clis()
        custom = load_cli_configs()

        all_configs = {c.name: c for c in detected}
        all_configs.update({c.name: c for c in custom if c.enabled})

        return [
            CLIConfigResponse(
                name=c.name,
                path=c.path,
                models=c.models,
                cli_type=c.cli_type,
                enabled=c.enabled,
                default_model=c.default_model,
            )
            for c in all_configs.values()
        ]

    @router.get("/api/clis/detect")
    async def detect_clis_endpoint() -> list[CLIConfigResponse]:
        """Trigger fresh CLI detection and return results."""
        detected = detect_clis()
        return [
            CLIConfigResponse(
                name=c.name,
                path=c.path,
                models=c.models,
                cli_type=c.cli_type,
                enabled=c.enabled,
                default_model=c.default_model,
            )
            for c in detected
        ]

    return router
