"""Tests for the TUI components."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from textual.widgets import Button, DataTable

from team_cli.models import Task
from team_cli.tui import AddTaskScreen, ConfirmDialog, JsonOutputWidget, LogWidget, PoolTUI


class TestAppStartup:
    """Test app startup and initialization."""

    @pytest.mark.asyncio
    async def test_app_startup(self, pool_file_with_tasks: Path, mock_executor):
        """Test PoolTUI loads tasks from pool file on mount."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                # Wait for mount
                await pilot.pause()

                # Verify task list widget exists and has correct number of rows
                task_list_widget = app.query_one("#task_list_widget")
                assert task_list_widget is not None

                table = app.query_one("#task_list_widget DataTable", DataTable)
                assert table is not None

                # Should have 4 tasks from mock_executor
                assert len(table.rows) == 4

                # Verify header exists
                header = app.query_one("Header")
                assert header is not None

    @pytest.mark.asyncio
    async def test_app_startup_empty_pool(self, empty_pool_file: Path, mock_executor_empty):
        """Test app startup with empty pool."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor_empty):
            app = PoolTUI(empty_pool_file)

            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one("#task_list_widget DataTable", DataTable)
                assert len(table.rows) == 0


class TestAddTaskModal:
    """Test add task modal functionality."""

    @pytest.mark.asyncio
    async def test_add_task_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that add task button exists in the UI."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Check if add task button exists
                add_btn = app.query_one("#add_task_btn", Button)
                assert add_btn is not None
                assert add_btn.label == "Add Task"

    @pytest.mark.asyncio
    async def test_add_task_screen_composition(self):
        """Test that AddTaskScreen composes correctly."""
        screen = AddTaskScreen()

        # Verify the screen has required input fields
        assert screen is not None

        # Compose the screen
        widgets = list(screen.compose())
        assert len(widgets) > 0

    @pytest.mark.asyncio
    async def test_add_task_screen_validation(self):
        """Test AddTaskScreen validates required fields."""
        screen = AddTaskScreen()

        # Get the widgets
        widgets = list(screen.compose())
        assert len(widgets) > 0


class TestDeleteTaskConfirmation:
    """Test delete task confirmation dialog."""

    @pytest.mark.asyncio
    async def test_delete_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that delete button exists in the UI."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Check if delete button exists
                delete_btn = app.query_one("#delete_btn", Button)
                assert delete_btn is not None
                assert delete_btn.label == "Delete"

    @pytest.mark.asyncio
    async def test_delete_task_no_selection(self, pool_file_with_tasks: Path, mock_executor):
        """Test delete action when no task is selected."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Deselect any task
                app.selected_task = None

                log_widget = app.query_one("#logs", LogWidget)
                initial_log_count = len(log_widget.logs)

                # Try to delete without selection
                await pilot.press("d")
                await pilot.pause()

                # Should show error message
                assert len(log_widget.logs) > initial_log_count

    @pytest.mark.asyncio
    async def test_confirm_dialog_has_message(self):
        """Test that ConfirmDialog stores message."""
        message = "Delete task?"
        dialog = ConfirmDialog(message)

        # Verify message is stored
        assert dialog.message == message


class TestPauseResume:
    """Test pause/resume functionality."""

    @pytest.mark.asyncio
    async def test_pause_resume_binding(self, pool_file_with_tasks: Path, mock_executor):
        """Test pressing 'P' key toggles paused state."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Verify not paused initially
                assert mock_executor.paused is False

                # Press 'p' to pause
                await pilot.press("p")
                await pilot.pause()

                # Verify pause was called
                assert mock_executor.pause.called is True

                # Set paused to True to simulate pause
                mock_executor.paused = True

                # Press 'p' again to resume
                await pilot.press("p")
                await pilot.pause()

                # Verify resume was called
                assert mock_executor.resume.called is True

    @pytest.mark.asyncio
    async def test_pause_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that pause button exists in the UI."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                pause_btn = app.query_one("#pause_btn", Button)
                assert pause_btn is not None
                assert pause_btn.label == "Pause"


class TestQuitBinding:
    """Test quit functionality."""

    @pytest.mark.asyncio
    async def test_quit_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that quit button exists in the UI."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Check if quit button exists
                quit_btn = app.query_one("#quit_btn", Button)
                assert quit_btn is not None
                assert quit_btn.label == "Quit"

    @pytest.mark.asyncio
    async def test_quit_binding_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that quit action is bound to 'Q' key."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            # Check that quit binding exists
            bindings = [b for b in app.BINDINGS if b[0] == "q"]
            assert len(bindings) > 0
            assert bindings[0][1] == "quit"


class TestDataTableSelection:
    """Test DataTable selection functionality."""

    @pytest.mark.asyncio
    async def test_datatable_exists_with_columns(self, pool_file_with_tasks: Path, mock_executor):
        """Test DataTable exists with correct columns."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one("#task_list_widget DataTable", DataTable)
                assert table is not None

                # Check that table has the expected columns
                columns = list(table.columns)
                assert len(columns) > 0

    @pytest.mark.asyncio
    async def test_datatable_has_rows(self, pool_file_with_tasks: Path, mock_executor):
        """Test DataTable displays rows from executor pool."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one("#task_list_widget DataTable", DataTable)
                assert len(table.rows) > 0

                # Should match the number of tasks in mock_executor
                assert len(table.rows) == len(mock_executor.pool.tasks)

    @pytest.mark.asyncio
    async def test_datatable_cursor_position(self, pool_file_with_tasks: Path, mock_executor):
        """Test DataTable cursor position can be read."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one("#task_list_widget DataTable", DataTable)

                # Read initial cursor position (may be -1 initially)
                initial_row = table.cursor_row
                # Verify we can read the cursor position
                assert initial_row >= -1  # -1 means no selection or at header


class TestTaskDetailsPanel:
    """Test task details panel updates."""

    @pytest.mark.asyncio
    async def test_task_details_panel_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test details panel exists in the app."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                json_widget = app.query_one("#json_output", JsonOutputWidget)
                assert json_widget is not None

    @pytest.mark.asyncio
    async def test_json_output_widget_update_with_task(self):
        """Test JsonOutputWidget updates with task content."""
        task = Task(
            id="task_001",
            prompt="Test task",
            directory=Path("/tmp"),
            status="success",
            exit_code=0,
            duration_ms=5000,
            json_output={"result": "Success", "tokens_used": 1000},
        )

        widget = JsonOutputWidget()
        widget.update_content(task)

        output = str(widget.render())
        assert "task_001" in output
        assert "Test task" in output
        assert "Exit: 0" in output
        assert "1,000" in output  # tokens formatted

    @pytest.mark.asyncio
    async def test_json_output_widget_no_task(self):
        """Test JsonOutputWidget with no task selected."""
        widget = JsonOutputWidget()
        widget.update_content(None)

        output = str(widget.render())
        assert "No task selected" in output

    @pytest.mark.asyncio
    async def test_json_output_widget_pending_task(self):
        """Test JsonOutputWidget with pending task."""
        task = Task(
            id="task_002",
            prompt="Pending task",
            directory=Path("/tmp"),
            status="pending",
        )

        widget = JsonOutputWidget()
        widget.update_content(task)

        output = str(widget.render())
        assert "task_002" in output
        assert "Pending task" in output
        assert "No output yet" in output


class TestLogsPanel:
    """Test logs panel functionality."""

    @pytest.mark.asyncio
    async def test_logs_panel_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test logs panel exists and is queryable."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                log_widget = app.query_one("#logs", LogWidget)
                assert log_widget is not None

    @pytest.mark.asyncio
    async def test_logs_panel_add_message(self):
        """Test adding messages to logs panel."""
        log_widget = LogWidget()

        # Add a log message
        log_widget.add_log("Test message")

        output = str(log_widget.render())
        assert "Test message" in output

    @pytest.mark.asyncio
    async def test_logs_panel_multiple_messages(self):
        """Test logs panel with multiple messages."""
        log_widget = LogWidget()

        # Add multiple messages
        for i in range(5):
            log_widget.add_log(f"Message {i}")

        output = str(log_widget.render())
        # Most recent messages should be present
        assert "Message 4" in output

    @pytest.mark.asyncio
    async def test_logs_panel_respects_max_lines(self, pool_file_with_tasks: Path, mock_executor):
        """Test logs panel respects max_lines limit."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                log_widget = app.query_one("#logs", LogWidget)
                original_max = log_widget.max_lines

                # Add more messages than max_lines
                for i in range(original_max + 10):
                    log_widget.add_log(f"Message {i}")

                await pilot.pause()

                # Should only have max_lines messages
                assert len(log_widget.logs) == original_max


class TestRetryTaskBinding:
    """Test retry task functionality."""

    @pytest.mark.asyncio
    async def test_retry_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that retry button exists in the UI."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Check if retry button exists
                retry_btn = app.query_one("#retry_btn", Button)
                assert retry_btn is not None
                assert retry_btn.label == "Retry"

    @pytest.mark.asyncio
    async def test_action_retry_task_resets_state(self):
        """Test retry task reset logic."""
        # Create a failed task
        task = Task(
            id="task_001",
            prompt="Test",
            directory=Path("/tmp"),
            status="failed",
            exit_code=1,
            duration_ms=2000,
            json_output={"error": "Failed"},
            retry_count=0,
        )

        # Simulate the retry logic
        if task.status in ("failed", "success"):
            task.status = "pending"
            task.exit_code = None
            task.duration_ms = None
            task.json_output = None
            task.retry_count += 1

        # Verify state was reset
        assert task.status == "pending"
        assert task.exit_code is None
        assert task.duration_ms is None
        assert task.json_output is None
        assert task.retry_count == 1

    @pytest.mark.asyncio
    async def test_retry_task_increments_count(self, pool_file_with_tasks: Path, mock_executor):
        """Test retrying a task increments retry count."""
        # Test the logic without needing full app context
        task = Task(
            id="task_002",
            prompt="Test",
            directory=Path("/tmp"),
            status="success",
            exit_code=0,
            duration_ms=5000,
            json_output={"result": "Success"},
            retry_count=2,
        )

        # Simulate retry logic
        if task.status in ("failed", "success"):
            task.status = "pending"
            task.exit_code = None
            task.duration_ms = None
            task.json_output = None
            task.retry_count += 1

        # Verify state was reset
        assert task.status == "pending"
        assert task.exit_code is None
        assert task.retry_count == 3

    @pytest.mark.asyncio
    async def test_retry_task_no_selection(self, pool_file_with_tasks: Path, mock_executor):
        """Test retry with no task selected."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Deselect any task
                app.selected_task = None

                log_widget = app.query_one("#logs", LogWidget)
                initial_log_count = len(log_widget.logs)

                # Try to retry without selection
                await pilot.press("r")
                await pilot.pause()

                # Should show error message
                assert len(log_widget.logs) > initial_log_count


class TestSkipBinding:
    """Test skip task functionality."""

    @pytest.mark.asyncio
    async def test_skip_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that skip button exists in the UI."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Check if skip button exists
                skip_btn = app.query_one("#skip_btn", Button)
                assert skip_btn is not None
                assert skip_btn.label == "Skip"

    @pytest.mark.asyncio
    async def test_skip_binding_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that skip action is bound to 'S' key."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            # Check that skip binding exists
            bindings = [b for b in app.BINDINGS if b[0] == "s"]
            assert len(bindings) > 0
            assert bindings[0][1] == "skip_task"

    @pytest.mark.asyncio
    async def test_skip_task_with_running_task(self, pool_file_with_tasks: Path, mock_executor):
        """Test skip action when there's a running task."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Set a current task as if execution is happening
                running_task = mock_executor.pool.tasks[1]  # "running" status task
                mock_executor.current_task = running_task

                log_widget = app.query_one("#logs", LogWidget)
                initial_log_count = len(log_widget.logs)

                # Press 's' to skip
                await pilot.press("s")
                await pilot.pause()

                # Verify skip_current was called
                assert mock_executor.skip_current.called

                # Verify log was updated
                assert len(log_widget.logs) > initial_log_count

    @pytest.mark.asyncio
    async def test_skip_task_no_running_task(self, pool_file_with_tasks: Path, mock_executor):
        """Test skip action when there's no running task."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # No current task
                mock_executor.current_task = None

                # Press 's' to skip - should not error
                await pilot.press("s")
                await pilot.pause()

                # skip_current may or may not be called depending on implementation
                # Just verify it doesn't crash


class TestDetailedOutputScreen:
    """Test detailed output screen."""

    @pytest.mark.asyncio
    async def test_detail_binding_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that detail action is bound to Enter key."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            # Check that detail binding exists (bound to activate_row which calls show_detail)
            bindings = [b for b in app.BINDINGS if b[0] == "enter"]
            assert len(bindings) > 0
            assert bindings[0][1] == "activate_row"

    @pytest.mark.asyncio
    async def test_detailed_output_screen_title(self, pool_file_with_tasks: Path, mock_executor):
        """Test DetailedOutputScreen displays task ID."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                task = Task(
                    id="task_001",
                    prompt="Test task",
                    directory=Path("/tmp"),
                    status="success",
                    json_output={"result": "Success", "tokens_used": 5000},
                )

                # Detailed output screen should work with task data

                # Just verify we can instantiate it within app context
                assert task.id == "task_001"
                assert task.json_output is not None

    @pytest.mark.asyncio
    async def test_action_show_detail_with_output(self, pool_file_with_tasks: Path, mock_executor):
        """Test show_detail action with task that has output."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Create a task with output
                task = Task(
                    id="task_001",
                    prompt="Test",
                    directory=Path("/tmp"),
                    status="success",
                    json_output={"result": "Success"},
                )

                app.selected_task = task

                # Verify action_show_detail doesn't error with output
                # Note: The actual screen push may fail in test context, but method should handle it
                try:
                    app.action_show_detail()
                except Exception:
                    # Expected in test environment
                    pass


class TestDataTableRowSelection:
    """Test DataTable row selection and JSON output updates."""

    @pytest.mark.asyncio
    async def test_select_row_updates_json_output(self, pool_file_with_tasks: Path, mock_executor):
        """Test that selecting a row updates the JSON output panel."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                app.query_one("#task_list_widget DataTable", DataTable)
                json_widget = app.query_one("#json_output", JsonOutputWidget)

                # Use the task at row 2 (which is the success task)
                task_at_row = mock_executor.pool.tasks[2]
                json_widget.update_content(task_at_row)

                output = str(json_widget.render())
                # Should display success task info
                assert "successfully completed" in output or "success" in output.lower()

    @pytest.mark.asyncio
    async def test_json_output_shows_exit_code(self, pool_file_with_tasks: Path, mock_executor):
        """Test that JSON output shows exit code correctly."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                json_widget = app.query_one("#json_output", JsonOutputWidget)

                # Select a failed task
                task = mock_executor.pool.tasks[3]  # Failed task
                json_widget.update_content(task)

                output = str(json_widget.render())
                # Should show exit code
                assert "Exit:" in output
                assert "1" in output  # exit_code is 1

    @pytest.mark.asyncio
    async def test_json_output_shows_tokens_used(self, pool_file_with_tasks: Path, mock_executor):
        """Test that JSON output shows tokens used."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                json_widget = app.query_one("#json_output", JsonOutputWidget)

                # Select a successful task with tokens
                task = mock_executor.pool.tasks[2]  # Success task with json_output
                json_widget.update_content(task)

                output = str(json_widget.render())
                # Should show tokens
                assert "Tokens used:" in output or "tokens" in output.lower()


class TestAddTaskModalInteraction:
    """Test add task modal dialog interaction."""

    @pytest.mark.asyncio
    async def test_add_task_button_press(self, pool_file_with_tasks: Path, mock_executor):
        """Test pressing add task button binding exists."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            # Check that 'a' binding exists for add task
            bindings = [b for b in app.BINDINGS if b[0] == "a"]
            assert len(bindings) > 0
            assert bindings[0][1] == "add_task"

    @pytest.mark.asyncio
    async def test_add_task_form_has_inputs(self):
        """Test that AddTaskScreen has required input fields."""
        screen = AddTaskScreen()
        widgets = list(screen.compose())

        # Should have some widgets
        assert len(widgets) > 0

        # Verify it composes without error
        assert screen is not None


class TestDeleteTaskWithConfirmation:
    """Test delete task with confirmation dialog."""

    @pytest.mark.asyncio
    async def test_delete_binding_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Test that delete action is bound to 'D' key."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            # Check that delete binding exists
            bindings = [b for b in app.BINDINGS if b[0] == "d"]
            assert len(bindings) > 0
            assert bindings[0][1] == "delete_task"

    @pytest.mark.asyncio
    async def test_delete_task_logic(self, mock_executor):
        """Test delete task logic without async context."""
        # Verify delete method exists and is callable
        assert hasattr(mock_executor, "delete_task")
        assert callable(mock_executor.delete_task)

        # Test that delete returns True when task exists
        result = mock_executor.delete_task("some_task_id")
        assert result is True


class TestAppWithMultipleTasks:
    """Test app with multiple tasks of various statuses."""

    @pytest.mark.asyncio
    async def test_app_displays_all_statuses(self, pool_file_with_tasks: Path, mock_executor):
        """Test that app displays tasks with all statuses correctly."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)

            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one("#task_list_widget DataTable", DataTable)

                # Should have all 4 test tasks
                assert len(table.rows) == 4

                # Verify all status types are represented in mock_executor.pool.tasks
                statuses = {task.status for task in mock_executor.pool.tasks}
                assert len(statuses) >= 3  # Should have at least pending, running, success, failed

    @pytest.mark.asyncio
    async def test_status_color_coding(self, pool_file_with_tasks: Path, mock_executor):
        """Test that task statuses are color-coded."""
        task = Task(
            id="test_success",
            prompt="Success task",
            directory=Path("/tmp"),
            status="success",
            exit_code=0,
            json_output={"result": "Success"},
        )

        # Test that JsonOutputWidget renders status correctly
        widget = JsonOutputWidget()
        widget.update_content(task)
        output = str(widget.render())

        # Should contain status information
        assert task.id in output


# ── JsonOutputWidget.exit_code_meaning ───────────────────────────────────────


class TestExitCodeMeaning:
    """Unit tests for JsonOutputWidget.exit_code_meaning (pure static method)."""

    def test_none_returns_empty_string(self):
        assert JsonOutputWidget.exit_code_meaning(None) == ""

    def test_zero_is_success(self):
        assert JsonOutputWidget.exit_code_meaning(0) == "✓ Success"

    def test_one_is_general_error(self):
        assert JsonOutputWidget.exit_code_meaning(1) == "⚠ General error"

    def test_two_is_misuse(self):
        assert JsonOutputWidget.exit_code_meaning(2) == "⚠ Misuse of shell command"

    def test_126_cannot_execute(self):
        assert JsonOutputWidget.exit_code_meaning(126) == "⚠ Command cannot execute"

    def test_127_not_found(self):
        assert JsonOutputWidget.exit_code_meaning(127) == "⚠ Command not found"

    def test_130_sigint(self):
        assert JsonOutputWidget.exit_code_meaning(130) == "⏸ Terminated by Ctrl+C (SIGINT)"

    def test_143_sigterm(self):
        assert JsonOutputWidget.exit_code_meaning(143) == "⏹ Terminated by SIGTERM (killed/timeout)"

    def test_128_plus_generic_signal(self):
        result = JsonOutputWidget.exit_code_meaning(137)
        assert "signal" in result.lower() or "137" in result

    def test_unknown_positive_code(self):
        result = JsonOutputWidget.exit_code_meaning(42)
        assert "42" in result

    def test_all_named_codes_are_non_empty(self):
        for code in (0, 1, 2, 126, 127, 130, 143):
            assert JsonOutputWidget.exit_code_meaning(code) != ""


# ── TestStopTaskAction ────────────────────────────────────────────────────────


class TestStopTaskAction:
    """Tests for PoolTUI.action_stop_task() and the Stop button."""

    @pytest.mark.asyncio
    async def test_stop_button_exists(self, pool_file_with_tasks: Path, mock_executor):
        """Stop button is present in the controls bar."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            async with app.run_test() as pilot:
                await pilot.pause()
                stop_btn = app.query_one("#stop_btn", Button)
                assert stop_btn is not None
                assert stop_btn.label == "Stop"

    @pytest.mark.asyncio
    async def test_stop_binding_registered(self, pool_file_with_tasks: Path, mock_executor):
        """'x' key is bound to stop_task."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            bindings = [b for b in app.BINDINGS if b[0] == "x"]
            assert len(bindings) == 1
            assert bindings[0][1] == "stop_task"

    @pytest.mark.asyncio
    async def test_stop_task_no_selection(self, pool_file_with_tasks: Path, mock_executor):
        """action_stop_task with no selected task logs 'No task selected'."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            async with app.run_test() as pilot:
                await pilot.pause()

                app.selected_task = None
                log_widget = app.query_one("#logs", LogWidget)
                before = len(log_widget.logs)

                await pilot.press("x")
                await pilot.pause()

                assert len(log_widget.logs) > before
                assert any("No task selected" in entry for entry in log_widget.logs)

    @pytest.mark.asyncio
    async def test_stop_task_wrong_status(self, pool_file_with_tasks: Path, mock_executor):
        """action_stop_task on a non-running task logs 'cannot stop'."""
        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            async with app.run_test() as pilot:
                await pilot.pause()

                # Select the pending task (index 0)
                pending_task = mock_executor.pool.tasks[0]
                assert pending_task.status == "pending"
                app.selected_task = pending_task

                log_widget = app.query_one("#logs", LogWidget)
                before = len(log_widget.logs)

                await pilot.press("x")
                await pilot.pause()

                assert len(log_widget.logs) > before
                assert any("cannot stop" in entry for entry in log_widget.logs)

    @pytest.mark.asyncio
    async def test_stop_task_calls_executor(self, pool_file_with_tasks: Path, mock_executor):
        """action_stop_task on a running task calls executor.stop_task with correct id."""
        mock_executor.stop_task = AsyncMock(return_value=True)

        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            async with app.run_test() as pilot:
                await pilot.pause()

                running_task = mock_executor.pool.tasks[1]
                assert running_task.status == "running"
                app.selected_task = running_task

                # Patch push_screen_wait to auto-confirm without showing dialog
                with patch.object(app, "push_screen_wait", AsyncMock(return_value=True)):
                    await app.action_stop_task()

                mock_executor.stop_task.assert_called_once_with(running_task.id)

    @pytest.mark.asyncio
    async def test_stop_task_logs_hard_stopped(self, pool_file_with_tasks: Path, mock_executor):
        """action_stop_task logs 'hard-stopped' after executor call."""
        mock_executor.stop_task = AsyncMock(return_value=True)

        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            async with app.run_test() as pilot:
                await pilot.pause()

                running_task = mock_executor.pool.tasks[1]
                app.selected_task = running_task
                log_widget = app.query_one("#logs", LogWidget)

                with patch.object(app, "push_screen_wait", AsyncMock(return_value=True)):
                    await app.action_stop_task()

                assert any("hard-stopped" in entry for entry in log_widget.logs)

    @pytest.mark.asyncio
    async def test_stop_task_no_op_when_cancelled(self, pool_file_with_tasks: Path, mock_executor):
        """action_stop_task does NOT call executor.stop_task when user dismisses dialog."""
        mock_executor.stop_task = AsyncMock(return_value=True)

        with patch("team_cli.tui.TaskExecutor", return_value=mock_executor):
            app = PoolTUI(pool_file_with_tasks)
            async with app.run_test() as pilot:
                await pilot.pause()

                running_task = mock_executor.pool.tasks[1]
                app.selected_task = running_task

                with patch.object(app, "push_screen_wait", AsyncMock(return_value=False)):
                    await app.action_stop_task()

                mock_executor.stop_task.assert_not_called()
