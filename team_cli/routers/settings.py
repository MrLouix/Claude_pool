"""Settings key-value store routes."""

from fastapi import APIRouter

from ..database import DatabaseManager


def create_router(server) -> APIRouter:
    router = APIRouter()

    def _db() -> DatabaseManager:
        return DatabaseManager(server.pool_file)

    @router.get("/api/settings")
    async def get_settings() -> dict[str, str]:
        return await _db().get_all_settings()

    @router.put("/api/settings")
    async def update_settings(body: dict[str, str]) -> dict[str, str]:
        db = _db()
        for key, value in body.items():
            await db.set_setting(key, value)
        return await db.get_all_settings()

    return router
