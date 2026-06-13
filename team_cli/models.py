"""Data models for TeamCLI TUI."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "running", "success", "failed", "skipped", "rate_limit_retry", "stopped"]
BucketType = Literal["cli", "chat"]
TaskKind = Literal["request", "subtask"]

MAIN_BUCKET_LABEL: str = "CLI / Dashboard"


@dataclass
class CLIConfig:
    """Configuration for an AI CLI tool."""

    name: str  # e.g. "claude", "mistral"
    path: str  # absolute path to binary
    models: list[str]  # available model names
    cli_type: str  # e.g. "anthropic", "mistral", "custom"
    default_model: str = ""
    args_template: str = ""  # for custom CLIs: "{prompt}", "{context}", "{model}"
    enabled: bool = True


# Project and Message types
MessageRole = Literal["user", "assistant", "system"]


@dataclass
class Project:
    """Represents a project with its directory and history."""

    id: str
    name: str
    directory: str  # Absolute path to the directory
    created_at: datetime = field(default_factory=datetime.now)
    default_cli: str | None = None  # Default CLI to use (or None for dynamic selection)
    allow_cli_switch: bool = True  # Allow switching CLI on rate limit
    # v2 fields
    git_remote: str | None = None
    archived: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        """Construct a Project from a database row dict."""
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            directory=str(data["directory"]),
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data.get("created_at"), str) else datetime.now(),
            default_cli=str(data["default_cli"]) if data.get("default_cli") else None,
            allow_cli_switch=bool(data.get("allow_cli_switch", True)),
            git_remote=str(data["git_remote"]) if data.get("git_remote") else None,
            archived=bool(data.get("archived", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for database insertion."""
        return {
            "id": self.id,
            "name": self.name,
            "directory": self.directory,
            "created_at": self.created_at.isoformat(),
            "default_cli": self.default_cli,
            "allow_cli_switch": self.allow_cli_switch,
            "git_remote": self.git_remote,
            "archived": 1 if self.archived else 0,
        }


@dataclass
class ProjectMessage:
    """Represents a message within a project's history."""

    id: str
    project_id: str
    content: str  # Prompt or AI response
    role: MessageRole  # "user" or "assistant"
    cli_used: str | None = None  # CLI that generated this response
    linked_message_id: str | None = None  # ID of parent message (for follow-ups)
    metadata: dict[str, Any] = field(default_factory=dict)  # Tokens used, duration, model, etc.
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 2
    is_step_task: bool = False  # True when this message is a StepTask result
    step_task_id: str | None = None  # ID of the associated StepTask

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectMessage":
        """Construct a ProjectMessage from a database row dict."""
        return cls(
            id=str(data["id"]),
            project_id=str(data["project_id"]),
            content=str(data["content"]),
            role=data.get("role", "user"),  # type: ignore[arg-type]
            cli_used=str(data["cli_used"]) if data.get("cli_used") else None,
            linked_message_id=str(data["linked_message_id"]) if data.get("linked_message_id") else None,
            metadata=dict(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {},
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data.get("created_at"), str) else datetime.now(),
            priority=_coerce_int(data.get("priority"), 2),
            is_step_task=bool(data.get("is_step_task", False)),
            step_task_id=str(data["step_task_id"]) if data.get("step_task_id") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for database insertion."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "content": self.content,
            "role": self.role,
            "cli_used": self.cli_used,
            "linked_message_id": self.linked_message_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "priority": self.priority,
            "is_step_task": self.is_step_task,
            "step_task_id": self.step_task_id,
        }


def _coerce_int(value: Any, default: int) -> int:
    """Coerce value to int, returning default if value is None."""
    return int(value) if value is not None else default


def _coerce_optional_int(value: Any) -> int | None:
    """Coerce value to int, returning None if value is None."""
    return int(value) if value is not None else None


def _default_buckets() -> "dict[str, Bucket]":
    return {"main": Bucket(id="main", type="cli", label=MAIN_BUCKET_LABEL)}


@dataclass
class Bucket:
    """Represents a task bucket — the CLI dashboard queue or a chat session."""

    id: str
    type: BucketType
    label: str
    directory: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bucket":
        """Construct a Bucket from a database row dict."""
        return cls(
            id=str(data["id"]),
            type=str(data.get("type", "cli")),  # type: ignore[arg-type]
            label=str(data.get("label", data["id"])),
            directory=str(data["directory"]) if data.get("directory") else None,
            created_at=str(data.get("created_at", datetime.now().isoformat())),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for database insertion."""
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "directory": self.directory,
            "created_at": self.created_at,
        }


@dataclass
class PoolState:
    """Global pool state metadata for rate-limit handling."""

    retry_count: int = 0
    suspended_until: datetime | None = None
    tasks: list["Task"] = field(default_factory=list)
    pool_file: Path = Path("pool.db")
    buckets: dict[str, Bucket] = field(default_factory=_default_buckets)
    provider: str = "claude"

    def __post_init__(self) -> None:
        if "main" not in self.buckets:
            self.buckets["main"] = Bucket(id="main", type="cli", label=MAIN_BUCKET_LABEL)

    @property
    def is_suspended(self) -> bool:
        return self.suspended_until is not None and datetime.now() < self.suspended_until

    @property
    def suspension_remaining(self) -> float:
        if not self.suspended_until:
            return 0
        return max(0, (self.suspended_until - datetime.now()).total_seconds())


@dataclass
class Task:
    """Represents a single Claude Code task."""

    id: str
    prompt: str
    directory: Path
    args: list[str] = field(default_factory=list)
    status: TaskStatus = "pending"
    exit_code: int | None = None
    duration_ms: int | None = None
    json_output: dict[str, Any] | None = None
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    session_id: str | None = None
    bucket_id: str = "main"
    priority: int = 2
    model: str = ""
    # v2 fields
    project_id: str | None = None
    chat_id: str | None = None
    parent_message_id: str | None = None
    parent_task_id: str | None = None
    kind: str = "request"  # 'request' | 'subtask'
    # Step 3 routing fields
    cli_id: str | None = None
    rerouted_from: str | None = None
    rerouted_to: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create a Task from a dictionary."""
        args_raw = data.get("args", [])
        args_list = list(args_raw) if isinstance(args_raw, list) else []

        json_output_raw = data.get("json_output")
        json_output = dict(json_output_raw) if isinstance(json_output_raw, dict) else None

        session_id_raw = data.get("session_id")
        session_id = str(session_id_raw) if session_id_raw is not None else None

        return cls(
            id=str(data["id"]),
            prompt=str(data["prompt"]),
            directory=Path(str(data["directory"])),
            args=args_list,
            status=str(data.get("status", "pending")),  # type: ignore[arg-type]
            exit_code=_coerce_optional_int(data.get("exit_code")),
            duration_ms=_coerce_optional_int(data.get("duration_ms")),
            json_output=json_output,
            retry_count=_coerce_int(data.get("retry_count"), 0),
            created_at=str(data.get("created_at") or datetime.now().isoformat()),
            session_id=session_id,
            bucket_id=str(data.get("bucket_id", "main")),
            priority=_coerce_int(data.get("priority"), 2),
            model=str(data.get("model", "")),
            project_id=str(data["project_id"]) if data.get("project_id") else None,
            chat_id=str(data["chat_id"]) if data.get("chat_id") else None,
            parent_message_id=str(data["parent_message_id"]) if data.get("parent_message_id") else None,
            parent_task_id=str(data["parent_task_id"]) if data.get("parent_task_id") else None,
            kind=str(data.get("kind", "request")),
            cli_id=str(data["cli_id"]) if data.get("cli_id") else None,
            rerouted_from=str(data["rerouted_from"]) if data.get("rerouted_from") else None,
            rerouted_to=str(data["rerouted_to"]) if data.get("rerouted_to") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert Task to a dictionary for JSON serialization."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "directory": str(self.directory),
            "args": self.args,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "json_output": self.json_output,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "bucket_id": self.bucket_id,
            "priority": self.priority,
            "model": self.model,
            "project_id": self.project_id,
            "chat_id": self.chat_id,
            "parent_message_id": self.parent_message_id,
            "parent_task_id": self.parent_task_id,
            "kind": self.kind,
            "cli_id": self.cli_id,
            "rerouted_from": self.rerouted_from,
            "rerouted_to": self.rerouted_to,
        }


# ---------------------------------------------------------------------------
# v2 Models: Chat, Message, CliCommand
# ---------------------------------------------------------------------------


@dataclass
class Chat:
    """Represents a v2 chat session within a project."""

    id: str
    project_id: str
    label: str
    position: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chat":
        """Construct a Chat from a database row dict."""
        return cls(
            id=str(data["id"]),
            project_id=str(data["project_id"]),
            label=str(data["label"]),
            position=_coerce_int(data.get("position"), 0),
            created_at=str(data.get("created_at") or datetime.now().isoformat()),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for database insertion."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "label": self.label,
            "position": self.position,
            "created_at": self.created_at,
        }


@dataclass
class Message:
    """Represents a v2 message within a chat (main thread or a reply thread)."""

    id: str
    chat_id: str
    role: MessageRole
    content: str
    thread_root_id: str | None = None  # None = main chat; set = reply in a thread
    task_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Construct a Message from a database row dict."""
        return cls(
            id=str(data["id"]),
            chat_id=str(data["chat_id"]),
            role=str(data.get("role", "user")),  # type: ignore[arg-type]
            content=str(data["content"]),
            thread_root_id=str(data["thread_root_id"]) if data.get("thread_root_id") else None,
            task_id=str(data["task_id"]) if data.get("task_id") else None,
            created_at=str(data.get("created_at") or datetime.now().isoformat()),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for database insertion."""
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "role": self.role,
            "content": self.content,
            "thread_root_id": self.thread_root_id,
            "task_id": self.task_id,
            "created_at": self.created_at,
        }


@dataclass
class CliCommand:
    """Represents a v2 CLI command configuration for multi-CLI routing."""

    id: str
    name: str
    binary: str
    args_template: str  # JSON array, e.g. '["-p","{prompt}","--output-format","json"]'
    resume_template: str | None = None  # JSON array, e.g. '["--resume","{session_id}"]'
    model_flag: str | None = None  # e.g. '--model'
    models: str = "[]"  # JSON array of available model names
    default_model: str | None = None
    enabled: bool = True
    priority_requests: int = 100
    priority_subtasks: int = 100
    parser: str = "claude_json"  # 'claude_json' | 'plain'

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliCommand":
        """Construct a CliCommand from a database row dict."""
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            binary=str(data["binary"]),
            args_template=str(data["args_template"]),
            resume_template=str(data["resume_template"]) if data.get("resume_template") else None,
            model_flag=str(data["model_flag"]) if data.get("model_flag") else None,
            models=str(data.get("models", "[]")),
            default_model=str(data["default_model"]) if data.get("default_model") else None,
            enabled=bool(data.get("enabled", True)),
            priority_requests=_coerce_int(data.get("priority_requests"), 100),
            priority_subtasks=_coerce_int(data.get("priority_subtasks"), 100),
            parser=str(data.get("parser", "claude_json")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for database insertion."""
        return {
            "id": self.id,
            "name": self.name,
            "binary": self.binary,
            "args_template": self.args_template,
            "resume_template": self.resume_template,
            "model_flag": self.model_flag,
            "models": self.models,
            "default_model": self.default_model,
            "enabled": 1 if self.enabled else 0,
            "priority_requests": self.priority_requests,
            "priority_subtasks": self.priority_subtasks,
            "parser": self.parser,
        }
