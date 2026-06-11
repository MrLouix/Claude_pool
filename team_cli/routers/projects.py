"""Project and project-message routes."""

import logging
import uuid as _uuid
from copy import copy as _copy
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..api_helpers import _validate_directory
from ..api_models import (
    ProjectEntry,
    ProjectInput,
    ProjectMessageInput,
    ProjectMessageResponse,
    ProjectUpdateInput,
)
from ..executor import NoCLIAvailableError
from ..models import Project, ProjectMessage

logger = logging.getLogger(__name__)


def create_router(server) -> APIRouter:
    router = APIRouter()

    @router.get("/api/projects")
    async def list_projects() -> list[ProjectEntry]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_projects, load_project_messages

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        projects = load_projects(db_path)

        result = []
        for project in projects:
            messages = load_project_messages(db_path, project.id)
            result.append(
                ProjectEntry(
                    id=project.id,
                    name=project.name,
                    directory=project.directory,
                    created_at=project.created_at.isoformat(),
                    default_cli=project.default_cli,
                    allow_cli_switch=project.allow_cli_switch,
                    message_count=len(messages),
                )
            )
        result.sort(key=lambda p: p.created_at, reverse=True)
        return result

    @router.post("/api/projects", status_code=201)
    async def create_project(project_input: ProjectInput) -> ProjectEntry:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        _validate_directory(project_input.directory)

        from ..storage import save_project

        db_path = server.executor.pool.pool_file.with_suffix(".db")

        project = Project(
            id=f"proj_{_uuid.uuid4().hex[:8]}",
            name=project_input.name,
            directory=project_input.directory,
            created_at=datetime.now(),
            default_cli=project_input.default_cli,
            allow_cli_switch=project_input.allow_cli_switch,
        )
        save_project(db_path, project)

        await server._broadcast_event({
            "event": "project_created",
            "project": {
                "id": project.id,
                "name": project.name,
                "directory": project.directory,
                "created_at": project.created_at.isoformat(),
            }
        })

        return ProjectEntry(
            id=project.id,
            name=project.name,
            directory=project.directory,
            created_at=project.created_at.isoformat(),
            default_cli=project.default_cli,
            allow_cli_switch=project.allow_cli_switch,
            message_count=0,
        )

    @router.get("/api/projects/{project_id}")
    async def get_project(project_id: str) -> ProjectEntry:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project, load_project_messages

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        project = load_project(db_path, project_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        messages = load_project_messages(db_path, project_id)

        return ProjectEntry(
            id=project.id,
            name=project.name,
            directory=project.directory,
            created_at=project.created_at.isoformat(),
            default_cli=project.default_cli,
            allow_cli_switch=project.allow_cli_switch,
            message_count=len(messages),
        )

    @router.delete("/api/projects/{project_id}")
    async def delete_project_endpoint(project_id: str) -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import delete_project as delete_project_db, load_project

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        project = load_project(db_path, project_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        delete_project_db(db_path, project_id)

        await server._broadcast_event({
            "event": "project_deleted",
            "project_id": project_id,
        })

        return {"deleted": True, "project_id": project_id}

    @router.patch("/api/projects/{project_id}")
    async def update_project(
        project_id: str, update_input: ProjectUpdateInput
    ) -> ProjectEntry:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project, save_project, load_project_messages

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        project = load_project(db_path, project_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        if update_input.name is not None:
            project.name = update_input.name
        if update_input.directory is not None:
            _validate_directory(update_input.directory)
            project.directory = update_input.directory
        if update_input.default_cli is not None:
            project.default_cli = update_input.default_cli
        if update_input.allow_cli_switch is not None:
            project.allow_cli_switch = update_input.allow_cli_switch

        save_project(db_path, project)

        messages = load_project_messages(db_path, project_id)
        return ProjectEntry(
            id=project.id,
            name=project.name,
            directory=project.directory,
            created_at=project.created_at.isoformat(),
            default_cli=project.default_cli,
            allow_cli_switch=project.allow_cli_switch,
            message_count=len(messages),
        )

    @router.get("/api/projects/{project_id}/messages")
    async def list_project_messages(
        project_id: str,
        linked_to: Optional[str] = Query(default=None),
    ) -> list[ProjectMessageResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project, load_project_messages

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        project = load_project(db_path, project_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        messages = load_project_messages(db_path, project_id)

        if linked_to is not None:
            messages = [m for m in messages if m.linked_message_id == linked_to]

        return [
            ProjectMessageResponse(
                id=m.id,
                project_id=m.project_id,
                content=m.content,
                role=m.role,
                cli_used=m.cli_used,
                linked_message_id=m.linked_message_id,
                metadata=m.metadata,
                created_at=m.created_at.isoformat(),
                priority=m.priority,
            )
            for m in messages
        ]

    @router.get("/api/projects/{project_id}/messages/{message_id}")
    async def get_project_message_endpoint(
        project_id: str, message_id: str
    ) -> ProjectMessageResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project_message

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        message = load_project_message(db_path, message_id)

        if message is None or message.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        return ProjectMessageResponse(
            id=message.id,
            project_id=message.project_id,
            content=message.content,
            role=message.role,
            cli_used=message.cli_used,
            linked_message_id=message.linked_message_id,
            metadata=message.metadata,
            created_at=message.created_at.isoformat(),
            priority=message.priority,
        )

    @router.delete("/api/projects/{project_id}/messages/{message_id}", status_code=204)
    async def delete_project_message_endpoint(
        project_id: str, message_id: str
    ) -> None:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project_message, delete_project_message

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        message = load_project_message(db_path, message_id)

        if message is None or message.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        delete_project_message(db_path, message_id)

    @router.post("/api/projects/{project_id}/messages", status_code=201)
    async def create_project_message(
        project_id: str, message_input: ProjectMessageInput
    ) -> ProjectMessageResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project, save_project_message

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        project = load_project(db_path, project_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        message = ProjectMessage(
            id=f"msg_{_uuid.uuid4().hex[:8]}",
            project_id=project_id,
            content=message_input.content,
            role=message_input.role,
            cli_used=message_input.cli_used,
            linked_message_id=message_input.linked_message_id,
            metadata={},
            created_at=datetime.now(),
            priority=message_input.priority,
        )
        if message_input.priority == 2:
            import team_cli.api as _api_mod
            message.priority = _api_mod.calculate_priority(message, project)
        save_project_message(db_path, message)

        await server._broadcast_event({
            "event": "project_message_created",
            "project_id": project_id,
            "message": {
                "id": message.id,
                "content": message.content,
                "role": message.role,
                "cli_used": message.cli_used,
                "linked_message_id": message.linked_message_id,
                "created_at": message.created_at.isoformat(),
            },
        })

        if message.role == "user":
            exec_project = project
            if message_input.cli_used:
                exec_project = _copy(project)
                exec_project.default_cli = message_input.cli_used
                exec_project.allow_cli_switch = False

            model = message.metadata.get("model") if message.metadata else None

            try:
                import team_cli.api as _api_mod
                result = await _api_mod.execute_message(
                    message=message,
                    project=exec_project,
                    cli_manager=server.executor.cli_manager,
                    db_path=str(db_path),
                    model=model,
                )
            except NoCLIAvailableError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"error": "no_cli_available", "message": str(exc)},
                )

            assistant_content = result.get("content", result.get("result", ""))
            _raw = result.get("raw", result)
            assistant_metadata = {
                k: v for k, v in _raw.items()
                if k not in ("result", "cli_used", "reasoning")
            }
            assistant_msg = ProjectMessage(
                id=f"msg_{_uuid.uuid4().hex[:8]}",
                project_id=project_id,
                content=assistant_content,
                role="assistant",
                cli_used=result.get("cli_used"),
                linked_message_id=message.id,
                metadata=assistant_metadata,
                created_at=datetime.now(),
                priority=message.priority,
            )
            save_project_message(db_path, assistant_msg)

            await server._broadcast_event({
                "event": "project_message_created",
                "project_id": project_id,
                "message": {
                    "id": assistant_msg.id,
                    "content": assistant_msg.content,
                    "role": assistant_msg.role,
                    "cli_used": assistant_msg.cli_used,
                    "linked_message_id": assistant_msg.linked_message_id,
                    "created_at": assistant_msg.created_at.isoformat(),
                },
            })

        return ProjectMessageResponse(
            id=message.id,
            project_id=message.project_id,
            content=message.content,
            role=message.role,
            cli_used=message.cli_used,
            linked_message_id=message.linked_message_id,
            metadata=message.metadata,
            created_at=message.created_at.isoformat(),
            priority=message.priority,
        )

    @router.post(
        "/api/projects/{project_id}/messages/{message_id}/promote",
        status_code=200,
    )
    async def promote_project_message(
        project_id: str, message_id: str
    ) -> ProjectMessageResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project_message, save_project_message
        from ..priority_engine import promote_priority

        db_path = server.executor.pool.pool_file.with_suffix(".db")
        message = load_project_message(db_path, message_id)

        if message is None or message.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        message.priority = promote_priority(message.priority)
        save_project_message(db_path, message)

        return ProjectMessageResponse(
            id=message.id,
            project_id=message.project_id,
            content=message.content,
            role=message.role,
            cli_used=message.cli_used,
            linked_message_id=message.linked_message_id,
            metadata=message.metadata,
            created_at=message.created_at.isoformat(),
            priority=message.priority,
        )

    return router
