"""Frontend tests for Step 7: Multi-Step Planner UI components and /plan command."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
HTML = FRONTEND.read_text(encoding="utf-8")
_CSS_DIR = Path(__file__).parent.parent / "team_cli" / "frontend" / "css"
CSS = "\n".join((_CSS_DIR / n).read_text(encoding="utf-8") for n in ["tokens.css", "layout.css", "components.css"])


# ---------------------------------------------------------------------------
# CSS — class presence
# ---------------------------------------------------------------------------


class TestStepPlanCss:
    def test_step_plan_card_class_defined(self):
        assert ".step-plan-card" in CSS

    def test_step_plan_header_class_defined(self):
        assert ".step-plan-header" in CSS

    def test_step_task_list_class_defined(self):
        assert ".step-task-list" in CSS

    def test_step_task_item_class_defined(self):
        assert ".step-task-item" in CSS

    def test_step_status_icon_class_defined(self):
        assert ".step-status-icon" in CSS

    def test_step_plan_actions_class_defined(self):
        assert ".step-plan-actions" in CSS

    def test_step_details_modal_class_defined(self):
        assert ".step-details-modal" in CSS

    def test_step_details_modal_content_class_defined(self):
        assert ".step-details-modal-content" in CSS


class TestStepTaskItemStatusColors:
    """Border-left colors for each status value."""

    def _css_block(self):
        start = CSS.index(".step-task-item[data-status=")
        end = CSS.index(".step-status-icon", start)
        return CSS[start:end]

    def test_pending_color(self):
        block = self._css_block()
        assert "#9ca3af" in block

    def test_running_color(self):
        block = self._css_block()
        assert "var(--color-warning)" in block or "#f59e0b" in block

    def test_success_color(self):
        block = self._css_block()
        assert "#22c55e" in block

    def test_failed_color(self):
        block = self._css_block()
        assert "var(--color-danger)" in block or "#ef4444" in block

    def test_rate_limit_color(self):
        block = self._css_block()
        assert "#f97316" in block


# ---------------------------------------------------------------------------
# JavaScript — function definitions
# ---------------------------------------------------------------------------


class TestGetStatusIcon:
    def _fn_body(self):
        start = HTML.index("function getStatusIcon")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "function getStatusIcon" in HTML

    def test_pending_returns_circle(self):
        body = self._fn_body()
        assert "pending" in body
        assert "⚪" in body

    def test_running_returns_yellow(self):
        body = self._fn_body()
        assert "running" in body
        assert "🟡" in body

    def test_rate_limit_returns_orange(self):
        body = self._fn_body()
        assert "rate_limit" in body
        assert "🟠" in body

    def test_success_returns_green(self):
        body = self._fn_body()
        assert "success" in body
        assert "🟢" in body

    def test_failed_returns_red(self):
        body = self._fn_body()
        assert "failed" in body
        assert "🔴" in body


class TestFormatDuration:
    def _fn_body(self):
        start = HTML.index("function formatDuration")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "function formatDuration" in HTML

    def test_returns_dash_for_null(self):
        body = self._fn_body()
        assert "null" in body or "== null" in body or "=== null" in body

    def test_handles_minutes(self):
        body = self._fn_body()
        assert re.search(r"60|minute|min", body)

    def test_handles_sub_second(self):
        body = self._fn_body()
        assert "ms" in body or "1000" in body


class TestRenderStepPlan:
    def _fn_body(self):
        start = HTML.index("function renderStepPlan")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "function renderStepPlan" in HTML

    def test_creates_step_plan_card(self):
        body = self._fn_body()
        assert "step-plan-card" in body

    def test_uses_step_plan_header(self):
        body = self._fn_body()
        assert "step-plan-header" in body

    def test_uses_step_task_list(self):
        body = self._fn_body()
        assert "step-task-list" in body

    def test_uses_step_task_item(self):
        body = self._fn_body()
        assert "step-task-item" in body

    def test_uses_step_status_icon(self):
        body = self._fn_body()
        assert "step-status-icon" in body

    def test_uses_step_plan_actions(self):
        body = self._fn_body()
        assert "step-plan-actions" in body

    def test_shows_step_count(self):
        body = self._fn_body()
        assert re.search(r"stepCount|step.*length|length.*step", body, re.IGNORECASE)

    def test_includes_delete_button(self):
        body = self._fn_body()
        assert "deleteStepPlan" in body or "Supprimer" in body

    def test_includes_retry_button_when_failed(self):
        body = self._fn_body()
        assert "retryFailedSteps" in body or "Relancer" in body

    def test_calls_get_status_icon(self):
        body = self._fn_body()
        assert "getStatusIcon" in body

    def test_calls_format_duration(self):
        body = self._fn_body()
        assert "formatDuration" in body

    def test_sets_plan_id_as_dataset(self):
        body = self._fn_body()
        assert re.search(r"dataset\.planId|data-plan-id", body)

    def test_calls_show_step_details_on_click(self):
        body = self._fn_body()
        assert "showStepDetails" in body


class TestRenderFinalEvaluation:
    def _fn_body(self):
        start = HTML.index("function renderFinalEvaluation")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "function renderFinalEvaluation" in HTML

    def test_shows_success_state(self):
        body = self._fn_body()
        assert re.search(r"Succ[eé]s|success", body, re.IGNORECASE)

    def test_shows_failure_state(self):
        body = self._fn_body()
        assert re.search(r"[EÉ]chec|failed|failure", body, re.IGNORECASE)

    def test_shows_summary(self):
        body = self._fn_body()
        assert "summary" in body

    def test_shows_missing_items(self):
        body = self._fn_body()
        assert "missing" in body

    def test_shows_suggestions(self):
        body = self._fn_body()
        assert "suggestions" in body

    def test_green_for_success(self):
        body = self._fn_body()
        assert "🟢" in body or "22c55e" in body or "green" in body.lower()

    def test_red_for_failure(self):
        body = self._fn_body()
        assert "🔴" in body or "ef4444" in body or "red" in body.lower()


class TestShowStepDetails:
    def _fn_body(self):
        start = HTML.index("async function showStepDetails")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "async function showStepDetails" in HTML

    def test_fetches_plan_steps(self):
        body = self._fn_body()
        assert re.search(r"/api/skills/multi_step_planner/plans/.*steps", body)

    def test_uses_step_details_modal_class(self):
        body = self._fn_body()
        assert "step-details-modal" in body

    def test_shows_output_or_error(self):
        body = self._fn_body()
        assert "output" in body and "error" in body

    def test_closes_on_overlay_click(self):
        body = self._fn_body()
        assert re.search(r"remove|close|click", body)


class TestDeleteStepPlan:
    def _fn_body(self):
        start = HTML.index("async function deleteStepPlan")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "async function deleteStepPlan" in HTML

    def test_calls_delete_endpoint(self):
        body = self._fn_body()
        assert re.search(r"/api/skills/multi_step_planner/plans/", body)
        assert "DELETE" in body

    def test_confirms_before_deleting(self):
        body = self._fn_body()
        assert "confirm" in body

    def test_removes_card_from_dom(self):
        body = self._fn_body()
        assert "remove" in body


class TestRetryFailedSteps:
    def _fn_body(self):
        start = HTML.index("async function retryFailedSteps")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_function_defined(self):
        assert "async function retryFailedSteps" in HTML

    def test_fetches_steps_first(self):
        body = self._fn_body()
        assert re.search(r"/api/skills/multi_step_planner/plans/.*steps", body)

    def test_calls_retry_endpoint_for_failed(self):
        body = self._fn_body()
        assert re.search(r"steps/.*retry", body)
        assert "failed" in body


# ---------------------------------------------------------------------------
# WebSocket handler — new event cases
# ---------------------------------------------------------------------------


class TestWebSocketHandlerNewEvents:
    def _handler_body(self):
        start = HTML.index("function handleWebSocketMessage")
        end = HTML.index("\n        }", start) + 10
        return HTML[start:end]

    def test_step_plan_created_handled(self):
        body = self._handler_body()
        assert "step_plan_created" in body

    def test_step_task_updated_handled(self):
        body = self._handler_body()
        assert "step_task_updated" in body

    def test_plan_completed_handled(self):
        body = self._handler_body()
        assert "plan_completed" in body

    def test_step_plan_created_calls_render_step_plan(self):
        body = self._handler_body()
        assert "renderStepPlan" in body

    def test_step_task_updated_updates_status_icon(self):
        body = self._handler_body()
        assert "getStatusIcon" in body

    def test_plan_completed_calls_render_final_evaluation(self):
        body = self._handler_body()
        assert "renderFinalEvaluation" in body

    def test_step_plan_created_fetches_plan(self):
        body = self._handler_body()
        assert re.search(r"/api/skills/multi_step_planner/plans/", body)

    def test_step_task_updated_updates_dom_step(self):
        body = self._handler_body()
        assert re.search(r"step-plan-card|data-plan-id", body)


# ---------------------------------------------------------------------------
# /plan slash command
# ---------------------------------------------------------------------------


class TestPlanSlashCommand:
    def _send_fn_body(self):
        start = HTML.index("async function sendProjectMessage")
        # Find closing brace — function is long so grab a big chunk
        end = HTML.index("document.getElementById('btn-send-project-message').addEventListener", start)
        return HTML[start:end]

    def test_slash_plan_detected(self):
        body = self._send_fn_body()
        assert "/plan " in body or "startsWith('/plan')" in body or "startsWith('/plan ')" in body

    def test_extracts_prompt_after_slash_plan(self):
        body = self._send_fn_body()
        assert re.search(r"slice\(6\)|slice\(5\)|\.slice\(.*plan", body)

    def test_calls_generate_endpoint(self):
        body = self._send_fn_body()
        assert "/api/skills/multi_step_planner/generate" in body

    def test_uses_post_method(self):
        body = self._send_fn_body()
        # The POST is in the generate call block
        assert re.search(r"method.*POST|POST.*method", body)

    def test_includes_project_id_in_body(self):
        body = self._send_fn_body()
        assert "project_id" in body and "currentProjectId" in body

    def test_loading_state_shown(self):
        body = self._send_fn_body()
        assert re.search(r"disabled\s*=\s*true|textContent.*…|….*textContent", body)

    def test_restores_input_after_completion(self):
        body = self._send_fn_body()
        assert re.search(r"input\.disabled\s*=\s*false|finally", body)

    def test_slash_plan_returns_early(self):
        body = self._send_fn_body()
        # Ensure early return after the /plan block
        assert "return;" in body
