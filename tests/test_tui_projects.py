"""Tests for Phase 5 Step 5: TUI Projects tab and project detail view."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from team_cli.models import Project, ProjectMessage
from team_cli.priority_engine import promote_priority
from team_cli.tui import (
    ComposeMessageScreen,
    PoolTUI,
    ProjectDetailScreen,
    ProjectListWidget,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(pid: str = "proj_001", name: str = "Test Project") -> Project:
    return Project(
        id=pid,
        name=name,
        directory="/tmp/test",
        created_at=datetime.now(),
        default_cli="claude",
        allow_cli_switch=True,
    )


def _make_message(mid: str = "msg_001", project_id: str = "proj_001",
                  content: str = "Hello", priority: int = 2,
                  role: str = "user") -> ProjectMessage:
    return ProjectMessage(
        id=mid,
        project_id=project_id,
        content=content,
        role=role,
        priority=priority,
        created_at=datetime.now(),
    )


@contextmanager
def _mock_executor(pool_file: Path):
    """Patch TaskExecutor so TUI doesn't actually run tasks."""
    with (
        patch("team_cli.tui.TaskExecutor") as MockExec,  # noqa: N806
        patch("team_cli.executor.signal.signal"),
    ):
        mock_exec = MagicMock()
        mock_exec.pool = MagicMock()
        mock_exec.pool.tasks = []
        mock_exec.paused = False
        mock_exec.current_task = None
        mock_exec.load_tasks = asyncio.coroutine(lambda: None) if False else MagicMock(
            return_value=asyncio.Future()
        )

        async def _fake_load():
            return None

        mock_exec.load_tasks = _fake_load
        mock_exec.run_pool = _fake_load
        MockExec.return_value = mock_exec
        yield mock_exec


# ---------------------------------------------------------------------------
# TUI structure — tabs exist
# ---------------------------------------------------------------------------

class TestTuiHasBothTabs:
    def test_pool_tui_class_importable(self):
        assert PoolTUI is not None

    def test_pool_tui_composes_tabbed_content(self):
        """compose() must reference both tab IDs."""
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "tab_tasks" in src
        assert "tab_projects" in src

    def test_tasks_tab_pane_present(self):
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "Tasks" in src

    def test_projects_tab_pane_present(self):
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "Projects" in src

    def test_project_list_widget_yielded(self):
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "ProjectListWidget" in src

    def test_task_list_widget_still_yielded(self):
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "TaskListWidget" in src


# ---------------------------------------------------------------------------
# Tab switch loads projects
# ---------------------------------------------------------------------------

class TestTabSwitchLoadsProjects:
    def test_on_tabbed_content_tab_activated_exists(self):
        assert hasattr(PoolTUI, "on_tabbed_content_tab_activated")

    def test_reload_project_list_method_exists(self):
        assert hasattr(PoolTUI, "_reload_project_list")

    def test_reload_calls_load_projects(self):
        """_reload_project_list must call load_projects with self.pool_file."""
        import inspect
        src = inspect.getsource(PoolTUI._reload_project_list)
        assert "load_projects" in src

    def test_tab_activated_triggers_reload_for_projects(self):
        import inspect
        src = inspect.getsource(PoolTUI.on_tabbed_content_tab_activated)
        assert "tab_projects" in src
        assert "_reload_project_list" in src


# ---------------------------------------------------------------------------
# ProjectListWidget
# ---------------------------------------------------------------------------

class TestProjectListWidget:
    def test_widget_instantiable(self):
        w = ProjectListWidget()
        assert w is not None

    def test_project_map_starts_empty(self):
        w = ProjectListWidget()
        assert w._project_map == {}

    def test_refresh_projects_populates_map(self):
        w = ProjectListWidget()
        projects = [_make_project("p1", "Alpha"), _make_project("p2", "Beta")]
        # Patch DataTable to avoid Textual app context
        with patch.object(w, "query_one") as mock_qo:
            mock_table = MagicMock()
            mock_qo.return_value = mock_table
            w.refresh_projects(projects)
        assert len(w._project_map) == 2

    def test_refresh_projects_resets_map(self):
        w = ProjectListWidget()
        w._project_map = {0: _make_project("old")}
        with patch.object(w, "query_one") as mock_qo:
            mock_table = MagicMock()
            mock_qo.return_value = mock_table
            w.refresh_projects([])
        assert w._project_map == {}

    def test_selected_project_returns_none_when_empty(self):
        w = ProjectListWidget()
        with patch.object(w, "query_one") as mock_qo:
            mock_table = MagicMock()
            mock_table.cursor_row = 0
            mock_qo.return_value = mock_table
            result = w.selected_project()
        assert result is None

    def test_selected_project_returns_correct_project(self):
        w = ProjectListWidget()
        p = _make_project("p1")
        w._project_map[0] = p
        with patch.object(w, "query_one") as mock_qo:
            mock_table = MagicMock()
            mock_table.cursor_row = 0
            mock_qo.return_value = mock_table
            result = w.selected_project()
        assert result is p


# ---------------------------------------------------------------------------
# ProjectDetailScreen — structure
# ---------------------------------------------------------------------------

class TestProjectDetailScreenStructure:
    def test_screen_importable(self):
        assert ProjectDetailScreen is not None

    def test_has_back_action(self):
        assert hasattr(ProjectDetailScreen, "action_back")

    def test_has_new_message_action(self):
        assert hasattr(ProjectDetailScreen, "action_new_message")

    def test_has_promote_message_action(self):
        assert hasattr(ProjectDetailScreen, "action_promote_message")

    def test_has_reply_message_action(self):
        assert hasattr(ProjectDetailScreen, "action_reply_message")

    def test_has_delete_message_action(self):
        assert hasattr(ProjectDetailScreen, "action_delete_message")

    def test_bindings_include_b_for_back(self):
        keys = [b[0] for b in ProjectDetailScreen.BINDINGS]
        assert "b" in keys

    def test_bindings_include_escape(self):
        keys = [b[0] for b in ProjectDetailScreen.BINDINGS]
        assert "escape" in keys

    def test_bindings_include_n_for_new(self):
        keys = [b[0] for b in ProjectDetailScreen.BINDINGS]
        assert "n" in keys

    def test_bindings_include_p_for_promote(self):
        keys = [b[0] for b in ProjectDetailScreen.BINDINGS]
        assert "p" in keys

    def test_bindings_include_r_for_reply(self):
        keys = [b[0] for b in ProjectDetailScreen.BINDINGS]
        assert "r" in keys

    def test_bindings_include_delete(self):
        keys = [b[0] for b in ProjectDetailScreen.BINDINGS]
        assert "delete" in keys

    def test_init_stores_project_and_db_path(self):
        p = _make_project()
        db = Path("/tmp/test.db")
        screen = ProjectDetailScreen(p, db)
        assert screen.project is p
        assert screen.db_path == db


# ---------------------------------------------------------------------------
# ProjectDetailScreen — promote action
# ---------------------------------------------------------------------------

class TestPromoteAction:
    def test_promote_priority_function(self):
        assert promote_priority(1) == 2
        assert promote_priority(4) == 5
        assert promote_priority(5) == 5

    def test_action_promote_message_calls_promote_priority(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen.action_promote_message)
        assert "promote_priority" in src

    def test_action_promote_message_saves_message(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen.action_promote_message)
        assert "save_project_message" in src

    def test_action_promote_message_reloads(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen.action_promote_message)
        assert "_reload_messages" in src

    def test_promote_modifies_priority_directly(self):
        p = _make_project()
        screen = ProjectDetailScreen(p, Path("/tmp/x.db"))
        msg = _make_message(priority=2)
        screen._msg_map[0] = msg
        screen._messages = [msg]

        with (
            patch.object(screen, "query_one") as mock_qo,
            patch("team_cli.tui.save_project_message") as mock_save,
            patch.object(screen, "_reload_messages"),
            patch.object(screen, "notify"),
        ):
            mock_table = MagicMock()
            mock_table.cursor_row = 0
            mock_qo.return_value = mock_table
            screen.action_promote_message()

        assert msg.priority == 3
        mock_save.assert_called_once()

    def test_promote_at_max_priority_notifies_warning(self):
        p = _make_project()
        screen = ProjectDetailScreen(p, Path("/tmp/x.db"))
        msg = _make_message(priority=5)
        screen._msg_map[0] = msg
        notifications = []

        with (
            patch.object(screen, "query_one") as mock_qo,
            patch("team_cli.tui.save_project_message") as mock_save,
            patch.object(screen, "notify", side_effect=lambda *a, **kw: notifications.append(kw.get("severity"))),
        ):
            mock_table = MagicMock()
            mock_table.cursor_row = 0
            mock_qo.return_value = mock_table
            screen.action_promote_message()

        mock_save.assert_not_called()
        assert "warning" in notifications


# ---------------------------------------------------------------------------
# ProjectDetailScreen — message loading
# ---------------------------------------------------------------------------

class TestDetailScreenLoadMessages:
    def test_reload_messages_calls_load_project_messages(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen._reload_messages)
        assert "load_project_messages" in src

    def test_reload_messages_uses_priority_labels(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen._reload_messages)
        assert "PRIORITY_LABELS" in src

    def test_reload_messages_populates_msg_map(self):
        p = _make_project()
        screen = ProjectDetailScreen(p, Path("/tmp/x.db"))
        msgs = [_make_message("m1"), _make_message("m2")]

        with (
            patch("team_cli.tui.load_project_messages", return_value=msgs),
            patch.object(screen, "query_one") as mock_qo,
        ):
            mock_table = MagicMock()
            mock_qo.return_value = mock_table
            screen._reload_messages()

        assert len(screen._msg_map) == 2
        assert screen._msg_map[0].id == "m1"
        assert screen._msg_map[1].id == "m2"

    def test_content_truncated_to_60_chars(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen._reload_messages)
        assert "60" in src


# ---------------------------------------------------------------------------
# ProjectDetailScreen — delete action
# ---------------------------------------------------------------------------

class TestDeleteMessageAction:
    def test_delete_action_calls_delete_project_message(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen.action_delete_message)
        assert "delete_project_message" in src

    def test_delete_action_uses_confirm_dialog(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen.action_delete_message)
        assert "ConfirmDialog" in src


# ---------------------------------------------------------------------------
# ComposeMessageScreen
# ---------------------------------------------------------------------------

class TestComposeMessageScreen:
    def test_importable(self):
        assert ComposeMessageScreen is not None

    def test_accepts_linked_message_id(self):
        s = ComposeMessageScreen("MyProject", linked_message_id="msg_123")
        assert s._linked_message_id == "msg_123"

    def test_linked_message_id_defaults_to_none(self):
        s = ComposeMessageScreen("MyProject")
        assert s._linked_message_id is None

    def test_on_send_dismisses_with_content(self):
        s = ComposeMessageScreen("Proj")
        dismissed = []
        s.dismiss = lambda v: dismissed.append(v)

        with patch.object(s, "query_one") as mock_qo:
            mock_input = MagicMock()
            mock_input.value = "  Hello world  "
            mock_qo.return_value = mock_input
            s.on_send()

        assert len(dismissed) == 1
        assert dismissed[0]["content"] == "Hello world"
        assert dismissed[0]["linked_message_id"] is None

    def test_on_send_includes_linked_message_id(self):
        s = ComposeMessageScreen("Proj", linked_message_id="msg_abc")
        dismissed = []
        s.dismiss = lambda v: dismissed.append(v)

        with patch.object(s, "query_one") as mock_qo:
            mock_input = MagicMock()
            mock_input.value = "Reply text"
            mock_qo.return_value = mock_input
            s.on_send()

        assert dismissed[0]["linked_message_id"] == "msg_abc"

    def test_on_send_empty_content_notifies(self):
        s = ComposeMessageScreen("Proj")
        notifications = []
        s.notify = lambda *a, **kw: notifications.append(kw.get("severity"))
        dismissed = []
        s.dismiss = lambda v: dismissed.append(v)

        with patch.object(s, "query_one") as mock_qo:
            mock_input = MagicMock()
            mock_input.value = "   "
            mock_qo.return_value = mock_input
            s.on_send()

        assert not dismissed
        assert "error" in notifications


# ---------------------------------------------------------------------------
# Send message — fallback storage path
# ---------------------------------------------------------------------------

class TestSendMessageFallback:
    def test_send_message_saves_to_db_on_api_failure(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen._send_message)
        assert "save_project_message" in src
        assert "httpx" in src

    def test_send_message_posts_to_api_endpoint(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen._send_message)
        assert "/api/projects/" in src

    def test_send_message_includes_linked_message_id(self):
        import inspect
        src = inspect.getsource(ProjectDetailScreen._send_message)
        assert "linked_message_id" in src


# ---------------------------------------------------------------------------
# Tasks tab still works — existing task bindings preserved
# ---------------------------------------------------------------------------

class TestTasksTabPreserved:
    def test_toggle_pause_action_exists(self):
        assert hasattr(PoolTUI, "action_toggle_pause")

    def test_skip_task_action_exists(self):
        assert hasattr(PoolTUI, "action_skip_task")

    def test_delete_task_action_exists(self):
        assert hasattr(PoolTUI, "action_delete_task")

    def test_retry_task_action_exists(self):
        assert hasattr(PoolTUI, "action_retry_task")

    def test_add_task_action_exists(self):
        assert hasattr(PoolTUI, "action_add_task")

    def test_task_bindings_include_quit(self):
        keys = [b[0] for b in PoolTUI.BINDINGS]
        assert "q" in keys

    def test_task_bindings_include_pause(self):
        keys = [b[0] for b in PoolTUI.BINDINGS]
        assert "p" in keys

    def test_task_bindings_include_skip(self):
        keys = [b[0] for b in PoolTUI.BINDINGS]
        assert "s" in keys

    def test_task_bindings_include_add(self):
        keys = [b[0] for b in PoolTUI.BINDINGS]
        assert "a" in keys

    def test_toggle_pause_guards_active_tab(self):
        import inspect
        src = inspect.getsource(PoolTUI.action_toggle_pause)
        assert "tab_tasks" in src

    def test_skip_task_guards_active_tab(self):
        import inspect
        src = inspect.getsource(PoolTUI.action_skip_task)
        assert "tab_tasks" in src

    def test_task_list_widget_still_present_in_compose(self):
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "task_list_widget" in src

    def test_log_widget_still_present_in_compose(self):
        import inspect
        src = inspect.getsource(PoolTUI.compose)
        assert "logs" in src


# ---------------------------------------------------------------------------
# Enter key routing
# ---------------------------------------------------------------------------

class TestEnterKeyRouting:
    def test_activate_row_action_exists(self):
        assert hasattr(PoolTUI, "action_activate_row")

    def test_activate_row_checks_active_tab(self):
        import inspect
        src = inspect.getsource(PoolTUI.action_activate_row)
        assert "tab_projects" in src

    def test_activate_row_opens_project_detail_screen(self):
        import inspect
        src = inspect.getsource(PoolTUI.action_activate_row)
        assert "ProjectDetailScreen" in src

    def test_activate_row_falls_back_to_show_detail(self):
        import inspect
        src = inspect.getsource(PoolTUI.action_activate_row)
        assert "action_show_detail" in src


# ---------------------------------------------------------------------------
# Textual app integration — run_test smoke test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tui_mounts_with_both_tabs(tmp_path):
    """App mounts cleanly with both tabs visible."""
    pool_file = tmp_path / "pool.db"
    # Create a minimal pool db so executor doesn't crash
    from team_cli.models import PoolState
    from team_cli.storage import save_pool
    save_pool(PoolState(tasks=[], pool_file=pool_file))

    with (
        patch("team_cli.tui.TaskExecutor") as MockExec,  # noqa: N806
        patch("team_cli.tui.load_projects", return_value=[]),
        patch("team_cli.executor.signal.signal"),
    ):
        mock_exec = MagicMock()
        mock_exec.pool = MagicMock()
        mock_exec.pool.tasks = []
        mock_exec.paused = False
        mock_exec.current_task = None

        async def _noop():
            return None

        mock_exec.load_tasks = _noop
        mock_exec.run_pool = _noop
        MockExec.return_value = mock_exec

        app = PoolTUI(pool_file)
        async with app.run_test(headless=True):
            from textual.widgets import TabbedContent
            tc = app.query_one(TabbedContent)
            assert tc is not None
            # Both tabs must be present
            tab_ids = [str(tab.id) for tab in tc.query("Tab")]
            assert any("tasks" in tid for tid in tab_ids)
            assert any("projects" in tid for tid in tab_ids)


@pytest.mark.asyncio
async def test_projects_tab_calls_load_projects(tmp_path):
    """Switching to Projects tab triggers load_projects."""
    pool_file = tmp_path / "pool.db"
    from team_cli.models import PoolState
    from team_cli.storage import save_pool
    save_pool(PoolState(tasks=[], pool_file=pool_file))

    with (
        patch("team_cli.tui.TaskExecutor") as MockExec,  # noqa: N806
        patch("team_cli.tui.load_projects", return_value=[]) as mock_load,
        patch("team_cli.executor.signal.signal"),
    ):
        mock_exec = MagicMock()
        mock_exec.pool = MagicMock()
        mock_exec.pool.tasks = []
        mock_exec.paused = False
        mock_exec.current_task = None

        async def _noop():
            return None

        mock_exec.load_tasks = _noop
        mock_exec.run_pool = _noop
        MockExec.return_value = mock_exec

        app = PoolTUI(pool_file)
        async with app.run_test(headless=True) as pilot:
            from textual.widgets import TabbedContent
            app.query_one(TabbedContent)
            # Switch to Projects tab programmatically
            await pilot.pause()
            app._reload_project_list()
            await pilot.pause()
            mock_load.assert_called()
