"""Tests for settings.js and components.css — Settings page UI (Step 7 final)."""

from pathlib import Path

_SETTINGS_JS  = Path(__file__).parent.parent / "team_cli" / "frontend" / "js" / "views" / "settings.js"
_COMPONENTS_CSS = Path(__file__).parent.parent / "team_cli" / "frontend" / "css" / "components.css"


def _js():
    return _SETTINGS_JS.read_text(encoding="utf-8")


def _css():
    return _COMPONENTS_CSS.read_text(encoding="utf-8")


class TestPriorityButtons:
    def test_priority_section_has_up_buttons(self):
        src = _js()
        assert "up" in src.lower() and ("aria-label" in src or "priority-up" in src), (
            "settings.js must have up-direction priority buttons"
        )

    def test_priority_section_has_down_buttons(self):
        src = _js()
        assert "down" in src.lower() and ("aria-label" in src or "priority-down" in src), (
            "settings.js must have down-direction priority buttons"
        )


class TestCliCommandUI:
    def test_cli_test_button_exists(self):
        assert "cli-test-btn" in _js(), (
            "settings.js must render a Test button with class 'cli-test-btn'"
        )

    def test_add_command_button_exists(self):
        assert "cli-add-btn" in _js(), (
            "settings.js must have an Add CLI command button with id 'cli-add-btn'"
        )

    def test_model_chips_present(self):
        assert "model-chip" in _js(), (
            "settings.js must render model chips with class 'model-chip'"
        )


class TestGeneralSection:
    def test_purge_button_exists(self):
        assert "settings-purge-btn" in _js(), (
            "settings.js must render a purge button with id 'settings-purge-btn'"
        )

    def test_auto_decompose_checkbox(self):
        assert "settings-auto-decompose" in _js(), (
            "settings.js must render auto-decompose checkbox with id 'settings-auto-decompose'"
        )

    def test_max_subtasks_input(self):
        assert "settings-max-subtasks" in _js(), (
            "settings.js must render max-subtasks input with id 'settings-max-subtasks'"
        )


class TestSettingsCSS:
    def test_settings_css_cli_card(self):
        assert ".cli-card" in _css(), (
            "components.css must define .cli-card styles"
        )

    def test_settings_css_priority_buttons_44px(self):
        assert "44px" in _css(), (
            "components.css must enforce 44px min touch target for priority buttons"
        )
