# Claude Pool TUI

A Text User Interface (TUI) application for managing sequential pools of Claude Code CLI tasks.

## Overview

Claude Pool TUI automates the execution of multiple Claude Code tasks in sequence, with:
- **Rate-limit handling**: Automatic exponential backoff when hitting rate limits
- **Interactive TUI**: Real-time monitoring with Textual framework
- **Task management**: Pause, skip, delete tasks on the fly
- **Persistent state**: Tasks saved to `pool.json` after each execution
- **Structured output**: Parses Claude's JSON output for easy integration

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

1. Create a `pool.json` file with your tasks:

```json
[
  {
    "id": "task_001",
    "prompt": "Fix the login bug in auth.py",
    "directory": "/home/user/my-project",
    "args": ["--model", "sonnet"],
    "status": "pending",
    "exit_code": null,
    "duration_ms": null,
    "json_output": null,
    "retry_count": 0
  }
]
```

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
  -v, --verbose     Enable verbose logging
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
| **↑ / ↓** | Navigate tasks |
| **Enter** | Show detailed JSON output |
| **P** | Pause/Resume execution |
| **S** | Skip current task |
| **D** | Delete selected task (with confirmation) |
| **Q** | Quit application |

## Task JSON Schema

### Required Fields

- `id` (string): Unique task identifier
- `prompt` (string): Task description passed to `claude -p`
- `directory` (string): Working directory for task execution

### Optional Fields

- `args` (array): Additional CLI arguments for claude
- `status` (string): `pending`, `running`, `success`, `failed`, `rate_limit_retry`
- `exit_code` (int|null): Exit code from claude command
- `duration_ms` (int|null): Execution time in milliseconds
- `json_output` (object|null): Parsed output from claude
- `retry_count` (int): Number of rate-limit retries (default: 0)

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

When Claude hits rate limits:
- Tasks automatically enter `rate_limit_retry` status
- Exponential backoff: `min(60 * 2^retry_count, 18000)` seconds
- Maximum 5 retries per task
- Pool execution pauses during backoff

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
