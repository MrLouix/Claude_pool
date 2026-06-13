"""Tests for Queue view JS source and CSS (Step 8)."""

from pathlib import Path

_ROOT = Path(__file__).parent.parent
_QUEUE_JS  = _ROOT / "team_cli" / "frontend" / "js" / "views" / "queue.js"
_DETAIL_JS = _ROOT / "team_cli" / "frontend" / "js" / "views" / "taskdetail.js"
_CSS       = _ROOT / "team_cli" / "frontend" / "css" / "components.css"


def _js() -> str:
    return _QUEUE_JS.read_text(encoding="utf-8")


def _css() -> str:
    return _CSS.read_text(encoding="utf-8")


class TestQueueJsSource:
    def test_filter_logic_present(self) -> None:
        """queue.js must contain filter logic."""
        assert "filter" in _js()

    def test_queue_card_class_referenced(self) -> None:
        """queue.js must reference the .queue-card CSS class."""
        assert ".queue-card" in _js()

    def test_task_detail_panel_or_import(self) -> None:
        """queue.js must either reference .task-detail-panel or import taskdetail."""
        src = _js()
        assert ".task-detail-panel" in src or "taskdetail" in src

    def test_clear_completed_text_present(self) -> None:
        """queue.js must contain the 'Clear completed' button label."""
        assert "Clear completed" in _js()

    def test_pool_status_event_listener(self) -> None:
        """queue.js must listen for the pool:pool_status WebSocket event."""
        assert "pool:pool_status" in _js()

    def test_task_kind_class_referenced(self) -> None:
        """queue.js must reference the task-kind CSS class."""
        assert "task-kind" in _js()

    def test_cleanup_export_present(self) -> None:
        """queue.js must export a cleanup() function."""
        assert "export function cleanup" in _js()

    def test_skip_button_present(self) -> None:
        """queue.js must include a skip action for pending tasks."""
        src = _js()
        assert "skip" in src.lower() or "skipped" in src


class TestTaskDetailJsSource:
    def test_show_task_detail_exported(self) -> None:
        """taskdetail.js must export showTaskDetail."""
        src = _DETAIL_JS.read_text(encoding="utf-8")
        assert "export function showTaskDetail" in src

    def test_task_detail_panel_class(self) -> None:
        """taskdetail.js must reference .task-detail-panel."""
        src = _DETAIL_JS.read_text(encoding="utf-8")
        assert ".task-detail-panel" in src or "task-detail-panel" in src

    def test_close_button_class(self) -> None:
        """taskdetail.js must reference .task-detail-close."""
        src = _DETAIL_JS.read_text(encoding="utf-8")
        assert "task-detail-close" in src

    def test_json_output_handling(self) -> None:
        """taskdetail.js must handle json_output."""
        src = _DETAIL_JS.read_text(encoding="utf-8")
        assert "json_output" in src

    def test_thread_link(self) -> None:
        """taskdetail.js must render a thread link when chat_id is set."""
        src = _DETAIL_JS.read_text(encoding="utf-8")
        assert "chat_id" in src


class TestQueueCss:
    def test_queue_card_rule_exists(self) -> None:
        """.queue-card rule must be defined in components.css."""
        assert ".queue-card" in _css()

    def test_task_kind_rule_exists(self) -> None:
        """.task-kind rule must be defined in components.css."""
        assert ".task-kind" in _css()

    def test_task_detail_panel_rule_exists(self) -> None:
        """.task-detail-panel rule must be defined in components.css."""
        assert ".task-detail-panel" in _css()

    def test_bulk_actions_rule_exists(self) -> None:
        """.bulk-actions rule must be defined in components.css."""
        assert ".bulk-actions" in _css()

    def test_mobile_filter_bar_scrollable(self) -> None:
        """Mobile overrides must make the filter bar scrollable."""
        css = _css()
        assert "overflow-x: auto" in css and "queue-filter-bar" in css
