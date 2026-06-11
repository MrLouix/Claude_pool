"""Frontend tests for Phase 4 Step 5: Promote button for manual priority escalation."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
HTML = FRONTEND.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CSS: .btn-promote class
# ---------------------------------------------------------------------------

class TestPromoteButtonCss:
    def test_btn_promote_class_defined(self):
        assert ".btn-promote" in HTML

    def test_btn_promote_has_border(self):
        assert re.search(r"\.btn-promote\s*\{[^}]*border", HTML, re.DOTALL)

    def test_btn_promote_has_cursor_pointer(self):
        assert re.search(r"\.btn-promote\s*\{[^}]*cursor\s*:\s*pointer", HTML, re.DOTALL)

    def test_btn_promote_disabled_state_defined(self):
        assert re.search(r"\.btn-promote:disabled", HTML)


# ---------------------------------------------------------------------------
# JS: promoteMessage function
# ---------------------------------------------------------------------------

class TestPromoteMessageFunction:
    def _fn_body(self):
        start = HTML.index("async function promoteMessage")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "async function promoteMessage" in HTML

    def test_calls_promote_api_endpoint(self):
        assert "/promote" in self._fn_body()

    def test_uses_post_method(self):
        assert re.search(r"method.*POST|POST.*method", self._fn_body(), re.DOTALL)

    def test_reads_priority_from_response(self):
        assert "priority" in self._fn_body()

    def test_disables_button_at_max_priority(self):
        body = self._fn_body()
        # Must check for priority >= 5 or === 5 and hide/remove the button
        assert re.search(r"[><=]=?\s*5|5\s*[<>=]", body)

    def test_updates_badge_class_in_dom(self):
        body = self._fn_body()
        assert "priority-badge" in body
        assert "className" in body

    def test_updates_badge_text(self):
        body = self._fn_body()
        assert "textContent" in body

    def test_error_handling_present(self):
        body = self._fn_body()
        assert re.search(r"catch|Error", body)

    def test_error_resets_button_text(self):
        body = self._fn_body()
        assert "setTimeout" in body or "origText" in body

    def test_accepts_project_id_param(self):
        # Function signature must include projectId
        sig_line = HTML[HTML.index("async function promoteMessage"):HTML.index("async function promoteMessage") + 100]
        assert "projectId" in sig_line

    def test_accepts_message_id_param(self):
        sig_line = HTML[HTML.index("async function promoteMessage"):HTML.index("async function promoteMessage") + 100]
        assert "messageId" in sig_line

    def test_accepts_button_el_param(self):
        sig_line = HTML[HTML.index("async function promoteMessage"):HTML.index("async function promoteMessage") + 100]
        assert "buttonEl" in sig_line

    def test_accepts_badge_el_param(self):
        sig_line = HTML[HTML.index("async function promoteMessage"):HTML.index("async function promoteMessage") + 100]
        assert "badgeEl" in sig_line


# ---------------------------------------------------------------------------
# JS: renderProjectMessages — promote button in template
# ---------------------------------------------------------------------------

class TestRenderProjectMessagesPromote:
    def _fn_body(self):
        start = HTML.index("function renderProjectMessages")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_promote_button_rendered(self):
        assert re.search(r"Promote|promote", self._fn_body())

    def test_promoteMessage_called_on_click(self):  # noqa: N802
        assert "promoteMessage" in self._fn_body()

    def test_promote_button_only_shown_when_priority_lt_5(self):
        body = self._fn_body()
        # There must be a conditional involving priority < 5 or priority !== 5
        assert re.search(r"priority\s*[<>!=]=?\s*5|5\s*[<>!=]=?\s*priority", body)

    def test_promote_button_omitted_for_assistant_messages(self):
        body = self._fn_body()
        # Promote button must be conditional on role === 'user'
        assert re.search(r"role.*user.*Promote|Promote.*role.*user|role.*user.*promoteMessage", body, re.DOTALL)

    def test_promote_button_has_btn_promote_class(self):
        assert "btn-promote" in self._fn_body()

    def test_promote_button_passes_message_id(self):
        body = self._fn_body()
        assert re.search(r"m\.id", body)

    def test_promote_api_url_contains_promote(self):
        assert "/promote" in HTML


# ---------------------------------------------------------------------------
# Integration: promote endpoint URL pattern in JS
# ---------------------------------------------------------------------------

class TestPromoteEndpointUrl:
    def test_api_projects_messages_promote_pattern(self):
        assert re.search(r"/api/projects/[^/]*messages/[^/]*/promote", HTML) or \
               re.search(r"promote.*api/projects|api/projects.*promote", HTML, re.DOTALL)

    def test_promote_url_uses_project_id_interpolation(self):
        assert re.search(r"\$\{projectId\}.*promote|promote.*\$\{projectId\}", HTML, re.DOTALL)

    def test_promote_url_uses_message_id_interpolation(self):
        assert re.search(r"\$\{messageId\}.*promote|promote.*\$\{messageId\}", HTML, re.DOTALL)
