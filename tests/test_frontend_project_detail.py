"""Frontend tests for Phase 5 Step 3: Project detail page with threading, actions, auto-refresh."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
HTML = FRONTEND.read_text(encoding="utf-8")
_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"
CSS = "\n".join((_CSS_DIR / n).read_text(encoding="utf-8") for n in ["tokens.css", "layout.css", "components.css"])


# ---------------------------------------------------------------------------
# HTML structure — header changes
# ---------------------------------------------------------------------------

class TestProjectViewHeader:
    def test_back_button_says_back_to_projects(self):
        assert "← Back to Projects" in HTML

    def test_cli_status_element_exists(self):
        assert 'id="project-cli-status"' in HTML

    def test_new_message_button_exists(self):
        assert 'id="btn-project-new-message"' in HTML


# ---------------------------------------------------------------------------
# HTML structure — reply banner
# ---------------------------------------------------------------------------

class TestReplyBannerHtml:
    def test_reply_banner_exists(self):
        assert 'id="project-reply-banner"' in HTML

    def test_reply_banner_has_hidden_class(self):
        assert re.search(r'id="project-reply-banner"[^>]*class="[^"]*hidden', HTML) or \
               re.search(r'id="project-reply-banner"[^>]*hidden', HTML)

    def test_reply_excerpt_exists(self):
        assert 'id="project-reply-excerpt"' in HTML

    def test_reply_close_button_exists(self):
        assert 'id="btn-project-reply-close"' in HTML


# ---------------------------------------------------------------------------
# CSS — new classes
# ---------------------------------------------------------------------------

class TestProjectDetailCss:
    def test_threaded_class_defined(self):
        assert ".project-msg-threaded" in CSS

    def test_threaded_class_has_indent(self):
        start = CSS.index(".project-msg-threaded")
        block = CSS[start:start + 200]
        assert "margin-left" in block or "padding-left" in block

    def test_msg_actions_class_defined(self):
        assert ".project-msg-actions" in CSS

    def test_btn_msg_action_class_defined(self):
        assert ".btn-msg-action" in CSS

    def test_btn_msg_delete_class_defined(self):
        assert ".btn-msg-delete" in CSS

    def test_reply_banner_class_defined(self):
        assert ".project-reply-banner" in CSS

    def test_reply_excerpt_class_defined(self):
        assert ".project-reply-excerpt" in CSS

    def test_reply_close_class_defined(self):
        assert ".project-reply-close" in CSS


# ---------------------------------------------------------------------------
# renderProjectMessages — threading and action buttons
# ---------------------------------------------------------------------------

class TestRenderProjectMessagesUpdated:
    def _fn_body(self):
        start = HTML.index("function renderProjectMessages")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_threaded_class_applied(self):
        body = self._fn_body()
        assert "project-msg-threaded" in body

    def test_threaded_based_on_linked_message_id(self):
        body = self._fn_body()
        assert "linked_message_id" in body

    def test_reply_button_rendered(self):
        body = self._fn_body()
        assert re.search(r"Reply", body)

    def test_reply_calls_set_reply_context(self):
        body = self._fn_body()
        assert "setReplyContext" in body

    def test_new_thread_button_rendered(self):
        body = self._fn_body()
        assert "New Thread" in body

    def test_new_thread_calls_set_new_thread_context(self):
        body = self._fn_body()
        assert "setNewThreadContext" in body

    def test_delete_button_rendered(self):
        body = self._fn_body()
        assert re.search(r"Delete|🗑", body)

    def test_delete_calls_delete_project_message(self):
        body = self._fn_body()
        assert "deleteProjectMessage" in body

    def test_action_buttons_container_class(self):
        body = self._fn_body()
        assert "project-msg-actions" in body

    def test_msg_data_attribute_set(self):
        body = self._fn_body()
        assert "data-msg-id" in body


# ---------------------------------------------------------------------------
# JS functions — reply context
# ---------------------------------------------------------------------------

class TestReplyContextJs:
    def test_set_reply_context_defined(self):
        assert "function setReplyContext" in HTML

    def test_set_reply_context_stores_id(self):
        start = HTML.index("function setReplyContext")
        block = HTML[start:start + 400]
        assert "_replyToMessageId" in block

    def test_set_reply_context_shows_banner(self):
        start = HTML.index("function setReplyContext")
        block = HTML[start:start + 400]
        assert "hidden" in block

    def test_set_reply_context_sets_excerpt(self):
        start = HTML.index("function setReplyContext")
        block = HTML[start:start + 400]
        assert "project-reply-excerpt" in block

    def test_clear_reply_context_defined(self):
        assert "function clearReplyContext" in HTML

    def test_clear_reply_context_nulls_id(self):
        start = HTML.index("function clearReplyContext")
        block = HTML[start:start + 300]
        assert "_replyToMessageId" in block

    def test_clear_reply_context_hides_banner(self):
        start = HTML.index("function clearReplyContext")
        block = HTML[start:start + 300]
        assert "hidden" in block

    def test_set_new_thread_context_defined(self):
        assert "function setNewThreadContext" in HTML

    def test_reply_to_id_variable_declared(self):
        assert "_replyToMessageId" in HTML


# ---------------------------------------------------------------------------
# JS functions — delete message
# ---------------------------------------------------------------------------

class TestDeleteProjectMessageJs:
    def _fn_body(self):
        start = HTML.index("async function deleteProjectMessage")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_delete_project_message_defined(self):
        assert "deleteProjectMessage" in HTML

    def test_uses_confirm_dialog(self):
        body = self._fn_body()
        assert "confirm(" in body

    def test_calls_delete_api(self):
        body = self._fn_body()
        assert re.search(r"DELETE.*api/projects|api/projects.*DELETE", body, re.DOTALL)

    def test_refreshes_after_delete(self):
        body = self._fn_body()
        assert "fetchProjectMessages" in body


# ---------------------------------------------------------------------------
# sendProjectMessage — includes linked_message_id
# ---------------------------------------------------------------------------

class TestSendProjectMessageUpdated:
    def _fn_body(self):
        start = HTML.index("async function sendProjectMessage")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_reads_reply_to_id(self):
        body = self._fn_body()
        assert "_replyToMessageId" in body

    def test_passes_linked_message_id_in_body(self):
        body = self._fn_body()
        assert "linked_message_id" in body

    def test_clears_reply_context_after_send(self):
        body = self._fn_body()
        assert "clearReplyContext" in body


# ---------------------------------------------------------------------------
# Auto-refresh polling
# ---------------------------------------------------------------------------

class TestProjectAutoRefresh:
    def test_poll_interval_defined(self):
        assert "_projectPollInterval" in HTML

    def test_set_interval_used(self):
        assert "setInterval" in HTML

    def test_interval_calls_fetch_project_messages(self):
        start = HTML.index("_projectPollInterval = setInterval")
        block = HTML[start:start + 300]
        assert "fetchProjectMessages" in block

    def test_interval_cleared_on_dashboard(self):
        start = HTML.index("function showDashboardView")
        block = HTML[start:start + 500]
        assert "clearInterval" in block


# ---------------------------------------------------------------------------
# loadProjectMeta — CLI status
# ---------------------------------------------------------------------------

class TestLoadProjectMetaCliStatus:
    def _fn_body(self):
        start = HTML.index("async function loadProjectMeta")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_updates_cli_status_element(self):
        body = self._fn_body()
        assert "project-cli-status" in body

    def test_shows_default_cli_name(self):
        body = self._fn_body()
        assert "default_cli" in body


# ---------------------------------------------------------------------------
# Event listeners wired
# ---------------------------------------------------------------------------

class TestProjectDetailEventListeners:
    def test_reply_close_button_listener(self):
        assert "btn-project-reply-close" in HTML
        assert re.search(r"btn-project-reply-close.*clearReplyContext|clearReplyContext.*btn-project-reply-close", HTML, re.DOTALL)

    def test_new_message_button_listener(self):
        assert re.search(r"btn-project-new-message.*addEventListener|addEventListener.*btn-project-new-message", HTML, re.DOTALL)
