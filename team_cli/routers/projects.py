"""Project and project-message routes (v2 implementation, backward-compatible)."""

import logging
import subprocess
import uuid as _uuid
from copy import copy as _copy
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..api_helpers import _validate_directory
from ..api_models import (
    ChatCreate,
    MessageCreate,
    ProjectCreate,
    ProjectMessageInput,
    ProjectMessageResponse,
    ProjectResponse,
    ProjectUpdate,
    V2ChatResponse,
    V2MessageResponse,
)
from ..database import DatabaseManager
from ..executor import NoCLIAvailableError
from ..models import Chat, Message, Project, ProjectMessage, Task

logger = logging.getLogger(__name__)


def _detect_git_remote(directory: str) -> str | None:
    """Return the 'origin' remote URL for *directory*, or None (non-fatal)."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=directory,
            timeout=5,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None
    except Exception:
        return None


def create_router(server) -> APIRouter:
    router = APIRouter()

    def _db() -> DatabaseManager:
        return DatabaseManager(server.pool_file)

    def _active_count(project_id: str) -> int:
        if not server.executor:
            return 0
        return sum(
            1
            for t in server.executor.pool.tasks
            if t.status == "running" and t.project_id == project_id
        )

    # ── Projects ─────────────────────────────────────────────────

    @router.get("/api/projects")
    async def list_projects() -> list[ProjectResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        rows = await db.get_all_projects()
        result: list[ProjectResponse] = []
        for row in rows:
            if row.get("archived"):
                continue
            proj = Project.from_dict(row)
            msgs = await db.get_project_messages(proj.id)
            result.append(
                ProjectResponse(
                    id=proj.id,
                    name=proj.name,
                    directory=proj.directory,
                    git_remote=proj.git_remote,
                    created_at=proj.created_at.isoformat(),
                    archived=proj.archived,
                    active_task_count=_active_count(proj.id),
                    default_cli=proj.default_cli,
                    allow_cli_switch=proj.allow_cli_switch,
                    message_count=len(msgs),
                )
            )
        result.sort(key=lambda p: p.created_at, reverse=True)
        return result

    @router.post("/api/projects", status_code=201)
    async def create_project(project_input: ProjectCreate) -> ProjectResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        _validate_directory(project_input.directory)

        git_remote = project_input.git_remote or _detect_git_remote(project_input.directory)

        db = _db()
        proj = Project(
            id=f"proj_{_uuid.uuid4().hex[:8]}",
            name=project_input.name,
            directory=project_input.directory,
            created_at=datetime.now(),
            default_cli=project_input.default_cli,
            allow_cli_switch=project_input.allow_cli_switch,
            git_remote=git_remote,
        )
        await db.upsert_project(proj.to_dict())

        await server._broadcast_event(
            {
                "event": "project_created",
                "project": {
                    "id": proj.id,
                    "name": proj.name,
                    "directory": proj.directory,
                    "created_at": proj.created_at.isoformat(),
                },
            }
        )

        return ProjectResponse(
            id=proj.id,
            name=proj.name,
            directory=proj.directory,
            git_remote=proj.git_remote,
            created_at=proj.created_at.isoformat(),
            archived=False,
            active_task_count=0,
            default_cli=proj.default_cli,
            allow_cli_switch=proj.allow_cli_switch,
            message_count=0,
        )

    @router.get("/api/projects/{project_id}")
    async def get_project(project_id: str) -> ProjectResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        row = await db.get_project(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        proj = Project.from_dict(row)
        msgs = await db.get_project_messages(project_id)
        return ProjectResponse(
            id=proj.id,
            name=proj.name,
            directory=proj.directory,
            git_remote=proj.git_remote,
            created_at=proj.created_at.isoformat(),
            archived=proj.archived,
            active_task_count=_active_count(project_id),
            default_cli=proj.default_cli,
            allow_cli_switch=proj.allow_cli_switch,
            message_count=len(msgs),
        )

    @router.patch("/api/projects/{project_id}")
    async def update_project(
        project_id: str, update_input: ProjectUpdate
    ) -> ProjectResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        row = await db.get_project(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        proj = Project.from_dict(row)

        if update_input.name is not None:
            proj.name = update_input.name
        if update_input.directory is not None:
            _validate_directory(update_input.directory)
            proj.directory = update_input.directory
        if update_input.git_remote is not None:
            proj.git_remote = update_input.git_remote
        if update_input.archived is not None:
            proj.archived = update_input.archived
        if update_input.default_cli is not None:
            proj.default_cli = update_input.default_cli
        if update_input.allow_cli_switch is not None:
            proj.allow_cli_switch = update_input.allow_cli_switch

        await db.upsert_project(proj.to_dict())

        msgs = await db.get_project_messages(project_id)
        return ProjectResponse(
            id=proj.id,
            name=proj.name,
            directory=proj.directory,
            git_remote=proj.git_remote,
            created_at=proj.created_at.isoformat(),
            archived=proj.archived,
            active_task_count=_active_count(project_id),
            default_cli=proj.default_cli,
            allow_cli_switch=proj.allow_cli_switch,
            message_count=len(msgs),
        )

    @router.delete("/api/projects/{project_id}")
    async def delete_project_endpoint(project_id: str) -> dict:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        row = await db.get_project(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        # Re-assign in-memory tasks to NULL (do not delete tasks per spec)
        for task in server.executor.pool.tasks:
            if task.project_id == project_id:
                task.project_id = None
        server.executor._save_state()

        # Re-assign DB tasks too (tasks not yet loaded into memory)
        await db.nullify_project_tasks(project_id)

        # Delete project; FK cascade removes chats + messages
        await db.delete_project(project_id)

        await server._broadcast_event(
            {"event": "project_deleted", "project_id": project_id}
        )
        return {"deleted": True, "project_id": project_id}

    # ── Project Chats (v2) ────────────────────────────────────────

    @router.get("/api/projects/{project_id}/chats")
    async def list_project_chats(project_id: str) -> list[V2ChatResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        row = await db.get_project(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        chats = await db.get_chats_for_project(project_id)
        return [
            V2ChatResponse(
                id=c["id"],
                project_id=c["project_id"],
                label=c["label"],
                position=c["position"],
                created_at=c["created_at"],
            )
            for c in chats
        ]

    @router.post("/api/projects/{project_id}/chats", status_code=201)
    async def create_project_chat(
        project_id: str, chat_input: ChatCreate
    ) -> V2ChatResponse:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")
        db = _db()
        row = await db.get_project(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        existing = await db.get_chats_for_project(project_id)
        next_pos = max((c["position"] for c in existing), default=-1) + 1

        chat = Chat(
            id=f"chat_{_uuid.uuid4().hex[:8]}",
            project_id=project_id,
            label=chat_input.label,
            position=next_pos,
            created_at=datetime.now().isoformat(),
        )
        await db.upsert_chat(chat.to_dict())

        await server._broadcast_event(
            {
                "event": "chat_created",
                "chat": {
                    "id": chat.id,
                    "project_id": chat.project_id,
                    "label": chat.label,
                    "position": chat.position,
                },
            }
        )

        return V2ChatResponse(
            id=chat.id,
            project_id=chat.project_id,
            label=chat.label,
            position=chat.position,
            created_at=chat.created_at,
        )

    # ── Legacy Project Messages (v1 system — kept for backward compat) ────────

    @router.get("/api/projects/{project_id}/messages")
    async def list_project_messages(
        project_id: str,
        linked_to: str | None = Query(default=None),
    ) -> list[ProjectMessageResponse]:
        if not server.executor:
            raise HTTPException(status_code=503, detail="Executor not initialized")

        from ..storage import load_project, load_project_messages

        db_path = server.pool_file.with_suffix(".db")
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

        db_path = server.pool_file.with_suffix(".db")
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

        from ..storage import delete_project_message, load_project_message

        db_path = server.pool_file.with_suffix(".db")
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

        db_path = server.pool_file.with_suffix(".db")
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

        await server._broadcast_event(
            {
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
            }
        )

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
                k: v
                for k, v in _raw.items()
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

            await server._broadcast_event(
                {
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
                }
            )

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

        from ..priority_engine import promote_priority
        from ..storage import load_project_message, save_project_message

        db_path = server.pool_file.with_suffix(".db")
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
