# GEMINI.md

This file provides guidance to Gemini / Antigravity when working with code in this repository.

## Project Overview

Claude Pool TUI is a Python TUI application (built with Textual) that manages a sequential pool of requests forwarded to the `claude -p` CLI. It loads tasks from `pool.json`, executes them sequentially via `claude -p <prompt> --output-format json --structured-output`, parses results, and saves state back to `pool.json`.

**Status:** Specification phase — the full spec is in `docs/spec.md`. No source code has been implemented yet.

## Development Commands

Use the following commands to install, test, lint, and run the project. Since **RTK (Rust Token Killer)** is installed, you should prefix test and lint commands with `rtk` (e.g. `rtk make test`, `rtk make lint`) to filter/compress the terminal output and optimize token usage:

- **Install dependencies:** `make install` or `pip install -e ".[dev]"`
- **Run tests:** `rtk make test` or `rtk pytest tests/ -v --cov=claude_pool`
- **Lint check:** `rtk make lint` or `rtk mypy claude_pool/ && rtk black --check claude_pool/ tests/ && rtk isort --check-only claude_pool/ tests/`
- **Format code:** `make format` or `black claude_pool/ tests/ && isort claude_pool/ tests/`
- **Run application:** `make run` or `python -m claude_pool --pool pool.json`
- **Clean build artifacts:** `make clean`
- **Check RTK stats:** `rtk gain`

## Tech Stack

- **Language:** Python 3.11+
- **TUI Framework:** Textual
- **External dependency:** `claude` CLI (must be installed and authenticated)
- **Platforms:** WSL2 / Ubuntu / macOS

## Architecture

The app follows a sequential execution model with rate-limit awareness:

- **`Task` dataclass**: Holds id, prompt, directory, args, status, exit_code, duration_ms, json_output
- **`PoolTUI(App)`**: Main Textual application with keyboard bindings (P=pause, S=skip, Del=delete, Q=quit)
- **`parse_claude_output()`**: Parses Claude CLI JSON output, strips `reasoning`, returns compact structure
- **`save_pool()` / `load_pool()`**: Serialize/deserialize tasks to `pool.json` (English-only keys)

### Execution flow

1. Load tasks from `pool.json`
2. For each pending task: `cd $directory && claude -p "$prompt" --output-format json --structured-output [args...]`
3. Handle exit codes: 0=success, 1=rate-limit retry with exponential backoff, ≥2=failed
4. Save updated state back to `pool.json`
5. On SIGINT: graceful shutdown, save current state

### Rate-limit strategy

- Trigger: exit_code==1 with rate-limit patterns, or session_usage_percent ≥ 80%
- Retry: up to 5 times, delay = `min(60 * 2^retry_count, 5 hours)` seconds

## Key Files

- [docs/spec.md](file:///home/ai_agent/projects/claude_pool/docs/spec.md) — Complete specification (JSON schema, TUI layout, class designs, retry logic, integration points)
- [docs/chat_spec.md](file:///home/ai_agent/projects/claude_pool/docs/chat_spec.md) — Chat Tab feature specification (web dashboard chat interface, bucket-based routing, REST API, WebSocket events)
- [pool.json](file:///home/ai_agent/projects/claude_pool/pool.json) — Runtime task data (JSON array of task objects)

## Constraints

- All JSON keys and UI labels must be English-only
- Per-task setup must be under 2 seconds; task timeout is 30 minutes
- Isolated `chdir` per task — no arbitrary code execution
- Logs must not leak secrets
- `json_output` must omit the `reasoning` field from Claude's response
