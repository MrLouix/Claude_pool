# Claude Pool TUI

A Text User Interface (TUI) application for managing sequential pools of Claude Code CLI tasks.

## Overview

Claude Pool TUI automates the execution of multiple Claude Code tasks in sequence, with:
- **Rate-limit handling**: Automatic exponential backoff and global pool suspension on rate limits
- **Interactive TUI**: Real-time monitoring with Textual framework and DataTable display
- **Task management**: Add, pause, delete, retry tasks on the fly
- **Persistent state**: Tasks saved to `pool.json` after each execution
- **Structured output**: Parses Claude's JSON output with token tracking
- **Auto-completion**: Minimal task definition (only prompt & directory required)
- **Scrollable panels**: Full result display with scroll support

## Installation

### Requirements

- Python 3.11+
- `claude` CLI installed and authenticated (optional for development)

### Quick Install

```bash
git clone https://github.com/MrLouix/Claude_pool.git
cd Claude_pool
./claude-pool.sh install
```

This will:
- Create a Python virtual environment
- Install all dependencies
- Set up the `claude-pool` command

## Usage

### Quick Start

1. Create a `pool.json` file with your tasks (minimal format):

```json
{
  "tasks": [
    {
      "prompt": "Fix the login bug in auth.py",
      "directory": "/home/user/my-project"
    }
  ]
}
```

All other fields (`id`, `args`, `status`, etc.) are auto-generated if missing.

2. Run the TUI:

```bash
./claude-pool.sh --pool pool.json
```

Or try the example:

```bash
./claude-pool.sh --pool examples/pool.json
```

### Command Line Options

```bash
./claude-pool.sh [OPTIONS]

Options:
  --pool PATH       Path to pool.json file (default: pool.json)
  --no-tui          Run in CLI mode without TUI
  -v, --verbose     Enable verbose logging (INFO level)
  --debug           Enable debug logging (DEBUG level, writes to file in TUI mode)
  -h, --help        Show help message

Special:
  install          Run installation/setup
```

### Examples

```bash
# Run with TUI (interactive)
./claude-pool.sh --pool examples/pool.json

# Run in CLI mode (headless)
./claude-pool.sh --pool pool.json --no-tui


### Valid Model Names

Use these model aliases in the `args` field:
- `haiku` - Fastest, most cost-effective
- `sonnet` - Balanced performance
- `opus` - Most capable

Or use full model names like `claude-sonnet-4-6`.

# Run with verbose logging
./claude-pool.sh --pool pool.json -v

# Reinstall or setup
./claude-pool.sh install
```

## TUI Controls

| Key | Action |
|-----|--------|
| **↑ / ↓** | Navigate tasks / Scroll in focused panel |
| **Tab** | Switch focus between panels |
| **Click** | Select task or focus panel |
| **A** | Add new task (opens form dialog) |
| **P** | Pause/Resume execution |
| **D** | Delete selected task (with confirmation) |
| **R** | Retry selected task (reset to pending) |
| **Enter** | Show detailed JSON output (modal) |
| **Q** | Quit application |

### TUI Layout

- **Top Panel (25%)**: Task list in table format (ID, Prompt preview, Directory, Status)
- **Middle Panel (50%)**: Selected task details (Prompt, Exit code, Duration, Tokens, Result, Files)
- **Bottom Panel (18%)**: Real-time logs
- **Control Bar**: Buttons for quick actions

All panels support scrolling when content exceeds visible area.

## Task JSON Schema

### Required Fields (User-Provided)

- `prompt` (string): Task description passed to `claude -p`
- `directory` (string): Working directory for task execution

### Auto-Generated Fields

- `id` (string): Auto-generated unique identifier (format: `task_YYYYMMDD_HHMMSS_uuid`)

### Optional Fields

- `args` (array): Additional CLI arguments for claude (e.g., `["--model", "haiku"]`)
- `status` (string): `pending`, `running`, `success`, `failed`, `skipped`, `rate_limit_retry`
- `exit_code` (int|null): Exit code from claude command
- `duration_ms` (int|null): Execution time in milliseconds
- `json_output` (object|null): Parsed output from claude
- `retry_count` (int): Number of retries (default: 0)

### JSON Output Structure

After execution, `json_output` contains:

```json
{
  "result": "Task summary",
  "code_blocks": [
    {
      "language": "python",
      "filename": "auth.py",
      "content": "def login(...)..."
    }
  ],
  "files_changed": ["/path/to/file1.py", "/path/to/file2.py"],
  "tokens_used": 1500,
  "session_usage_percent": 25.5
}
```

## Rate Limiting

When Claude hits rate limits (exit code 1 or session usage ≥ 80%):
- **Global pool suspension**: All execution pauses
- **Exponential backoff**: `min(60 * 2^pool_retry_count, 5 hours)` seconds
- **Maximum 5 retries** for the entire pool
- **Automatic resume**: Pool resumes after suspension period
- **Task retry**: Failed task is retried first after resume
- **Session tracking**: Monitors `session_usage_percent` to prevent limits

## Development

### Manual Setup

If you prefer manual setup instead of the launcher script:

```bash
python -m venv venv
. venv/bin/activate  # or `source venv/bin/activate` on some shells
pip install -e ".[dev]"
```

### Run Tests

```bash
make test
```

### Format Code

```bash
make format
```

### Type Check

```bash
make lint
```

### All Commands

```bash
make help
```

## Integration Examples

### n8n Workflow

Read `pool.json` with a File node, extract `json_output.code_blocks[0].content`, and apply patches with a Function node.

### Home Assistant / OpenClaw

Monitor `pool.json` for status changes and display `session_usage_percent` in dashboards.

## Troubleshooting

### "claude: command not found"

Ensure `claude` CLI is installed and in your PATH:

```bash
which claude
claude --version
```

### "Virtual environment not found"

Run the installation:

```bash
./claude-pool.sh install
```

### Rate Limit Errors

Check `session_usage_percent` in task output. If consistently hitting limits:
- Reduce concurrent tasks
- Increase backoff time
- Spread tasks across multiple sessions

### Tasks Not Starting

Verify:
- `pool.json` exists and is valid JSON
- `directory` paths exist and are accessible
- `claude` is authenticated (`claude auth status`)

## Architecture

- **models.py**: `Task` dataclass
- **storage.py**: `load_pool()` / `save_pool()` functions
- **parser.py**: `parse_claude_output()` for JSON extraction
- **executor.py**: `TaskExecutor` with rate-limit logic
- **tui.py**: Textual-based interactive interface
- **__main__.py**: CLI entry point

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

See LICENSE file for details.
