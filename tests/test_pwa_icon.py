"""Tests for PWA manifest, favicon, viewport meta, and touch target CSS (mobile polish step)."""

import json
from pathlib import Path

_ROOT    = Path(__file__).parent.parent
_FRONT   = _ROOT / "team_cli" / "frontend"
_MANIFEST = _FRONT / "manifest.json"
_INDEX   = _FRONT / "index.html"
_CSS     = _FRONT / "css" / "components.css"


class TestManifest:
    def test_display_is_standalone(self) -> None:
        """manifest.json must set display to 'standalone'."""
        data = json.loads(_MANIFEST.read_text())
        assert data["display"] == "standalone"

    def test_name_present(self) -> None:
        """manifest.json must have a non-empty name."""
        data = json.loads(_MANIFEST.read_text())
        assert data.get("name")

    def test_short_name_present(self) -> None:
        """manifest.json must have a non-empty short_name."""
        data = json.loads(_MANIFEST.read_text())
        assert data.get("short_name")

    def test_start_url_is_root(self) -> None:
        """manifest.json start_url must be '/'."""
        data = json.loads(_MANIFEST.read_text())
        assert data.get("start_url") == "/"

    def test_background_color_present(self) -> None:
        """manifest.json must have background_color."""
        data = json.loads(_MANIFEST.read_text())
        assert data.get("background_color")

    def test_theme_color_present(self) -> None:
        """manifest.json must have theme_color."""
        data = json.loads(_MANIFEST.read_text())
        assert data.get("theme_color")

    def test_icons_non_empty(self) -> None:
        """manifest.json icons array must have at least one entry."""
        data = json.loads(_MANIFEST.read_text())
        assert isinstance(data.get("icons"), list)
        assert len(data["icons"]) >= 1

    def test_icon_src_file_exists(self) -> None:
        """The first icon src must resolve to an existing file under frontend/."""
        data = json.loads(_MANIFEST.read_text())
        icon_src = data["icons"][0]["src"]
        # src is a URL path like /static/favicon.svg — resolve relative to frontend/
        relative = icon_src.lstrip("/").replace("static/", "", 1)
        icon_path = _FRONT / relative
        assert icon_path.exists(), f"Icon file not found: {icon_path}"


class TestIndexHtml:
    def _html(self) -> str:
        return _INDEX.read_text(encoding="utf-8")

    def test_manifest_link_present(self) -> None:
        """index.html must include a <link rel='manifest'> tag."""
        assert 'rel="manifest"' in self._html()

    def test_viewport_has_width_device_width(self) -> None:
        """index.html viewport meta must include width=device-width."""
        assert "width=device-width" in self._html()

    def test_viewport_has_viewport_fit_cover(self) -> None:
        """index.html viewport meta must include viewport-fit=cover."""
        assert "viewport-fit=cover" in self._html()

    def test_favicon_link_present(self) -> None:
        """index.html must include a <link rel='icon'> tag pointing to favicon.svg."""
        html = self._html()
        assert 'rel="icon"' in html and "favicon.svg" in html


class TestComponentsCss:
    def _css(self) -> str:
        return _CSS.read_text(encoding="utf-8")

    def test_min_height_44px_rule_present(self) -> None:
        """components.css must have at least one rule with min-height: 44px."""
        css = self._css()
        assert "min-height: 44px" in css or "min-height: var(--touch-target-min" in css

    def test_thread_panel_transform_transition(self) -> None:
        """#thread-panel must use transform transition for slide-in animation."""
        css = self._css()
        assert "transform" in css and "#thread-panel" in css

    def test_dir_item_min_height(self) -> None:
        """.dir-item must have a min-height for touch target compliance."""
        css = self._css()
        # Find the .dir-item rule block and check for min-height
        assert "min-height" in css and ".dir-item" in css
