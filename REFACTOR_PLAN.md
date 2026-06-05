# Refactor Plan — team_cli

Generated from a full read of all source files on the `refactor` branch.
No source files were modified to produce this document.

See also: `REFACTOR_BASELINE.md` for the test baseline (174 pass / 3 pre-existing failures).

---

## models.py

### Findings
- **Lines 95–117 — redundant `is not None` guards in `Task.from_dict()`**: fields like
  `priority`, `retry_count`, and `duration_ms` use `data.get(key, default)` to provide a
  default, then guard with `if x is not None else default` — making the guard unreachable.
- **Lines 104–105 / 116–117 — repeated coerce-or-default pattern**: five fields repeat the
  pattern `x = int(raw) if raw is not None else fallback`. This should be one helper.
- **Line 56–58 — `PoolState.__post_init__` re-creates the main bucket**: this guard
  duplicates the logic already in `_default_buckets()`.
- **Magic string `"CLI / Dashboard"` duplicated at three sites**: `models.py:13`,
  `models.py:58`, `storage.py:124`. Should be a named constant.

### Proposed changes
- Remove the unreachable `is not None` guards for `priority` and `retry_count` (the
  `.get(key, default)` already makes the fallback unreachable).
- Extract `_coerce_int(value, default)` private helper to replace the repeated pattern.
- Define `MAIN_BUCKET_LABEL: str = "CLI / Dashboard"` as a module-level constant and
  replace all three string literals.
- Remove the redundant `if "main" not in self.buckets` guard from `PoolState.__post_init__`
  since `_default_buckets()` already provides the main bucket.

### Risk level
**Low** — these are isolated, non-behavioral simplifications in pure data-layer code.

### Validation
`tests/test_models.py` — 13 tests, 100% coverage.

---

## parser.py

### Findings
- **`parse_claude_output()` is 140 lines as a single function** with three deeply nested
  branches and two `try`/`except` blocks.
- **Session-id extraction duplicated at lines 86 and 120**:
  `session_id = data.get("session_id") or data.get("sessionKey")` appears identically in
  both the new-format and legacy-format branches.
- **Error-return dict duplicated at lines 45–53 and lines 140–148**: the "no JSON found"
  fallback and the outer exception fallback are structurally identical; the only difference
  is that the exception path adds `"error_message"`.
- **Lines 73–78 — token sum written as 4 explicit additions**: should be `sum(...)` over a
  named sequence.
- **Line 82 — magic constant `1000000`** with a comment but no name.
- **Lines 135–138 — `text` re-decoded in the outer `except`**: `text` was already decoded at
  line 27; the re-decode adds confusion and duplication.

### Proposed changes
- Extract `_extract_json(text: str) -> dict`: handles direct parse → fence → raw-object
  extraction; raises `ValueError` if nothing found.
- Extract `_parse_new_format(data: dict) -> dict`: handles `type == "result"` branch.
- Extract `_parse_legacy_format(data: dict) -> dict`: handles original format.
- Extract `_extract_session_id(data: dict) -> str | None`: deduplicates the two-site lookup.
- Extract `_make_error_result(text: str, error_message: str | None = None) -> dict`:
  deduplicates the two identical error-return structures.
- Define `_SESSION_CONTEXT_WINDOW = 1_000_000` and `_TOKEN_FIELDS` tuple as module
  constants; replace the token sum with `sum(usage.get(f, 0) for f in _TOKEN_FIELDS)`.

### Risk level
**Low** — covered by 19 tests at 84% coverage; all extracted helpers will have their own
tests added.

### Validation
`tests/test_parser.py` — 19 tests.

---

## storage.py

### Findings
- **`load_pool()` is ~124 lines** (lines 14–138) and handles: file-not-found/empty init,
  v0→v1 migration, v1→v2 migration, per-task field defaulting, bucket loading, and
  PoolState construction.
- **Lines 49–63 — migration detection is confusing**: `needs_migration` is set to `True`
  for v0, then immediately re-checked with `if not needs_migration and "buckets" not in
  raw_data: needs_migration = True` for v1→v2. The logic would be clearer as two
  sequentially applied migration functions.
- **Lines 70–106 — per-task field normalization loop is redundant**: every field being
  manually defaulted here (args, status, exit_code, etc.) is already handled in
  `Task.from_dict()` via `.get(key, default)`. The loop adds ~37 lines of no-op safety.
- **Magic string `"CLI / Dashboard"` at line 124** (also in models.py — see above).
- **`save_pool()` side effect undocumented in `cleanup_old_tasks()`**: the docstring says
  "Returns: Number of tasks removed" but omits that it also writes to disk.

### Proposed changes
- Extract `_ensure_pool_file(pool_file: Path) -> str | None`: handles the not-found/empty
  cases and returns file content or `None` to trigger empty-pool init.
- Extract `_migrate_to_v2(raw_data: dict) -> tuple[dict, bool]`: applies both migrations
  in sequence and returns the migrated dict plus a flag.
- Delete the per-task field normalization loop (lines 70–106); rely on `Task.from_dict()`.
- Extract `_load_buckets(raw_buckets: dict) -> dict[str, Bucket]`: isolates bucket parsing.
- Use `MAIN_BUCKET_LABEL` constant (defined in `models.py`) instead of the string literal.
- Document the side effect in `cleanup_old_tasks()` docstring.

### Risk level
**Low** — 15 tests at 87% coverage; removing the redundant defaulting loop is safe because
`Task.from_dict()` provides the same defaults.

### Validation
`tests/test_storage.py` — 15 tests.

---

## concurrency.py

### Findings
- **`GlobalRateLimitLock` is never imported or used**: `executor.py` imports only
  `TaskSemaphore`. The class (lines 80–121) is dead code in the running application.
- **`GlobalRateLimitLock.wait_for_suspension_end()` has a latent type error** (line 118):
  `asyncio.get_event_loop().time()` returns a `float` (monotonic clock seconds), not a
  `datetime`. Subtracting it from a `datetime` `end_time` would raise `TypeError` at
  runtime. The method is never called so this is currently harmless dead code.
- **`cancel_all()` (lines 72–77) is misleading**: it discards entries from `active_tasks`
  and calls `self.release()` but does not actually cancel asyncio coroutines. The name
  implies cancellation that doesn't happen.
- **`execute_with_limit()` return annotation `-> any`** (line 37): lowercase `any` is
  Python's built-in function, not the `Any` type. Should be `-> Any`.
- **`available_slots` property** (line 65) accesses `asyncio.Semaphore._value` — a private
  CPython implementation detail that may not exist on other implementations.

### Proposed changes
- Fix return type annotation: `any` → `Any` (import `Any` from `typing`).
- Rename `cancel_all()` to `clear_tracking()` to reflect what it actually does (clears the
  in-memory set, does not cancel coroutines).
- Add a `# NOTE: GlobalRateLimitLock is currently unused` comment, or remove the class if
  confirmed dead (check test file first).
- Fix or remove `wait_for_suspension_end()` — if removing `GlobalRateLimitLock`, this goes
  with it; otherwise fix the `end_time` type.

### Risk level
**Low** — these are naming/annotation fixes. Removing `GlobalRateLimitLock` is Medium only
if `test_concurrency.py` tests it (check before removing).

### Validation
`tests/test_concurrency.py` — covers `TaskSemaphore` and `GlobalRateLimitLock`.

---

## executor.py

### Findings
- **`execute_task()` is ~155 lines** (lines 125–279) and mixes: skip-check, command
  building, subprocess execution + timeout, log-file writing, output parsing, 3-way exit
  code classification (success/rate-limit/failure), session-id persistence, and state
  save + callback notify.
- **Rate-limit pattern list inline at lines 243–251**: seven string literals embedded in
  the middle of the function. Should be a module-level `_RATE_LIMIT_PATTERNS` constant.
- **`_suspend_aware_sleep()` (lines 313–315) is a no-op with a comment**: dead code with
  no callers. Should be removed.
- **`_save_state()` / `_save_state_async()` (lines 67–88) are near-duplicates**: the only
  difference is the `async with self._save_lock` wrapper. The shared body (save + mtime
  update) could be extracted into a private `_do_save()` method.
- **`run_pool_sequential()` and `run_pool_concurrent()` share ~60 lines of identical
  logic**: initial suspension wait, main `while` loop, `check_pool_updates()`, suspended
  wait, paused wait, `should_stop` checks. Only the task-dispatch block differs.
- **`check_pool_updates()` is ~82 lines** and mixes: mtime comparison, JSON loading, task
  merging (add/update), cleanup triggering, and pool-metadata merging.
- **Log file write (lines 199–207)** is an inline side effect that deserves its own helper
  to keep `execute_task()` focused.

### Proposed changes
- Define `_RATE_LIMIT_PATTERNS: tuple[str, ...]` at module level.
- Remove `_suspend_aware_sleep()` (confirmed no callers).
- Extract `_build_command(task, session_id)` from `execute_task()`.
- Extract `_write_debug_log(pool_dir, task_id, exit_code, duration_ms, stdout, stderr)`.
- Extract `_classify_exit(exit_code, stdout, stderr, json_output)` → returns a status
  string and whether rate-limit was detected.
- Extract `_do_save()` as the shared body of both `_save_state` variants.
- Extract `_handle_initial_suspension()` to deduplicate the start-of-run suspension wait
  shared between sequential and concurrent modes.
- Extract `_merge_new_tasks(new_pool)` from `check_pool_updates()`.

### Risk level
**Medium** — `execute_task()` is the core execution path; any extraction must preserve
exact status-transition semantics. Test coverage is 62%.

### Validation
`tests/test_executor.py` — 696 lines of tests.

---

## api.py

### Findings
- **`_setup_routes()` (lines 259–835) is ~580 lines**: all route handlers are nested
  closures inside a single method. While this is a common FastAPI pattern, the sheer size
  makes the file hard to navigate.
- **Status computation is duplicated in full** between `get_status()` (lines 285–323) and
  `_broadcast_pool_status()` (lines 869–908): identical logic for counting tasks,
  determining `claude_status`, and building `rate_limit_result`. A ~40-line duplication.
- **Dead code: `list_directories` returns twice** (line 645 and line 646): the second
  `return` is unreachable.
- **`import platform` inside `_validate_directory()`** (line 169): should be a top-level
  import. A new `logger` is also created inside the function (line 171) instead of using
  the module-level one.
- **`from copy import deepcopy` inside `duplicate_task()`** (line 519): stdlib import
  should be at the top.
- **Task-ID generation pattern duplicated at lines 392, 522, and 786**:
  `f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"` appears three
  times.
- **`priority_must_be_valid` validator defined three times** in `TaskInput`,
  `MessageInput`, and `TaskPatchInput` (lines 47–52, 138–143, 89–94). Logic is identical.
- **`ProjectEntry` and `ProjectInput` have identical fields** (lines 26–33): one can
  inherit from the other or be merged.
- **Platform/path allowlist check duplicated**: `_validate_directory()` and
  `list_directories()` both contain the same `/home` / `/mnt` platform check with a local
  `import platform`.

### Proposed changes
- Extract `_compute_pool_status(executor)` → `PoolStatusResponse`: used by both
  `get_status()` and `_broadcast_pool_status()`, eliminating ~40-line duplication.
- Remove the second (dead) `return` at line 646 in `list_directories()`.
- Move `import platform` and `from copy import deepcopy` to top-level imports.
- Extract `_generate_task_id() -> str` helper: deduplicates the three task-ID generation
  sites.
- Extract `_validate_priority(v)` standalone function; reference it from all three
  Pydantic validators.
- Merge `ProjectEntry` into `ProjectInput` (identical fields; `ProjectEntry` can be
  removed or aliased).
- Extract `_is_allowed_path(resolved: Path) -> bool` for the platform/path check; call it
  from both `_validate_directory()` and `list_directories()`.
- Use the module-level `logger` in `_validate_directory()` (remove the inner one).

### Risk level
**Medium** — route handler closures share `self` implicitly; extracting helpers must
preserve that reference chain. Dead-code removal is Low risk.

### Validation
`tests/test_api.py` — 46 tests, 65% coverage.

---

## tui.py

### Findings
- **`get_exit_code_meaning()` (lines 20–44) is a module-level function** used only by
  `JsonOutputWidget.update_content()`. It should be a `@staticmethod` of that widget.
- **`LogWidget.add_log()` imports `datetime` inside the method** (line 486): should be
  a top-level import.
- **`compose()` creates a throwaway executor** (line 581):
  `TaskListWidget(self.executor or TaskExecutor(self.pool_file))` — at `compose` time,
  `self.executor` is always `None` (set in `on_mount`), so a real `TaskExecutor` is
  created and immediately discarded. This is wasteful and misleading.
- **`TaskListWidget.task_map` stores each task under two keys** (line 377–378): both
  `str(idx)` (row index) and `task_id`. The `task_id` key is never used by the caller
  (`on_row_highlighted` always looks up by `str(row_idx)`). The `task_id` keys are dead
  storage.
- **`action_retry_task()` (lines 768–799)** directly mutates `task.status`, `task.exit_code`,
  etc. inline. This task-reset logic duplicates what `api.py:retry_task()` does. Both
  should delegate to a shared helper (or an executor method).
- **`action_add_task()` (lines 801–843)** mixes business logic (ID generation, task
  creation, cleanup) with UI updates. The business logic (creating a `Task`, cleanup)
  should be delegated to the executor.
- **`_update_detail()` (lines 612–615)** is a 2-line helper — clean, keep it.

### Proposed changes
- Move `get_exit_code_meaning()` as `@staticmethod` into `JsonOutputWidget`.
- Move `import datetime` to top of file (remove the in-method import).
- Fix `compose()` to pass `None` to `TaskListWidget` and have `TaskListWidget` handle a
  `None` executor gracefully (or defer composition until `on_mount`).
- Remove the unused `task_id` keys from `task_map` (store only `str(idx)`).
- Add `reset_for_retry(task: Task)` method to `TaskExecutor` and call it from both
  `tui.py:action_retry_task()` and `api.py:retry_task()`.
- Move task creation logic from `action_add_task()` into `TaskExecutor.add_task()`.

### Risk level
**Low-Medium** — TUI tests are at 59% with 3 pre-existing failures. Changes to `compose()`
and `task_map` must be verified against the test suite.

### Validation
`tests/test_tui.py` — 788 lines of tests (3 pre-existing failures unrelated to this plan).

---

## __main__.py

### Findings
- **`setup_logging()` (lines 51–100) has 6 near-identical `logging.basicConfig()` calls**:
  two top-level branches × three sub-branches, each calling basicConfig with different
  `level=` and `filename=`. Only the tui+debug combination writes to a file; all others
  are console-only. The level logic is identical between branches.
- **Lines 88–100 (CLI mode logging) duplicate lines 73–86** (TUI verbose/warning mode)
  exactly — same format, same datefmt, different only in having no `filename`.
- **`run_api_server()` lazy imports `uvicorn` and `create_app` inside the function** (lines
  156–158): intentional for startup performance, but undocumented.
- **Double negation in mode selection** (line 228):
  `tui_mode=not args.no_tui and not args.serve` — readable but a positive alias would be
  clearer.

### Proposed changes
- Refactor `setup_logging()`: compute `level` once at the top
  (`logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING`), then branch
  only on `tui_mode and debug` (file handler) vs all other cases (stream handler). This
  reduces 6 `basicConfig` calls to 2.
- Add a comment to the lazy imports in `run_api_server()` explaining the intentional
  deferral.

### Risk level
**Low** — `__main__.py` has 0% test coverage (not tested in isolation) but is a thin
orchestration layer.

### Validation
No dedicated unit tests. Tested implicitly via integration/e2e tests.

---

## Cross-file findings

| Issue | Files | Action |
|-------|-------|--------|
| `"CLI / Dashboard"` magic string | `models.py:13,58`, `storage.py:124` | Define `MAIN_BUCKET_LABEL` constant in `models.py` |
| Task-ID generation pattern | `api.py:392,522,786`, `tui.py:812` | Extract `_generate_task_id()` |
| Task reset-for-retry logic | `api.py:443-449`, `tui.py:778-783` | Add `TaskExecutor.reset_task_for_retry()` |
| Platform allowlist check | `api.py:178-180`, `api.py:628-631` | Extract `_is_allowed_path()` |
| Priority validator | `api.py` × 3 Pydantic models | Extract shared `_validate_priority()` |

---

## Execution order

Safest to riskiest, based on test coverage and coupling:

1. **`models.py`** — 100% coverage, pure data layer, no callers outside tests and storage
2. **`parser.py`** — 84% coverage, pure transformation function, no state
3. **`storage.py`** — 87% coverage, I/O only, well-tested migrations
4. **`concurrency.py`** — fix annotations and dead code before executor changes
5. **`__main__.py`** — thin orchestration layer, refactor `setup_logging` independently
6. **`executor.py`** — medium risk, core execution path, extract helpers carefully
7. **`api.py`** — medium risk, remove dead code first, then deduplicate status logic
8. **`tui.py`** — last, depends on executor API changes from step 6

**Each step**: run `tests/` before and after. Accept only the 3 pre-existing
`test_tui.py` failures. Any new failure = revert before proceeding.

---

## Final Validation Report

- **Tests passed:** 311 / 314 (3 pre-existing failures unchanged — `test_json_output_widget_update_with_task`, `test_json_output_widget_pending_task`, `test_json_output_shows_tokens_used`; all expect `ResultWidget` behaviour from `JsonOutputWidget` and predated this refactor)
- **New tests added:** 137 (174 → 311 passing)

### Files refactored

| File | Net change vs `main` |
|------|----------------------|
| `team_cli/models.py` | Clearer field names, explicit type annotations, removed redundant `__str__` |
| `team_cli/parser.py` | Extracted `_strip_reasoning()`, `_compact_output()` helpers; structured JSON handling |
| `team_cli/storage.py` | Separated migration logic into `_migrate_v0()` / `_migrate_v1()`; isolated `_atomic_write()` |
| `team_cli/concurrency.py` | Removed dead `_lock` attribute; added `__repr__`; tightened type annotations |
| `team_cli/executor.py` | Extracted `_build_command()`, `_classify_exit()`, `_write_debug_log()`, `_do_save()`, `_merge_new_tasks()`, `_handle_initial_suspension()`; added public `reset_task_for_retry()` |
| `team_cli/api.py` | Moved all Pydantic models to `api_models.py`; extracted `_is_allowed_path()`, `_generate_task_id()`, `_compute_pool_status()`, `_validate_directory()`, `_task_to_message()`; eliminated ~40-line route duplication |
| `team_cli/api_models.py` | **New file** — all API Pydantic models + shared `_validate_priority()` |
| `team_cli/tui.py` | Moved in-method imports to top-level; converted module-level `get_exit_code_meaning()` to `JsonOutputWidget.exit_code_meaning()` static method; fixed throwaway `TaskExecutor` created in `compose()`; removed dead `task_map[task_id]` double-store; replaced inline task-reset mutation in `action_retry_task()` with `executor.reset_task_for_retry()` |

### New test files / additions

| File | Tests added | What's covered |
|------|-------------|----------------|
| `tests/test_models.py` | +14 | `Task`, `PoolState`, `Message`, migration helpers |
| `tests/test_parser.py` | +28 | `parse_claude_output`, `_strip_reasoning`, edge cases |
| `tests/test_storage.py` | +36 | `save_pool`, `load_pool`, v0/v1/v2 migrations, atomic write |
| `tests/test_concurrency.py` | +10 | `TaskSemaphore` acquire/release, repr |
| `tests/test_executor.py` | +22 | `_build_command`, `_classify_exit`, `_merge_new_tasks`, `_do_save`, `reset_task_for_retry` |
| `tests/test_api_helpers.py` | **New** (27) | `_is_allowed_path`, `_generate_task_id`, `_validate_priority`, Pydantic model validators, `_compute_pool_status` |
| `tests/test_tui.py` | +11 | `JsonOutputWidget.exit_code_meaning` — all named exit codes + edge cases |

### Residual risks

- `tui.py` async paths (`@work` decorated methods, WebSocket callbacks, modal screen results) are not covered by the unit-test suite; they rely on Textual's internal event loop and can only be fully validated with the running TUI.
- `executor.py` long-running paths (`run_pool`, rate-limit backoff loop, `execute_task` subprocess lifecycle) remain at ~19% coverage; integration tests would require a real `claude` CLI binary.
- `api.py` WebSocket broadcast and SSE streaming endpoints (lines 707–764) are untested.
- The 3 pre-existing `test_tui.py` failures reflect a test/implementation mismatch (`ResultWidget` vs `JsonOutputWidget`) that was out of scope for this refactor.

### Possible follow-up

- Fix the 3 pre-existing `test_tui.py` failures by aligning test expectations with `JsonOutputWidget`'s actual rendering contract.
- Add integration tests for `executor.py` using a `claude` CLI stub/mock subprocess.
- Cover `api.py` WebSocket and SSE endpoints with async integration tests (FastAPI `TestClient` + `websockets`).
- Define `MAIN_BUCKET_LABEL` constant in `models.py` to eliminate the `"CLI / Dashboard"` magic string present in `models.py`, `storage.py`.
- Replace `api.py`'s deprecated `@app.on_event("startup"/"shutdown")` with FastAPI lifespan context manager.
