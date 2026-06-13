"""Frontend tests for Phase 5 Step 4: Enhanced message composition panel."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"
HTML = FRONTEND.read_text(encoding="utf-8")
CSS = "\n".join((_CSS_DIR / n).read_text(encoding="utf-8") for n in ["tokens.css", "layout.css", "components.css"])


# ---------------------------------------------------------------------------
# HTML structure — compose panel
# ---------------------------------------------------------------------------

class TestComposePanelHtml:
    def test_compose_panel_wrapper_exists(self):
        assert 'id="project-compose-panel"' in HTML

    def test_compose_panel_has_wrapper_class(self):
        assert re.search(r'id="project-compose-panel"[^>]*class="[^"]*project-compose-panel', HTML)

    def test_textarea_exists(self):
        assert 'id="project-input"' in HTML

    def test_textarea_inside_compose_panel(self):
        panel_start = HTML.index('id="project-compose-panel"')
        textarea_pos = HTML.index('id="project-input"')
        assert textarea_pos > panel_start

    def test_controls_row_exists(self):
        assert 'class="project-compose-controls"' in HTML

    def test_link_select_exists(self):
        assert 'id="project-link-select"' in HTML

    def test_link_select_has_no_link_option(self):
        start = HTML.index('id="project-link-select"')
        block = HTML[start:start + 200]
        assert "No link" in block or "new thread" in block.lower()

    def test_cli_select_exists(self):
        assert 'id="project-cli-select"' in HTML

    def test_send_button_exists(self):
        assert 'id="btn-send-project-message"' in HTML

    def test_reply_banner_inside_compose_panel(self):
        panel_start = HTML.index('id="project-compose-panel"')
        banner_pos = HTML.index('id="project-reply-banner"')
        assert banner_pos > panel_start


# ---------------------------------------------------------------------------
# CSS — compose panel styles
# ---------------------------------------------------------------------------

class TestComposePanelCss:
    def test_compose_panel_class_defined(self):
        assert ".project-compose-panel" in CSS

    def test_compose_controls_class_defined(self):
        assert ".project-compose-controls" in CSS

    def test_link_select_css_defined(self):
        assert "#project-link-select" in CSS


# ---------------------------------------------------------------------------
# populateProjectLinkSelect
# ---------------------------------------------------------------------------

class TestPopulateProjectLinkSelect:
    def _fn_body(self):
        start = HTML.index("async function populateProjectLinkSelect")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "populateProjectLinkSelect" in HTML

    def test_fetches_project_messages(self):
        body = self._fn_body()
        assert re.search(r"/api/projects/.*messages", body)

    def test_filters_user_messages(self):
        body = self._fn_body()
        assert re.search(r"role.*user|user.*role", body)

    def test_truncates_label_at_60_chars(self):
        body = self._fn_body()
        assert "60" in body

    def test_resets_to_no_link_option(self):
        body = self._fn_body()
        assert re.search(r"No link|new thread", body, re.IGNORECASE)

    def test_sets_option_value_to_message_id(self):
        body = self._fn_body()
        assert "m.id" in body or "msg.id" in body


# ---------------------------------------------------------------------------
# setReplyContext — syncs link dropdown
# ---------------------------------------------------------------------------

class TestSetReplyContextSyncsDropdown:
    def _fn_body(self):
        start = HTML.index("function setReplyContext")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_sets_link_select_value(self):
        body = self._fn_body()
        assert "project-link-select" in body

    def test_sets_link_select_to_message_id(self):
        body = self._fn_body()
        assert re.search(r"linkSel\.value\s*=\s*messageId|project-link-select.*value.*messageId", body, re.DOTALL)


# ---------------------------------------------------------------------------
# sendProjectMessage — updated behavior
# ---------------------------------------------------------------------------

class TestSendProjectMessageCompose:
    def _fn_body(self):
        start = HTML.index("async function sendProjectMessage")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_reads_link_select_value(self):
        body = self._fn_body()
        assert "project-link-select" in body

    def test_uses_link_select_for_linked_message_id(self):
        body = self._fn_body()
        assert "linked_message_id" in body

    def test_includes_content_in_body(self):
        body = self._fn_body()
        assert re.search(r"body.*content|content.*body", body, re.DOTALL)

    def test_includes_role_in_body(self):
        body = self._fn_body()
        assert re.search(r"role.*user|body\.role", body)

    def test_includes_cli_used_when_set(self):
        body = self._fn_body()
        assert "cli_used" in body

    def test_resets_cli_select_after_send(self):
        body = self._fn_body()
        assert re.search(r"project-cli-select.*value\s*=\s*''|cliSel\.value\s*=\s*''", body, re.DOTALL)

    def test_loading_state_on_button(self):
        body = self._fn_body()
        assert re.search(r"sendBtn\.textContent|btn-send.*textContent|origBtnText", body)

    def test_restores_button_text_in_finally(self):
        body = self._fn_body()
        assert "origBtnText" in body

    def test_clears_reply_context(self):
        body = self._fn_body()
        assert "clearReplyContext" in body

    def test_refreshes_link_select_after_send(self):
        body = self._fn_body()
        assert "populateProjectLinkSelect" in body


# ---------------------------------------------------------------------------
# Ctrl+Enter shortcut
# ---------------------------------------------------------------------------

class TestCtrlEnterShortcut:
    def test_ctrl_enter_listener_exists(self):
        assert re.search(r"project-input.*keydown|keydown.*project-input", HTML, re.DOTALL)

    def test_ctrl_enter_calls_send(self):
        # Find the keydown listener wired to project-input
        kd_pos = HTML.index("'project-input').addEventListener('keydown'")
        block = HTML[kd_pos:kd_pos + 200]
        assert "ctrlKey" in block
        assert "sendProjectMessage" in block


# ---------------------------------------------------------------------------
# showProjectView — auto-focus and link select init
# ---------------------------------------------------------------------------

class TestShowProjectViewCompose:
    def _fn_body(self):
        start = HTML.index("function showProjectView")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_calls_populate_link_select(self):
        body = self._fn_body()
        assert "populateProjectLinkSelect" in body

    def test_auto_focuses_textarea(self):
        body = self._fn_body()
        assert re.search(r"project-input.*focus|focus.*project-input", body, re.DOTALL)

    def test_clears_reply_context_on_open(self):
        body = self._fn_body()
        assert "clearReplyContext" in body


# ---------------------------------------------------------------------------
# CLI select visibility (allow_cli_switch)
# ---------------------------------------------------------------------------

class TestCliSelectVisibility:
    def _fn_body(self):
        start = HTML.index("async function loadProjectMeta")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_cli_select_hidden_when_switch_disabled(self):
        body = self._fn_body()
        assert "allow_cli_switch" in body

    def test_cli_select_display_toggled(self):
        body = self._fn_body()
        assert re.search(r"cliSel\.style\.display|project-cli-select.*display", body, re.DOTALL)
