"""Tests for Phase 2.4 — Focus Visible Styles in frontend/index.html."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"


def _style():
    content = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
    assert m, "No <style> block found"
    return m.group(1)


# ── :focus-visible rules ──────────────────────────────────────────────────────

class TestFocusVisibleRules:
    def test_global_focus_visible_present(self):
        style = _style()
        assert ":focus-visible" in style, (
            ":focus-visible selector not found in <style> — "
            "keyboard users have no visible focus indicator"
        )

    def test_global_focus_visible_has_outline(self):
        style = _style()
        # The bare :focus-visible rule (not button/input/etc.) should set outline
        bare_rule = re.search(
            r"(?<![a-z\-]):focus-visible\s*\{([^}]+)\}",
            style,
            re.DOTALL,
        )
        assert bare_rule, "No bare :focus-visible { } rule found"
        block = bare_rule.group(1)
        assert "outline:" in block, (
            "bare :focus-visible rule has no outline property"
        )

    def test_button_focus_visible_present(self):
        style = _style()
        assert "button:focus-visible" in style, (
            "button:focus-visible selector not found — "
            "buttons have no keyboard focus indicator"
        )

    def test_button_focus_visible_has_box_shadow(self):
        style = _style()
        btn_rule = re.search(
            r"button:focus-visible\s*\{([^}]+)\}",
            style,
            re.DOTALL,
        )
        assert btn_rule, "button:focus-visible { } rule not found"
        block = btn_rule.group(1)
        assert "box-shadow:" in block, (
            "button:focus-visible rule should use box-shadow ring instead of outline"
        )

    def test_input_focus_visible_present(self):
        style = _style()
        assert "input:focus-visible" in style, (
            "input:focus-visible selector not found"
        )

    def test_textarea_focus_visible_present(self):
        style = _style()
        assert "textarea:focus-visible" in style, (
            "textarea:focus-visible selector not found"
        )

    def test_select_focus_visible_present(self):
        style = _style()
        assert "select:focus-visible" in style, (
            "select:focus-visible selector not found"
        )

    def test_input_focus_visible_has_border_color(self):
        style = _style()
        # The input/textarea/select focus rule should set border-color
        input_block = re.search(
            r"input:focus-visible[^{]*\{([^}]+)\}",
            style,
            re.DOTALL,
        )
        assert input_block, "input:focus-visible rule block not found"
        assert "border-color:" in input_block.group(1), (
            "input:focus-visible should set border-color to brand primary"
        )

    def test_dir_item_focus_visible_present(self):
        style = _style()
        assert ".dir-item:focus-visible" in style, (
            ".dir-item:focus-visible selector not found — "
            "directory items have no keyboard focus indicator"
        )

    def test_task_item_focus_visible_present(self):
        style = _style()
        assert ".task-item:focus-visible" in style, (
            ".task-item:focus-visible selector not found"
        )

    def test_message_bubble_focus_visible_present(self):
        style = _style()
        assert ".message-bubble:focus-visible" in style, (
            ".message-bubble:focus-visible selector not found"
        )

    def test_focus_visible_uses_brand_token(self):
        style = _style()
        # At least the global :focus-visible rule should reference the brand token
        bare_rule = re.search(
            r"(?<![a-z\-]):focus-visible\s*\{([^}]+)\}",
            style,
            re.DOTALL,
        )
        assert bare_rule
        assert "var(--color-brand-primary)" in bare_rule.group(1), (
            ":focus-visible should use var(--color-brand-primary) for consistency"
        )

    def test_focus_visible_rules_before_component_rules(self):
        """Focus rules should come early in the stylesheet (after :root/typography)."""
        style = _style()
        fv_pos   = style.find(":focus-visible")
        body_pos = style.find("body {") if "body {" in style else style.find("body\n")
        assert fv_pos != -1 and body_pos != -1
        assert fv_pos < body_pos, (
            ":focus-visible rules should appear before component rules like body { }"
        )


# ── No bare outline:none suppression ─────────────────────────────────────────

class TestNoOutlineSuppression:
    def test_no_global_outline_none(self):
        style = _style()
        # Detect bare * { outline: none } or *{outline:0} patterns
        matches = re.findall(
            r"\*\s*\{[^}]*outline\s*:\s*(none|0)\b[^}]*\}",
            style,
            re.DOTALL,
        )
        assert not matches, (
            "Global outline:none found — this kills all keyboard focus indicators. "
            "Remove it or scope to :not(:focus-visible)"
        )

    def test_no_button_outline_none_without_focus_visible(self):
        style = _style()
        # A bare `button { outline: none }` without a corresponding
        # button:focus-visible rule would be an accessibility regression.
        bare_btn_outline_none = re.findall(
            r"(?:^|\n)\s{0,12}button\s*\{[^}]*outline\s*:\s*(none|0)\b[^}]*\}",
            style,
            re.DOTALL,
        )
        if bare_btn_outline_none:
            # Only allowed if button:focus-visible also exists
            assert "button:focus-visible" in style, (
                "button { outline: none } found but button:focus-visible is missing — "
                "buttons would have no focus indicator"
            )

    def test_no_input_outline_none_without_focus_visible(self):
        style = _style()
        bare_input_outline_none = re.findall(
            r"(?:^|\n)\s{0,12}input\s*\{[^}]*outline\s*:\s*(none|0)\b[^}]*\}",
            style,
            re.DOTALL,
        )
        if bare_input_outline_none:
            assert "input:focus-visible" in style, (
                "input { outline: none } found but input:focus-visible is missing"
            )


# ── Minimum touch target sizes ────────────────────────────────────────────────

class TestTouchTargetSizes:
    def test_min_height_2_75rem_present(self):
        style = _style()
        assert "min-height: 2.75rem" in style, (
            "min-height: 2.75rem not found — "
            "buttons may be too small for touch targets (WCAG 2.5.5 requires 44×44px)"
        )

    def test_button_targeted_for_min_height(self):
        style = _style()
        min_height_rule = re.search(
            r"([^{]+)\{[^}]*min-height:\s*2\.75rem[^}]*\}",
            style,
            re.DOTALL,
        )
        assert min_height_rule, "Could not find rule with min-height: 2.75rem"
        selector = min_height_rule.group(1)
        assert "button" in selector, (
            "button not listed in the min-height: 2.75rem rule"
        )

    def test_btn_instant_retry_targeted(self):
        style = _style()
        min_height_rule = re.search(
            r"([^{]+)\{[^}]*min-height:\s*2\.75rem[^}]*\}",
            style,
            re.DOTALL,
        )
        assert min_height_rule, "Could not find rule with min-height: 2.75rem"
        selector = min_height_rule.group(1)
        assert ".btn-instant-retry" in selector, (
            ".btn-instant-retry not in min-height: 2.75rem selector"
        )
