"""Data models for Claude Pool TUI."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "running", "success", "failed", "skipped", "rate_limit_retry"]
BucketType = Literal["cli", "chat"]


def _default_buckets() -> "dict[str, Bucket]":
    return {"main": Bucket(id="main", type="cli", label="CLI / Dashboard")}


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
        return cls(
            id=str(data["id"]),
            type=str(data.get("type", "cli")),  # type: ignore[arg-type]
            label=str(data.get("label", data["id"])),
            directory=str(data["directory"]) if data.get("directory") else None,
            created_at=str(data.get("created_at", datetime.now().isoformat())),
        )

    def to_dict(self) -> dict[str, Any]:
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
    pool_file: Path = Path("pool.json")
    buckets: dict[str, Bucket] = field(default_factory=_default_buckets)

    def __post_init__(self) -> None:
        if "main" not in self.buckets:
            self.buckets["main"] = Bucket(id="main", type="cli", label="CLI / Dashboard")

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create a Task from a dictionary."""
        args_raw = data.get("args", [])
        args_list = list(args_raw) if isinstance(args_raw, list) else []

        exit_code_raw = data.get("exit_code")
        exit_code = int(exit_code_raw) if exit_code_raw is not None else None

        duration_ms_raw = data.get("duration_ms")
        duration_ms = int(duration_ms_raw) if duration_ms_raw is not None else None

        json_output_raw = data.get("json_output")
        json_output = dict(json_output_raw) if isinstance(json_output_raw, dict) else None

        retry_count_raw = data.get("retry_count", 0)
        retry_count = int(retry_count_raw) if retry_count_raw is not None else 0

        created_at = data.get("created_at")
        if not created_at:
            created_at = datetime.now().isoformat()

        session_id = data.get("session_id")
        session_id = str(session_id) if session_id is not None else None

        bucket_id = str(data.get("bucket_id", "main"))

        return cls(
            id=str(data["id"]),
            prompt=str(data["prompt"]),
            directory=Path(str(data["directory"])),
            args=args_list,
            status=str(data.get("status", "pending")),  # type: ignore[arg-type]
            exit_code=exit_code,
            duration_ms=duration_ms,
            json_output=json_output,
            retry_count=retry_count,
            created_at=str(created_at),
            session_id=session_id,
            bucket_id=bucket_id,
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
        }
