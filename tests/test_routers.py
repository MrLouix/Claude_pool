"""Tests for the router modules.

Part 1 (TestRouters*): unit checks — importability and route-structure.
Part 2 (TestIntegration*): full HTTP request/response cycles via TestClient.
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState
from team_cli.storage import save_pool


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


# ===========================================================================
# Integration helpers
# ===========================================================================

@contextmanager
def _make_api(pool_file: Path):
    """Yield a (TestClient, ApiServer) with run_pool and signal patched out."""
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


def _pool(tmp_path: Path) -> Path:
    """Create an empty pool DB and return its path."""
    pf = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pf))
    return pf


# ===========================================================================
# Part 2 — full HTTP request/response cycles
# ===========================================================================


class TestIntegrationTasksRouter:
    """Full request/response cycles for team_cli/routers/tasks.py."""

    def test_post_task_returns_id_and_priority(self, tmp_path: Path) -> None:
        """POST /api/tasks with valid directory → 200, contains 'id' and 'priority'."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "hello world", "directory": str(Path.home())},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "priority" in data

    def test_get_tasks_returns_list(self, tmp_path: Path) -> None:
        """GET /api/tasks → 200 and a JSON list."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_patch_task_priority(self, tmp_path: Path) -> None:
        """PATCH /api/tasks/{id} with priority=3 → 200, priority field updated."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            task_id = client.post(
                "/api/tasks",
                json={"prompt": "patch me", "directory": str(Path.home())},
            ).json()["id"]
            resp = client.patch(f"/api/tasks/{task_id}", json={"priority": 3})
        assert resp.status_code == 200
        assert resp.json()["priority"] == 3

    def test_delete_task_returns_200_for_existing(self, tmp_path: Path) -> None:
        """DELETE /api/tasks/{id} on a known task → 200."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            task_id = client.post(
                "/api/tasks",
                json={"prompt": "delete me", "directory": str(Path.home())},
            ).json()["id"]
            resp = client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 200

    def test_delete_task_returns_404_for_unknown(self, tmp_path: Path) -> None:
        """DELETE /api/tasks/{id} on a nonexistent task → 404."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.delete("/api/tasks/task_nonexistent_0000")
        assert resp.status_code == 404

    def test_get_tasks_after_create(self, tmp_path: Path) -> None:
        """A task created via POST appears in GET /api/tasks."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            client.post(
                "/api/tasks",
                json={"prompt": "visible task", "directory": str(Path.home())},
            )
            tasks = client.get("/api/tasks").json()
        assert any(t["prompt"] == "visible task" for t in tasks)


class TestIntegrationPoolsRouter:
    """Full request/response cycles for team_cli/routers/pools.py."""

    def test_get_status_returns_claude_status(self, tmp_path: Path) -> None:
        """GET /api/status → 200, response contains 'claude_status' key."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/status")
        assert resp.status_code == 200
        assert "claude_status" in resp.json()

    def test_instant_retry_returns_200(self, tmp_path: Path) -> None:
        """POST /api/pool/instant-retry → 200."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post("/api/pool/instant-retry")
        assert resp.status_code == 200

    def test_get_status_shape(self, tmp_path: Path) -> None:
        """GET /api/status response contains all required PoolStatusResponse fields."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            data = client.get("/api/status").json()
        for field in ("total_tasks", "pending_tasks", "pool_suspended", "claude_status"):
            assert field in data, f"missing field: {field}"


class TestIntegrationChatsRouter:
    """Full request/response cycles for team_cli/routers/chats.py."""

    def test_post_chat_returns_201(self, tmp_path: Path) -> None:
        """POST /api/chats with valid directory → 201."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "Test Chat"},
            )
        assert resp.status_code == 201

    def test_get_chats_returns_list(self, tmp_path: Path) -> None:
        """GET /api/chats → 200 and a JSON list."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/chats")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_delete_chat_returns_200(self, tmp_path: Path) -> None:
        """DELETE /api/chats/{id} on a chat that exists → 200."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            chat_id = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "To Delete"},
            ).json()["id"]
            resp = client.delete(f"/api/chats/{chat_id}")
        assert resp.status_code == 200

    def test_created_chat_appears_in_list(self, tmp_path: Path) -> None:
        """A chat created via POST appears in GET /api/chats."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            label = "Unique Label XYZ"
            client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": label},
            )
            chats = client.get("/api/chats").json()
        assert any(c["label"] == label for c in chats)


class TestIntegrationProjectsRouter:
    """Full request/response cycles for team_cli/routers/projects.py."""

    def test_post_project_returns_201(self, tmp_path: Path) -> None:
        """POST /api/projects → 201."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/projects",
                json={"name": "My Project", "directory": str(Path.home())},
            )
        assert resp.status_code == 201

    def test_get_project_returns_200(self, tmp_path: Path) -> None:
        """GET /api/projects/{id} on an existing project → 200."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            proj_id = client.post(
                "/api/projects",
                json={"name": "Fetch Me", "directory": str(Path.home())},
            ).json()["id"]
            resp = client.get(f"/api/projects/{proj_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == proj_id

    def test_post_project_message_returns_201(self, tmp_path: Path) -> None:
        """POST /api/projects/{id}/messages with role='assistant' → 201."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            proj_id = client.post(
                "/api/projects",
                json={"name": "Msg Project", "directory": str(Path.home())},
            ).json()["id"]
            resp = client.post(
                f"/api/projects/{proj_id}/messages",
                json={"content": "hello", "role": "assistant", "priority": 1},
            )
        assert resp.status_code == 201

    def test_get_project_404_for_unknown(self, tmp_path: Path) -> None:
        """GET /api/projects/{id} on an unknown ID → 404."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/projects/proj_does_not_exist")
        assert resp.status_code == 404


class TestIntegrationAdminRouter:
    """Full request/response cycles for team_cli/routers/admin.py."""

    def test_get_migration_status_returns_200(self, tmp_path: Path) -> None:
        """GET /api/admin/migration-status → 200."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.get("/api/admin/migration-status")
        assert resp.status_code == 200

    def test_migration_status_has_required_keys(self, tmp_path: Path) -> None:
        """GET /api/admin/migration-status response contains db_path, applied_migrations, pending_migrations."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            data = client.get("/api/admin/migration-status").json()
        for key in ("db_path", "applied_migrations", "pending_migrations", "backup_exists"):
            assert key in data, f"missing key: {key}"
