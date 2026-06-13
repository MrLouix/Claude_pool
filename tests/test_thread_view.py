"""Tests for Step 6 — thread.js view: thread panel, subtasks, and real-time updates."""
import re
from pathlib import Path

_THREAD_JS = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "views" / "thread.js"
_COMPONENTS_CSS = Path(__file__).parent.parent / "team_cli" / "frontend" / "css" / "components.css"
_CHAT_JS = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "views" / "chat.js"


def _thread_src():
    return _THREAD_JS.read_text(encoding="utf-8")


def _components_css_src():
    return _COMPONENTS_CSS.read_text(encoding="utf-8")


def _chat_src():
    return _CHAT_JS.read_text(encoding="utf-8")


class TestThreadJsExports:
    """Test that thread.js exports the required mount function."""

    def test_thread_js_exports_mount(self):
        src = _thread_src()
        assert "export function mount" in src or "export async function mount" in src, (
            "thread.js must export a 'mount' function for router compatibility"
        )


class TestThreadEventHandling:
    """Test that thread.js properly listens for and handles events."""

    def test_thread_listens_open_thread_event(self):
        src = _thread_src()
        assert "open-thread" in src, (
            "thread.js must listen for 'open-thread' custom DOM events"
        )

    def test_thread_listens_on_window(self):
        src = _thread_src()
        assert "window.addEventListener" in src, (
            "thread.js must use window.addEventListener for global events"
        )


class TestThreadCloseFunction:
    """Test that thread.js has a close function."""

    def test_thread_has_close_function(self):
        src = _thread_src()
        assert "_close" in src or "closeThread" in src, (
            "thread.js must have a _close() or closeThread() function"
        )


class TestThreadApiIntegration:
    """Test that thread.js integrates with the API."""

    def test_thread_fetches_api(self):
        src = _thread_src()
        assert "/api/messages/" in src, (
            "thread.js must fetch from /api/messages/ endpoint"
        )
        assert "thread" in src.lower(), (
            "thread.js must reference 'thread' in API calls"
        )


class TestThreadRendering:
    """Test that thread.js renders the required UI components."""

    def test_thread_renders_root_card(self):
        src = _thread_src()
        assert "thread-root-card" in src, (
            "thread.js must render a root message card with class 'thread-root-card'"
        )

    def test_thread_renders_task_cards(self):
        src = _thread_src()
        assert "thread-task-card" in src, (
            "thread.js must render task cards with class 'thread-task-card'"
        )

    def test_thread_renders_subtask_indent(self):
        src = _thread_src()
        assert "thread-task--subtask" in src, (
            "thread.js must support indented subtasks with class 'thread-task--subtask'"
        )


class TestThreadComposer:
    """Test that thread.js has a working composer."""

    def test_thread_composer_posts_with_thread_root_id(self):
        src = _thread_src()
        assert "thread_root_id" in src, (
            "thread.js composer must POST with thread_root_id parameter"
        )

    def test_thread_composer_uses_chat_api(self):
        src = _thread_src()
        assert "/api/chats/" in src, (
            "thread.js composer must POST to /api/chats/{chatId}/messages"
        )


class TestThreadWebSocketUpdates:
    """Test that thread.js handles WebSocket events."""

    def test_thread_ws_updates_task_status(self):
        src = _thread_src()
        assert "pool:task_" in src or "task_started" in src, (
            "thread.js must listen to pool:task_* WebSocket events for task status updates"
        )

    def test_thread_ws_listens_to_message_created(self):
        src = _thread_src()
        assert "pool:message_created" in src, (
            "thread.js must listen to pool:message_created for new replies"
        )

    def test_thread_ws_uses_data_task_id(self):
        src = _thread_src()
        assert "data-task-id" in src, (
            "thread.js must use data-task-id attribute to match task cards"
        )


class TestThreadMobileSwipe:
    """Test that thread.js supports mobile swipe-to-dismiss."""

    def test_thread_mobile_swipe(self):
        src = _thread_src()
        assert "touchstart" in src, (
            "thread.js must handle touchstart for mobile swipe detection"
        )

    def test_thread_mobile_swipe_move(self):
        src = _thread_src()
        assert "touchmove" in src, (
            "thread.js must handle touchmove for mobile swipe detection"
        )

    def test_thread_mobile_swipe_end(self):
        src = _thread_src()
        assert "touchend" in src, (
            "thread.js must handle touchend for mobile swipe cleanup"
        )

    def test_thread_mobile_swipe_cancel(self):
        src = _thread_src()
        assert "touchcancel" in src, (
            "thread.js must handle touchcancel for mobile swipe cleanup"
        )


class TestThreadPanelCSS:
    """Test that components.css has thread panel styles."""

    def test_thread_panel_css_defined(self):
        src = _components_css_src()
        assert "#thread-panel" in src, (
            "components.css must define #thread-panel styles"
        )
        assert "thread-panel--visible" in src, (
            "components.css must define .thread-panel--visible class for mobile"
        )

    def test_thread_panel_desktop_styles(self):
        src = _components_css_src()
        assert "body.thread-open .center-zone" in src, (
            "components.css must style body.thread-open for desktop layout shift"
        )

    def test_thread_panel_mobile_styles(self):
        src = _components_css_src()
        assert "@media (max-width: 767px)" in src, (
            "components.css must have mobile media query for thread panel"
        )

    def test_thread_root_card_css(self):
        src = _components_css_src()
        assert ".thread-root-card" in src, (
            "components.css must define .thread-root-card styles"
        )

    def test_thread_task_card_css(self):
        src = _components_css_src()
        assert ".thread-task-card" in src, (
            "components.css must define .thread-task-card styles"
        )

    def test_thread_composer_css(self):
        src = _components_css_src()
        assert ".thread-composer" in src, (
            "components.css must define .thread-composer styles"
        )


class TestChatJsBadgeCounts:
    """Test that chat.js updates thread badge counts in real-time."""

    def test_chat_update_thread_badge_function(self):
        src = _chat_src()
        assert "_updateThreadBadge" in src or "updateThreadBadge" in src, (
            "chat.js must have a function to update thread badge counts"
        )

    def test_chat_checks_thread_root_id(self):
        src = _chat_src()
        assert "thread_root_id" in src, (
            "chat.js must check for thread_root_id in WebSocket messages"
        )

    def test_chat_increments_badge_on_reply(self):
        src = _chat_src()
        assert "replyCount" in src or "reply-count" in src, (
            "chat.js must track replyCount on thread buttons"
        )

    def test_chat_uses_data_reply_count(self):
        src = _chat_src()
        assert "data-reply-count" in src, (
            "chat.js must use data-reply-count attribute on thread buttons"
        )
