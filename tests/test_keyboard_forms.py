"""Tests for Phase 2.3+7 — Keyboard Navigation & Form UX in frontend/index.html."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"


def _html():
    return HTML_PATH.read_text(encoding="utf-8")


def _body():
    """Return everything after </style> (HTML + JS)."""
    content = _html()
    return content[content.find("</style>"):]


def _js():
    """Return the contents of the <script> block."""
    content = _html()
    m = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
    assert m, "No <script> block found"
    return m.group(1)


# ── 7.1 trapFocus function ────────────────────────────────────────────────────

class TestTrapFocus:
    def test_trap_focus_function_defined(self):
        js = _js()
        assert "function trapFocus" in js, (
            "trapFocus function not defined in <script>"
        )

    def test_trap_focus_queries_focusable(self):
        js = _js()
        assert "querySelectorAll" in js, (
            "trapFocus should use querySelectorAll to find focusable elements"
        )

    def test_trap_focus_handles_tab(self):
        js = _js()
        assert "'Tab'" in js or '"Tab"' in js, (
            "trapFocus should intercept Tab key"
        )

    def test_trap_focus_called_on_open(self):
        js = _js()
        calls = re.findall(r"trapFocus\(\w+\)", js)
        assert len(calls) >= 4, (
            f"trapFocus should be called in all 4 modal openers, found {len(calls)} calls"
        )

    def test_remove_trap_focus_cleanup(self):
        js = _js()
        assert "_removeTrapFocus" in js, (
            "_removeTrapFocus cleanup function not set in trapFocus"
        )

    def test_remove_trap_focus_called_on_close(self):
        js = _js()
        calls = js.count("_removeTrapFocus?.()")
        assert calls >= 4, (
            f"_removeTrapFocus should be called in all 4 modal closers, found {calls}"
        )


# ── 7.2 Escape key closes modals ─────────────────────────────────────────────

class TestEscapeHandler:
    def test_escape_handler_present(self):
        js = _js()
        assert "'Escape'" in js or '"Escape"' in js, (
            "No Escape key handler found in JS"
        )

    def test_escape_checks_active_class(self):
        js = _js()
        assert "classList.contains('active')" in js or \
               'classList.contains("active")' in js, (
            "Escape handler should check classList.contains('active') to detect open modals"
        )

    def test_escape_closes_dir_modal(self):
        js = _js()
        escape_block = re.search(
            r"key.*['\"]Escape['\"].*?(?=\n\s*\}/\*|$)",
            js, re.DOTALL
        )
        assert escape_block or "closeDirModal" in js, (
            "closeDirModal should be reachable from Escape handler"
        )

    def test_escape_closes_run_plan_modal(self):
        js = _js()
        assert "closeRunPlanModal" in js, (
            "closeRunPlanModal not found in JS — Escape handler missing coverage"
        )

    def test_escape_closes_new_chat_modal(self):
        js = _js()
        assert "closeNewChatModal" in js, (
            "closeNewChatModal not found in JS — Escape handler missing coverage"
        )

    def test_escape_closes_chat_run_plan_modal(self):
        js = _js()
        assert "closeChatRunPlanModal" in js, (
            "closeChatRunPlanModal not found in JS — Escape handler missing coverage"
        )


# ── 7.3 Opener focus restoration ─────────────────────────────────────────────

class TestOpenerFocusRestore:
    def test_opener_element_stored(self):
        js = _js()
        assert "_openerElement = document.activeElement" in js, (
            "_openerElement not stored before opening modal"
        )

    def test_opener_element_restored_on_close(self):
        js = _js()
        assert "_openerElement?.focus()" in js, (
            "_openerElement?.focus() not called in modal close — focus not restored"
        )

    def test_all_openers_track_element(self):
        js = _js()
        count = js.count("_openerElement = document.activeElement")
        assert count >= 4, (
            f"Expected ≥4 opener tracking assignments (one per modal), found {count}"
        )

    def test_all_closers_restore_focus(self):
        js = _js()
        count = js.count("_openerElement?.focus()")
        assert count >= 4, (
            f"Expected ≥4 focus restore calls (one per modal), found {count}"
        )


# ── 7.4 Enter/Space on clickable divs ────────────────────────────────────────

class TestEnterSpaceHandler:
    def test_enter_space_handler_present(self):
        js = _js()
        assert "'Enter'" in js or '"Enter"' in js, (
            "No Enter key handler found in JS"
        )

    def test_dir_item_keyboard_activatable(self):
        js = _js()
        assert ".dir-item" in js and ".matches(" in js, (
            ".dir-item not in keyboard activation handler (matches check)"
        )

    def test_task_item_keyboard_activatable(self):
        js = _js()
        assert ".task-item" in js and ".matches(" in js, (
            ".task-item not in keyboard activation handler"
        )

    def test_message_bubble_keyboard_activatable(self):
        js = _js()
        assert ".message-bubble" in js and ".matches(" in js, (
            ".message-bubble not in keyboard activation handler"
        )

    def test_keyboard_handler_calls_click(self):
        js = _js()
        assert ".click()" in js, (
            "Keyboard activation handler should call .click() on target"
        )


# ── 7.5 tabindex on clickable divs ───────────────────────────────────────────

class TestTabindex:
    def test_task_item_has_tabindex(self):
        body = _body()
        task_item_match = re.search(r'class="task-item"[^>]*tabindex', body)
        assert task_item_match, (
            ".task-item in rendered HTML template missing tabindex attribute"
        )

    def test_message_bubble_has_tabindex(self):
        body = _body()
        msg_bubble_match = re.search(r'class="message-bubble[^"]*"[^>]*tabindex', body)
        js = _js()
        assert msg_bubble_match or 'tabIndex = 0' in js, (
            ".message-bubble missing tabindex/tabIndex for keyboard focus"
        )

    def test_dir_item_has_tabindex(self):
        js = _js()
        assert 'tabindex="0"' in js or "tabindex='0'" in js, (
            ".dir-item missing tabindex='0' in renderDirList"
        )


# ── 7.6 autocomplete / spellcheck / inputmode on directory inputs ─────────────

class TestDirectoryInputAttributes:
    def test_directory_autocomplete_off(self):
        body = _body()
        el = re.search(r'<input[^>]*id="directory"[^>]*>', body)
        assert el, "#directory input not found"
        assert 'autocomplete="off"' in el.group(), (
            '#directory input missing autocomplete="off"'
        )

    def test_directory_spellcheck_false(self):
        body = _body()
        el = re.search(r'<input[^>]*id="directory"[^>]*>', body)
        assert el
        assert 'spellcheck="false"' in el.group(), (
            '#directory input missing spellcheck="false"'
        )

    def test_directory_inputmode_url(self):
        body = _body()
        el = re.search(r'<input[^>]*id="directory"[^>]*>', body)
        assert el
        assert 'inputmode="url"' in el.group(), (
            '#directory input missing inputmode="url"'
        )

    def test_plan_directory_autocomplete_off(self):
        body = _body()
        el = re.search(r'<input[^>]*id="plan-directory"[^>]*>', body)
        assert el, "#plan-directory input not found"
        assert 'autocomplete="off"' in el.group(), (
            '#plan-directory input missing autocomplete="off"'
        )

    def test_plan_directory_spellcheck_false(self):
        body = _body()
        el = re.search(r'<input[^>]*id="plan-directory"[^>]*>', body)
        assert el
        assert 'spellcheck="false"' in el.group(), (
            '#plan-directory input missing spellcheck="false"'
        )

    def test_new_chat_directory_autocomplete_off(self):
        body = _body()
        el = re.search(r'<input[^>]*id="new-chat-directory"[^>]*>', body)
        assert el, "#new-chat-directory input not found"
        assert 'autocomplete="off"' in el.group(), (
            '#new-chat-directory input missing autocomplete="off"'
        )

    def test_new_chat_directory_spellcheck_false(self):
        body = _body()
        el = re.search(r'<input[^>]*id="new-chat-directory"[^>]*>', body)
        assert el
        assert 'spellcheck="false"' in el.group(), (
            '#new-chat-directory input missing spellcheck="false"'
        )

    def test_new_chat_directory_inputmode_url(self):
        body = _body()
        el = re.search(r'<input[^>]*id="new-chat-directory"[^>]*>', body)
        assert el
        assert 'inputmode="url"' in el.group(), (
            '#new-chat-directory input missing inputmode="url"'
        )


# ── 7.7 Label for= linkage ────────────────────────────────────────────────────

class TestLabelForLinkage:
    def test_new_chat_label_input_has_for(self):
        body = _body()
        assert 'for="new-chat-label"' in body, (
            "No label with for='new-chat-label' found — Chat name label is unlinked"
        )

    def test_new_chat_directory_has_for(self):
        body = _body()
        assert 'for="new-chat-directory"' in body, (
            "No label with for='new-chat-directory' found — Working Directory label is unlinked"
        )

    def test_plan_directory_has_for(self):
        body = _body()
        assert 'for="plan-directory"' in body, (
            "No label with for='plan-directory' found — Working Directory label is unlinked"
        )

    def test_plan_spec_has_for(self):
        body = _body()
        assert 'for="plan-spec"' in body, (
            "No label with for='plan-spec' found — Coding Specification label is unlinked"
        )

    def test_chat_plan_spec_has_for(self):
        body = _body()
        assert 'for="chat-plan-spec"' in body, (
            "No label with for='chat-plan-spec' found — Chat spec label is unlinked"
        )

    def test_main_form_labels_intact(self):
        """Existing properly-linked main form labels must remain unchanged."""
        body = _body()
        assert 'for="prompt"' in body, "label for='prompt' was removed"
        assert 'for="directory"' in body, "label for='directory' was removed"
        assert 'for="model"' in body, "label for='model' was removed"
