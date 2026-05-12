"""Data models for Claude Pool TUI."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "running", "success", "failed", "rate_limit_retry"]


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
        }
