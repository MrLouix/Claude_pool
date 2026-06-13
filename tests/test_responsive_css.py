"""Tests for Step 4 — Responsive layout and mobile-first CSS."""
import re
from pathlib import Path

_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"
_HTML_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"


def _layout():
    return (_CSS_DIR / "layout.css").read_text(encoding="utf-8")


def _tokens():
    return (_CSS_DIR / "tokens.css").read_text(encoding="utf-8")


def _combined():
    combined = ""
    for name in ["tokens.css", "layout.css", "components.css"]:
        combined += (_CSS_DIR / name).read_text(encoding="utf-8") + "\n"
    return combined


def _html():
    return _HTML_PATH.read_text(encoding="utf-8")


class TestMobileFirstBreakpoints:
    def test_tablet_breakpoint_present(self):
        assert "@media (min-width: 768px)" in _layout(), (
            "@media (min-width: 768px) tablet breakpoint not found in layout.css"
        )

    def test_desktop_breakpoint_present(self):
        assert "@media (min-width: 1100px)" in _layout(), (
            "@media (min-width: 1100px) desktop breakpoint not found in layout.css"
        )

    def test_dvh_used_for_viewport_height(self):
        assert "100dvh" in _layout(), (
            "100dvh not found in layout.css — use dynamic viewport height for mobile"
        )

    def test_sidebar_hidden_by_default(self):
        layout = _layout()
        sidebar_rule = re.search(r"\.sidebar\s*\{([^}]+)\}", layout, re.DOTALL)
        assert sidebar_rule, "No .sidebar { } rule found in layout.css"
        block = sidebar_rule.group(1)
        assert "display: none" in block or "width: 0" in block or "hidden" in block, (
            ".sidebar should be hidden on mobile (before 768px breakpoint)"
        )

    def test_sidebar_shown_at_tablet(self):
        layout = _layout()
        tablet_block = re.search(
            r"@media\s*\(min-width:\s*768px\)\s*\{(.+?)(?=@media|\Z)",
            layout, re.DOTALL
        )
        assert tablet_block, "Could not extract 768px media block"
        assert ".sidebar" in tablet_block.group(1), (
            ".sidebar not shown inside @media (min-width: 768px)"
        )

    def test_bottom_nav_hidden_at_tablet(self):
        layout = _layout()
        tablet_block = re.search(
            r"@media\s*\(min-width:\s*768px\)\s*\{(.+?)(?=@media|\Z)",
            layout, re.DOTALL
        )
        assert tablet_block, "Could not extract 768px media block"
        block = tablet_block.group(1)
        assert ".bottom-nav" in block, (
            ".bottom-nav should be hidden inside @media (min-width: 768px)"
        )


class TestTouchTokens:
    def test_touch_target_min_token_present(self):
        tokens = _tokens()
        assert "--touch-target-min" in tokens, (
            "--touch-target-min token not defined in tokens.css"
        )

    def test_touch_target_min_is_44px(self):
        tokens = _tokens()
        m = re.search(r"--touch-target-min\s*:\s*(\S+)", tokens)
        assert m, "--touch-target-min not found in tokens.css"
        assert m.group(1).rstrip(";") == "44px", (
            f"--touch-target-min should be 44px, got {m.group(1)}"
        )

    def test_safe_area_inset_bottom_referenced(self):
        combined = _combined()
        assert "safe-area-inset-bottom" in combined, (
            "safe-area-inset-bottom not referenced in any CSS file"
        )


class TestBottomNav:
    def test_bottom_nav_in_html(self):
        html = _html()
        assert 'class="bottom-nav"' in html, (
            ".bottom-nav element not found in index.html"
        )

    def test_bottom_nav_has_three_items(self):
        html = _html()
        items = re.findall(r'class="bottom-nav-item"', html)
        assert len(items) == 3, (
            f"Expected 3 .bottom-nav-item elements, found {len(items)}"
        )

    def test_bottom_nav_has_aria_label(self):
        html = _html()
        nav_match = re.search(r'<nav[^>]*class="bottom-nav"[^>]*>', html)
        assert nav_match, "No <nav class='bottom-nav'> found"
        assert "aria-label" in nav_match.group(), (
            ".bottom-nav is missing aria-label"
        )

    def test_bottom_nav_links_have_aria_labels(self):
        html = _html()
        nav_block = re.search(
            r'<nav[^>]*class="bottom-nav"[^>]*>(.*?)</nav>',
            html, re.DOTALL
        )
        assert nav_block, "No .bottom-nav block found"
        links = re.findall(r'<a[^>]+>', nav_block.group(1))
        for link in links:
            assert "aria-label" in link, (
                f"Bottom nav link missing aria-label: {link}"
            )

    def test_bottom_nav_routes(self):
        html = _html()
        assert 'href="#/chats"' in html or 'data-route="chats"' in html, (
            "Bottom nav missing chats route"
        )
        assert 'href="#/queue"' in html or 'data-route="queue"' in html, (
            "Bottom nav missing queue route"
        )
        assert 'href="#/settings"' in html or 'data-route="settings"' in html, (
            "Bottom nav missing settings route"
        )


class TestSidebarNav:
    def test_sidebar_nav_in_html(self):
        html = _html()
        assert 'id="sidebar"' in html, (
            "#sidebar element not found in index.html"
        )

    def test_sidebar_has_navigation_role(self):
        html = _html()
        sidebar_tag = re.search(r'<[a-z]+[^>]*id="sidebar"[^>]*>', html)
        assert sidebar_tag, "No element with id='sidebar' found"
        tag = sidebar_tag.group()
        assert 'role="navigation"' in tag or tag.startswith("<nav"), (
            "#sidebar should have role='navigation' or be a <nav> element"
        )
