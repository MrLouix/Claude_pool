# Examples

This directory contains example pool files for Claude Pool TUI.

## Files

### `pool.json`
Main example file with various task types demonstrating different features:
- Simple text file creation
- File analysis tasks
- Different models (haiku, sonnet)
- Effort levels
- Multiple tasks with different statuses

**Usage:**
```bash
./claude-pool.sh --pool examples/pool.json
```

### `example_pool.json`
Minimal example showing the simplest possible pool structure with basic tasks.

**Usage:**
```bash
./claude-pool.sh --pool examples/example_pool.json
```

### `test_pool.json`
Small test file for quick testing and development.

### `pool_backup.json`
Backup of a previous pool state (for reference).

## Creating Your Own Pool

Minimal format (only required fields):
```json
{
  "tasks": [
    {
      "prompt": "Your task description here",
      "directory": "/path/to/working/directory"
    }
  ]
}
```

Full format (with all optional fields):
```json
{
  "pool_retry_count": 0,
  "pool_suspended_until": null,
  "tasks": [
    {
      "id": "task_001",
      "prompt": "Your task description",
      "directory": "/path/to/working/directory",
      "args": ["--model", "haiku", "--effort", "low"],
      "status": "pending",
      "exit_code": null,
      "duration_ms": null,
      "json_output": null,
      "retry_count": 0
    }
  ]
}
```

## Tips

- **Start simple**: Use only `prompt` and `directory` - everything else is auto-generated
- **Use relative paths**: For portable pools across machines
- **Add tasks via TUI**: Press 'A' in the TUI to add tasks interactively
- **Model selection**: `haiku` (fast/cheap), `sonnet` (balanced), `opus` (powerful)
- **Effort levels**: `low`, `medium`, `high`, `xhigh`, `max`
