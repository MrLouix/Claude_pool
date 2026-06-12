"""Multi-step planner skill routes."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..api_models import StepPlanGenerateRequest

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    @router.post("/api/skills/multi_step_planner/generate")
    async def generate_plan(body: StepPlanGenerateRequest) -> dict:
        from ..skills.multi_step_planner.generator import PlanGenerator
        from ..skills.multi_step_planner.utils import MAX_PROMPT_LENGTH
        from ..storage import load_project, save_step_plan, save_step_task

        if len(body.prompt) > MAX_PROMPT_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Prompt exceeds maximum length of {MAX_PROMPT_LENGTH} characters",
            )

        project = await asyncio.to_thread(load_project, server.pool_file, body.project_id)
        if project is None:
            raise HTTPException(
                status_code=404, detail=f"Project {body.project_id} not found"
            )

        generator = PlanGenerator()
        plan = await generator.generate(body.prompt, body.project_id, body.message_id)

        await asyncio.to_thread(save_step_plan, plan, server.pool_file)
        for task in plan.steps:
            await asyncio.to_thread(save_step_task, task, server.pool_file)

        await server._broadcast_event({
            "event": "step_plan_created",
            "data": {
                "plan_id": plan.id,
                "project_id": plan.project_id,
                "message_id": plan.message_id,
                "description": plan.description,
                "status": plan.status,
                "step_count": len(plan.steps),
            },
        })

        asyncio.create_task(server._execute_plan_background(plan))

        return plan.model_dump(mode="json")

    @router.get("/api/skills/multi_step_planner/plans/{plan_id}")
    async def get_plan(plan_id: str) -> dict:
        from ..storage import load_step_plan

        plan = await asyncio.to_thread(load_step_plan, plan_id, server.pool_file)
        if plan is None:
            raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
        return plan.model_dump(mode="json")

    @router.get("/api/skills/multi_step_planner/plans/{plan_id}/steps")
    async def get_plan_steps(plan_id: str) -> list:
        from ..storage import load_step_plan, load_step_tasks_for_plan

        plan = await asyncio.to_thread(load_step_plan, plan_id, server.pool_file)
        if plan is None:
            raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
        steps = await asyncio.to_thread(load_step_tasks_for_plan, plan_id, server.pool_file)
        return [s.model_dump(mode="json") for s in steps]

    @router.post("/api/skills/multi_step_planner/steps/{step_id}/retry")
    async def retry_step(step_id: str) -> dict:
        from ..storage import load_step_plan, load_step_task, update_step_task_status

        step = await asyncio.to_thread(load_step_task, step_id, server.pool_file)
        if step is None:
            raise HTTPException(status_code=404, detail=f"Step {step_id} not found")
        if step.status != "failed":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry step in {step.status!r} status",
            )

        await asyncio.to_thread(update_step_task_status, step_id, "pending", server.pool_file)
        step = step.model_copy(update={"status": "pending"})

        plan = await asyncio.to_thread(load_step_plan, step.plan_id, server.pool_file)
        asyncio.create_task(server._execute_step_background(plan, step))

        return step.model_dump(mode="json")

    @router.delete("/api/skills/multi_step_planner/plans/{plan_id}", status_code=204)
    async def delete_plan(plan_id: str) -> None:
        from ..storage import delete_step_plan, load_step_plan

        plan = await asyncio.to_thread(load_step_plan, plan_id, server.pool_file)
        if plan is None:
            raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
        await asyncio.to_thread(delete_step_plan, plan_id, server.pool_file)

    return router
