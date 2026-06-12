"""Pydantic request/response models for the TeamCLI REST API."""


from pydantic import BaseModel, field_validator


def _validate_priority(v: int) -> int:
    """Shared validator: priority must be 1–5."""
    if v not in (1, 2, 3, 4, 5):
        raise ValueError("priority must be between 1 and 5")
    return v


class ProjectInput(BaseModel):
    """Input model for creating a project."""
    name: str
    directory: str
    default_cli: str | None = None
    allow_cli_switch: bool = True


class ProjectEntry(BaseModel):
    """Response model for a project."""
    id: str
    name: str
    directory: str
    created_at: str
    default_cli: str | None = None
    allow_cli_switch: bool = True
    message_count: int = 0


class ProjectUpdateInput(BaseModel):
    """Input model for PATCH /api/projects/{project_id}. All fields optional."""
    name: str | None = None
    directory: str | None = None
    default_cli: str | None = None
    allow_cli_switch: bool | None = None


class ProjectMessageInput(BaseModel):
    """Input model for creating a project message."""
    content: str
    role: str = "user"  # "user" or "assistant"
    cli_used: str | None = None
    linked_message_id: str | None = None  # ID of parent message for thread continuation
    priority: int = 2

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v: int) -> int:
        return _validate_priority(v)


class ProjectMessageResponse(BaseModel):
    """Response model for a project message."""
    id: str
    project_id: str
    content: str
    role: str
    cli_used: str | None = None
    linked_message_id: str | None = None
    metadata: dict = {}
    created_at: str
    priority: int = 2


class TaskInput(BaseModel):
    prompt: str
    directory: str | None = None
    github_url: str | None = None
    args: list[str] = []
    model: str | None = None
    effort: str | None = None
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
    exit_code: int | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    bucket_id: str = "main"
    priority: int = 2
    created_at: str | None = None


class TaskDetailResponse(BaseModel):
    id: str
    prompt: str
    directory: str
    status: str
    exit_code: int | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    bucket_id: str = "main"
    args: list[str] = []
    json_output: dict | None = None
    created_at: str | None = None
    priority: int = 2


class TaskPatchInput(BaseModel):
    prompt: str | None = None
    model: str | None = None
    effort: str | None = None
    priority: int | None = None

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v: int | None) -> int | None:
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
    rate_limit_result: str | None = None


class ChatCreateInput(BaseModel):
    """Input model for creating a chat bucket."""

    directory: str
    label: str | None = None


class ChatResponse(BaseModel):
    """Response model for a chat bucket."""

    id: str
    label: str
    directory: str | None = None
    created_at: str
    message_count: int = 0
    last_activity: str | None = None
    session_usage_percent: float | None = None


class MessageInput(BaseModel):
    """Input model for sending a chat message (creates a task)."""

    prompt: str
    model: str | None = None
    effort: str | None = None
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
    assistant_response: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None


class CLIConfigResponse(BaseModel):
    """Response model for CLI configuration."""

    name: str
    path: str
    models: list[str]
    cli_type: str
    enabled: bool
    default_model: str = ""


class StepPlanGenerateRequest(BaseModel):
    """Input model for generating a multi-step coding plan."""

    project_id: str
    message_id: str
    prompt: str
