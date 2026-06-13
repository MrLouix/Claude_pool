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


# ---------------------------------------------------------------------------
# v2 Project models (old ProjectInput / ProjectEntry kept for backward compat)
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    """v2 input for creating a project."""

    name: str
    directory: str
    git_remote: str | None = None
    # backward-compat fields accepted but optional
    default_cli: str | None = None
    allow_cli_switch: bool = True


class ProjectUpdate(BaseModel):
    """v2 input for PATCH /api/projects/{id}. All fields optional."""

    name: str | None = None
    git_remote: str | None = None
    archived: bool | None = None
    # backward-compat fields
    directory: str | None = None
    default_cli: str | None = None
    allow_cli_switch: bool | None = None


class ProjectResponse(BaseModel):
    """v2 response for a project (superset of legacy ProjectEntry)."""

    id: str
    name: str
    directory: str
    git_remote: str | None = None
    created_at: str
    archived: bool = False
    active_task_count: int = 0
    # backward-compat fields
    default_cli: str | None = None
    allow_cli_switch: bool = True
    message_count: int = 0


# ---------------------------------------------------------------------------
# v2 Chat models (old ChatCreateInput / ChatResponse kept for backward compat)
# ---------------------------------------------------------------------------


class ChatCreate(BaseModel):
    """v2 input for creating a chat within a project."""

    label: str


class ChatUpdate(BaseModel):
    """v2 input for PATCH /api/chats/{id}."""

    label: str | None = None
    position: int | None = None


class V2ChatResponse(BaseModel):
    """v2 response for a project chat."""

    id: str
    project_id: str
    label: str
    position: int
    created_at: str


# ---------------------------------------------------------------------------
# v2 Message models (old MessageInput / MessageResponse kept for backward compat)
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    """v2 input for sending a message in a chat.

    Accepts both v2 ``content`` and legacy ``prompt`` field so existing
    clients continue to work without changes.
    """

    content: str | None = None
    prompt: str | None = None  # legacy alias — resolved to content below
    thread_root_id: str | None = None
    cli_id: str | None = None
    model: str | None = None
    effort: str | None = None  # legacy
    priority: int = 2  # legacy

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v: int) -> int:
        return _validate_priority(v)

    def model_post_init(self, __context: object) -> None:
        if self.content is None and self.prompt is not None:
            self.content = self.prompt
        if self.content is None:
            raise ValueError("'content' (or legacy 'prompt') is required")


class V2MessageResponse(BaseModel):
    """v2 response for a message."""

    id: str
    chat_id: str
    thread_root_id: str | None = None
    role: str
    content: str
    task_id: str | None = None
    created_at: str


class TaskSummary(BaseModel):
    """Compact task view used in thread listings."""

    id: str
    status: str
    prompt: str
    created_at: str
    parent_message_id: str | None = None
    parent_task_id: str | None = None
    kind: str = "request"


class ThreadResponse(BaseModel):
    """Full thread view: root message + subtasks + reply messages."""

    root: V2MessageResponse
    subtasks: list[TaskSummary]
    messages: list[V2MessageResponse]


# ---------------------------------------------------------------------------
# CLI commands settings API (Step 3)
# ---------------------------------------------------------------------------


class CliCommandResponse(BaseModel):
    """Response model for a CLI command configuration."""

    id: str
    name: str
    binary: str
    args_template: str
    resume_template: str | None = None
    model_flag: str | None = None
    models: list[str] = []
    default_model: str | None = None
    enabled: bool = True
    priority_requests: int = 100
    priority_subtasks: int = 100
    parser: str = "claude_json"


class CliCommandUpdate(BaseModel):
    """Input model for PUT /api/settings/cli-commands (one entry in the list)."""

    id: str
    name: str
    binary: str
    args_template: str
    resume_template: str | None = None
    model_flag: str | None = None
    models: list[str] = []
    default_model: str | None = None
    enabled: bool = True
    priority_requests: int = 100
    priority_subtasks: int = 100
    parser: str = "claude_json"


class CliCommandTestInput(BaseModel):
    """Input model for POST /api/settings/cli-commands/test."""

    id: str


class CliCommandTestResult(BaseModel):
    """Result of testing a CLI command binary."""

    success: bool
    output: str
