"""Pydantic request/response models for the TeamCLI REST API."""

from typing import Optional

from pydantic import BaseModel, field_validator


def _validate_priority(v: int) -> int:
    """Shared validator: priority must be 1, 2, or 3."""
    if v not in (1, 2, 3):
        raise ValueError("priority must be 1, 2, or 3")
    return v


class ProjectInput(BaseModel):
    """Input model for creating a project."""
    name: str
    directory: str
    default_cli: Optional[str] = None
    allow_cli_switch: bool = True


class ProjectEntry(BaseModel):
    """Response model for a project."""
    id: str
    name: str
    directory: str
    created_at: str
    default_cli: Optional[str] = None
    allow_cli_switch: bool = True
    message_count: int = 0


class ProjectMessageInput(BaseModel):
    """Input model for creating a project message."""
    content: str
    role: str = "user"  # "user" or "assistant"
    cli_used: Optional[str] = None
    linked_message_id: Optional[str] = None  # ID of parent message for thread continuation


class ProjectMessageResponse(BaseModel):
    """Response model for a project message."""
    id: str
    project_id: str
    content: str
    role: str
    cli_used: Optional[str] = None
    linked_message_id: Optional[str] = None
    metadata: dict = {}
    created_at: str


class TaskInput(BaseModel):
    prompt: str
    directory: Optional[str] = None
    github_url: Optional[str] = None
    args: list[str] = []
    model: Optional[str] = None
    effort: Optional[str] = None
    priority: int = 2

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v: int) -> int:
        return _validate_priority(v)


class TaskResponse(BaseModel):
    id: str
    prompt: str
    directory: str
    status: str
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0
    bucket_id: str = "main"
    priority: int = 2
    created_at: Optional[str] = None


class TaskDetailResponse(BaseModel):
    id: str
    prompt: str
    directory: str
    status: str
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0
    bucket_id: str = "main"
    args: list[str] = []
    json_output: Optional[dict] = None
    created_at: Optional[str] = None
    priority: int = 2


class TaskPatchInput(BaseModel):
    prompt: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    priority: Optional[int] = None

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v: Optional[int]) -> Optional[int]:
        if v is not None:
            _validate_priority(v)
        return v


class PoolStatusResponse(BaseModel):
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    pool_suspended: bool
    suspension_remaining: float = 0.0
    retry_count: int = 0
    claude_status: str
    rate_limit_result: Optional[str] = None


class ChatCreateInput(BaseModel):
    """Input model for creating a chat bucket."""

    directory: str
    label: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for a chat bucket."""

    id: str
    label: str
    directory: Optional[str] = None
    created_at: str
    message_count: int = 0
    last_activity: Optional[str] = None
    session_usage_percent: Optional[float] = None


class MessageInput(BaseModel):
    """Input model for sending a chat message (creates a task)."""

    prompt: str
    model: Optional[str] = None
    effort: Optional[str] = None
    priority: int = 2

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v: int) -> int:
        return _validate_priority(v)


class MessageResponse(BaseModel):
    """Response model for a chat message (task projected as chat turn)."""

    id: str
    role: str = "user"
    content: str
    created_at: str
    status: str
    assistant_response: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None


class CLIConfigResponse(BaseModel):
    """Response model for CLI configuration."""

    name: str
    path: str
    models: list[str]
    cli_type: str
    enabled: bool
    default_model: str = ""
