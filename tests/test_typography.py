"""Tests for Phase 5 — Typography & Content Improvements in frontend/css/*.css."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"


def _content():
    return HTML_PATH.read_text(encoding="utf-8")


def _style():
    combined = ""
    for name in ["tokens.css", "layout.css", "components.css"]:
        combined += (_CSS_DIR / name).read_text(encoding="utf-8") + "\n"
    return combined


def _html_body():
    """Return everything after </head> (body + JS)."""
    content = _content()
    idx = content.find("</head>")
    return content[idx:] if idx != -1 else content


# ── 5.1 Tabular numbers ───────────────────────────────────────────────────────

class TestTabularNumbers:
    def test_tabular_nums_present(self):
        assert "font-variant-numeric: tabular-nums" in _style(), (
            "font-variant-numeric: tabular-nums not found in <style>"
        )

    def test_stat_card_number_targeted(self):
        style = _style()
        tabular_rule = re.search(
            r"([^{]+)\{[^}]*font-variant-numeric:\s*tabular-nums[^}]*\}",
            style, re.DOTALL,
        )
        assert tabular_rule, "Could not find font-variant-numeric: tabular-nums rule"
        selector = tabular_rule.group(1)
        assert ".stat-card" in selector, (
            ".stat-card not targeted by tabular-nums rule"
        )

    def test_log_line_targeted(self):
        style = _style()
        tabular_rule = re.search(
            r"([^{]+)\{[^}]*font-variant-numeric:\s*tabular-nums[^}]*\}",
            style, re.DOTALL,
        )
        assert tabular_rule
        assert ".log-line" in tabular_rule.group(1), (
            ".log-line not targeted by tabular-nums rule"
        )

    def test_td_duration_targeted(self):
        style = _style()
        tabular_rule = re.search(
            r"([^{]+)\{[^}]*font-variant-numeric:\s*tabular-nums[^}]*\}",
            style, re.DOTALL,
        )
        assert tabular_rule
        assert "#td-duration" in tabular_rule.group(1), (
            "#td-duration not targeted by tabular-nums rule"
        )


# ── 5.2 Text-wrap balance ─────────────────────────────────────────────────────

class TestTextWrapBalance:
    def test_text_wrap_balance_present(self):
        assert "text-wrap: balance" in _style(), (
            "text-wrap: balance not found in <style>"
        )

    def test_header_h1_targeted(self):
        style = _style()
        balance_rule = re.search(
            r"([^{]+)\{[^}]*text-wrap:\s*balance[^}]*\}",
            style, re.DOTALL,
        )
        assert balance_rule, "Could not find text-wrap: balance rule"
        assert ".header h1" in balance_rule.group(1), (
            ".header h1 not targeted by text-wrap: balance rule"
        )

    def test_stat_card_h3_targeted(self):
        style = _style()
        balance_rules = re.findall(
            r"([^{]+)\{[^}]*text-wrap:\s*balance[^}]*\}",
            style, re.DOTALL,
        )
        assert balance_rules, "Could not find any text-wrap: balance rule"
        assert any(".stat-card h3" in sel for sel in balance_rules), (
            ".stat-card h3 not targeted by text-wrap: balance rule"
        )


# ── 5.3 Text overflow ─────────────────────────────────────────────────────────

class TestTextOverflow:
    def test_text_overflow_ellipsis_present(self):
        assert "text-overflow: ellipsis" in _style(), (
            "text-overflow: ellipsis not found in <style>"
        )

    def _ellipsis_rules(self, style):
        """Return list of (selector, body) for every rule containing text-overflow: ellipsis."""
        return re.findall(
            r"([^{}]+)\{([^}]*text-overflow:\s*ellipsis[^}]*)\}",
            style, re.DOTALL,
        )

    def test_task_prompt_gets_ellipsis(self):
        style = _style()
        rules = self._ellipsis_rules(style)
        assert rules, "No rule with text-overflow: ellipsis found"
        selectors = " ".join(sel for sel, _ in rules)
        assert ".task-prompt" in selectors, (
            ".task-prompt not targeted by any text-overflow: ellipsis rule"
        )

    def test_message_prompt_gets_ellipsis(self):
        style = _style()
        rules = self._ellipsis_rules(style)
        selectors = " ".join(sel for sel, _ in rules)
        assert ".message-prompt" in selectors, (
            ".message-prompt not targeted by any text-overflow: ellipsis rule"
        )

    def test_task_id_gets_ellipsis(self):
        style = _style()
        rules = self._ellipsis_rules(style)
        selectors = " ".join(sel for sel, _ in rules)
        assert ".task-id" in selectors, (
            ".task-id not targeted by any text-overflow: ellipsis rule"
        )

    def test_ellipsis_rule_has_white_space_nowrap(self):
        """white-space: nowrap is required for ellipsis to work."""
        style = _style()
        rules = self._ellipsis_rules(style)
        # The task-prompt rule must also have white-space: nowrap
        task_prompt_rules = [(sel, body) for sel, body in rules if ".task-prompt" in sel]
        assert task_prompt_rules, ".task-prompt ellipsis rule not found"
        _, body = task_prompt_rules[0]
        assert "white-space: nowrap" in body, (
            ".task-prompt ellipsis rule is missing white-space: nowrap"
        )

    def test_task_info_has_min_width_zero(self):
        style = _style()
        task_info = re.search(r"\.task-info\s*\{([^}]+)\}", style, re.DOTALL)
        assert task_info, ".task-info rule not found"
        assert "min-width: 0" in task_info.group(1), (
            ".task-info is missing min-width: 0 — flex truncation won't work"
        )

    def test_message_info_has_min_width_zero(self):
        style = _style()
        assert ".message-info" in style, ".message-info rule not found in style"
        msg_info = re.search(r"\.message-info\s*\{([^}]+)\}", style, re.DOTALL)
        assert msg_info, ".message-info rule not found"
        assert "min-width: 0" in msg_info.group(1), (
            ".message-info is missing min-width: 0"
        )


# ── 5.4 Empty state ───────────────────────────────────────────────────────────

class TestEmptyState:
    def test_empty_state_padding_uses_token(self):
        style = _style()
        empty_rule = re.search(r"\.empty-state\s*\{([^}]+)\}", style, re.DOTALL)
        assert empty_rule, ".empty-state CSS rule not found"
        block = empty_rule.group(1)
        assert "var(--space-12)" in block, (
            ".empty-state padding should use var(--space-12) token, not raw px"
        )

    def test_empty_state_has_font_size(self):
        style = _style()
        empty_rule = re.search(r"\.empty-state\s*\{([^}]+)\}", style, re.DOTALL)
        assert empty_rule
        assert "font-size:" in empty_rule.group(1), (
            ".empty-state rule should declare font-size"
        )

    def test_empty_state_has_line_height(self):
        style = _style()
        empty_rule = re.search(r"\.empty-state\s*\{([^}]+)\}", style, re.DOTALL)
        assert empty_rule
        assert "line-height:" in empty_rule.group(1), (
            ".empty-state rule should declare line-height"
        )

    def test_empty_state_html_elements_have_meaningful_text(self):
        """Every static .empty-state div in the HTML body should have >5 chars."""
        html_body = _html_body()
        matches = re.findall(
            r'<div class="empty-state">([^<]+)<',
            html_body,
        )
        assert matches, "No .empty-state elements found in HTML body"
        short = [t for t in matches if len(t.strip()) <= 5]
        assert not short, (
            f"Empty-state elements with generic/short text: {short}"
        )

    def test_empty_state_count(self):
        """There should be at least 3 empty-state elements (tasks, chats, messages)."""
        html_body = _html_body()
        matches = re.findall(r'class="empty-state"', html_body)
        assert len(matches) >= 3, (
            f"Expected ≥3 .empty-state elements, found {len(matches)}"
        )


# ── 5.5 Font size rem ─────────────────────────────────────────────────────────

class TestFontSizeRem:
    BANNED_PX = ["14px", "12px", "11px", "13px", "16px", "18px"]

    def test_no_font_size_14px_in_css(self):
        style = _style()
        matches = re.findall(r"font-size:\s*14px\b", style)
        assert not matches, (
            f"font-size: 14px still present {len(matches)} time(s) in CSS — "
            "should be 0.875rem"
        )

    def test_no_font_size_12px_in_css(self):
        style = _style()
        matches = re.findall(r"font-size:\s*12px\b", style)
        assert not matches, (
            f"font-size: 12px still present {len(matches)} time(s) in CSS — "
            "should be 0.75rem"
        )

    def test_no_font_size_11px_in_css(self):
        style = _style()
        matches = re.findall(r"font-size:\s*11px\b", style)
        assert not matches, (
            f"font-size: 11px still present {len(matches)} time(s) in CSS — "
            "should be 0.6875rem"
        )

    def test_no_font_size_13px_in_css(self):
        style = _style()
        matches = re.findall(r"font-size:\s*13px\b", style)
        assert not matches, (
            f"font-size: 13px still present {len(matches)} time(s) in CSS — "
            "should be 0.8125rem"
        )

    def test_rem_values_present(self):
        style = _style()
        assert "0.875rem" in style, "0.875rem not found — 14px conversion missing"
        assert "0.75rem" in style, "0.75rem not found — 12px conversion missing"
