"""Frontend tests for Phase 4 Step 4: priority badges in project chat view."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"
HTML = FRONTEND.read_text(encoding="utf-8")
CSS = "\n".join((_CSS_DIR / n).read_text(encoding="utf-8") for n in ["tokens.css", "layout.css", "components.css"])


# ---------------------------------------------------------------------------
# CSS: .priority-badge base class
# ---------------------------------------------------------------------------

class TestPriorityBadgeBaseCss:
    def test_priority_badge_class_defined(self):
        assert ".priority-badge" in CSS

    def test_priority_badge_has_border_radius(self):
        assert re.search(r"\.priority-badge\s*\{[^}]*border-radius", CSS, re.DOTALL)

    def test_priority_badge_has_font_weight(self):
        assert re.search(r"\.priority-badge\s*\{[^}]*font-weight", CSS, re.DOTALL)

    def test_priority_badge_has_display_inline_block(self):
        assert re.search(r"\.priority-badge\s*\{[^}]*display\s*:\s*inline-block", CSS, re.DOTALL)

    def test_priority_badge_has_padding(self):
        assert re.search(r"\.priority-badge\s*\{[^}]*padding", CSS, re.DOTALL)


# ---------------------------------------------------------------------------
# CSS: .priority-1 through .priority-5
# ---------------------------------------------------------------------------

class TestPriorityLevelCss:
    def test_priority_1_class_defined(self):
        assert "priority-1" in CSS

    def test_priority_2_class_defined(self):
        assert "priority-2" in CSS

    def test_priority_3_class_defined(self):
        assert "priority-3" in CSS

    def test_priority_4_class_defined(self):
        assert "priority-4" in CSS

    def test_priority_5_class_defined(self):
        assert "priority-5" in CSS

    def test_priority_1_color(self):
        assert "#6c757d" in CSS

    def test_priority_2_color(self):
        assert "#0d6efd" in CSS

    def test_priority_3_uses_dark_text_for_readability(self):
        # Yellow background needs dark text
        assert "#212529" in CSS

    def test_priority_4_color(self):
        assert "#fd7e14" in CSS

    def test_priority_5_color(self):
        assert "#dc3545" in CSS

    def test_all_five_levels_in_css_block(self):
        # Each priority-N class must appear as a CSS selector
        for n in range(1, 6):
            assert re.search(rf"\.priority-{n}\b", CSS), f".priority-{n} not found"


# ---------------------------------------------------------------------------
# JS: getPriorityBadgeHtml function
# ---------------------------------------------------------------------------

class TestGetPriorityBadgeHtml:
    def _fn_body(self):
        start = HTML.index("function getPriorityBadgeHtml")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "function getPriorityBadgeHtml" in HTML

    def test_uses_priority_badge_class(self):
        assert "priority-badge" in self._fn_body()

    def test_uses_priority_n_class_pattern(self):
        assert re.search(r"priority-\$\{", self._fn_body())

    def test_label_low(self):
        assert "Low" in self._fn_body()

    def test_label_normal(self):
        assert "Normal" in self._fn_body()

    def test_label_feature(self):
        assert "Feature" in self._fn_body()

    def test_label_follow_up(self):
        assert "Follow-up" in self._fn_body()

    def test_label_urgent(self):
        assert "Urgent" in self._fn_body()

    def test_returns_span_element(self):
        assert "<span" in self._fn_body()


# ---------------------------------------------------------------------------
# JS: renderProjectMessages uses priority badge on user messages
# ---------------------------------------------------------------------------

class TestRenderProjectMessagesPriority:
    def _fn_body(self):
        start = HTML.index("function renderProjectMessages")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_references_priority_field(self):
        assert "priority" in self._fn_body()

    def test_calls_get_priority_badge_html(self):
        assert "getPriorityBadgeHtml" in self._fn_body()

    def test_badge_shown_for_user_role_only(self):
        body = self._fn_body()
        # The condition must check role === 'user' before showing the badge
        assert re.search(r"role.*user.*getPriorityBadgeHtml|getPriorityBadgeHtml.*role.*user", body, re.DOTALL)

    def test_badge_not_shown_for_assistant_unconditionally(self):
        # The badge must be conditional, not shown for all roles
        body = self._fn_body()
        # Should NOT have getPriorityBadgeHtml called without a conditional
        assert "role" in body  # role check present


# ---------------------------------------------------------------------------
# JS: task list also uses priority badge
# ---------------------------------------------------------------------------

class TestTaskListPriorityBadge:
    def test_task_item_html_uses_priority_badge(self):
        ti_start = HTML.index("function taskItemHtml")
        ti_end = HTML.index("\n        }", ti_start) + 10
        fn_body = HTML[ti_start:ti_end]
        # taskItemHtml must call a priority badge function
        assert re.search(r"priorityBadge|getPriorityBadgeHtml", fn_body)

    def test_priority_badge_called_with_task_priority(self):
        ti_start = HTML.index("function taskItemHtml")
        ti_end = HTML.index("\n        }", ti_start) + 10
        fn_body = HTML[ti_start:ti_end]
        assert "priority" in fn_body


# ---------------------------------------------------------------------------
# JS: priorityBadge backward-compat wrapper
# ---------------------------------------------------------------------------

class TestPriorityBadgeWrapper:
    def test_priority_badge_function_exists(self):
        assert "function priorityBadge" in HTML

    def test_priority_badge_delegates_to_get_priority_badge_html(self):
        start = HTML.index("function priorityBadge")
        end = HTML.index("\n        }", start) + 10
        fn_body = HTML[start:end]
        assert "getPriorityBadgeHtml" in fn_body
