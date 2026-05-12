"""Text User Interface for Claude Pool."""

import asyncio
import json
import logging
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Label, Static, Tree
from textual.widgets.tree import TreeNode

from .executor import TaskExecutor
from .models import Task

logger = logging.getLogger(__name__)


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
        margin: 0 1;
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
        width: auto;
        margin-top: 1;
    }
    """


class TaskListWidget(Static):
    """Widget displaying the list of tasks."""

    def __init__(self, executor: TaskExecutor) -> None:
        """Initialize the task list widget."""
        super().__init__()
        self.executor = executor

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        yield Tree("Tasks")

    def update_tasks(self) -> None:
        """Update the task list display."""
        tree = self.query_one(Tree)
        tree.clear()
        root = tree.root
        root.expand()

        for task in self.executor.tasks:
            # Format task line with status color
            status_emoji = {
                "pending": "⏸",
                "running": "▶",
                "success": "✓",
                "failed": "✗",
                "rate_limit_retry": "⟳",
            }.get(task.status, "?")

            label = f"{status_emoji} [{task.id}] {task.prompt[:50]}"

            if task.status == "success" and task.json_output:
                tokens = task.json_output.get("tokens_used", 0)
                label += f" ({tokens} tokens)"
            elif task.duration_ms:
                label += f" ({task.duration_ms}ms)"

            node = root.add(label, data=task)

            # Add task details as child nodes
            details_text = f"📁 Directory: {task.directory}"
            node.add_leaf(details_text)
            
            if task.args:
                args_text = f"⚙️  Args: {' '.join(task.args)}"
                node.add_leaf(args_text)
            
            if task.exit_code is not None:
                exit_text = f"🔢 Exit code: {task.exit_code}"
                node.add_leaf(exit_text)
            
            if task.retry_count > 0:
                retry_text = f"🔁 Retries: {task.retry_count}/5"
                node.add_leaf(retry_text)

            # Apply status-based styling
            if task.status == "success":
                node.set_label(f"[green]{label}[/green]")
            elif task.status == "failed":
                node.set_label(f"[red]{label}[/red]")
            elif task.status in ("running", "rate_limit_retry"):
                node.set_label(f"[yellow]{label}[/yellow]")
            else:
                node.set_label(f"[dim]{label}[/dim]")


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

        if task.json_output is None:
            self.update(f"Task {task.id}: No output yet")
            return

        # Format compact JSON display
        output = task.json_output
        lines = [f"[bold]Task {task.id} Output:[/bold]"]

        if "result" in output:
            result = str(output["result"])[:200]
            lines.append(f"Result: {result}")

        if "code_blocks" in output and output["code_blocks"]:
            lines.append(f"Code blocks: {len(output['code_blocks'])}")
            for i, block in enumerate(output["code_blocks"][:3]):
                lang = block.get("language", "unknown")
                filename = block.get("filename", "")
                lines.append(f"  [{i+1}] {lang}: {filename}")

        if "files_changed" in output and output["files_changed"]:
            lines.append(f"Files changed: {', '.join(output['files_changed'][:3])}")

        if "tokens_used" in output:
            lines.append(f"Tokens: {output['tokens_used']}")

        if "session_usage_percent" in output:
            usage = output["session_usage_percent"]
            color = "red" if usage > 80 else "yellow" if usage > 50 else "green"
            lines.append(f"Session usage: [{color}]{usage}%[/{color}]")

        if task.exit_code is not None:
            lines.append(f"Exit code: {task.exit_code}")

        if task.duration_ms:
            lines.append(f"Duration: {task.duration_ms}ms ({task.duration_ms/1000:.1f}s)")

        lines.append("\n[dim]Press Enter for detailed view[/dim]")

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
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("p", "toggle_pause", "Pause/Resume"),
        ("s", "skip_task", "Skip"),
        ("d", "delete_task", "Delete"),
        ("enter", "show_detail", "Detail"),
        ("q", "quit", "Quit"),
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
            Button("Pause", id="pause_btn", variant="warning"),
            Button("Skip", id="skip_btn", variant="error"),
            Button("Delete", id="delete_btn", variant="error"),
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
            log_widget.add_log(f"Loaded {len(self.executor.tasks)} tasks")
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

    @on(Tree.NodeSelected)
    @on(Tree.NodeSelected)
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle task selection."""
        json_output = self.query_one("#json_output", JsonOutputWidget)
        if event.node.data:
            self.selected_task = event.node.data
            json_output.update_content(self.selected_task)
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

    def action_skip_task(self) -> None:
        """Skip current task."""
        if self.executor and self.executor.current_task:
            log_widget = self.query_one("#logs", LogWidget)
            log_widget.add_log(
                f"[yellow]Skipping task {self.executor.current_task.id}[/yellow]"
            )
            self.executor.skip_current()

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

    @on(Button.Pressed, "#pause_btn")
    def on_pause_pressed(self) -> None:
        """Handle pause button press."""
        self.action_toggle_pause()

    @on(Button.Pressed, "#skip_btn")
    def on_skip_pressed(self) -> None:
        """Handle skip button press."""
        self.action_skip_task()

    @on(Button.Pressed, "#delete_btn")
    async def on_delete_pressed(self) -> None:
        """Handle delete button press."""
        await self.action_delete_task()

    @on(Button.Pressed, "#quit_btn")
    def on_quit_pressed(self) -> None:
        """Handle quit button press."""
        self.exit()

    def action_quit(self) -> None:
        """Quit the application."""
        if self.executor:
            self.executor.should_stop = True
        self.exit()


async def run_tui(pool_file: Path) -> None:
    """Run the TUI application."""
    app = PoolTUI(pool_file)
    await app.run_async()
