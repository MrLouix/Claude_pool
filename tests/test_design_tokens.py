"""Tests for Phase 1 — CSS Design Tokens in frontend/index.html."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "claude_pool" / "frontend" / "index.html"


def _load():
    return HTML_PATH.read_text(encoding="utf-8")


def _style_block(content):
    """Return the full text inside <style>...</style>."""
    m = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
    assert m, "No <style> block found"
    return m.group(1)


def _root_block(style):
    """Return text of the :root { ... } block."""
    m = re.search(r":root\s*\{([^}]+)\}", style, re.DOTALL)
    assert m, "No :root block found"
    return m.group(1)


def _non_root_css(style):
    """Return style text with the :root block removed."""
    return re.sub(r":root\s*\{[^}]+\}", "", style, count=1, flags=re.DOTALL)


# ── :root block presence and variables ────────────────────────────────────────

class TestRootBlock:
    REQUIRED_VARS = [
        # Brand
        "--color-brand-primary",
        "--color-brand-dark",
        "--color-brand-deep",
        # Semantic
        "--color-success",
        "--color-success-dark",
        "--color-success-bg",
        "--color-success-text",
        "--color-success-border",
        "--color-info",
        "--color-info-dark",
        "--color-info-bg",
        "--color-info-text",
        "--color-info-border",
        "--color-warning",
        "--color-warning-dark",
        "--color-warning-bg",
        "--color-warning-text",
        "--color-warning-border",
        "--color-danger",
        "--color-danger-dark",
        "--color-danger-bg",
        "--color-danger-text",
        "--color-purple",
        "--color-purple-bg",
        "--color-purple-text",
        # Neutrals
        "--color-surface",
        "--color-surface-alt",
        "--color-surface-hover",
        "--color-text-primary",
        "--color-text-secondary",
        "--color-text-muted",
        "--color-border",
        "--color-border-dark",
        "--color-code-bg",
        "--color-code-text",
        "--color-inline-code-bg",
        # Spacing
        "--space-1",
        "--space-2",
        "--space-3",
        "--space-4",
        "--space-5",
        "--space-6",
        "--space-8",
        "--space-10",
        "--space-12",
        # Radii
        "--radius-sm",
        "--radius-md",
        "--radius-lg",
        "--radius-xl",
        "--radius-2xl",
        "--radius-full",
        # Shadows
        "--shadow-sm",
        "--shadow-md",
        "--shadow-lg",
        "--shadow-hover",
        # Transitions
        "--transition-fast",
        "--transition-base",
        "--transition-slow",
        # Typography
        "--font-sans",
        "--font-mono",
    ]

    def test_root_block_exists(self):
        style = _style_block(_load())
        assert ":root" in style, ":root block not found in <style>"

    def test_root_block_at_top_of_style(self):
        """The :root block should appear before any other CSS rules."""
        style = _style_block(_load())
        root_pos = style.find(":root")
        # First occurrence of a class selector or element rule after style opens
        first_rule = re.search(r"\*\s*\{|body\s*\{|\.[\w-]+\s*\{", style)
        assert first_rule is not None
        assert root_pos < first_rule.start(), (
            ":root block should appear before other CSS rules"
        )

    def test_all_required_variables_defined(self):
        style = _style_block(_load())
        root = _root_block(style)
        missing = [v for v in self.REQUIRED_VARS if v not in root]
        assert not missing, f"Missing CSS variables in :root: {missing}"

    def test_root_variables_have_values(self):
        style = _style_block(_load())
        root = _root_block(style)
        # Each var should have a colon and a value
        for var in self.REQUIRED_VARS:
            m = re.search(re.escape(var) + r"\s*:\s*\S+", root)
            assert m, f"{var} has no value in :root"


# ── Typography utility classes ─────────────────────────────────────────────────

class TestTypographyClasses:
    EXPECTED = {
        ".text-xs":   "0.75rem",
        ".text-sm":   "0.875rem",
        ".text-base": "1rem",
        ".text-lg":   "1.125rem",
        ".text-xl":   "1.25rem",
        ".text-2xl":  "1.5rem",
        ".text-3xl":  "2rem",
    }

    def test_typography_classes_defined(self):
        style = _style_block(_load())
        missing = [cls for cls in self.EXPECTED if cls not in style]
        assert not missing, f"Missing typography classes: {missing}"

    def test_typography_class_values(self):
        style = _style_block(_load())
        for cls, expected_size in self.EXPECTED.items():
            pattern = re.escape(cls) + r"\s*\{[^}]*font-size:\s*" + re.escape(expected_size)
            assert re.search(pattern, style), (
                f"{cls} should have font-size: {expected_size}"
            )


# ── No banned hardcoded colors in CSS rules ───────────────────────────────────

class TestNoHardcodedColors:
    # These colors should have been replaced by CSS variables everywhere
    # outside the :root block
    BANNED_HEX = [
        "#10b981",  # -> var(--color-success)
        "#059669",  # -> var(--color-success-dark)
        "#dcfce7",  # -> var(--color-success-bg)
        "#166534",  # -> var(--color-success-text)
        "#a7f3d0",  # -> var(--color-success-border)
        "#3b82f6",  # -> var(--color-info)
        "#1e40af",  # -> var(--color-info-text)
        "#dbeafe",  # -> var(--color-info-bg)
        "#bfdbfe",  # -> var(--color-info-border)
        "#f59e0b",  # -> var(--color-warning)
        "#d97706",  # -> var(--color-warning-dark)
        "#fef3c7",  # -> var(--color-warning-bg)
        "#92400e",  # -> var(--color-warning-text)
        "#fde68a",  # -> var(--color-warning-border)
        "#ef4444",  # -> var(--color-danger)
        "#dc2626",  # -> var(--color-danger-dark)
        "#fee2e2",  # -> var(--color-danger-bg)
        "#991b1b",  # -> var(--color-danger-text)
        "#a855f7",  # -> var(--color-purple)
        "#f3e8ff",  # -> var(--color-purple-bg)
        "#6b21a8",  # -> var(--color-purple-text)
        "#fafafa",  # -> var(--color-surface-alt)
        "#f0f0ff",  # -> var(--color-surface-hover)
        "#1f2937",  # -> var(--color-code-bg)
        "#e5e7eb",  # -> var(--color-code-text)
        "#f3f4f6",  # -> var(--color-inline-code-bg)
    ]

    def test_no_banned_colors_outside_root(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        found = []
        for color in self.BANNED_HEX:
            if re.search(re.escape(color), non_root, re.IGNORECASE):
                found.append(color)
        assert not found, (
            f"Hardcoded colors still present outside :root block: {found}"
        )

    def test_no_background_white_in_css(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        matches = re.findall(r"background(?:-color)?:\s*white\b", non_root)
        assert not matches, (
            f"'background: white' still present {len(matches)} time(s) — "
            "replace with var(--color-surface)"
        )

    def test_no_raw_ffffff_outside_root(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        matches = re.findall(r"#ffffff\b", non_root, re.IGNORECASE)
        assert not matches, (
            f"#ffffff still present {len(matches)} time(s) outside :root"
        )

    def test_no_raw_eeeeee_or_eee_outside_root(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        matches = re.findall(r"#(?:eee(?:eee)?)\b", non_root, re.IGNORECASE)
        assert not matches, (
            f"#eee/#eeeeee still present {len(matches)} time(s) outside :root"
        )

    def test_no_raw_ddd_outside_root(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        matches = re.findall(r"#(?:ddd(?:ddd)?)\b", non_root, re.IGNORECASE)
        assert not matches, (
            f"#ddd/#dddddd still present {len(matches)} time(s) outside :root"
        )


# ── Border-radius tokens ───────────────────────────────────────────────────────

class TestBorderRadiusTokens:
    REPLACED_VALUES = ["3px", "5px", "8px", "10px", "12px", "20px"]

    def test_border_radius_tokens_used(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        # Verify at least some var(--radius-*) references exist
        assert "var(--radius-md)" in non_root or "var(--radius-sm)" in non_root, (
            "No var(--radius-*) tokens found in non-root CSS"
        )

    def test_border_radius_mapped_px_replaced(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        for px in self.REPLACED_VALUES:
            pattern = rf"border-radius:\s*{re.escape(px)}\b"
            matches = re.findall(pattern, non_root)
            assert not matches, (
                f"border-radius: {px} still present {len(matches)} time(s) — "
                f"should be var(--radius-*)"
            )


# ── Box-shadow tokens ─────────────────────────────────────────────────────────

class TestShadowTokens:
    def test_shadow_md_token_used(self):
        style = _style_block(_load())
        assert "var(--shadow-md)" in style, "var(--shadow-md) not found in style"

    def test_shadow_lg_token_used(self):
        style = _style_block(_load())
        assert "var(--shadow-lg)" in style, "var(--shadow-lg) not found in style"

    def test_raw_shadow_md_replaced(self):
        """The literal 0 4px 6px rgba(0,0,0,0.1) pattern should be gone."""
        style = _style_block(_load())
        non_root = _non_root_css(style)
        pattern = r"box-shadow:\s*0\s+4px\s+6px\s+rgba\(0,\s*0,\s*0,\s*0?\.1\)"
        matches = re.findall(pattern, non_root)
        assert not matches, (
            f"Raw box-shadow: 0 4px 6px rgba(0,0,0,0.1) still present "
            f"{len(matches)} time(s)"
        )

    def test_raw_shadow_lg_replaced(self):
        style = _style_block(_load())
        non_root = _non_root_css(style)
        pattern = r"box-shadow:\s*0\s+12px\s+40px\s+rgba\(0,\s*0,\s*0,\s*0?\.2\)"
        matches = re.findall(pattern, non_root)
        assert not matches, (
            f"Raw box-shadow: 0 12px 40px rgba(0,0,0,0.2) still present "
            f"{len(matches)} time(s)"
        )


# ── Body gradient preserved ───────────────────────────────────────────────────

class TestBodyGradient:
    def test_body_gradient_preserved_with_literal_colors(self):
        """Body gradient must still use literal hex (not var()) per spec."""
        style = _style_block(_load())
        assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" in style, (
            "Body gradient should still use literal #667eea and #764ba2"
        )
