# Refactor Branch — Test Baseline

This document captures the test suite state at the start of the `refactor` branch.
It is the safety net that must be verified after every refactor step.

## Baseline Results

| Metric | Value |
|--------|-------|
| Tests passed | 174 |
| Tests failed | 3 (pre-existing) |
| Tests collected | 177 |
| Run duration | ~14s |

## Command

```bash
/home/ai_agent/projects/claude_pool/.venv/bin/python -m pytest tests/
```

> Note: `python` in the system PATH does not have pytest installed.
> Always use the venv interpreter: `.venv/bin/python -m pytest tests/`

## Pre-existing Failures (do NOT fix during refactor)

All 3 failures are in `tests/test_tui.py` and existed on `main` before any refactor:

1. `TestTaskDetailsPanel::test_json_output_widget_update_with_task`
2. `TestTaskDetailsPanel::test_json_output_widget_pending_task`
3. `TestDataTableRowSelection::test_json_output_shows_tokens_used`

**Root cause**: The tests assert that `JsonOutputWidget.render()` includes `"Tokens used:"` or `"tokens"`, but the widget's rendered output only contains `Prompt:`, `Exit:`, `Duration:`, and `Retry:` — no token display. These tests describe desired behavior not yet implemented.

**Refactor rule**: these 3 tests may still fail after each refactor step. Any *new* failure beyond these 3 is a regression introduced by the refactor and must be fixed before proceeding.

## Coverage at Baseline

| File | Coverage |
|------|----------|
| `models.py` | 100% |
| `parser.py` | 84% |
| `storage.py` | 87% |
| `concurrency.py` | 67% |
| `executor.py` | 62% |
| `api.py` | 65% |
| `tui.py` | 59% |
| `__main__.py` | 0% |
| **Total** | **63%** |

## Deprecation Warnings (pre-existing)

`api.py` uses the deprecated `@self.app.on_event("startup"/"shutdown")` FastAPI pattern.
138 warnings are emitted during the test run. These are pre-existing and should be noted
as a follow-up improvement but are outside the refactor scope.
