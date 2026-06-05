# AGENTS.md

## Commands

```
make install      # pip install -e ".[dev]"
make format       # black + isort on team_cli/ tests/
make lint         # mypy + black --check + isort --check-only
make test         # pytest tests/ -v --cov=team_cli
make run          # python -m team_cli --pool pool.json
make clean        # remove build artifacts
```

Run `make lint` before `make test`. Use `./claude-pool.sh install` if working from a clone without an active venv.

## Architecture

Three execution modes from one entry point (`team_cli/__main__.py`):
- **TUI** (default): `claude-pool --pool pool.json` — Textual interface
- **CLI** (`--no-tui`): headless sequential execution
- **API server** (`--serve`): FastAPI + Uvicorn on port 8000, serves web dashboard + REST API + WebSocket

Core modules in `team_cli/`:
- `models.py` — Task dataclass, PoolState
- `executor.py` — TaskExecutor: loads, runs, retries tasks via `claude -p` CLI
- `api.py` — FastAPI app: REST endpoints, WebSocket events, serves `frontend/index.html`
- `storage.py` — pool.json read/write with file-watch detection
- `parser.py` — strips `reasoning` from Claude CLI JSON output
- `tui.py` — Textual app (mypy errors ignored per pyproject.toml)
- `concurrency.py` — parallel execution support (--parallel N)

## pool.json format

```json
{"tasks": [...], "pool_retry_count": 0, "pool_suspended_until": null}
```

Task statuses: `pending`, `running`, `success`, `failed`, `skipped`, `rate_limit_retry`
File is gitignored — runtime data only.

## Testing

- `pytest tests/ -v` — 146 tests, asyncio_mode = "auto"
- Shared fixtures in `tests/conftest.py`: `temp_pool_file`, `sample_task`, `multiple_tasks`, `pool_file_with_tasks`, `mock_executor`, `mock_executor_empty`
- Test files: `test_executor`, `test_tui`, `test_models`, `test_parser`, `test_storage`, `test_api`, `test_e2e`, `test_concurrency`

## Gotchas

- **Requires `claude` CLI** installed and authenticated — executor shells out to it
- **`CLAUDE.md` is stale** — says "specification phase, no code implemented" but the project is fully built. Ignore it.
- **`docs/` is gitignored** — local dev docs only
- **`package.json` is empty** — ignore it, this is a Python project
- **Python 3.11+** required
- **venv lives at `./venv/`** — use `source venv/bin/activate` or `./claude-pool.sh`
- Rate-limit retry: retry toutes les heures, sans limite d'attempts

## RTK (Token Saver)

RTK is installed (`rtk 0.40.0`) and initialized for this project. Commands like `pytest`, `ls`, `git status`, `grep` are automatically rewritten to `rtk` equivalents, saving 60-90% tokens.

- `rtk gain` — show token savings stats
- `rtk pytest tests/ -v` — run tests with compact output (~90% savings)
- `rtk read <file>` — smart file reading
- `rtk git status` — compact git status
- `rtk discover` — find missed savings opportunities
- Project filters: `.rtk/filters.toml`
