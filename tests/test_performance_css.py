"""Tests for Phase 4 — Animation & Performance CSS in frontend/css/*.css."""
import re
from pathlib import Path

_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"


def _style():
    combined = ""
    for name in ["tokens.css", "layout.css", "components.css"]:
        combined += (_CSS_DIR / name).read_text(encoding="utf-8") + "\n"
    return combined


# ── prefers-reduced-motion ────────────────────────────────────────────────────

class TestPrefersReducedMotion:
    def test_media_query_present(self):
        assert "@media (prefers-reduced-motion: reduce)" in _style(), (
            "@media (prefers-reduced-motion: reduce) block is missing"
        )

    def test_animation_duration_disabled(self):
        assert "animation-duration: 0.01ms" in _style(), (
            "animation-duration: 0.01ms not found inside reduced-motion block"
        )

    def test_animation_iteration_count_disabled(self):
        assert "animation-iteration-count: 1" in _style(), (
            "animation-iteration-count: 1 not found inside reduced-motion block"
        )

    def test_transition_duration_disabled(self):
        assert "transition-duration: 0.01ms" in _style(), (
            "transition-duration: 0.01ms not found inside reduced-motion block"
        )

    def test_important_flags_present(self):
        style = _style()
        # Verify the three !important overrides are inside the reduced-motion block
        reduced_motion_block = re.search(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.+?)\}",
            style,
            re.DOTALL,
        )
        assert reduced_motion_block, "Could not extract prefers-reduced-motion block"
        block_content = reduced_motion_block.group(1)
        assert "!important" in block_content, (
            "!important flags missing from prefers-reduced-motion rules"
        )

    def test_reduced_motion_block_targets_all_elements(self):
        style = _style()
        reduced_motion_block = re.search(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.+?)\}",
            style,
            re.DOTALL,
        )
        assert reduced_motion_block
        block_content = reduced_motion_block.group(1)
        # Should target *, *::before, *::after
        assert "*" in block_content, (
            "prefers-reduced-motion should target * selector"
        )


# ── No transition: all anti-pattern ──────────────────────────────────────────

class TestNoTransitionAll:
    def test_no_transition_all_in_css(self):
        style = _style()
        matches = re.findall(r"transition:\s*all\b", style)
        assert not matches, (
            f"'transition: all' still present {len(matches)} time(s) — "
            "replace with explicit property lists"
        )

    def test_explicit_transition_properties_used(self):
        style = _style()
        # At least one rule should now use explicit transition tokens
        assert "var(--transition-base)" in style or "var(--transition-slow)" in style, (
            "No var(--transition-base) or var(--transition-slow) tokens found — "
            "transition: all replacements may not have applied"
        )

    def test_button_uses_explicit_transition(self):
        style = _style()
        # Find the standalone `button { }` rule (not `.something button { }`)
        # It appears as whitespace-only before `button` on the same line.
        button_block = re.search(
            r"(?:^|\n)\s{0,12}button\s*\{([^}]+)\}", style, re.DOTALL
        )
        assert button_block, "No standalone button { } rule found"
        block = button_block.group(1)
        assert "transition:" in block, (
            "standalone button rule has no transition property"
        )
        transition_match = re.search(r"transition:[^;]+", block)
        assert transition_match and "all" not in transition_match.group(), (
            "standalone button rule still uses 'transition: all'"
        )


# ── Safe areas & overflow ─────────────────────────────────────────────────────

class TestSafeAreasAndOverflow:
    def test_body_overflow_x_hidden(self):
        style = _style()
        body_block = re.search(r"\bbody\s*\{([^}]+)\}", style, re.DOTALL)
        assert body_block, "No body { } rule found"
        assert "overflow-x: hidden" in body_block.group(1), (
            "body rule missing overflow-x: hidden"
        )

    def test_container_safe_area_left(self):
        style = _style()
        assert "env(safe-area-inset-left)" in style, (
            "env(safe-area-inset-left) not found in style — "
            ".container is missing safe area insets"
        )

    def test_container_safe_area_right(self):
        style = _style()
        assert "env(safe-area-inset-right)" in style, (
            "env(safe-area-inset-right) not found in style — "
            ".container is missing safe area insets"
        )

    def test_container_uses_max_function(self):
        style = _style()
        container_block = re.search(r"\.container\s*\{([^}]+)\}", style, re.DOTALL)
        assert container_block, "No .container { } rule found"
        block = container_block.group(1)
        assert "max(" in block, (
            ".container should use max(20px, env(safe-area-inset-*)) "
            "to fall back gracefully on non-notched devices"
        )


# ── Overscroll containment ────────────────────────────────────────────────────

class TestOverscrollContainment:
    def test_overscroll_behavior_present(self):
        assert "overscroll-behavior: contain" in _style(), (
            "overscroll-behavior: contain not found — "
            "add it to .message-thread, .modal-body, .log-container, .task-list"
        )

    def test_message_thread_targeted(self):
        style = _style()
        # Find the overscroll rule and check .message-thread is in it
        overscroll_selector = re.search(
            r"([^{]+)\{[^}]*overscroll-behavior:\s*contain[^}]*\}",
            style,
            re.DOTALL,
        )
        assert overscroll_selector, "Could not find rule with overscroll-behavior: contain"
        selector_text = overscroll_selector.group(1)
        assert ".message-thread" in selector_text, (
            ".message-thread not listed in overscroll-behavior: contain rule"
        )

    def test_modal_body_targeted(self):
        style = _style()
        overscroll_selector = re.search(
            r"([^{]+)\{[^}]*overscroll-behavior:\s*contain[^}]*\}",
            style,
            re.DOTALL,
        )
        assert overscroll_selector
        assert ".modal-body" in overscroll_selector.group(1), (
            ".modal-body not listed in overscroll-behavior: contain rule"
        )


# ── Touch optimisation ────────────────────────────────────────────────────────

class TestTouchOptimisation:
    def test_touch_action_manipulation(self):
        assert "touch-action: manipulation" in _style(), (
            "touch-action: manipulation not found — "
            "add it to button, .dir-item, .message-bubble, .task-item"
        )

    def test_webkit_tap_highlight_transparent(self):
        assert "-webkit-tap-highlight-color: transparent" in _style(), (
            "-webkit-tap-highlight-color: transparent not found"
        )

    def test_button_targeted_for_touch(self):
        style = _style()
        touch_selector = re.search(
            r"([^{]+)\{[^}]*touch-action:\s*manipulation[^}]*\}",
            style,
            re.DOTALL,
        )
        assert touch_selector, "Could not find rule with touch-action: manipulation"
        selector_text = touch_selector.group(1)
        assert "button" in selector_text, (
            "button not listed in touch-action: manipulation rule"
        )
