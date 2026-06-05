"""Frontend tests for Phase 3 Step 5: per-message CLI override in project chat view."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
HTML = FRONTEND.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML: project view structure
# ---------------------------------------------------------------------------

class TestProjectViewHtml:
    def test_project_view_exists(self):
        assert 'id="project-view"' in HTML

    def test_project_view_hidden_by_default(self):
        assert re.search(r'id="project-view"[^>]*style="[^"]*display\s*:\s*none', HTML)

    def test_project_header_label_exists(self):
        assert 'id="project-header-label"' in HTML

    def test_project_header_dir_exists(self):
        assert 'id="project-header-dir"' in HTML

    def test_project_back_button_exists(self):
        assert 'id="btn-project-back"' in HTML

    def test_project_message_thread_exists(self):
        assert 'id="project-message-thread"' in HTML

    def test_project_input_exists(self):
        assert 'id="project-input"' in HTML

    def test_project_cli_select_exists(self):
        assert 'id="project-cli-select"' in HTML

    def test_project_send_button_exists(self):
        assert 'id="btn-send-project-message"' in HTML

    def test_cli_select_has_auto_default_option(self):
        assert re.search(r'Auto.*project default', HTML)

    def test_project_input_has_placeholder(self):
        assert re.search(r'id="project-input"[^>]*placeholder=|placeholder=[^>]*id="project-input"', HTML)


# ---------------------------------------------------------------------------
# HTML: CLI override select default option
# ---------------------------------------------------------------------------

class TestCliOverrideSelect:
    def test_auto_option_has_empty_value(self):
        assert re.search(r'<option\s+value=""[^>]*>Auto', HTML)

    def test_select_is_inside_project_view(self):
        pv_start = HTML.index('id="project-view"')
        sel_pos = HTML.index('id="project-cli-select"')
        assert sel_pos > pv_start


# ---------------------------------------------------------------------------
# JS: routing and view functions
# ---------------------------------------------------------------------------

class TestProjectRouting:
    def test_current_project_id_variable(self):
        assert 'currentProjectId' in HTML

    def test_show_project_view_function_defined(self):
        assert 'function showProjectView' in HTML

    def test_handle_route_includes_project(self):
        assert re.search(r"parts\[0\]\s*===\s*['\"]project['\"]", HTML)

    def test_show_project_view_called_in_router(self):
        assert 'showProjectView' in HTML

    def test_project_view_hidden_in_show_dashboard(self):
        # showDashboardView must hide projectView
        sv_start = HTML.index('function showDashboardView')
        sv_end = HTML.index('\n        }', sv_start)
        fn_body = HTML[sv_start:sv_end]
        assert "projectView" in fn_body
        assert "display" in fn_body

    def test_project_view_hidden_in_show_chat(self):
        sc_start = HTML.index('function showChatView')
        sc_end = HTML.index('\n        }', sc_start)
        fn_body = HTML[sc_start:sc_end]
        assert "projectView" in fn_body

    def test_project_view_ref_assigned(self):
        assert "getElementById('project-view')" in HTML


# ---------------------------------------------------------------------------
# JS: project view logic
# ---------------------------------------------------------------------------

class TestProjectViewJs:
    def test_load_project_meta_function_defined(self):
        assert 'function loadProjectMeta' in HTML

    def test_fetch_project_messages_function_defined(self):
        assert 'function fetchProjectMessages' in HTML

    def test_render_project_messages_function_defined(self):
        assert 'function renderProjectMessages' in HTML

    def test_populate_project_cli_select_function_defined(self):
        assert 'function populateProjectCliSelect' in HTML

    def test_api_projects_id_fetch(self):
        assert re.search(r'/api/projects/\$\{projectId\}', HTML)

    def test_api_projects_id_messages_fetch(self):
        assert re.search(r'/api/projects/\$\{projectId\}/messages', HTML)

    def test_api_projects_messages_post(self):
        assert re.search(r"/api/projects/\$\{currentProjectId\}/messages", HTML)

    def test_cli_override_sent_in_body(self):
        assert 'cli_used' in HTML

    def test_back_button_navigates_home(self):
        assert re.search(r"btn-project-back.*navigate\(''\)|navigate\(''\).*btn-project-back", HTML, re.DOTALL)

    def test_ctrl_enter_sends_message(self):
        assert re.search(r"ctrlKey.*sendProjectMessage|sendProjectMessage.*ctrlKey", HTML, re.DOTALL)

    def test_send_button_listener_wired(self):
        assert re.search(
            r"btn-send-project-message.*sendProjectMessage|sendProjectMessage.*btn-send-project-message",
            HTML, re.DOTALL,
        )


# ---------------------------------------------------------------------------
# JS: renderProjectMessages — badge and message structure
# ---------------------------------------------------------------------------

class TestRenderProjectMessages:
    def _fn_body(self):
        start = HTML.index('function renderProjectMessages')
        end = HTML.index('\n        }', start) + 10
        return HTML[start:end]

    def test_renders_msg_cli_badge(self):
        assert 'msg-cli-badge' in self._fn_body()

    def test_badge_only_for_assistant(self):
        body = self._fn_body()
        assert "cli_used" in body
        assert "assistant" in body

    def test_uses_project_msg_css_classes(self):
        body = self._fn_body()
        assert 'project-msg' in body

    def test_distinguishes_user_assistant(self):
        body = self._fn_body()
        assert 'project-msg-user' in body
        assert 'project-msg-assistant' in body

    def test_scrolls_to_bottom(self):
        body = self._fn_body()
        assert 'scrollTop' in body and 'scrollHeight' in body


# ---------------------------------------------------------------------------
# JS: renderProjectList navigates to project
# ---------------------------------------------------------------------------

class TestProjectListNavigation:
    def test_project_list_uses_navigate(self):
        rl_start = HTML.index('function renderProjectList')
        rl_end = HTML.index('\n        }', rl_start) + 10
        fn_body = HTML[rl_start:rl_end]
        assert "navigate" in fn_body

    def test_project_list_no_alert(self):
        rl_start = HTML.index('function renderProjectList')
        rl_end = HTML.index('\n        }', rl_start) + 10
        fn_body = HTML[rl_start:rl_end]
        assert "alert(" not in fn_body

    def test_project_list_includes_project_id_in_navigate(self):
        rl_start = HTML.index('function renderProjectList')
        rl_end = HTML.index('\n        }', rl_start) + 10
        fn_body = HTML[rl_start:rl_end]
        assert re.search(r"navigate\([^)]*project/", fn_body)
