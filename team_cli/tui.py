"""Text User Interface for TeamCLI."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, ScrollableContainer, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .executor import CLIManager, TaskExecutor
from .models import ProjectMessage, Task
from .priority_engine import PRIORITY_LABELS, promote_priority
from .storage import (
    cleanup_old_tasks,
    delete_project_message,
    load_project_messages,
    load_projects,
    save_project_message,
)

logger = logging.getLogger(__name__)

_API_BASE = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Task-related modals (unchanged)
# ---------------------------------------------------------------------------

class AddTaskScreen(ModalScreen[dict | None]):
    """Modal screen for adding a new task."""

    def compose(self) -> ComposeResult:
        """Compose the add task form."""
        yield Container(
            Label("[bold]Add New Task[/bold]"),
            VerticalScroll(
                Label("Directory (required):"),
                Input(placeholder="/path/to/directory", id="directory_input"),
                Label("Prompt (required):"),
                Input(placeholder="Enter task prompt...", id="prompt_input"),
                Label("Model (optional):"),
                Select(
                    [
                        ("(None)", ""),
                        ("Haiku", "haiku"),
                        ("Sonnet", "sonnet"),
                        ("Opus", "opus"),
                    ],
                    allow_blank=True,
                    id="model_select",
                ),
                Label("Effort level (optional):"),
                Select(
                    [
                        ("(None)", ""),
                        ("Low", "low"),
                        ("Medium", "medium"),
                        ("High", "high"),
                        ("Extra High", "xhigh"),
                        ("Maximum", "max"),
                    ],
                    allow_blank=True,
                    id="effort_select",
                ),
                Label("Additional args (optional, space-separated):"),
                Input(placeholder="--add-dir /path --max-budget-usd 1.0", id="args_input"),
            ),
            Container(
                Button("Create", id="create", variant="success"),
                Button("Cancel", id="cancel", variant="primary"),
                id="add_task_buttons",
            ),
            id="add_task_dialog",
        )

    @on(Button.Pressed, "#create")
    def on_create(self) -> None:
        """Handle create button."""
        from textual.widgets._select import NoSelection

        directory = self.query_one("#directory_input", Input).value.strip()
        prompt = self.query_one("#prompt_input", Input).value.strip()

        model_value = self.query_one("#model_select", Select).value
        model = (
            "" if isinstance(model_value, NoSelection) or model_value == "" else str(model_value)
        )

        effort_value = self.query_one("#effort_select", Select).value
        effort = (
            "" if isinstance(effort_value, NoSelection) or effort_value == "" else str(effort_value)
        )

        args = self.query_one("#args_input", Input).value.strip()

        if not directory:
            self.notify("Directory is required", severity="error")
            return
        if not prompt:
            self.notify("Prompt is required", severity="error")
            return

        try:
            dir_path = Path(directory).expanduser().resolve()
            if not dir_path.exists():
                self.notify(f"Directory does not exist: {directory}", severity="error")
                return
            if not dir_path.is_dir():
                self.notify(f"Path is not a directory: {directory}", severity="error")
                return
        except Exception as e:
            self.notify(f"Invalid directory path: {e}", severity="error")
            return

        args_list = []
        if model:
            args_list.extend(["--model", model])
        if effort:
            args_list.extend(["--effort", effort])
        if args:
            args_list.extend(args.split())

        self.dismiss(
            {
                "directory": str(dir_path),
                "prompt": prompt,
                "args": args_list,
            }
        )

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        """Handle cancel button."""
        self.dismiss(None)

    def on_key(self, event) -> None:
        """Handle key press."""
        if event.key == "escape":
            self.dismiss(None)

    CSS = """
    #add_task_dialog {
        width: 80;
        height: auto;
        max-height: 90%;
        border: thick $background 80%;
        background: $surface;
        padding: 1;
        align: center middle;
    }

    #add_task_dialog VerticalScroll {
        width: 100%;
        height: auto;
        max-height: 30;
        margin: 1 0;
    }

    #add_task_dialog Label {
        margin-top: 1;
    }

    #add_task_dialog Input {
        width: 100%;
        margin-bottom: 1;
    }

    #add_task_dialog Select {
        width: 100%;
        margin-bottom: 1;
    }

    #add_task_buttons {
        width: 100%;
        height: 3;
        align: center middle;
        layout: horizontal;
    }

    #add_task_buttons Button {
        height: 3;
        margin: 0 1;
        padding: 0 2;
    }
    """


class ConfirmDialog(ModalScreen[bool]):
    """Modal dialog for confirmation."""

    def __init__(self, message: str) -> None:
        """Initialize the dialog."""
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Container(
            Label(self.message),
            Container(
                Button("Yes", id="yes", variant="error"),
                Button("No", id="no", variant="primary"),
                id="dialog_buttons",
            ),
            id="dialog",
        )

    @on(Button.Pressed, "#yes")
    def on_yes(self) -> None:
        """Handle yes button."""
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def on_no(self) -> None:
        """Handle no button."""
        self.dismiss(False)

    CSS = """
    #dialog {
        width: 50;
        height: 11;
        border: thick $background 80%;
        background: $surface;
        padding: 1;
        align: center middle;
    }

    #dialog_buttons {
        width: 100%;
        height: 3;
        align: center middle;
        layout: horizontal;
    }

    #dialog Button {
        height: 3;
        margin: 0;
        padding: 0 1;
    }
    """


class DetailedOutputScreen(ModalScreen):
    """Screen showing detailed JSON output."""

    def __init__(self, task: Task) -> None:
        """Initialize the screen."""
        super().__init__()
        self.task = task

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        output = self.task.json_output or {}
        formatted = json.dumps(output, indent=2)

        yield Container(
            Label(f"[bold]Task {self.task.id} - Detailed Output[/bold]"),
            Static(formatted, id="detailed_json"),
            Button("Close", id="close", variant="primary"),
            id="detail_container",
        )

    @on(Button.Pressed, "#close")
    def on_close(self) -> None:
        """Handle close button."""
        self.dismiss()

    def on_key(self, event) -> None:
        """Handle key press."""
        if event.key == "escape":
            self.dismiss()

    CSS = """
    #detail_container {
        width: 80%;
        height: 80%;
        border: thick $background 80%;
        background: $surface;
        padding: 1;
        align: center middle;
    }

    #detailed_json {
        width: 100%;
        height: 1fr;
        overflow-y: scroll;
        border: solid $primary;
        padding: 1;
    }

    #detail_container Button {
        height: 3;
        width: auto;
        margin-top: 1;
    }
    """


# ---------------------------------------------------------------------------
# Task tab widgets (unchanged internals)
# ---------------------------------------------------------------------------

class TaskListWidget(Static):
    """Widget displaying the list of tasks in a table."""

    def __init__(self, executor: TaskExecutor | None) -> None:
        """Initialize the task list widget."""
        super().__init__()
        self.executor = executor
        self.task_map: dict[str, Task] = {}

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        table = DataTable()
        table.add_columns("ID", "Prompt", "Directory", "Status")
        table.cursor_type = "row"
        yield table

    def update_tasks(self) -> None:
        """Update the task list display."""
        if self.executor is None:
            return
        table = self.query_one(DataTable)
        table.clear()
        self.task_map.clear()

        for idx, task in enumerate(self.executor.pool.tasks):
            task_id = task.id
            kind = getattr(task, 'kind', 'request') or 'request'
            kind_tag = "\\[sub]" if kind == 'subtask' else "\\[req]"
            parent_prefix = "  ↳ " if getattr(task, 'parent_task_id', None) else ""
            short_prompt = task.prompt[:20] + ("..." if len(task.prompt) > 20 else "")
            prompt = f"{parent_prefix}{kind_tag} {short_prompt}"
            directory = str(task.directory)
            cli_name = getattr(task, 'cli_id', None) or 'claude'

            status_emoji = {
                "pending": "⏸",
                "running": "▶",
                "success": "✓",
                "failed": "✗",
                "skipped": "⏭",
                "rate_limit_retry": "⟳",
                "stopped": "⛔",
            }.get(task.status, "?")

            status_text = f"{status_emoji} {task.status}"

            if task.status == "success":
                status_display = f"[green]{status_text}[/green] {cli_name}"
            elif task.status in ("failed", "stopped"):
                status_display = f"[bold red]{status_text}[/bold red] {cli_name}"
            elif task.status in ("running", "rate_limit_retry"):
                status_display = f"[yellow]{status_text}[/yellow] {cli_name}"
            else:
                status_display = f"[dim]{status_text}[/dim] {cli_name}"

            table.add_row(task_id, prompt, directory, status_display)
            self.task_map[str(idx)] = task


class JsonOutputWidget(Static):
    """Widget displaying JSON output of selected task."""

    can_focus = True

    def __init__(self) -> None:
        """Initialize the JSON output widget."""
        super().__init__()
        self.current_task: Task | None = None

    @staticmethod
    def exit_code_meaning(exit_code: int | None) -> str:
        """Return a human-readable label for *exit_code*."""
        if exit_code is None:
            return ""
        if exit_code == 0:
            return "✓ Success"
        if exit_code == 1:
            return "⚠ General error"
        if exit_code == 2:
            return "⚠ Misuse of shell command"
        if exit_code == 126:
            return "⚠ Command cannot execute"
        if exit_code == 127:
            return "⚠ Command not found"
        if exit_code == 130:
            return "⏸ Terminated by Ctrl+C (SIGINT)"
        if exit_code == 143:
            return "⏹ Terminated by SIGTERM (killed/timeout)"
        if exit_code >= 128:
            return f"⏹ Terminated by signal {exit_code - 128}"
        return f"⚠ Error code {exit_code}"

    def update_content(self, task: Task | None) -> None:
        """Update the displayed JSON output."""
        self.current_task = task

        if task is None:
            self.update("No task selected")
            return

        content = f"[bold]Task {task.id}[/bold]\n\n"
        content += f"[bold]Prompt:[/bold]\n{task.prompt}\n\n"

        if task.exit_code is not None:
            meaning = self.exit_code_meaning(task.exit_code)
            content += f"Exit: {task.exit_code} ({meaning}) | "
        else:
            content += "Exit: - | "

        if task.duration_ms is not None:
            content += f"Duration: {task.duration_ms/1000:.1f}s | "
        else:
            content += "Duration: - | "

        content += f"Retry: {task.retry_count}\n\n"

        if task.json_output is None:
            content += "[dim]No output yet[/dim]"
        else:
            output = task.json_output
            if "tokens_used" in output:
                content += f"[bold]Tokens used:[/bold] {output['tokens_used']:,}\n"
            result_value = output.get("result", "")
            if result_value:
                content += f"[bold]Result:[/bold]\n{str(result_value).strip()}\n"

        self.update(content)


class ResultWidget(Static):
    """Widget displaying task result and output."""

    can_focus = True

    def __init__(self) -> None:
        """Initialize the result widget."""
        super().__init__()
        self.current_task: Task | None = None

    def update_content(self, task: Task | None) -> None:
        """Update the displayed result."""
        self.current_task = task

        if task is None:
            self.update("")
            return

        if task.json_output is None:
            self.update("[dim]No output yet[/dim]")
            return

        output = task.json_output
        content = ""

        if "tokens_used" in output:
            content += f"[bold]Tokens used:[/bold] {output['tokens_used']:,}\n"

        if "session_usage_percent" in output:
            usage = output["session_usage_percent"]
            color = "red" if usage > 80 else "yellow" if usage > 50 else "green"
            content += f"[bold]Session usage:[/bold] [{color}]{usage}%[/{color}]\n\n"

        result_value = output.get("result", "")
        if result_value:
            result = str(result_value).strip()
            content += f"[bold]Result:[/bold]\n{result}\n\n"

        if "code_blocks" in output and output["code_blocks"]:
            content += f"[bold]Code blocks:[/bold] {len(output['code_blocks'])}\n"
            for i, block in enumerate(output["code_blocks"][:5]):
                lang = block.get("language", "unknown")
                filename = block.get("filename", "")
                content += f"  [{i+1}] {lang}: {filename}\n"
            content += "\n"

        if "files_changed" in output and output["files_changed"]:
            files = ", ".join(output["files_changed"][:5])
            if len(output["files_changed"]) > 5:
                files += f" ... ({len(output['files_changed'])} total)"
            content += f"[bold]Files changed:[/bold] {files}\n\n"

        self.update(content if content else "[dim]No output yet[/dim]")


class LogWidget(Static):
    """Widget displaying logs."""

    can_focus = True

    def __init__(self) -> None:
        """Initialize the log widget."""
        super().__init__()
        self.logs: list[str] = []
        self.max_lines = 20

    def add_log(self, message: str) -> None:
        """Add a log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[dim]{timestamp}[/dim] {message}")
        if len(self.logs) > self.max_lines:
            self.logs.pop(0)
        self.update("\n".join(self.logs))


# ---------------------------------------------------------------------------
# Project tab widgets
# ---------------------------------------------------------------------------

class ProjectListWidget(Static):
    """DataTable listing all projects."""

    def __init__(self) -> None:
        super().__init__()
        self._project_map: dict[int, object] = {}  # row_idx -> Project

    def compose(self) -> ComposeResult:
        table = DataTable(id="projects_table")
        table.add_columns("Name", "Directory", "Default CLI", "CLI Switch")
        table.cursor_type = "row"
        yield table

    def refresh_projects(self, projects: list) -> None:
        """Repopulate the table from *projects* list."""
        table = self.query_one(DataTable)
        table.clear()
        self._project_map.clear()
        for idx, p in enumerate(projects):
            cli_switch = "✓" if p.allow_cli_switch else "✗"
            table.add_row(
                p.name,
                p.directory[:40] + ("…" if len(p.directory) > 40 else ""),
                p.default_cli or "—",
                cli_switch,
            )
            self._project_map[idx] = p

    def selected_project(self) -> object | None:
        """Return the Project at the current cursor row, or None."""
        try:
            table = self.query_one(DataTable)
            idx = table.cursor_row
            return self._project_map.get(idx)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Compose message modal
# ---------------------------------------------------------------------------

class ComposeMessageScreen(ModalScreen[dict | None]):
    """Modal for composing a new project message."""

    def __init__(self, project_name: str, linked_message_id: str | None = None) -> None:
        super().__init__()
        self._project_name = project_name
        self._linked_message_id = linked_message_id

    def compose(self) -> ComposeResult:
        title = "Reply" if self._linked_message_id else "New Message"
        yield Container(
            Label(f"[bold]{title}[/bold] — {self._project_name}"),
            Label("Message:"),
            Input(placeholder="Type your message…", id="msg_input"),
            Container(
                Button("Send", id="send_btn", variant="success"),
                Button("Cancel", id="cancel_btn", variant="primary"),
                id="compose_buttons",
            ),
            id="compose_dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#msg_input", Input).focus()

    @on(Button.Pressed, "#send_btn")
    def on_send(self) -> None:
        content = self.query_one("#msg_input", Input).value.strip()
        if not content:
            self.notify("Message cannot be empty", severity="error")
            return
        self.dismiss({"content": content, "linked_message_id": self._linked_message_id})

    @on(Button.Pressed, "#cancel_btn")
    def on_cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    CSS = """
    #compose_dialog {
        width: 70;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1;
        align: center middle;
    }
    #compose_dialog Label { margin-top: 1; }
    #compose_dialog Input { width: 100%; margin-bottom: 1; }
    #compose_buttons {
        width: 100%;
        height: 3;
        align: center middle;
        layout: horizontal;
    }
    #compose_buttons Button { height: 3; margin: 0 1; padding: 0 2; }
    """


# ---------------------------------------------------------------------------
# Project detail screen
# ---------------------------------------------------------------------------

class ProjectDetailScreen(Screen):
    """Full-screen view of a single project's messages."""

    BINDINGS = [
        ("b", "back", "Back"),
        ("escape", "back", "Back"),
        ("n", "new_message", "New Message"),
        ("p", "promote_message", "Promote"),
        ("r", "reply_message", "Reply"),
        ("delete", "delete_message", "Delete"),
    ]

    def __init__(self, project, db_path: Path) -> None:
        super().__init__()
        self.project = project
        self.db_path = db_path
        self._messages: list[ProjectMessage] = []
        self._msg_map: dict[int, ProjectMessage] = {}

    # ---- layout ----

    def compose(self) -> ComposeResult:
        p = self.project
        cli_switch = "Yes" if p.allow_cli_switch else "No"
        meta = (
            f"[bold]{p.name}[/bold]  |  {p.directory}"
            f"  |  CLI: {p.default_cli or '(auto)'}  |  Switch: {cli_switch}"
        )
        yield Header()
        yield Static(meta, id="proj_meta")
        with ScrollableContainer(id="msg_scroll"):
            yield DataTable(id="msg_table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#msg_table", DataTable)
        table.add_columns("Role", "Priority", "CLI", "Content", "Created")
        table.cursor_type = "row"
        self._reload_messages()

    # ---- data ----

    def _reload_messages(self) -> None:
        self._messages = load_project_messages(self.db_path, self.project.id)
        table = self.query_one("#msg_table", DataTable)
        table.clear()
        self._msg_map.clear()
        for idx, m in enumerate(self._messages):
            label = PRIORITY_LABELS.get(m.priority, str(m.priority))
            content_preview = m.content[:60] + ("…" if len(m.content) > 60 else "")
            created = m.created_at.strftime("%m-%d %H:%M") if m.created_at else ""
            table.add_row(m.role, label, m.cli_used or "—", content_preview, created)
            self._msg_map[idx] = m

    def _selected_message(self) -> ProjectMessage | None:
        try:
            table = self.query_one("#msg_table", DataTable)
            return self._msg_map.get(table.cursor_row)
        except Exception:
            return None

    # ---- actions ----

    def action_back(self) -> None:
        self.app.pop_screen()

    async def action_new_message(self) -> None:
        result = await self.app.push_screen_wait(
            ComposeMessageScreen(self.project.name)
        )
        if result:
            await self._send_message(result["content"], result["linked_message_id"])

    async def action_reply_message(self) -> None:
        msg = self._selected_message()
        linked_id = msg.id if msg else None
        result = await self.app.push_screen_wait(
            ComposeMessageScreen(self.project.name, linked_message_id=linked_id)
        )
        if result:
            await self._send_message(result["content"], result["linked_message_id"])

    def action_promote_message(self) -> None:
        msg = self._selected_message()
        if msg is None:
            self.notify("No message selected", severity="warning")
            return
        new_priority = promote_priority(msg.priority)
        if new_priority == msg.priority:
            self.notify("Already at maximum priority", severity="warning")
            return
        msg.priority = new_priority
        save_project_message(self.db_path, msg)
        self._reload_messages()
        self.notify(
            f"Priority → {PRIORITY_LABELS.get(new_priority, str(new_priority))}",
            severity="information",
        )

    async def action_delete_message(self) -> None:
        msg = self._selected_message()
        if msg is None:
            self.notify("No message selected", severity="warning")
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmDialog("Delete this message?")
        )
        if confirmed:
            delete_project_message(self.db_path, msg.id)
            self._reload_messages()
            self.notify("Message deleted", severity="information")

    async def _send_message(self, content: str, linked_message_id: str | None) -> None:
        """POST to the API, falling back to direct storage if API is unreachable."""
        payload = {"content": content, "role": "user"}
        if linked_message_id:
            payload["linked_message_id"] = linked_message_id
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/api/projects/{self.project.id}/messages",
                    json=payload,
                )
            if resp.status_code in (200, 201):
                self.notify("Message sent", severity="information")
            else:
                self.notify(f"API error {resp.status_code}", severity="error")
        except Exception:
            # API not running — save directly to DB
            msg_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            msg = ProjectMessage(
                id=msg_id,
                project_id=self.project.id,
                content=content,
                role="user",
                linked_message_id=linked_message_id,
            )
            save_project_message(self.db_path, msg)
            self.notify("Message saved (offline)", severity="information")
        self._reload_messages()

    CSS = """
    #proj_meta {
        height: 3;
        padding: 1;
        background: $boost;
        border-bottom: solid $primary;
    }
    #msg_scroll {
        height: 1fr;
    }
    """


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class PoolTUI(App):
    """Main TUI application for TeamCLI."""

    CSS = """
    Screen {
        layout: vertical;
    }

    TabbedContent {
        height: 1fr;
    }

    /* Tasks tab */
    #task_list_widget {
        height: 30%;
        border: solid green;
        padding: 1;
    }

    #json_output_container {
        height: 45%;
        layout: vertical;
    }

    #prompt_container {
        height: 1fr;
        border: solid blue;
    }

    #result_container {
        height: 1fr;
        border: solid cyan;
    }

    #json_output {
        width: 100%;
        height: auto;
        padding: 1;
    }

    #result_output {
        width: 100%;
        height: auto;
        padding: 1;
    }

    #logs_container {
        height: 18%;
        border: solid yellow;
    }

    #logs {
        width: 100%;
        height: auto;
        padding: 1;
    }

    #controls {
        height: 3;
        layout: horizontal;
    }

    Button {
        height: 3;
        margin: 0;
        padding: 0 1;
    }

    /* Projects tab */
    #projects_tab_content {
        height: 1fr;
        padding: 1;
    }

    #project_list_widget {
        height: 1fr;
        border: solid $primary;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        # Tasks tab bindings
        ("p", "toggle_pause", "Pause/Resume"),
        ("s", "skip_task", "Skip"),
        ("x", "stop_task", "Stop"),
        ("d", "delete_task", "Delete"),
        ("enter", "activate_row", "Open/Detail"),
        ("r", "retry_task", "Retry"),
        ("a", "add_task", "Add Task"),
    ]

    def __init__(
        self,
        pool_file: Path,
        max_concurrent: int = 1,
        cli_manager: "CLIManager | None" = None,
    ) -> None:
        """Initialize the TUI application."""
        super().__init__()
        self.pool_file = pool_file
        self.max_concurrent = max_concurrent
        self.cli_manager = cli_manager
        self.executor: TaskExecutor | None = None
        self.selected_task: Task | None = None

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Header()

        with TabbedContent(initial="tab_tasks"):
            with TabPane("Tasks", id="tab_tasks"):
                task_list_widget = TaskListWidget(None)
                task_list_widget.id = "task_list_widget"
                yield task_list_widget

                with Container(id="json_output_container"):
                    with ScrollableContainer(id="prompt_container"):
                        json_widget = JsonOutputWidget()
                        json_widget.id = "json_output"
                        yield json_widget
                    with ScrollableContainer(id="result_container"):
                        result_widget = ResultWidget()
                        result_widget.id = "result_output"
                        yield result_widget

                with ScrollableContainer(id="logs_container"):
                    log_widget = LogWidget()
                    log_widget.id = "logs"
                    yield log_widget

                yield Container(
                    Button("Add Task", id="add_task_btn", variant="success"),
                    Button("Pause", id="pause_btn", variant="warning"),
                    Button("Skip", id="skip_btn", variant="error"),
                    Button("Stop", id="stop_btn", variant="error"),
                    Button("Delete", id="delete_btn", variant="error"),
                    Button("Retry", id="retry_btn", variant="warning"),
                    Button("Quit", id="quit_btn", variant="primary"),
                    id="controls",
                )

            with TabPane("Projects", id="tab_projects"):
                with Container(id="projects_tab_content"):
                    proj_list = ProjectListWidget()
                    proj_list.id = "project_list_widget"
                    yield proj_list

        yield Footer()

    # ---- helpers ----

    def _update_detail(self, task: "Task | None") -> None:
        """Update both prompt and result detail widgets."""
        self.query_one("#json_output", JsonOutputWidget).update_content(task)
        self.query_one("#result_output", ResultWidget).update_content(task)

    def _active_tab(self) -> str:
        try:
            return str(self.query_one(TabbedContent).active)
        except Exception:
            return "tab_tasks"

    # ---- lifecycle ----

    async def on_mount(self) -> None:
        """Called when app is mounted."""
        self.executor = TaskExecutor(
            self.pool_file,
            on_task_update=self._on_task_update,
            max_concurrent=self.max_concurrent,
            cli_manager=self.cli_manager,
        )

        task_list = self.query_one("#task_list_widget", TaskListWidget)
        task_list.executor = self.executor

        log_widget = self.query_one("#logs", LogWidget)
        log_widget.add_log("Loading tasks…")

        try:
            await self.executor.load_tasks()
            log_widget.add_log(f"Loaded {len(self.executor.pool.tasks)} tasks")
            task_list.update_tasks()
            self._start_execution()
        except Exception as e:
            log_widget.add_log(f"[red]Error loading tasks: {e}[/red]")

    @work(exclusive=True)
    async def _start_execution(self) -> None:
        """Start task execution in background."""
        if self.executor:
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log("[green]Starting task execution…[/green]")
            await self.executor.run_pool()
            log_widget.add_log("[green]All tasks completed[/green]")

    # ---- tab switching ----

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Reload projects whenever the Projects tab becomes active."""
        if str(event.tab.id) == "tab_projects":
            self._reload_project_list()

    def _reload_project_list(self) -> None:
        try:
            projects = load_projects(self.pool_file)
            self.query_one("#project_list_widget", ProjectListWidget).refresh_projects(projects)
        except Exception as e:
            self.notify(f"Error loading projects: {e}", severity="error")

    # ---- task update callback ----

    def _on_task_update(self, task: Task) -> None:
        self.call_later(self._update_ui, task)

    def _update_ui(self, task: Task) -> None:
        task_list = self.query_one("#task_list_widget", TaskListWidget)
        task_list.update_tasks()

        log_widget = self.query_one("#logs", LogWidget)
        log_widget.add_log(f"Task {task.id}: {task.status}")

        if self.selected_task and self.selected_task.id == task.id:
            self._update_detail(task)

    # ---- row highlight (tasks table) ----

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight — only act on the task table."""
        try:
            table = self.query_one("#task_list_widget DataTable", DataTable)
        except Exception:
            return
        if event.data_table is not table:
            return

        if event.row_key is None or table.cursor_row < 0:
            self.selected_task = None
            self._update_detail(None)
            return

        task_list = self.query_one("#task_list_widget", TaskListWidget)
        row_idx = table.cursor_row
        if str(row_idx) in task_list.task_map:
            self.selected_task = task_list.task_map[str(row_idx)]
            self._update_detail(self.selected_task)
        else:
            self.selected_task = None
            self._update_detail(None)

    # ---- enter / activate ----

    def action_activate_row(self) -> None:
        """Enter key: open project detail if on Projects tab, else show task detail."""
        if self._active_tab() == "tab_projects":
            proj = self.query_one("#project_list_widget", ProjectListWidget).selected_project()
            if proj is not None:
                self.push_screen(ProjectDetailScreen(proj, self.pool_file))
        else:
            self.action_show_detail()

    def action_show_detail(self) -> None:
        """Show detailed output for selected task."""
        if self.selected_task and self.selected_task.json_output:
            self.push_screen(DetailedOutputScreen(self.selected_task))

    # ---- task actions ----

    def action_toggle_pause(self) -> None:
        if self._active_tab() != "tab_tasks":
            return
        if self.executor:
            if self.executor.paused:
                self.executor.resume()
                self.query_one("#logs", LogWidget).add_log("[green]Execution resumed[/green]")
                self.query_one("#pause_btn", Button).label = "Pause"
            else:
                self.executor.pause()
                self.query_one("#logs", LogWidget).add_log("[yellow]Execution paused[/yellow]")
                self.query_one("#pause_btn", Button).label = "Resume"

    def action_skip_task(self) -> None:
        if self._active_tab() != "tab_tasks":
            return
        if self.executor and self.executor.current_task:
            self.query_one("#logs", LogWidget).add_log(
                f"[yellow]Skipping task {self.executor.current_task.id}[/yellow]"
            )
            self.executor.skip_current()

    async def action_stop_task(self) -> None:
        if self._active_tab() != "tab_tasks":
            return
        log_widget = self.query_one("#logs", LogWidget)
        if not self.selected_task:
            log_widget.add_log("[red]No task selected[/red]")
            return
        task = self.selected_task
        if task.status != "running":
            log_widget.add_log(f"[yellow]Task {task.id} is {task.status}, cannot stop[/yellow]")
            return
        result = await self.push_screen_wait(ConfirmDialog(f"Hard-stop running task {task.id}?"))
        if result and self.executor:
            await self.executor.stop_task(task.id)
            log_widget.add_log(f"[red]Task {task.id} hard-stopped[/red]")
            self.query_one("#task_list_widget", TaskListWidget).update_tasks()
            self._update_detail(self.selected_task)

    async def action_delete_task(self) -> None:
        if self._active_tab() != "tab_tasks":
            return
        if not self.selected_task:
            self.query_one("#logs", LogWidget).add_log("[red]No task selected[/red]")
            return
        result = await self.push_screen_wait(ConfirmDialog(f"Delete task {self.selected_task.id}?"))
        if result and self.executor:
            task_id = self.selected_task.id
            if self.executor.delete_task(task_id):
                self.query_one("#logs", LogWidget).add_log(f"[red]Deleted task {task_id}[/red]")
                self.query_one("#task_list_widget", TaskListWidget).update_tasks()
                self.selected_task = None
                self._update_detail(None)

    def action_retry_task(self) -> None:
        if self._active_tab() != "tab_tasks":
            return
        log_widget = self.query_one("#logs", LogWidget)
        if not self.selected_task:
            log_widget.add_log("[red]No task selected[/red]")
            return
        task = self.selected_task
        if task.status in ("failed", "success"):
            if self.executor:
                self.executor.reset_task_for_retry(task)
            log_widget.add_log(
                f"[yellow]Task {task.id} reset to pending (retry #{task.retry_count})[/yellow]"
            )
            self.query_one("#task_list_widget", TaskListWidget).update_tasks()
            self._update_detail(task)
        else:
            log_widget.add_log(f"[yellow]Task {task.id} is {task.status}, cannot retry[/yellow]")

    async def action_add_task(self) -> None:
        if self._active_tab() != "tab_tasks":
            return
        result = await self.push_screen_wait(AddTaskScreen())
        if result and self.executor:
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            new_task = Task(
                id=task_id,
                prompt=result["prompt"],
                directory=Path(result["directory"]),
                args=result["args"],
                status="pending",
                priority=2,
            )
            self.executor.pool.tasks.append(new_task)
            removed = cleanup_old_tasks(self.executor.pool, max_age_hours=48)
            if removed > 0:
                logger.info(f"Automatically cleaned up {removed} old completed tasks")
            self.executor._save_state()
            self.query_one("#task_list_widget", TaskListWidget).update_tasks()
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log(f"[green]Added new task {task_id}: {result['prompt'][:40]}…[/green]")
            if removed > 0:
                log_widget.add_log(f"[dim]Cleaned up {removed} old completed task(s)[/dim]")

    # ---- button handlers ----

    @on(Button.Pressed, "#add_task_btn")
    def on_add_task_pressed(self) -> None:
        self.run_worker(self.action_add_task())

    @on(Button.Pressed, "#pause_btn")
    def on_pause_pressed(self) -> None:
        self.action_toggle_pause()

    @on(Button.Pressed, "#skip_btn")
    def on_skip_pressed(self) -> None:
        self.action_skip_task()

    @on(Button.Pressed, "#stop_btn")
    def on_stop_pressed(self) -> None:
        self.run_worker(self.action_stop_task())

    @on(Button.Pressed, "#delete_btn")
    def on_delete_pressed(self) -> None:
        self.run_worker(self.action_delete_task())

    @on(Button.Pressed, "#retry_btn")
    def on_retry_pressed(self) -> None:
        self.action_retry_task()

    @on(Button.Pressed, "#quit_btn")
    def on_quit_pressed(self) -> None:
        self.exit()

    def action_quit(self) -> None:
        if self.executor:
            self.executor.should_stop = True
        self.exit()


async def run_tui(pool_file: Path, max_concurrent: int = 1, cli_manager: CLIManager | None = None) -> None:
    """Run the TUI application."""
    app = PoolTUI(pool_file, max_concurrent=max_concurrent, cli_manager=cli_manager)
    await app.run_async()
