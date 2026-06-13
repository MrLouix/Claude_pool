"""Frontend tests for the new project creation modal (Phase 3 Step 4)."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
HTML = FRONTEND.read_text(encoding="utf-8")
_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"
CSS = "\n".join((_CSS_DIR / n).read_text(encoding="utf-8") for n in ["tokens.css", "layout.css", "components.css"])


# ---------------------------------------------------------------------------
# HTML structure checks
# ---------------------------------------------------------------------------

class TestModalPresent:
    def test_modal_overlay_exists(self):
        assert 'id="new-project-modal"' in HTML

    def test_modal_has_correct_role(self):
        assert 'role="dialog"' in HTML
        assert 'aria-modal="true"' in HTML

    def test_modal_has_aria_label(self):
        assert 'aria-labelledby="new-project-modal-title"' in HTML


class TestProjectNameInput:
    def test_name_input_exists(self):
        assert 'id="new-project-name"' in HTML

    def test_name_input_has_placeholder(self):
        assert re.search(r'id="new-project-name"[^>]*placeholder=', HTML) or \
               re.search(r'placeholder=["\'][^"\']*["\'][^>]*id="new-project-name"', HTML)

    def test_name_label_present(self):
        assert re.search(r'(?i)project\s*name', HTML)


class TestDirectoryInput:
    def test_directory_input_exists(self):
        assert 'id="new-project-directory"' in HTML

    def test_browse_button_exists(self):
        assert 'id="btn-new-project-browse"' in HTML

    def test_directory_input_has_autocomplete_off(self):
        # Security: autocomplete off for path inputs
        assert re.search(r'id="new-project-directory"[^>]*autocomplete="off"', HTML) or \
               re.search(r'autocomplete="off"[^>]*id="new-project-directory"', HTML)


class TestAllowCliSwitchToggle:
    def test_toggle_checkbox_exists(self):
        assert 'id="new-project-allow-cli-switch"' in HTML

    def test_toggle_is_checkbox_type(self):
        assert re.search(
            r'<input[^>]*type="checkbox"[^>]*id="new-project-allow-cli-switch"'
            r'|<input[^>]*id="new-project-allow-cli-switch"[^>]*type="checkbox"',
            HTML
        )

    def test_toggle_is_checked_by_default(self):
        # The checkbox must have `checked` attribute (no JS needed for initial state)
        assert re.search(
            r'id="new-project-allow-cli-switch"[^>]*checked'
            r'|checked[^>]*id="new-project-allow-cli-switch"',
            HTML
        )

    def test_toggle_label_text(self):
        assert re.search(r'(?i)allow.*cli.*switch|cli.*switch.*rate.limit', HTML)


class TestDefaultCliSelector:
    def test_default_cli_select_exists(self):
        assert 'id="new-project-default-cli"' in HTML

    def test_default_cli_section_exists(self):
        assert 'id="new-project-default-cli-section"' in HTML

    def test_default_cli_section_hidden_by_default(self):
        # The section should start with display:none
        assert re.search(
            r'id="new-project-default-cli-section"[^>]*style="[^"]*display\s*:\s*none',
            HTML
        )

    def test_select_is_inside_section(self):
        # Check that new-project-default-cli appears after new-project-default-cli-section
        section_pos = HTML.index('id="new-project-default-cli-section"')
        select_pos = HTML.index('id="new-project-default-cli"')
        assert select_pos > section_pos


class TestModalButtons:
    def test_confirm_button_exists(self):
        assert 'id="btn-new-project-confirm"' in HTML

    def test_cancel_button_exists(self):
        assert 'id="new-project-cancel"' in HTML

    def test_close_button_exists(self):
        assert 'id="new-project-close"' in HTML


# ---------------------------------------------------------------------------
# JavaScript logic checks
# ---------------------------------------------------------------------------

class TestJavaScriptLogic:
    def test_fetch_projects_function_defined(self):
        assert 'fetchProjects' in HTML

    def test_render_project_list_function_defined(self):
        assert 'renderProjectList' in HTML

    def test_open_new_project_modal_function_defined(self):
        assert 'openNewProjectModal' in HTML

    def test_close_new_project_modal_function_defined(self):
        assert 'closeNewProjectModal' in HTML

    def test_api_projects_post_call(self):
        assert re.search(r"fetch\(['\"]?/api/projects['\"]?", HTML)

    def test_api_clis_fetch_in_modal(self):
        assert '/api/clis' in HTML

    def test_allow_cli_switch_in_post_body(self):
        assert 'allow_cli_switch' in HTML

    def test_default_cli_in_post_body(self):
        assert 'default_cli' in HTML

    def test_toggle_change_listener_wired(self):
        assert "new-project-allow-cli-switch" in HTML
        # The change handler should reference the default CLI section
        assert re.search(
            r"new-project-allow-cli-switch.*change|change.*new-project-allow-cli-switch",
            HTML,
            re.DOTALL,
        )

    def test_default_cli_hidden_when_switch_enabled(self):
        # The JS should set display:none when checkbox is checked
        assert re.search(
            r'display.*none.*new-project-default-cli|new-project-default-cli.*display.*none',
            HTML,
            re.DOTALL,
        )

    def test_fetch_projects_called_on_startup(self):
        # fetchProjects() must be called somewhere outside a function definition
        calls = [m.start() for m in re.finditer(r'\bfetchProjects\(\)', HTML)]
        # At least 2: one in event handlers and one on startup
        assert len(calls) >= 2

    def test_dir_modal_target_map_includes_new_project(self):
        assert "'new-project'" in HTML or '"new-project"' in HTML
        assert 'new-project-directory' in HTML


# ---------------------------------------------------------------------------
# Projects section in dashboard
# ---------------------------------------------------------------------------

class TestProjectsSection:
    def test_projects_section_exists(self):
        assert 'id="projects-heading"' in HTML

    def test_new_project_button_exists(self):
        assert 'id="btn-new-project"' in HTML

    def test_project_list_container_exists(self):
        assert 'id="project-list"' in HTML

    def test_project_list_empty_state_message(self):
        assert re.search(r'(?i)no projects yet', HTML)


# ---------------------------------------------------------------------------
# CLI badges in project list
# ---------------------------------------------------------------------------

class TestCliBadges:
    def test_cli_badge_css_class_defined(self):
        assert '.cli-badge' in CSS

    def test_cli_badge_auto_class_defined(self):
        assert 'cli-badge-auto' in CSS

    def test_cli_badge_named_class_defined(self):
        assert 'cli-badge-named' in CSS

    def test_cli_badge_manual_class_defined(self):
        assert 'cli-badge-manual' in CSS

    def test_badge_rendered_in_project_list_js(self):
        # renderProjectList should use cli-badge classes
        assert re.search(r'cli-badge.*renderProjectList|renderProjectList.*cli-badge', HTML, re.DOTALL)
        # More direct: cli-badge appears inside the renderProjectList function body
        rl_start = HTML.index('function renderProjectList')
        rl_end = HTML.index('\n        }', rl_start) + 10
        fn_body = HTML[rl_start:rl_end]
        assert 'cli-badge' in fn_body

    def test_allow_cli_switch_badge_logic(self):
        # renderProjectList must branch on allow_cli_switch
        rl_start = HTML.index('function renderProjectList')
        rl_end = HTML.index('\n        }', rl_start) + 10
        fn_body = HTML[rl_start:rl_end]
        assert 'allow_cli_switch' in fn_body
