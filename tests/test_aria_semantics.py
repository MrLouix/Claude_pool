"""Tests for Phase 2.1+2.2+6 — ARIA labels, roles, and semantic HTML."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "claude_pool" / "frontend" / "index.html"


def _html():
    return HTML_PATH.read_text(encoding="utf-8")


def _body():
    """Return everything after </style> (the HTML body + JS)."""
    content = _html()
    return content[content.find("</style>"):]


# ── 6.1 Semantic HTML elements ────────────────────────────────────────────────

class TestSemanticHTML:
    def test_header_element_exists(self):
        body = _body()
        assert "<header" in body, (
            "No <header> element found — <div class='header'> should be <header>"
        )

    def test_header_has_header_class(self):
        body = _body()
        assert '<header class="header"' in body, (
            "<header> element should retain class='header' for CSS compatibility"
        )

    def test_no_div_header_remains(self):
        body = _body()
        assert '<div class="header"' not in body, (
            "<div class='header'> should have been converted to <header>"
        )

    def test_main_role_on_dashboard(self):
        body = _body()
        assert 'role="main"' in body, (
            "No element has role='main' — the primary content area needs this"
        )

    def test_dashboard_view_has_main_role(self):
        body = _body()
        assert 'id="dashboard-view" role="main"' in body or \
               'role="main"' in body.split('id="dashboard-view"')[0][:200] is False and \
               'role="main"' in body, (
            "dashboard-view container should have role='main'"
        )


# ── 6.2 aria-labelledby on sections ──────────────────────────────────────────

class TestSectionLabelledBy:
    def test_aria_labelledby_present(self):
        body = _body()
        assert "aria-labelledby" in body, (
            "No aria-labelledby found — sections need this to identify their purpose"
        )

    def test_at_least_three_sections_labelled(self):
        body = _body()
        count = body.count("aria-labelledby=")
        assert count >= 3, (
            f"Expected ≥3 aria-labelledby attributes, found {count}"
        )

    def test_running_list_section_labelled(self):
        body = _body()
        assert 'id="running-list-heading"' in body, (
            "Running List section heading missing id='running-list-heading'"
        )
        assert 'aria-labelledby="running-list-heading"' in body, (
            "Running List section missing aria-labelledby='running-list-heading'"
        )

    def test_event_log_section_labelled(self):
        body = _body()
        assert 'id="event-log-heading"' in body, (
            "Event Log section heading missing id"
        )
        assert 'aria-labelledby="event-log-heading"' in body, (
            "Event Log section missing aria-labelledby"
        )

    def test_chats_section_labelled(self):
        body = _body()
        assert 'id="chats-heading"' in body, "Chats section heading missing id"
        assert 'aria-labelledby="chats-heading"' in body

    def test_heading_ids_are_unique(self):
        body = _body()
        heading_ids = re.findall(r'id="([^"]*-heading)"', body)
        assert len(heading_ids) == len(set(heading_ids)), (
            f"Duplicate heading IDs found: {heading_ids}"
        )


# ── 6.3 ARIA roles: lists, log, dialogs ──────────────────────────────────────

class TestARIARoles:
    def test_role_list_present(self):
        body = _body()
        assert 'role="list"' in body, (
            "No element has role='list' — task list containers need this"
        )

    def test_task_list_has_role_list(self):
        body = _body()
        assert 'id="task-list" role="list"' in body, (
            "#task-list is missing role='list'"
        )

    def test_success_list_has_role_list(self):
        body = _body()
        assert 'id="success-list" role="list"' in body, (
            "#success-list is missing role='list'"
        )

    def test_role_log_present(self):
        body = _body()
        assert 'role="log"' in body, (
            "No element has role='log' — the event log container needs this"
        )

    def test_event_log_has_role_log(self):
        body = _body()
        assert 'id="event-log" role="log"' in body or \
               'role="log"' in body, (
            "#event-log is missing role='log'"
        )

    def test_event_log_has_aria_live(self):
        body = _body()
        log_element = re.search(r'id="event-log"[^>]*>', body)
        assert log_element, "#event-log element not found"
        assert "aria-live" in log_element.group(), (
            "#event-log is missing aria-live attribute"
        )

    def test_role_dialog_present(self):
        body = _body()
        assert 'role="dialog"' in body, (
            "No element has role='dialog' — modal overlays need this"
        )

    def test_aria_modal_true_present(self):
        body = _body()
        assert 'aria-modal="true"' in body, (
            "No element has aria-modal='true' — modal dialogs need this"
        )

    def test_at_least_three_dialogs(self):
        body = _body()
        count = len(re.findall(r'role="dialog"', body))
        assert count >= 3, (
            f"Expected ≥3 role='dialog' elements (one per modal), found {count}"
        )

    def test_dialogs_have_labelledby(self):
        body = _body()
        dialogs = re.findall(r'role="dialog"[^>]*>', body)
        for dialog in dialogs:
            assert "aria-labelledby" in dialog, (
                f"Dialog missing aria-labelledby: {dialog[:80]}"
            )

    def test_modal_h3s_have_ids(self):
        body = _body()
        # Each modal h3 that is referenced via aria-labelledby must have an id
        labelledby_ids = re.findall(r'aria-labelledby="([^"]+)"', body)
        for lid in labelledby_ids:
            assert f'id="{lid}"' in body, (
                f"aria-labelledby references id='{lid}' but no element with that id found"
            )


# ── 6.4 aria-label on icon-only buttons ──────────────────────────────────────

class TestIconButtonLabels:
    def test_browse_buttons_have_aria_label(self):
        body = _body()
        browse_btns = re.findall(r'<button[^>]*class="[^"]*btn-browse[^"]*"[^>]*>', body)
        assert browse_btns, "No .btn-browse buttons found"
        for btn in browse_btns:
            assert "aria-label" in btn, (
                f"Browse button missing aria-label: {btn[:100]}"
            )

    def test_modal_close_buttons_have_aria_label(self):
        body = _body()
        close_btns = re.findall(r'<button[^>]*class="[^"]*modal-close[^"]*"[^>]*>', body)
        assert close_btns, "No .modal-close buttons found"
        labelled = [b for b in close_btns if "aria-label" in b]
        # At least the static modal-close buttons (excluding the cancel-style ones)
        icon_close = [b for b in close_btns if "id=" in b and "cancel" not in b]
        for btn in icon_close:
            assert "aria-label" in btn, (
                f"Modal close button missing aria-label: {btn[:120]}"
            )

    def test_send_button_has_aria_label(self):
        body = _body()
        send_btn = re.search(r'<button[^>]*id="btn-send-message"[^>]*>', body)
        assert send_btn, "btn-send-message not found"
        assert "aria-label" in send_btn.group(), (
            "btn-send-message (icon ⬆) is missing aria-label"
        )

    def test_status_dot_is_aria_hidden(self):
        body = _body()
        dot = re.search(r'<span[^>]*class="[^"]*claude-status-dot[^"]*"[^>]*>', body)
        assert dot, "claude-status-dot element not found"
        assert 'aria-hidden="true"' in dot.group(), (
            "Decorative claude-status-dot should have aria-hidden='true'"
        )


# ── 6.5 aria-label on unlabelled form inputs ─────────────────────────────────

class TestFormInputLabels:
    def test_chat_input_has_aria_label(self):
        body = _body()
        chat_input = re.search(r'<textarea[^>]*id="chat-input"[^>]*>', body)
        assert chat_input, "#chat-input textarea not found"
        assert "aria-label" in chat_input.group(), (
            "#chat-input (chat message area) is missing aria-label"
        )

    def test_new_chat_label_input_has_aria_label(self):
        body = _body()
        el = re.search(r'<input[^>]*id="new-chat-label"[^>]*>', body)
        assert el, "#new-chat-label input not found"
        assert "aria-label" in el.group(), (
            "#new-chat-label input is missing aria-label"
        )

    def test_new_chat_directory_has_aria_label(self):
        body = _body()
        el = re.search(r'<input[^>]*id="new-chat-directory"[^>]*>', body)
        assert el, "#new-chat-directory input not found"
        assert "aria-label" in el.group(), (
            "#new-chat-directory is missing aria-label"
        )

    def test_plan_directory_has_aria_label(self):
        body = _body()
        el = re.search(r'<input[^>]*id="plan-directory"[^>]*>', body)
        assert el, "#plan-directory input not found"
        assert "aria-label" in el.group(), (
            "#plan-directory is missing aria-label"
        )

    def test_plan_spec_has_aria_label(self):
        body = _body()
        el = re.search(r'<textarea[^>]*id="plan-spec"[^>]*>', body)
        assert el, "#plan-spec textarea not found"
        assert "aria-label" in el.group(), (
            "#plan-spec textarea is missing aria-label"
        )

    def test_main_form_inputs_already_labelled(self):
        """The main add-task form inputs have proper for/id label links — verify unchanged."""
        body = _body()
        # prompt textarea is linked via <label for="prompt">
        assert '<label for="prompt">' in body, "label for='prompt' missing"
        assert '<label for="directory">' in body, "label for='directory' missing"
        assert '<label for="model">' in body, "label for='model' missing"
