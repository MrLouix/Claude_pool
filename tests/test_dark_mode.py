"""Tests for Phase 3 — Dark Mode via prefers-color-scheme in frontend/index.html."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"


def _html():
    return HTML_PATH.read_text(encoding="utf-8")


def _head():
    content = _html()
    m = re.search(r"<head>(.*?)</head>", content, re.DOTALL)
    assert m, "No <head> block found"
    return m.group(1)


def _style():
    content = _html()
    m = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
    assert m, "No <style> block found"
    return m.group(1)


def _dark_block():
    """Return the contents of the prefers-color-scheme: dark media query."""
    style = _style()
    m = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{(.+)\}\s*$",
        style, re.DOTALL
    )
    assert m, "@media (prefers-color-scheme: dark) block not found in <style>"
    return m.group(1)


# ── 3.1 Dark media query present ─────────────────────────────────────────────

class TestDarkMediaQuery:
    def test_dark_media_query_present(self):
        style = _style()
        assert "@media (prefers-color-scheme: dark)" in style, (
            "@media (prefers-color-scheme: dark) block is missing from <style>"
        )

    def test_dark_block_overrides_css_variables(self):
        block = _dark_block()
        var_count = len(re.findall(r"--color-\w+", block))
        assert var_count >= 8, (
            f"Expected ≥8 --color-* variable overrides inside dark media query, found {var_count}"
        )

    def test_dark_block_has_color_scheme(self):
        block = _dark_block()
        assert "color-scheme: dark" in block, (
            "color-scheme: dark not set inside @media (prefers-color-scheme: dark)"
        )

    def test_dark_block_has_body_gradient(self):
        block = _dark_block()
        body_rule = re.search(r"\bbody\s*\{([^}]+)\}", block, re.DOTALL)
        assert body_rule, "No body { } rule inside dark media query"
        assert "background" in body_rule.group(1), (
            "body rule inside dark media query has no background property"
        )
        assert "linear-gradient" in body_rule.group(1), (
            "body background in dark mode should use a dark linear-gradient"
        )

    def test_dark_block_includes_surface_token(self):
        block = _dark_block()
        assert "--color-surface:" in block, (
            "--color-surface token not overridden in dark media query"
        )

    def test_dark_block_includes_text_primary_token(self):
        block = _dark_block()
        assert "--color-text-primary:" in block, (
            "--color-text-primary token not overridden in dark media query"
        )

    def test_dark_block_includes_border_token(self):
        block = _dark_block()
        assert "--color-border:" in block, (
            "--color-border token not overridden in dark media query"
        )

    def test_dark_block_includes_status_overrides(self):
        block = _dark_block()
        assert "--color-success-bg:" in block, (
            "--color-success-bg not overridden for dark mode contrast"
        )
        assert "--color-danger-bg:" in block, (
            "--color-danger-bg not overridden for dark mode contrast"
        )

    def test_dark_block_includes_input_rule(self):
        block = _dark_block()
        assert "input" in block and "textarea" in block, (
            "input/textarea dark mode rules missing"
        )

    def test_dark_block_includes_modal_rule(self):
        block = _dark_block()
        assert ".modal-box" in block, (
            ".modal-box dark mode background rule missing"
        )

    def test_dark_block_includes_select_rule(self):
        block = _dark_block()
        assert "select" in block, (
            "select dark mode rule missing — native selects may be unreadable"
        )

    def test_dark_block_has_scrollbar_styling(self):
        block = _dark_block()
        assert "::-webkit-scrollbar" in block, (
            "::-webkit-scrollbar dark mode styling missing"
        )


# ── 3.2 Meta color-scheme tag ─────────────────────────────────────────────────

class TestMetaColorScheme:
    def test_meta_color_scheme_present(self):
        head = _head()
        assert 'name="color-scheme"' in head, (
            '<meta name="color-scheme"> tag not found in <head>'
        )

    def test_meta_color_scheme_includes_dark(self):
        head = _head()
        meta = re.search(r'<meta[^>]*name="color-scheme"[^>]*>', head)
        assert meta, '<meta name="color-scheme"> not found'
        assert "dark" in meta.group(), (
            '<meta name="color-scheme"> content does not include "dark"'
        )

    def test_meta_color_scheme_includes_light(self):
        head = _head()
        meta = re.search(r'<meta[^>]*name="color-scheme"[^>]*>', head)
        assert meta
        assert "light" in meta.group(), (
            '<meta name="color-scheme"> content does not include "light"'
        )


# ── 3.3 Dark mode doesn't duplicate prefers-reduced-motion ───────────────────

class TestDarkModeStructure:
    def test_dark_media_query_after_reduced_motion(self):
        style = _style()
        rm_pos = style.find("prefers-reduced-motion")
        dark_pos = style.find("prefers-color-scheme: dark")
        assert rm_pos != -1 and dark_pos != -1
        assert dark_pos > rm_pos, (
            "Dark mode media query should appear after prefers-reduced-motion block"
        )

    def test_shadow_tokens_overridden_in_dark(self):
        block = _dark_block()
        assert "--shadow-md:" in block or "--shadow-lg:" in block, (
            "Shadow tokens should be darkened for dark mode"
        )
