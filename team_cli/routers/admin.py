"""Admin and diagnostics routes."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    @router.get("/api/admin/migration-status")
    async def get_migration_status() -> dict:
        from ..migrations import check_migration_status

        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        db_path_str = str(db_path)

        backup_pattern = f"{db_path.name}.bak.*"
        backups = sorted(db_path.parent.glob(backup_pattern))
        backup_exists = len(backups) > 0

        status = await asyncio.to_thread(check_migration_status, db_path_str)

        return {
            "db_path": db_path_str,
            "backup_exists": backup_exists,
            "applied_migrations": status["applied"],
            "pending_migrations": status["pending"],
        }

    return router
