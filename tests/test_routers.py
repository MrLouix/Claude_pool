"""Unit tests for the router modules.

Verifies that:
- Each router module is independently importable
- create_router(server) returns an APIRouter with the expected routes
- Route paths are unchanged from the original api.py
"""

from unittest.mock import MagicMock, AsyncMock


def _make_server():
    """Build a minimal mock ApiServer with the attributes routers need."""
    server = MagicMock()
    server.executor = MagicMock()
    server.pool_file = MagicMock()
    server._broadcast_event = AsyncMock()
    server._broadcast_pool_status = AsyncMock()
    server._resolve_directory = MagicMock(return_value=None)
    server._execute_plan_background = AsyncMock()
    server._execute_step_background = AsyncMock()
    return server


class TestRoutersImportable:
    """Each router module can be imported without side effects."""

    def test_tasks_importable(self):
        from team_cli.routers.tasks import create_router
        assert callable(create_router)

    def test_pools_importable(self):
        from team_cli.routers.pools import create_router
        assert callable(create_router)

    def test_chats_importable(self):
        from team_cli.routers.chats import create_router
        assert callable(create_router)

    def test_projects_importable(self):
        from team_cli.routers.projects import create_router
        assert callable(create_router)

    def test_skills_importable(self):
        from team_cli.routers.skills import create_router
        assert callable(create_router)

    def test_admin_importable(self):
        from team_cli.routers.admin import create_router
        assert callable(create_router)


class TestRouterFactory:
    """create_router(server) returns an APIRouter with the expected route paths."""

    def _get_routes(self, router) -> set[str]:
        """Return set of 'METHOD /path' strings for all routes on the router."""
        result = set()
        for route in router.routes:
            for method in route.methods:
                result.add(f"{method} {route.path}")
        return result

    def test_tasks_router_has_all_routes(self):
        from team_cli.routers.tasks import create_router
        from fastapi.routing import APIRouter

        router = create_router(_make_server())
        assert isinstance(router, APIRouter)
        routes = self._get_routes(router)

        assert "GET /api/tasks" in routes
        assert "POST /api/tasks" in routes
        assert "GET /api/tasks/{task_id}" in routes
        assert "POST /api/tasks/{task_id}/retry" in routes
        assert "POST /api/tasks/{task_id}/skip" in routes
        assert "POST /api/tasks/{task_id}/stop" in routes
        assert "DELETE /api/tasks/{task_id}" in routes
        assert "POST /api/tasks/{task_id}/duplicate" in routes
        assert "PATCH /api/tasks/{task_id}" in routes

    def test_pools_router_has_all_routes(self):
        from team_cli.routers.pools import create_router
        from fastapi.routing import APIRouter

        router = create_router(_make_server())
        assert isinstance(router, APIRouter)
        routes = self._get_routes(router)

        assert "GET /api/status" in routes
        assert "GET /api/providers" in routes
        assert "POST /api/pool/instant-retry" in routes
        assert "GET /api/directories" in routes
        assert "GET /api/clis" in routes
        assert "GET /api/clis/detect" in routes

    def test_chats_router_has_all_routes(self):
        from team_cli.routers.chats import create_router
        from fastapi.routing import APIRouter

        router = create_router(_make_server())
        assert isinstance(router, APIRouter)
        routes = self._get_routes(router)

        assert "GET /api/chats" in routes
        assert "POST /api/chats" in routes
        assert "DELETE /api/chats/{chat_id}" in routes
        assert "GET /api/chats/{chat_id}/messages" in routes
        assert "POST /api/chats/{chat_id}/messages" in routes

    def test_projects_router_has_all_routes(self):
        from team_cli.routers.projects import create_router
        from fastapi.routing import APIRouter

        router = create_router(_make_server())
        assert isinstance(router, APIRouter)
        routes = self._get_routes(router)

        assert "GET /api/projects" in routes
        assert "POST /api/projects" in routes
        assert "GET /api/projects/{project_id}" in routes
        assert "DELETE /api/projects/{project_id}" in routes
        assert "PATCH /api/projects/{project_id}" in routes
        assert "GET /api/projects/{project_id}/messages" in routes
        assert "GET /api/projects/{project_id}/messages/{message_id}" in routes
        assert "DELETE /api/projects/{project_id}/messages/{message_id}" in routes
        assert "POST /api/projects/{project_id}/messages" in routes
        assert "POST /api/projects/{project_id}/messages/{message_id}/promote" in routes

    def test_skills_router_has_all_routes(self):
        from team_cli.routers.skills import create_router
        from fastapi.routing import APIRouter

        router = create_router(_make_server())
        assert isinstance(router, APIRouter)
        routes = self._get_routes(router)

        assert "POST /api/skills/multi_step_planner/generate" in routes
        assert "GET /api/skills/multi_step_planner/plans/{plan_id}" in routes
        assert "GET /api/skills/multi_step_planner/plans/{plan_id}/steps" in routes
        assert "POST /api/skills/multi_step_planner/steps/{step_id}/retry" in routes
        assert "DELETE /api/skills/multi_step_planner/plans/{plan_id}" in routes

    def test_admin_router_has_all_routes(self):
        from team_cli.routers.admin import create_router
        from fastapi.routing import APIRouter

        router = create_router(_make_server())
        assert isinstance(router, APIRouter)
        routes = self._get_routes(router)

        assert "GET /api/admin/migration-status" in routes

    def test_each_router_returns_independent_instance(self):
        """Two calls to create_router produce distinct router instances."""
        from team_cli.routers.tasks import create_router
        from fastapi.routing import APIRouter

        server = _make_server()
        r1 = create_router(server)
        r2 = create_router(server)
        assert r1 is not r2


class TestRouterTotalRouteCoverage:
    """Regression guard: total route count hasn't shrunk."""

    def _count_routes(self, router) -> int:
        total = 0
        for route in router.routes:
            total += len(route.methods)
        return total

    def test_total_route_count(self):
        from team_cli.routers.tasks import create_router as tasks
        from team_cli.routers.pools import create_router as pools
        from team_cli.routers.chats import create_router as chats
        from team_cli.routers.projects import create_router as projects
        from team_cli.routers.skills import create_router as skills
        from team_cli.routers.admin import create_router as admin

        server = _make_server()
        total = sum(
            self._count_routes(fn(server))
            for fn in [tasks, pools, chats, projects, skills, admin]
        )
        # 9 task + 6 pools + 5 chats + 10 projects + 5 skills + 1 admin = 36
        assert total >= 36
