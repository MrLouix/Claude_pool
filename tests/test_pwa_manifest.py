"""Tests for Step 4 — PWA manifest in frontend/manifest.json."""
import json
import re
from pathlib import Path

_MANIFEST_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "manifest.json"
_HTML_PATH = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"


def _manifest():
    assert _MANIFEST_PATH.exists(), "manifest.json not found"
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _html():
    return _HTML_PATH.read_text(encoding="utf-8")


class TestManifestExists:
    def test_manifest_file_exists(self):
        assert _MANIFEST_PATH.exists(), (
            "team_cli/frontend/manifest.json not found"
        )

    def test_manifest_is_valid_json(self):
        data = _manifest()
        assert isinstance(data, dict), "manifest.json is not a JSON object"


class TestManifestFields:
    def test_name_field_present(self):
        data = _manifest()
        assert "name" in data, "manifest.json missing 'name' field"
        assert data["name"], "manifest.json 'name' field is empty"

    def test_display_field_is_standalone(self):
        data = _manifest()
        assert data.get("display") == "standalone", (
            f"manifest.json 'display' should be 'standalone', got {data.get('display')!r}"
        )

    def test_theme_color_present(self):
        data = _manifest()
        assert "theme_color" in data, "manifest.json missing 'theme_color' field"

    def test_theme_color_matches_dark_background(self):
        data = _manifest()
        theme = data.get("theme_color", "")
        assert theme.lower() == "#1e1e2f", (
            f"theme_color should be #1e1e2f (dark background), got {theme!r}"
        )

    def test_start_url_present(self):
        data = _manifest()
        assert "start_url" in data, "manifest.json missing 'start_url' field"

    def test_short_name_present(self):
        data = _manifest()
        assert "short_name" in data, "manifest.json missing 'short_name' field"


class TestManifestLinkedFromHTML:
    def test_manifest_link_in_html_head(self):
        html = _html()
        assert 'rel="manifest"' in html, (
            '<link rel="manifest"> not found in index.html'
        )

    def test_manifest_href_points_to_static(self):
        html = _html()
        link = re.search(r'<link[^>]*rel="manifest"[^>]*>', html)
        assert link, '<link rel="manifest"> not found'
        tag = link.group()
        assert "manifest.json" in tag, (
            f'manifest link href should reference manifest.json, got: {tag}'
        )
