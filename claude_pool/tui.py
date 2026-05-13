"""Text User Interface for Claude Pool."""

import asyncio
import json
import logging
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static

from .executor import TaskExecutor
from .models import Task

logger = logging.getLogger(__name__)

def get_exit_code_meaning(exit_code: int | None) -> str:
    """Get human-readable meaning of exit code."""
    if exit_code is None:
        return ""
    
    # Common exit codes
    if exit_code == 0:
        return "✓ Success"
    elif exit_code == 1:
        return "⚠ General error"
    elif exit_code == 2:
        return "⚠ Misuse of shell command"
    elif exit_code == 126:
        return "⚠ Command cannot execute"
    elif exit_code == 127:
        return "⚠ Command not found"
    elif exit_code == 130:
        return "⏸ Terminated by Ctrl+C (SIGINT)"
    elif exit_code == 143:
        return "⏹ Terminated by SIGTERM (killed/timeout)"
    elif exit_code >= 128:
        signal_num = exit_code - 128
        return f"⏹ Terminated by signal {signal_num}"
    else:
        return f"⚠ Error code {exit_code}"



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
        directory = self.query_one("#directory_input", Input).value.strip()
        prompt = self.query_one("#prompt_input", Input).value.strip()
        model = self.query_one("#model_select", Select).value or ""
        effort = self.query_one("#effort_select", Select).value or ""
        args = self.query_one("#args_input", Input).value.strip()

        # Validate required fields
        if not directory:
            self.notify("Directory is required", severity="error")
            return
        if not prompt:
            self.notify("Prompt is required", severity="error")
            return

        # Build args list
        args_list = []
        if model:
            args_list.extend(["--model", model])
        if effort:
            args_list.extend(["--effort", effort])
        if args:
            # Split by spaces, respecting quotes
            args_list.extend(args.split())

        self.dismiss({
            "directory": directory,
            "prompt": prompt,
            "args": args_list,
        })

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


class TaskListWidget(Static):
    """Widget displaying the list of tasks in a table."""

    def __init__(self, executor: TaskExecutor) -> None:
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
        table = self.query_one(DataTable)
        table.clear()
        self.task_map.clear()

        for idx, task in enumerate(self.executor.pool.tasks):
            # Format task fields
            task_id = task.id
            prompt = task.prompt[:20] + ("..." if len(task.prompt) > 20 else "")
            directory = str(task.directory)
            
            # Format status with emoji and color
            status_emoji = {
                "pending": "⏸",
                "running": "▶",
                "success": "✓",
                "failed": "✗",
                "skipped": "⏭",
                "rate_limit_retry": "⟳",
            }.get(task.status, "?")
            
            status_text = f"{status_emoji} {task.status}"
            
            # Apply color based on status
            if task.status == "success":
                status_display = f"[green]{status_text}[/green]"
            elif task.status == "failed":
                status_display = f"[red]{status_text}[/red]"
            elif task.status in ("running", "rate_limit_retry"):
                status_display = f"[yellow]{status_text}[/yellow]"
            else:
                status_display = f"[dim]{status_text}[/dim]"
            
            # Add row and store task mapping by row index
            row_key = table.add_row(task_id, prompt, directory, status_display)
            # Store by both row_key value (int) and task_id (str) for flexibility
            self.task_map[str(idx)] = task
            self.task_map[task_id] = task


class JsonOutputWidget(Static):
    """Widget displaying JSON output of selected task."""

    def __init__(self) -> None:
        """Initialize the JSON output widget."""
        super().__init__()
        self.current_task: Task | None = None

    def update_content(self, task: Task | None) -> None:
        """Update the displayed JSON output."""
        self.current_task = task

        if task is None:
            self.update("No task selected")
            return

        lines = [f"[bold]Task {task.id}[/bold]\n"]

        # Display full prompt
        lines.append(f"[bold]Prompt:[/bold]\n{task.prompt}\n")

        # Display exit_code, duration_ms, retry_count
        if task.exit_code is not None:
            meaning = get_exit_code_meaning(task.exit_code)
            lines.append(f"Exit code: {task.exit_code} - {meaning}")
        else:
            lines.append("Exit code: -")

        if task.duration_ms is not None:
            lines.append(f"Duration: {task.duration_ms}ms ({task.duration_ms/1000:.1f}s)")
        else:
            lines.append("Duration: -")

        lines.append(f"Retry count: {task.retry_count}")
        lines.append("")

        # Display all json_output fields
        if task.json_output is None:
            lines.append("[dim]No output yet[/dim]")
        else:
            output = task.json_output
            
            # Result
            if "result" in output:
                result = str(output["result"])
                if len(result) > 500:
                    result = result[:500] + "..."
                lines.append(f"[bold]Result:[/bold]\n{result}\n")

            # Code blocks
            if "code_blocks" in output and output["code_blocks"]:
                lines.append(f"[bold]Code blocks:[/bold] {len(output['code_blocks'])}")
                for i, block in enumerate(output["code_blocks"][:5]):
                    lang = block.get("language", "unknown")
                    filename = block.get("filename", "")
                    lines.append(f"  [{i+1}] {lang}: {filename}")
                lines.append("")

            # Files changed
            if "files_changed" in output and output["files_changed"]:
                files = ', '.join(output['files_changed'][:5])
                if len(output['files_changed']) > 5:
                    files += f" ... ({len(output['files_changed'])} total)"
                lines.append(f"[bold]Files changed:[/bold] {files}\n")

            # Tokens
            if "tokens_used" in output:
                tokens = output['tokens_used']
                lines.append(f"[bold]Tokens used:[/bold] {tokens:,}")

            # Session usage
            if "session_usage_percent" in output:
                usage = output["session_usage_percent"]
                color = "red" if usage > 80 else "yellow" if usage > 50 else "green"
                lines.append(f"[bold]Session usage:[/bold] [{color}]{usage}%[/{color}]")

        lines.append("\n[dim]Press Enter for detailed JSON view[/dim]")

        self.update("\n".join(lines))


class LogWidget(Static):
    """Widget displaying logs."""

    def __init__(self) -> None:
        """Initialize the log widget."""
        super().__init__()
        self.logs: list[str] = []
        self.max_lines = 20

    def add_log(self, message: str) -> None:
        """Add a log message."""
        import datetime

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[dim]{timestamp}[/dim] {message}")
        if len(self.logs) > self.max_lines:
            self.logs.pop(0)
        self.update("\n".join(self.logs))


class PoolTUI(App):
    """Main TUI application for Claude Pool."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #task_list_widget {
        height: 35%;
        border: solid green;
        padding: 1;
    }

    #json_output {
        height: 30%;
        border: solid blue;
        padding: 1;
        overflow-y: scroll;
    }

    #logs {
        height: 28%;
        border: solid yellow;
        padding: 1;
        overflow-y: scroll;
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
    """

    BINDINGS = [
        ("p", "toggle_pause", "Pause/Resume"),
        # ("s", "skip_task", "Skip"),  # Disabled for future use
        ("d", "delete_task", "Delete"),
        ("enter", "show_detail", "Detail"),
        ("q", "quit", "Quit"),
        ("r", "retry_task", "Retry"),
        ("a", "add_task", "Add Task"),
    ]

    def __init__(self, pool_file: Path) -> None:
        """Initialize the TUI application."""
        super().__init__()
        self.pool_file = pool_file
        self.executor: TaskExecutor | None = None
        self.selected_task: Task | None = None

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Header()
        
        task_list_widget = TaskListWidget(
            self.executor or TaskExecutor(self.pool_file)
        )
        task_list_widget.id = "task_list_widget"
        yield task_list_widget
        
        json_widget = JsonOutputWidget()
        json_widget.id = "json_output"
        yield json_widget
        
        log_widget = LogWidget()
        log_widget.id = "logs"
        yield log_widget
        
        yield Container(
            Button("Add Task", id="add_task_btn", variant="success"),
            Button("Pause", id="pause_btn", variant="warning"),
            # Button("Skip", id="skip_btn", variant="error"),  # Disabled for future use
            Button("Delete", id="delete_btn", variant="error"),
            Button("Retry", id="retry_btn", variant="warning"),
            Button("Quit", id="quit_btn", variant="primary"),
            id="controls",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Called when app is mounted."""
        # Initialize executor
        self.executor = TaskExecutor(
            self.pool_file, on_task_update=self._on_task_update
        )

        # Update task list widget with executor
        task_list = self.query_one("#task_list_widget", TaskListWidget)
        task_list.executor = self.executor

        # Load tasks
        log_widget = self.query_one("#logs", LogWidget)
        log_widget.add_log("Loading tasks...")

        try:
            await self.executor.load_tasks()
            log_widget.add_log(f"Loaded {len(self.executor.pool.tasks)} tasks")
            task_list.update_tasks()

            # Start execution in background
            self._start_execution()

        except Exception as e:
            log_widget.add_log(f"[red]Error loading tasks: {e}[/red]")

    @work(exclusive=True)
    async def _start_execution(self) -> None:
        """Start task execution in background."""
        if self.executor:
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log("[green]Starting task execution...[/green]")
            await self.executor.run_pool()
            log_widget.add_log("[green]All tasks completed[/green]")

    def _on_task_update(self, task: Task) -> None:
        """Called when a task is updated."""
        # Update UI from main thread
        self.call_later(self._update_ui, task)

    def _update_ui(self, task: Task) -> None:
        """Update UI elements."""
        task_list = self.query_one("#task_list_widget", TaskListWidget)
        task_list.update_tasks()

        log_widget = self.query_one("#logs", LogWidget)
        log_widget.add_log(f"Task {task.id}: {task.status}")

        # Update JSON output if this is the selected task
        if self.selected_task and self.selected_task.id == task.id:
            json_output = self.query_one("#json_output", JsonOutputWidget)
            json_output.update_content(task)

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle task row selection."""
        json_output = self.query_one("#json_output", JsonOutputWidget)
        task_list = self.query_one("#task_list_widget", TaskListWidget)
        
        if event.row_key is not None:
            # Get the row index (cursor_row is 0-based)
            table = self.query_one("#task_list_widget DataTable", DataTable)
            row_idx = table.cursor_row
            
            if str(row_idx) in task_list.task_map:
                self.selected_task = task_list.task_map[str(row_idx)]
                json_output.update_content(self.selected_task)
            else:
                self.selected_task = None
                json_output.update_content(None)
        else:
            self.selected_task = None
            json_output.update_content(None)
    def action_show_detail(self) -> None:
        """Show detailed output for selected task."""
        if self.selected_task and self.selected_task.json_output:
            self.push_screen(DetailedOutputScreen(self.selected_task))

    def action_toggle_pause(self) -> None:
        """Toggle pause state."""
        if self.executor:
            if self.executor.paused:
                self.executor.resume()
                log_widget = self.query_one("#logs", LogWidget)
                log_widget.add_log("[green]Execution resumed[/green]")
                btn = self.query_one("#pause_btn", Button)
                btn.label = "Pause"
            else:
                self.executor.pause()
                log_widget = self.query_one("#logs", LogWidget)
                log_widget.add_log("[yellow]Execution paused[/yellow]")
                btn = self.query_one("#pause_btn", Button)
                btn.label = "Resume"

    # Disabled for future use
    # def action_skip_task(self) -> None:
    #     """Skip current task."""
    #     if self.executor and self.executor.current_task:
    #         log_widget = self.query_one("#logs", LogWidget)
    #         log_widget.add_log(
    #             f"[yellow]Skipping task {self.executor.current_task.id}[/yellow]"
    #         )
    #         self.executor.skip_current()
    #         
    #         # Refresh UI
    #         task_list = self.query_one("#task_list_widget", TaskListWidget)
    #         task_list.update_tasks()

    async def action_delete_task(self) -> None:
        """Delete selected task."""
        if not self.selected_task:
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log("[red]No task selected[/red]")
            return

        # Show confirmation dialog
        result = await self.push_screen_wait(
            ConfirmDialog(f"Delete task {self.selected_task.id}?")
        )

        if result and self.executor:
            task_id = self.selected_task.id
            if self.executor.delete_task(task_id):
                log_widget = self.query_one("#logs", LogWidget)
                log_widget.add_log(f"[red]Deleted task {task_id}[/red]")

                task_list = self.query_one("#task_list_widget", TaskListWidget)
                task_list.update_tasks()

                self.selected_task = None
                json_output = self.query_one("#json_output", JsonOutputWidget)
                json_output.update_content(None)

    @on(Button.Pressed, "#add_task_btn")
    def on_add_task_pressed(self) -> None:
        """Handle add task button press."""
        self.run_worker(self.action_add_task())

    @on(Button.Pressed, "#pause_btn")
    def on_pause_pressed(self) -> None:
        """Handle pause button press."""
        self.action_toggle_pause()

    # Disabled for future use
    # @on(Button.Pressed, "#skip_btn")
    # def on_skip_pressed(self) -> None:
    #     """Handle skip button press."""
    #     self.action_skip_task()

    @on(Button.Pressed, "#delete_btn")
    def on_delete_pressed(self) -> None:
        """Handle delete button press."""
        self.run_worker(self.action_delete_task())

    @on(Button.Pressed, "#retry_btn")
    def on_retry_pressed(self) -> None:
        """Handle retry button press."""
        self.action_retry_task()

    @on(Button.Pressed, "#quit_btn")
    def on_quit_pressed(self) -> None:
        """Handle quit button press."""
        self.exit()


    def action_retry_task(self) -> None:
        """Retry selected task by resetting it to pending and incrementing retry count."""
        if not self.selected_task:
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log("[red]No task selected[/red]")
            return
        
        task = self.selected_task
        if task.status in ("failed", "success"):
            # Reset task fields
            task.status = "pending"
            task.exit_code = None
            task.duration_ms = None
            task.json_output = None
            # Increment retry count
            task.retry_count += 1
            
            if self.executor:
                self.executor._save_state()
            
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log(f"[yellow]Task {task.id} reset to pending (retry #{task.retry_count})[/yellow]")
            
            task_list = self.query_one("#task_list_widget", TaskListWidget)
            task_list.update_tasks()
            
            json_output = self.query_one("#json_output", JsonOutputWidget)
            json_output.update_content(task)
        else:
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log(f"[yellow]Task {task.id} is {task.status}, cannot retry[/yellow]")

    async def action_add_task(self) -> None:
        """Show add task dialog."""
        result = await self.push_screen_wait(AddTaskScreen())
        
        if result and self.executor:
            import uuid
            from datetime import datetime
            
            # Generate unique ID
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            
            # Create new task
            new_task = Task(
                id=task_id,
                prompt=result["prompt"],
                directory=Path(result["directory"]),
                args=result["args"],
                status="pending",
            )
            
            # Add to executor's pool
            self.executor.pool.tasks.append(new_task)
            self.executor._save_state()
            
            # Update UI
            task_list = self.query_one("#task_list_widget", TaskListWidget)
            task_list.update_tasks()
            
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log(f"[green]Added new task {task_id}: {result['prompt'][:40]}...[/green]")

    def action_quit(self) -> None:
        """Quit the application."""
        if self.executor:
            self.executor.should_stop = True
        self.exit()


async def run_tui(pool_file: Path) -> None:
    """Run the TUI application."""
    app = PoolTUI(pool_file)
    await app.run_async()
