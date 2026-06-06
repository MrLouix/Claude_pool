"""Storage functions for loading and saving task pools (SQLite backend)."""

import asyncio
import concurrent.futures
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .database import DatabaseManager
from .models import MAIN_BUCKET_LABEL, Bucket, PoolState, Project, ProjectMessage, Task
from .skills.multi_step_planner.models import StepPlan, StepTask

logger = logging.getLogger(__name__)

_DEFAULT_CLEANUP_AGE_HOURS = 48

# Active statuses that are never removed by cleanup regardless of age.
_ACTIVE_STATUSES = frozenset({"pending", "running", "rate_limit_retry"})


# ---------------------------------------------------------------------------
# Async bridge
# ---------------------------------------------------------------------------

def _run_async(coro: Any) -> Any:
    """Run a coroutine synchronously, even from within a running event loop.

    Callers inside an async context get a thread-based trampoline so they do
    not need to be aware of the storage layer's implementation detail.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()


# ---------------------------------------------------------------------------
# One-time JSON → SQLite migration
# ---------------------------------------------------------------------------

def migrate_from_json(json_path: Path, db_path: Path) -> bool:
    """Migrate a pool.json to pool.db on first use.

    Conditions for migration (both must hold):
    - json_path exists
    - db_path does NOT exist

    On success renames pool.json to pool.json.bak and returns True.
    Returns False when no migration is needed.
    """
    if not json_path.exists() or db_path.exists():
        return False

    logger.info(f"Migrating {json_path} → {db_path}")
    content = json_path.read_text(encoding="utf-8").strip()
    if not content:
        return False

    raw: Any = json.loads(content)
    if isinstance(raw, list):
        raw = {"pool_retry_count": 0, "pool_suspended_until": None, "tasks": raw}

    async def _do_migrate() -> None:
        db = DatabaseManager(db_path)
        await db.init()

        await db.set_pool_meta(
            retry_count=int(raw.get("pool_retry_count", 0)),
            suspended_until=raw.get("pool_suspended_until"),
            provider=str(raw.get("provider", "claude")),
        )

        # Buckets
        raw_buckets = raw.get("buckets", {})
        if isinstance(raw_buckets, dict):
            for bid, bdata in raw_buckets.items():
                if isinstance(bdata, dict):
                    bdata = dict(bdata)
                    bdata.setdefault("id", bid)
                    bdata.setdefault("type", "cli")
                    bdata.setdefault("label", bid)
                    bdata.setdefault("created_at", datetime.now().isoformat())
                    await db.upsert_bucket(bdata)

        existing = {b["id"] for b in await db.get_all_buckets()}
        if "main" not in existing:
            await db.upsert_bucket({
                "id": "main",
                "type": "cli",
                "label": MAIN_BUCKET_LABEL,
                "directory": None,
                "created_at": datetime.now().isoformat(),
            })

        # Tasks
        seen_ids: set[str] = set()
        for task_data in raw.get("tasks", []):
            if not isinstance(task_data, dict):
                continue
            task_data = dict(task_data)
            if not task_data.get("id"):
                task_data["id"] = (
                    f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                )
            while task_data["id"] in seen_ids:
                task_data["id"] = f"{task_data['id']}_{uuid.uuid4().hex[:4]}"
            seen_ids.add(task_data["id"])
            task_data.setdefault("created_at", datetime.now().isoformat())
            await db.upsert_task(task_data)

    _run_async(_do_migrate())

    backup = json_path.with_suffix(".json.bak")
    json_path.rename(backup)
    logger.info(f"Migration complete. Original backed up to {backup}")
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_pool(pool_file: Path) -> PoolState:
    """Load pool state from the SQLite database.

    pool_file may be a .json or .db path; the .db file is always used.
    If pool.json exists at the same location and pool.db does not, it is
    migrated automatically.
    """
    db_path = pool_file.with_suffix(".db")
    json_path = pool_file.with_suffix(".json")

    migrate_from_json(json_path, db_path)

    async def _load() -> tuple[dict, list[dict], list[dict]]:
        db = DatabaseManager(db_path)
        await db.init()
        meta = await db.get_pool_meta()
        task_rows = await db.get_all_tasks()
        bucket_rows = await db.get_all_buckets()
        return meta, task_rows, bucket_rows

    meta, task_rows, bucket_rows = _run_async(_load())

    suspended_until_raw = meta.get("suspended_until")
    suspended_until = (
        datetime.fromisoformat(suspended_until_raw) if suspended_until_raw else None
    )

    tasks = [Task.from_dict(row) for row in task_rows]

    buckets: dict[str, Bucket] = {}
    for row in bucket_rows:
        buckets[row["id"]] = Bucket.from_dict(row)
    if "main" not in buckets:
        buckets["main"] = Bucket(id="main", type="cli", label=MAIN_BUCKET_LABEL)

    return PoolState(
        retry_count=int(meta.get("retry_count", 0)),
        suspended_until=suspended_until,
        tasks=tasks,
        pool_file=db_path,
        buckets=buckets,
        provider=str(meta.get("provider", "claude")),
    )


def save_pool(state: PoolState) -> None:
    """Persist pool state to the SQLite database.

    Syncs tasks bidirectionally: tasks absent from state are deleted from DB.
    """
    db_path = state.pool_file.with_suffix(".db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _save() -> None:
        db = DatabaseManager(db_path)
        await db.init()

        await db.set_pool_meta(
            retry_count=state.retry_count,
            suspended_until=(
                state.suspended_until.isoformat() if state.suspended_until else None
            ),
            provider=getattr(state, "provider", "claude"),
        )

        for task in state.tasks:
            await db.upsert_task(task.to_dict())

        for bucket in state.buckets.values():
            await db.upsert_bucket(bucket.to_dict())

        # Remove DB rows for tasks no longer in state
        all_db_tasks = await db.get_all_tasks()
        state_ids = {t.id for t in state.tasks}
        for db_task in all_db_tasks:
            if db_task["id"] not in state_ids:
                await db.delete_task(db_task["id"])

    _run_async(_save())


def _should_keep_task(task: Task, cutoff_time: datetime) -> bool:
    """Return True when a task should be retained during cleanup."""
    if task.status in _ACTIVE_STATUSES:
        return True
    return datetime.fromisoformat(task.created_at) > cutoff_time


def cleanup_old_tasks(state: PoolState, max_age_hours: int = _DEFAULT_CLEANUP_AGE_HOURS) -> int:
    """Remove finished tasks older than max_age_hours from state and DB.

    Active tasks (pending / running / rate_limit_retry) are never removed.
    Returns the number of tasks removed.
    """
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    initial_count = len(state.tasks)

    state.tasks = [t for t in state.tasks if _should_keep_task(t, cutoff_time)]

    removed_count = initial_count - len(state.tasks)
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} old tasks (older than {max_age_hours}h)")
        save_pool(state)

    return removed_count


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def load_projects(db_path: Path) -> list[Project]:
    """Load all projects from the database."""
    async def _load() -> list[Project]:
        db = DatabaseManager(db_path)
        await db.init()
        rows = await db.get_all_projects()
        return [Project.from_dict(row) for row in rows]

    return _run_async(_load())


def load_project(db_path: Path, project_id: str) -> Project | None:
    """Load a single project by ID from the database."""
    async def _load() -> Project | None:
        db = DatabaseManager(db_path)
        await db.init()
        row = await db.get_project(project_id)
        if row is None:
            return None
        return Project.from_dict(row)

    return _run_async(_load())


def save_project(db_path: Path, project: Project) -> None:
    """Save a project to the database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _save() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.upsert_project(project.to_dict())

    _run_async(_save())


def delete_project(db_path: Path, project_id: str) -> None:
    """Delete a project and all its messages from the database."""
    async def _delete() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.delete_project(project_id)

    _run_async(_delete())


# ---------------------------------------------------------------------------
# Project Messages
# ---------------------------------------------------------------------------

def load_project_messages(db_path: Path, project_id: str) -> list[ProjectMessage]:
    """Load all messages for a project from the database."""
    async def _load() -> list[ProjectMessage]:
        db = DatabaseManager(db_path)
        await db.init()
        rows = await db.get_project_messages(project_id)
        return [ProjectMessage.from_dict(row) for row in rows]

    return _run_async(_load())


def load_project_message(db_path: Path, message_id: str) -> ProjectMessage | None:
    """Load a single project message by ID, or None if not found."""
    async def _load() -> ProjectMessage | None:
        db = DatabaseManager(db_path)
        await db.init()
        row = await db.get_project_message(message_id)
        return ProjectMessage.from_dict(row) if row is not None else None

    return _run_async(_load())


def save_project_message(db_path: Path, message: ProjectMessage) -> None:
    """Save a project message to the database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _save() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.upsert_project_message(message.to_dict())

    _run_async(_save())


def delete_project_message(db_path: Path, message_id: str) -> None:
    """Delete a project message from the database."""
    async def _delete() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.delete_project_message(message_id)

    _run_async(_delete())


def get_message_history(db_path: Path, message_id: str, limit: int = 3) -> list[ProjectMessage]:
    """Load message history following linked_message_id chain.
    
    Returns up to `limit` messages from the chain, ordered from oldest to newest.
    """
    async def _load() -> list[ProjectMessage]:
        db = DatabaseManager(db_path)
        await db.init()
        rows = await db.get_message_history(message_id, limit)
        return [ProjectMessage.from_dict(row) for row in rows]

    return _run_async(_load())


def build_context(message: ProjectMessage, db_path: Path) -> list[dict[str, str]]:
    """Build context for a message from its linked history.
    
    If linked_message_id is set, retrieves up to 3 previous messages from the thread.
    Otherwise returns empty list (new thread).
    
    Returns:
        List of context messages as {"role": "user"|"assistant", "content": str} dicts,
        ordered from oldest to newest.
    """
    if message.linked_message_id:
        history = get_message_history(db_path, message.linked_message_id, limit=3)
        return [{"role": m.role, "content": m.content} for m in history]
    return []


# ---------------------------------------------------------------------------
# Migration: Chats (buckets) → Projects
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Step Plans
# ---------------------------------------------------------------------------

def save_step_plan(plan: StepPlan, db_path: Path) -> None:
    """Upsert a StepPlan (without its steps — save each StepTask separately)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _save() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.upsert_step_plan({
            "id": plan.id,
            "project_id": plan.project_id,
            "message_id": plan.message_id,
            "description": plan.description,
            "status": plan.status,
            "created_at": plan.created_at.isoformat(),
            "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
            "final_evaluation": plan.final_evaluation,
        })

    _run_async(_save())


def load_step_plan(plan_id: str, db_path: Path) -> StepPlan | None:
    """Load a StepPlan by id, including its StepTask list, or None if missing."""
    async def _load() -> StepPlan | None:
        db = DatabaseManager(db_path)
        await db.init()
        row = await db.get_step_plan(plan_id)
        if row is None:
            return None
        task_rows = await db.get_step_tasks_for_plan(plan_id)
        steps = [StepTask.from_db_row(r) for r in task_rows]
        return StepPlan.from_db_row(row, steps=steps)

    return _run_async(_load())


def load_step_plans_for_message(message_id: str, db_path: Path) -> list[StepPlan]:
    """Load all StepPlans associated with a message (without their tasks)."""
    async def _load() -> list[StepPlan]:
        db = DatabaseManager(db_path)
        await db.init()
        rows = await db.get_step_plans_for_message(message_id)
        return [StepPlan.from_db_row(r) for r in rows]

    return _run_async(_load())


def update_step_plan_status(
    plan_id: str,
    status: str,
    db_path: Path,
    completed_at: datetime | None = None,
    final_evaluation: dict | None = None,
) -> None:
    """Update the status (and optionally completed_at / final_evaluation) of a StepPlan."""
    async def _update() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        final_eval_json = (
            json.dumps(final_evaluation) if final_evaluation is not None else None
        )
        await db.update_step_plan(
            plan_id,
            status=status,
            completed_at=completed_at.isoformat() if completed_at else None,
            final_evaluation=final_eval_json,
        )

    _run_async(_update())


def delete_step_plan(plan_id: str, db_path: Path) -> None:
    """Delete a StepPlan and all its StepTasks from the database."""
    async def _delete() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.delete_step_plan(plan_id)

    _run_async(_delete())


# ---------------------------------------------------------------------------
# Step Tasks
# ---------------------------------------------------------------------------

def save_step_task(task: StepTask, db_path: Path) -> None:
    """Upsert a StepTask."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _save() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        await db.upsert_step_task({
            "id": task.id,
            "plan_id": task.plan_id,
            "step_number": task.step_number,
            "description": task.description,
            "prompt": task.prompt,
            "status": task.status,
            "cli_used": task.cli_used,
            "model_used": task.model_used,
            "output": task.output,
            "error": task.error,
            "tokens_used": task.tokens_used,
            "duration_ms": task.duration_ms,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        })

    _run_async(_save())


def load_step_tasks_for_plan(plan_id: str, db_path: Path) -> list[StepTask]:
    """Load all StepTasks for a plan, ordered by step_number ascending."""
    async def _load() -> list[StepTask]:
        db = DatabaseManager(db_path)
        await db.init()
        rows = await db.get_step_tasks_for_plan(plan_id)
        return [StepTask.from_db_row(r) for r in rows]

    return _run_async(_load())


def update_step_task_status(task_id: str, status: str, db_path: Path, **kwargs: Any) -> None:
    """Update the status and any provided optional fields of a StepTask.

    Accepted keyword arguments: cli_used, model_used, output, error,
    tokens_used, duration_ms, started_at, completed_at.
    datetime values are automatically serialised to ISO strings.
    """
    async def _update() -> None:
        db = DatabaseManager(db_path)
        await db.init()
        fields: dict[str, Any] = {"status": status}
        for key, val in kwargs.items():
            if isinstance(val, datetime):
                fields[key] = val.isoformat()
            else:
                fields[key] = val
        await db.update_step_task(task_id, **fields)

    _run_async(_update())


# ---------------------------------------------------------------------------
# Migration: Chats (buckets) → Projects
# ---------------------------------------------------------------------------

def migrate_chats_to_projects(db_path: Path) -> int:
    """Migrate chat buckets to projects.

    For each bucket of type 'chat':
    - Creates a Project with allow_cli_switch=False
    - Migrates all tasks in that bucket to ProjectMessage

    Returns the number of projects created.
    """
    async def _migrate() -> int:
        db = DatabaseManager(db_path)
        await db.init()

        # Get all buckets of type 'chat'
        buckets = await db.get_all_buckets()
        chat_buckets = [b for b in buckets if b.get("type") == "chat"]

        if not chat_buckets:
            logger.info("No chat buckets to migrate.")
            return 0

        logger.info(f"Found {len(chat_buckets)} chat buckets to migrate to projects.")

        # Get all tasks once
        all_tasks = await db.get_all_tasks()

        migrated_count = 0

        for bucket in chat_buckets:
            bucket_id = bucket["id"]
            bucket_label = bucket.get("label", bucket_id)
            bucket_directory = bucket.get("directory", "/")
            bucket_created_at = bucket.get("created_at", datetime.now().isoformat())

            # Create project
            project = {
                "id": bucket_id,
                "name": bucket_label,
                "directory": bucket_directory,
                "created_at": bucket_created_at,
                "default_cli": None,
                "allow_cli_switch": False,
            }
            await db.upsert_project(project)

            # Migrate tasks to project messages
            bucket_tasks = [t for t in all_tasks if t.get("bucket_id") == bucket_id]

            for task in bucket_tasks:
                # Determine role: user for prompts, assistant for responses
                # Tasks in chat buckets: user messages have status='success' typically
                # This is a simplification - adjust based on actual data structure
                role = "user"  # Default to user, can be refined

                # Check if this looks like an assistant response
                if task.get("json_output") and task.get("status") == "success":
                    role = "assistant"

                message = {
                    "id": task["id"],
                    "project_id": bucket_id,
                    "content": task.get("prompt", ""),
                    "role": role,
                    "cli_used": task.get("provider"),
                    "linked_message_id": None,  # No linking for initial migration
                    "metadata": {
                        "original_status": task.get("status"),
                        "exit_code": task.get("exit_code"),
                        "duration_ms": task.get("duration_ms"),
                        "tokens_used": task.get("json_output", {}).get("usage", {}).get("total_tokens") if isinstance(task.get("json_output"), dict) else None,
                        "model": task.get("model"),
                        "created_at": task.get("created_at"),
                    },
                    "created_at": task.get("created_at", datetime.now().isoformat()),
                }
                await db.upsert_project_message(message)

            migrated_count += 1
            logger.info(f"Migrated chat bucket '{bucket_label}' ({bucket_id}) to project with {len(bucket_tasks)} messages.")

        return migrated_count

    return _run_async(_migrate())
