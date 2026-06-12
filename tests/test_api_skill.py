"""Integration tests for the multi_step_planner API endpoints (Step 6)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.database import DatabaseManager
from team_cli.models import PoolState, Project, ProjectMessage
from team_cli.skills.multi_step_planner.models import StepPlan, StepTask
from team_cli.storage import save_pool, save_project, save_project_message

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)

_PLAN_ID = "plan-abc"
_PROJECT_ID = "proj-abc"
_MESSAGE_ID = "msg-abc"


@pytest.fixture
def pool_file(tmp_path: Path) -> Path:
    state = PoolState(pool_file=tmp_path / "pool.json")
    save_pool(state)
    return tmp_path / "pool.json"


@pytest.fixture
def api(pool_file: Path):
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


@pytest.fixture
def seeded_api(api):
    """api fixture with a project and message already in the DB."""
    client, server = api
    db_path = server.pool_file

    asyncio.run(DatabaseManager(db_path).init())

    save_project(
        db_path,
        Project(
            id=_PROJECT_ID,
            name="Test Project",
            directory="/tmp",
            created_at=NOW,
        ),
    )
    save_project_message(
        db_path,
        ProjectMessage(
            id=_MESSAGE_ID,
            project_id=_PROJECT_ID,
            content="Build API",
            role="user",
            created_at=NOW,
        ),
    )
    yield client, server


def _make_plan(steps: int = 2) -> StepPlan:
    step_list = [
        StepTask(
            id=f"task-{i}",
            plan_id=_PLAN_ID,
            step_number=i,
            description=f"Step {i}",
            prompt=f"Do step {i}",
            status="pending",
            created_at=NOW,
        )
        for i in range(1, steps + 1)
    ]
    return StepPlan(
        id=_PLAN_ID,
        project_id=_PROJECT_ID,
        message_id=_MESSAGE_ID,
        description="Build a REST API",
        status="pending",
        created_at=NOW,
        steps=step_list,
    )


def _patch_generator(plan: StepPlan):
    """Patch PlanGenerator.generate to return *plan* immediately."""
    return patch(
        "team_cli.skills.multi_step_planner.generator.PlanGenerator.generate",
        new=AsyncMock(return_value=plan),
    )


def _patch_execute_plan():
    """Patch ApiServer._execute_plan_background to be a no-op."""
    return patch.object(ApiServer, "_execute_plan_background", new=AsyncMock(return_value=None))


# ---------------------------------------------------------------------------
# POST /api/skills/multi_step_planner/generate — success
# ---------------------------------------------------------------------------


def test_generate_returns_200(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        r = client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    assert r.status_code == 200


def test_generate_returns_plan_id(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        r = client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    data = r.json()
    assert data["id"] == _PLAN_ID


def test_generate_returns_steps(seeded_api):
    client, server = seeded_api
    plan = _make_plan(steps=3)

    with _patch_generator(plan), _patch_execute_plan():
        r = client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    data = r.json()
    assert len(data["steps"]) == 3


def test_generate_saves_plan_to_db(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    from team_cli.storage import load_step_plan
    saved = load_step_plan(_PLAN_ID, server.pool_file)
    assert saved is not None
    assert saved.id == _PLAN_ID


# ---------------------------------------------------------------------------
# POST /api/skills/multi_step_planner/generate — validation errors
# ---------------------------------------------------------------------------


def test_generate_returns_400_when_prompt_too_long(seeded_api):
    client, _ = seeded_api
    long_prompt = "x" * 10_001

    r = client.post(
        "/api/skills/multi_step_planner/generate",
        json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": long_prompt},
    )

    assert r.status_code == 400
    assert "10000" in r.json()["detail"]


def test_generate_returns_400_on_exact_limit(seeded_api):
    client, server = seeded_api
    plan = _make_plan()
    at_limit_prompt = "x" * 10_000

    with _patch_generator(plan), _patch_execute_plan():
        r = client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": at_limit_prompt},
        )

    assert r.status_code == 200


def test_generate_returns_404_when_project_not_found(api):
    client, _ = api

    r = client.post(
        "/api/skills/multi_step_planner/generate",
        json={"project_id": "nonexistent", "message_id": _MESSAGE_ID, "prompt": "hello"},
    )

    assert r.status_code == 404
    assert "nonexistent" in r.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/skills/multi_step_planner/plans/{plan_id}
# ---------------------------------------------------------------------------


def test_get_plan_returns_200(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    r = client.get(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")
    assert r.status_code == 200
    assert r.json()["id"] == _PLAN_ID


def test_get_plan_returns_steps(seeded_api):
    client, server = seeded_api
    plan = _make_plan(steps=3)

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    r = client.get(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")
    assert len(r.json()["steps"]) == 3


def test_get_plan_returns_404_when_not_found(api):
    client, _ = api
    r = client.get("/api/skills/multi_step_planner/plans/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/skills/multi_step_planner/plans/{plan_id}/steps
# ---------------------------------------------------------------------------


def test_get_steps_returns_list(seeded_api):
    client, server = seeded_api
    plan = _make_plan(steps=2)

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    r = client.get(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}/steps")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 2


def test_get_steps_ordered_by_step_number(seeded_api):
    client, server = seeded_api
    plan = _make_plan(steps=3)

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    r = client.get(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}/steps")
    numbers = [s["step_number"] for s in r.json()]
    assert numbers == sorted(numbers)


def test_get_steps_returns_404_for_unknown_plan(api):
    client, _ = api
    r = client.get("/api/skills/multi_step_planner/plans/ghost/steps")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/skills/multi_step_planner/steps/{step_id}/retry
# ---------------------------------------------------------------------------


def _seed_plan_with_failed_step(server: ApiServer) -> StepTask:
    """Insert a plan with one failed step directly into the DB."""
    from team_cli.storage import save_step_plan, save_step_task

    plan = StepPlan(
        id="plan-retry",
        project_id=_PROJECT_ID,
        message_id=_MESSAGE_ID,
        description="retry plan",
        status="running",
        created_at=NOW,
    )
    step = StepTask(
        id="step-failed",
        plan_id="plan-retry",
        step_number=1,
        description="Step 1",
        prompt="Do step 1",
        status="failed",
        error="Something went wrong",
        created_at=NOW,
    )
    save_step_plan(plan, server.pool_file)
    save_step_task(step, server.pool_file)
    return step


def test_retry_step_returns_200_with_pending_status(seeded_api):
    client, server = seeded_api
    _seed_plan_with_failed_step(server)

    with patch.object(ApiServer, "_execute_step_background", new=AsyncMock(return_value=None)):
        r = client.post("/api/skills/multi_step_planner/steps/step-failed/retry")

    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_retry_step_updates_db_to_pending(seeded_api):
    client, server = seeded_api
    _seed_plan_with_failed_step(server)

    with patch.object(ApiServer, "_execute_step_background", new=AsyncMock(return_value=None)):
        client.post("/api/skills/multi_step_planner/steps/step-failed/retry")

    from team_cli.storage import load_step_task
    step = load_step_task("step-failed", server.pool_file)
    assert step.status == "pending"


def test_retry_step_returns_400_if_not_failed(seeded_api):
    client, server = seeded_api
    from team_cli.storage import save_step_plan, save_step_task

    plan = StepPlan(
        id="plan-pnd",
        project_id=_PROJECT_ID,
        message_id=_MESSAGE_ID,
        description="d",
        status="running",
        created_at=NOW,
    )
    step = StepTask(
        id="step-pnd",
        plan_id="plan-pnd",
        step_number=1,
        description="d",
        prompt="p",
        status="pending",
        created_at=NOW,
    )
    save_step_plan(plan, server.pool_file)
    save_step_task(step, server.pool_file)

    r = client.post("/api/skills/multi_step_planner/steps/step-pnd/retry")
    assert r.status_code == 400


def test_retry_step_returns_400_if_running(seeded_api):
    client, server = seeded_api
    from team_cli.storage import save_step_plan, save_step_task

    plan = StepPlan(
        id="plan-run",
        project_id=_PROJECT_ID,
        message_id=_MESSAGE_ID,
        description="d",
        status="running",
        created_at=NOW,
    )
    step = StepTask(
        id="step-run",
        plan_id="plan-run",
        step_number=1,
        description="d",
        prompt="p",
        status="running",
        created_at=NOW,
    )
    save_step_plan(plan, server.pool_file)
    save_step_task(step, server.pool_file)

    r = client.post("/api/skills/multi_step_planner/steps/step-run/retry")
    assert r.status_code == 400


def test_retry_step_returns_404_for_unknown_step(api):
    client, _ = api
    r = client.post("/api/skills/multi_step_planner/steps/ghost/retry")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/skills/multi_step_planner/plans/{plan_id}
# ---------------------------------------------------------------------------


def test_delete_plan_returns_204(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    r = client.delete(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")
    assert r.status_code == 204


def test_delete_plan_removes_from_db(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    client.delete(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")

    from team_cli.storage import load_step_plan
    assert load_step_plan(_PLAN_ID, server.pool_file) is None


def test_delete_plan_cascades_to_steps(seeded_api):
    client, server = seeded_api
    plan = _make_plan(steps=2)

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    client.delete(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")

    from team_cli.storage import load_step_tasks_for_plan
    assert load_step_tasks_for_plan(_PLAN_ID, server.pool_file) == []


def test_delete_plan_returns_404_when_not_found(api):
    client, _ = api
    r = client.delete("/api/skills/multi_step_planner/plans/ghost")
    assert r.status_code == 404


def test_delete_plan_then_get_returns_404(seeded_api):
    client, server = seeded_api
    plan = _make_plan()

    with _patch_generator(plan), _patch_execute_plan():
        client.post(
            "/api/skills/multi_step_planner/generate",
            json={"project_id": _PROJECT_ID, "message_id": _MESSAGE_ID, "prompt": "Build REST API"},
        )

    client.delete(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")
    r = client.get(f"/api/skills/multi_step_planner/plans/{_PLAN_ID}")
    assert r.status_code == 404
