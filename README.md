# Claude Pool

**A sequential (and parallel) task pool for Claude Code CLI.**

Claude Pool dispatches coding tasks to the `claude -p` CLI — with a real-time TUI, optional REST/WebSocket API, rate-limit handling, and up to 2 concurrent executions.

## Features

| Feature | Description |
|---------|-------------|
| **Sequential execution** | Tasks run one after another, each via `claude -p` |
| **Parallel execution** | Up to 2 concurrent tasks with rate-limit isolation |
| **Interactive TUI** | Real-time monitoring, add/delete/skip/retry/pause tasks |
| **Rate-limit handling** | Auto-suspension + fixed 1h backoff, no retry limit |
| **Web API** | REST endpoints + WebSocket for remote monitoring & control |
| **n8n integration** | Exportable workflow JSON for CI/CD, Slack, GitHub PRs |
| **Session reuse** | Persistent sessions per directory (no re-auth per task) |
| **Hot-reload** | Detects external `pool.json` changes (added by APIs/crons) |
| **CLI mode** | Headless `--no-tui` for server/daemon usage |

## Installation

### Requirements

- Python 3.11+
- `claude` CLI installed and authenticated (required for task execution)

### From wheel (production)

```bash
pip install claude_pool-1.0.0-py3-none-any.whl
```

### From source (development)

```bash
git clone https://github.com/MrLouix/Claude_pool.git
cd Claude_pool
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

### 1. Create a pool

```json
{
  "tasks": [
    {
      "id": "example_task",
      "prompt": "Create a hello_world.py that prints Hello World",
      "directory": "/tmp/myproject"
    }
  ],
  "pool_retry_count": 0
}
```

Save as `data/pool.json`.

### 2. Launch

```bash
# Interactive TUI
claude-pool --pool data/pool.json

# Headless mode (no TUI)
claude-pool --pool data/pool.json --no-tui

# With Web API on port 8000
claude-pool --pool data/pool.json --serve --port 8000

# Parallel mode (up to 2 concurrent tasks)
claude-pool --pool data/pool.json --no-tui --parallel 2
```

## CLI Flags

| Flag | Description |
|------|-------------|
| `--pool PATH` | Path to pool.json **(required)** |
| `--no-tui` | Run headless (no Textual UI) |
| `--serve` | Start FastAPI server alongside pool execution |
| `--port PORT` | Port for the API server (default: 8000) |
| `--parallel N` | Max concurrent tasks (default: 1, sequential) |

## Web API Endpoints

When launched with `--serve`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Pool state (suspended, retry_count, task list) |
| `GET` | `/api/tasks` | Full task list |
| `POST` | `/api/tasks` | Add a task (body: `{prompt, directory, args}`) |
| `POST` | `/api/tasks/{id}/retry` | Reset a task to pending |
| `POST` | `/api/tasks/{id}/skip` | Skip a task |
| `WS` | `/ws/events` | WebSocket stream of task updates |

A basic HTML dashboard is included at `frontend/index.html` — served statically or via the API server.

## pool.json Format

```json
{
  "tasks": [
    {
      "id": "task_20260521_001",
      "prompt": "Detailed instructions for Claude",
      "directory": "/absolute/path/to/project",
      "status": "pending",
      "args": ["--model", "haiku", "--effort", "low"],
      "exit_code": null,
      "duration_ms": null,
      "json_output": null,
      "retry_count": 0
    }
  ],
  "pool_retry_count": 0,
  "pool_suspended_until": null
}
```

### Task statuses

`pending` → `running` → `success` / `failed` / `skipped` / `rate_limit_retry`

### Task args

| Arg | Values | Default |
|-----|--------|---------|
| `--model` | `haiku`, `sonnet`, `opus` | `sonnet` |
| `--effort` | `low`, `medium`, `high`, `max` | `medium` |
| `--max-budget-usd` | Any float | No limit |
| `--add-dir` | Additional working directory | None |

## Project Structure

```
claude_pool/
├── __init__.py          # Package init
├── __main__.py          # CLI entry point (argparse)
├── models.py            # Task, PoolState dataclasses
├── executor.py          # TaskExecutor — sequential & parallel execution
├── concurrency.py       # TaskSemaphore for parallel mode
├── api.py               # FastAPI app with REST + WebSocket
├── storage.py           # pool.json load/save with state tracking
├── parser.py            # Claude JSON output parser
└── tui.py               # Textual TUI application
tests/                   # 108 unit + integration tests
docs/                    # Technical docs (see below)
n8n_workflows/           # Exportable n8n workflow JSONs
frontend/                # HTML dashboard
examples/                # Sample pool configurations
```

## Documentation

| File | Description |
|------|-------------|
| `docs/spec.md` | Complete technical specification (schemas, architecture) |
| `docs/ROADMAP.md` | Next steps and feature roadmap |
| `docs/FUTURE_STEPS.md` | Long-term vision and planned enhancements |
| `docs/N8N_INTEGRATION.md` | Guide for n8n workflow integration |

## Running Tests

```bash
cd claude_pool
source venv/bin/activate
pytest -v
```

108 tests — executor, TUI, models, parser, storage, concurrency, e2e.

## n8n Integration

The `n8n_workflows/` directory contains 4 ready-to-import workflows:

| Workflow | Purpose |
|----------|---------|
| `read_completed_tasks.json` | Read & filter completed tasks from pool.json |
| `create_github_pr.json` | Create a PR from Claude's code blocks |
| `notify_slack.json` | Send Slack notifications on task events |
| `trigger_ci.json` | Trigger CI/CD when files change |

See `docs/N8N_INTEGRATION.md` for setup instructions.

---

**Repository**: [github.com/MrLouix/Claude_pool](https://github.com/MrLouix/Claude_pool)
**License**: MIT
