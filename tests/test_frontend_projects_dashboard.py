"""Frontend tests for Phase 5 Step 2: Projects dashboard with Open/Edit/Delete."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
HTML = FRONTEND.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Navigation — "Projects" tab label
# ---------------------------------------------------------------------------

class TestProjectsNav:
    def test_projects_heading_exists(self):
        assert 'id="projects-heading"' in HTML

    def test_projects_heading_label(self):
        assert re.search(r'id="projects-heading"[^>]*>\s*Projects', HTML)

    def test_chats_section_no_longer_primary(self):
        # The old Chats section heading should not be the first major section anymore
        # (it may still exist as hidden or gone)
        chats_heading_pos = HTML.find('id="chats-heading"')
        projects_heading_pos = HTML.find('id="projects-heading"')
        # If chats-heading still exists it must come AFTER projects-heading, or not exist
        if chats_heading_pos != -1:
            assert chats_heading_pos > projects_heading_pos

    def test_new_project_button_exists(self):
        assert 'id="btn-new-project"' in HTML

    def test_project_list_container_exists(self):
        assert 'id="project-list"' in HTML


# ---------------------------------------------------------------------------
# Project row rendering — action buttons
# ---------------------------------------------------------------------------

class TestProjectRowRendering:
    def _fn_body(self):
        start = HTML.index("function renderProjectList")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_open_button_rendered(self):
        assert re.search(r"Open", self._fn_body())

    def test_edit_button_rendered(self):
        assert re.search(r"Edit", self._fn_body())

    def test_delete_button_rendered(self):
        assert re.search(r"Delete", self._fn_body())

    def test_open_navigates_to_project(self):
        body = self._fn_body()
        assert re.search(r"navigate.*project/|project/.*navigate", body, re.DOTALL)

    def test_edit_calls_open_edit_project_modal(self):
        body = self._fn_body()
        assert "openEditProjectModal" in body

    def test_delete_calls_delete_project_confirm(self):
        body = self._fn_body()
        assert "deleteProjectConfirm" in body

    def test_renders_project_name(self):
        body = self._fn_body()
        assert re.search(r"p\.name", body)

    def test_renders_project_directory(self):
        body = self._fn_body()
        assert re.search(r"p\.directory", body)

    def test_renders_message_count(self):
        body = self._fn_body()
        assert "message_count" in body

    def test_renders_cli_badge(self):
        body = self._fn_body()
        assert "cli-badge" in body

    def test_project_map_populated(self):
        body = self._fn_body()
        assert "_projectMap" in body


# ---------------------------------------------------------------------------
# Edit Project modal — HTML
# ---------------------------------------------------------------------------

class TestEditProjectModalHtml:
    def test_edit_modal_exists(self):
        assert 'id="edit-project-modal"' in HTML

    def test_edit_modal_has_aria_role(self):
        assert re.search(r'id="edit-project-modal"[^>]*role="dialog"', HTML)

    def test_edit_modal_has_aria_modal(self):
        assert re.search(r'id="edit-project-modal"[^>]*aria-modal="true"', HTML)

    def test_edit_name_input(self):
        assert 'id="edit-project-name"' in HTML

    def test_edit_directory_input(self):
        assert 'id="edit-project-directory"' in HTML

    def test_edit_browse_button(self):
        assert 'id="btn-edit-project-browse"' in HTML

    def test_edit_allow_cli_switch_checkbox(self):
        assert 'id="edit-project-allow-cli-switch"' in HTML

    def test_edit_default_cli_section(self):
        assert 'id="edit-project-default-cli-section"' in HTML

    def test_edit_default_cli_select(self):
        assert 'id="edit-project-default-cli"' in HTML

    def test_edit_confirm_button(self):
        assert 'id="btn-edit-project-confirm"' in HTML

    def test_edit_cancel_button(self):
        assert 'id="edit-project-cancel"' in HTML

    def test_edit_close_button(self):
        assert 'id="edit-project-close"' in HTML


# ---------------------------------------------------------------------------
# Edit Project modal — JS logic
# ---------------------------------------------------------------------------

class TestEditProjectModalJs:
    def _fn_body(self):
        start = HTML.index("window.openEditProjectModal = async function")
        end = HTML.index("\n        };", start) + 10
        return HTML[start:end]

    def test_open_edit_project_modal_defined(self):
        assert "openEditProjectModal" in HTML

    def test_prepopulates_name(self):
        body = self._fn_body()
        assert re.search(r"edit-project-name.*\.value|\.value.*edit-project-name", body, re.DOTALL)

    def test_prepopulates_directory(self):
        body = self._fn_body()
        assert re.search(r"edit-project-directory.*\.value|\.value.*edit-project-directory", body, re.DOTALL)

    def test_prepopulates_allow_cli_switch(self):
        body = self._fn_body()
        assert "allow_cli_switch" in body

    def test_fetches_clis_for_dropdown(self):
        body = self._fn_body()
        assert "/api/clis" in body

    def test_preselects_current_default_cli(self):
        body = self._fn_body()
        assert re.search(r"default_cli.*selected|selected.*default_cli", body, re.DOTALL)

    def test_close_edit_project_modal_defined(self):
        assert "closeEditProjectModal" in HTML

    def test_patch_api_call_present(self):
        assert re.search(r"PATCH.*api/projects|api/projects.*PATCH", HTML, re.DOTALL)

    def test_patch_url_uses_project_id(self):
        assert re.search(r"/api/projects/\$\{_editingProjectId\}", HTML)

    def test_edit_submit_calls_fetch_projects(self):
        # After successful PATCH, the list should refresh
        # Find the addEventListener block for the confirm button
        start = HTML.index("'btn-edit-project-confirm'")
        patch_block = HTML[start:start + 1500]
        assert "fetchProjects" in patch_block


# ---------------------------------------------------------------------------
# Delete confirmation — JS logic
# ---------------------------------------------------------------------------

class TestDeleteProjectConfirm:
    def _fn_body(self):
        start = HTML.index("window.deleteProjectConfirm = async function")
        end = HTML.index("\n        };", start) + 10
        return HTML[start:end]

    def test_delete_project_confirm_defined(self):
        assert "deleteProjectConfirm" in HTML

    def test_uses_confirm_dialog(self):
        body = self._fn_body()
        assert "confirm(" in body

    def test_confirm_message_mentions_project(self):
        body = self._fn_body()
        assert re.search(r"confirm.*project|project.*confirm", body, re.DOTALL | re.IGNORECASE)

    def test_calls_delete_api(self):
        body = self._fn_body()
        assert re.search(r"DELETE.*api/projects|api/projects.*DELETE", body, re.DOTALL)

    def test_refreshes_list_after_delete(self):
        body = self._fn_body()
        assert "fetchProjects" in body


# ---------------------------------------------------------------------------
# showDashboardView calls fetchProjects
# ---------------------------------------------------------------------------

class TestDashboardFetchesProjects:
    def test_show_dashboard_view_calls_fetch_projects(self):
        start = HTML.index("function showDashboardView")
        end = HTML.index("\n        }", start) + 10
        fn_body = HTML[start:end]
        assert "fetchProjects" in fn_body
