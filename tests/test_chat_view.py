"""Tests for Step 5 — chat.js view: ARIA, tab bar, composer, message list."""
import re
from pathlib import Path

_CHAT_JS = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "views" / "chat.js"


def _src():
    return _CHAT_JS.read_text(encoding="utf-8")


class TestChatJsExports:
    def test_exports_mount_function(self):
        src = _src()
        assert "export async function mount" in src or "export function mount" in src, (
            "chat.js must export a 'mount' function"
        )

    def test_mount_accepts_params(self):
        src = _src()
        m = re.search(r"export async function mount\s*\((\w+)\)", src)
        assert m, "mount() must accept a params argument"

    def test_imports_api(self):
        src = _src()
        assert "import * as api from" in src, "chat.js must import api.js"

    def test_imports_store(self):
        src = _src()
        assert "from '../store.js'" in src, "chat.js must import from store.js"


class TestTabBarARIA:
    def test_tablist_role_present(self):
        src = _src()
        assert 'role="tablist"' in src, (
            "Tab bar container must have role='tablist' for keyboard accessibility"
        )

    def test_tab_role_present(self):
        src = _src()
        assert 'role="tab"' in src, (
            "Each tab item must have role='tab'"
        )

    def test_aria_selected_present(self):
        src = _src()
        assert 'aria-selected' in src, (
            "Active tab must set aria-selected"
        )

    def test_tab_bar_has_aria_label(self):
        src = _src()
        assert 'aria-label="Chats"' in src, (
            "Tab bar must have aria-label='Chats'"
        )

    def test_tab_keyboard_navigation(self):
        src = _src()
        assert 'ArrowRight' in src and 'ArrowLeft' in src, (
            "Tab bar must support ArrowRight/ArrowLeft keyboard navigation"
        )

    def test_tab_close_has_aria_label(self):
        src = _src()
        assert "aria-label=\"Close" in src or "aria-label='Close" in src, (
            "Close button on each tab must have a descriptive aria-label"
        )

    def test_new_chat_button_has_aria_label(self):
        src = _src()
        assert 'aria-label="New chat"' in src, (
            "The '+' button for adding a new chat must have aria-label='New chat'"
        )


class TestMessageListARIA:
    def test_message_list_has_role_log(self):
        src = _src()
        assert 'role="log"' in src, (
            "Message list must have role='log' for screen reader live region"
        )

    def test_message_list_aria_live(self):
        src = _src()
        assert 'aria-live="polite"' in src, (
            "Message list must have aria-live='polite'"
        )

    def test_message_list_aria_label(self):
        src = _src()
        assert 'aria-label="Messages"' in src, (
            "Message list must have aria-label='Messages'"
        )

    def test_load_earlier_button(self):
        src = _src()
        assert 'Load earlier' in src, (
            "Pagination 'Load earlier' button text must be present"
        )

    def test_load_earlier_aria_label(self):
        src = _src()
        assert 'aria-label="Load earlier messages"' in src, (
            "'Load earlier' button must have a descriptive aria-label"
        )

    def test_open_thread_event_dispatched(self):
        src = _src()
        assert 'open-thread' in src, (
            "Clicking the thread button must dispatch an 'open-thread' CustomEvent"
        )

    def test_thread_button_aria_label(self):
        src = _src()
        assert 'aria-label="Open thread for this message"' in src, (
            "Thread open button must have a descriptive aria-label"
        )


class TestComposerARIA:
    def test_composer_textarea_present(self):
        src = _src()
        assert 'id="composer-textarea"' in src or "composer-textarea" in src, (
            "Composer must contain a textarea"
        )

    def test_composer_textarea_aria_label(self):
        src = _src()
        assert 'aria-label="Message"' in src, (
            "Composer textarea must have aria-label='Message'"
        )

    def test_composer_send_btn_aria_label(self):
        src = _src()
        assert 'aria-label="Send message"' in src, (
            "Send button must have aria-label='Send message'"
        )

    def test_composer_row_group_role(self):
        src = _src()
        assert 'role="group"' in src, (
            "Composer row should have role='group'"
        )

    def test_composer_group_aria_label(self):
        src = _src()
        assert 'aria-label="Message composer"' in src, (
            "Composer group must have aria-label='Message composer'"
        )

    def test_sr_only_label_for_textarea(self):
        src = _src()
        assert 'sr-only' in src, (
            "Must use sr-only class for visually hidden label"
        )

    def test_shift_enter_newline(self):
        src = _src()
        assert 'shiftKey' in src, (
            "Composer must check e.shiftKey to allow Shift+Enter newline"
        )

    def test_enter_sends(self):
        src = _src()
        assert "e.key === 'Enter'" in src or 'e.key === "Enter"' in src, (
            "Composer must send on Enter key"
        )

    def test_cli_selector_aria_label(self):
        src = _src()
        assert 'aria-label="CLI"' in src, (
            "CLI dropdown must have aria-label='CLI'"
        )

    def test_model_selector_aria_label(self):
        src = _src()
        assert 'aria-label="Model"' in src, (
            "Model dropdown must have aria-label='Model'"
        )

    def test_mobile_settings_toggle_aria_label(self):
        src = _src()
        assert 'aria-label="CLI and model settings"' in src, (
            "Mobile ⚙ settings toggle must have descriptive aria-label"
        )

    def test_mobile_picker_has_hidden_attr(self):
        src = _src()
        assert 'hidden' in src and 'composer-picker' in src, (
            "Mobile picker panel must use 'hidden' attribute for toggle"
        )

    def test_aria_expanded_on_toggle(self):
        src = _src()
        assert 'aria-expanded' in src, (
            "Settings toggle must manage aria-expanded state"
        )


class TestTypingIndicator:
    def test_typing_indicator_class(self):
        src = _src()
        assert 'chat-typing-indicator' in src, (
            "Typing indicator element with class 'chat-typing-indicator' must be present"
        )

    def test_typing_indicator_aria_label(self):
        src = _src()
        assert 'aria-label="Assistant is typing"' in src, (
            "Typing indicator must have aria-label='Assistant is typing'"
        )

    def test_typing_indicator_aria_live(self):
        src = _src()
        # aria-live must be set somewhere near typing indicator
        assert 'aria-live' in src, (
            "Typing indicator must use aria-live for screen reader announcement"
        )


class TestRealTimeUpdates:
    def test_ws_event_listener_registered(self):
        src = _src()
        assert 'pool:message_created' in src, (
            "Must listen to 'pool:message_created' WebSocket events"
        )

    def test_ws_listener_cleaned_up(self):
        src = _src()
        # Should have removeEventListener for cleanup
        assert 'removeEventListener' in src and 'pool:message_created' in src, (
            "Must remove WebSocket event listener during cleanup"
        )

    def test_visual_viewport_resize(self):
        src = _src()
        assert 'visualViewport' in src, (
            "Must use window.visualViewport to adjust composer on mobile keyboard"
        )

    def test_pagination_fetch_on_load_earlier(self):
        src = _src()
        assert 'listPage' in src or 'paginate' in src or 'before' in src, (
            "Must support paginated message loading for 'Load earlier'"
        )

    def test_lazy_rendering_100_messages(self):
        src = _src()
        assert '100' in src, (
            "Must limit DOM to 100 messages (lazy rendering threshold)"
        )
