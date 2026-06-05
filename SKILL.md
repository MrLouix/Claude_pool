# TeamCLI Integration Guide for AI Agents

This guide explains how AI agents (OpenClaw, Hermes, n8n workflows, etc.) can interact with TeamCLI by adding tasks and retrieving results.

## Quick Start

TeamCLI uses a simple JSON file (`pool.json`) for task management. AI agents can:
1. Add tasks by modifying the JSON file
2. Monitor task status by reading the JSON file
3. Retrieve results from completed tasks

## File Location

Default: `pool.json` in the TeamCLI directory

Custom location can be specified when running:
```bash
./claude-pool.sh --pool /path/to/custom-pool.json
```

## JSON Structure

### Minimal Task Addition

To add a task, you only need two fields:

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

All other fields (`id`, `status`, `args`, etc.) are auto-generated.

### Full Task Structure

```json
{
  "pool_retry_count": 0,
  "pool_suspended_until": null,
  "tasks": [
    {
      "id": "task_20260513_103045_a1b2c3d4",
      "prompt": "Analyze this codebase and suggest improvements",
      "directory": "/home/user/project",
      "args": ["--model", "sonnet", "--effort", "high"],
      "status": "pending",
      "exit_code": null,
      "duration_ms": null,
      "json_output": null,
      "retry_count": 0
    }
  ]
}
```

## Task States

| Status | Description |
|--------|-------------|
| `pending` | Task waiting to be executed |
| `running` | Task currently executing |
| `success` | Task completed successfully |
| `failed` | Task failed with error |
| `rate_limit_retry` | Task hit rate limit, will retry |
| `skipped` | Task was skipped |

## Adding a Task (Agent Workflow)

### Step 1: Read existing pool.json

```python
import json
from pathlib import Path

pool_file = Path("pool.json")

# Load existing pool or create new
if pool_file.exists():
    with open(pool_file, 'r') as f:
        pool = json.load(f)
else:
    pool = {"pool_retry_count": 0, "pool_suspended_until": null, "tasks": []}
```

### Step 2: Add your task

```python
import uuid
from datetime import datetime

# Generate a custom ID for easy retrieval
# Format: task_YYYYMMDD_HHMMSS_<8char_uuid>
custom_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

new_task = {
    "id": custom_id,  # Recommended: set your own ID for easy lookup
    "prompt": "Explain how the authentication system works",
    "directory": "/home/user/my-project",
    # Optional: add model and effort level
    "args": ["--model", "haiku", "--effort", "low"]
}

pool["tasks"].append(new_task)

# Save the ID for later retrieval
return custom_id  # Use this to find your task later
```

**Note:** While `id` is auto-generated if omitted, it's **highly recommended** for AI agents to set their own ID using the format above. This makes task tracking much easier.

### Step 3: Save pool.json

```python
with open(pool_file, 'w') as f:
    json.dump(pool, f, indent=2)
```

### Step 4: Wait for completion

```python
import time

task_id = None  # Will be auto-generated

while True:
    with open(pool_file, 'r') as f:
        pool = json.load(f)
    
    # Find your task (by prompt or id if you know it)
    for task in pool["tasks"]:
        if task["prompt"] == "Explain how the authentication system works":
            if task["status"] == "success":
                result = task["json_output"]["result"]
                print(f"Task completed: {result}")
                break
            elif task["status"] == "failed":
                print(f"Task failed: {task.get('json_output', {}).get('result', 'Unknown error')}")
                break
    else:
        # Task not finished, wait
        time.sleep(5)
        continue
    break
```

## Retrieving Results

Once a task completes, the `json_output` field contains:

```json
{
  "result": "The authentication system uses JWT tokens...",
  "code_blocks": [
    {
      "language": "python",
      "filename": "auth.py",
      "content": "def authenticate(user, password):\n    ..."
    }
  ],
  "files_changed": ["/home/user/project/auth.py"],
  "tokens_used": 15420,
  "session_usage_percent": 7.71
}
```

### Extracting Specific Information

```python
task = pool["tasks"][0]  # Your completed task

# Get main result text
result_text = task["json_output"]["result"]

# Get code blocks (if Claude wrote code)
code_blocks = task["json_output"]["code_blocks"]
for block in code_blocks:
    language = block["language"]
    filename = block["filename"]
    code = block["content"]
    print(f"Code in {filename} ({language}):")
    print(code)

# Get list of modified files
files_changed = task["json_output"]["files_changed"]
print(f"Modified files: {files_changed}")

# Get token usage
tokens = task["json_output"]["tokens_used"]
usage_percent = task["json_output"]["session_usage_percent"]
print(f"Used {tokens:,} tokens ({usage_percent}% of session)")

# Get execution info
exit_code = task["exit_code"]  # 0 = success, 1 = rate limit, >1 = error
duration_ms = task["duration_ms"]
print(f"Completed in {duration_ms/1000:.1f}s with exit code {exit_code}")
```

## Advanced: Model and Effort Selection

### Available Models

```python
# Fast and cheap
task["args"] = ["--model", "haiku"]

# Balanced (default)
task["args"] = ["--model", "sonnet"]

# Most capable
task["args"] = ["--model", "opus"]
```

### Available Effort Levels

```python
# Quick responses
task["args"] = ["--effort", "low"]

# Standard (default)
task["args"] = ["--effort", "medium"]

# More thorough
task["args"] = ["--effort", "high"]

# Maximum quality
task["args"] = ["--effort", "max"]

# Combine model and effort
task["args"] = ["--model", "sonnet", "--effort", "high"]
```

### Additional Options

```python
# Limit budget
task["args"] = ["--max-budget-usd", "0.50"]

# Add extra directories
task["args"] = ["--add-dir", "/path/to/extra/dir"]

# Combine multiple options
task["args"] = [
    "--model", "haiku",
    "--effort", "low",
    "--max-budget-usd", "0.25",
    "--add-dir", "/path/to/docs"
]
```

## Complete Example: Agent Integration

```python
import json
import time
from pathlib import Path

class ClaudePoolClient:
    def __init__(self, pool_file="pool.json"):
        self.pool_file = Path(pool_file)
    
    def add_task(self, prompt, directory, model="sonnet", effort="medium"):
        """Add a task to the pool"""
        # Load existing pool
        if self.pool_file.exists():
            with open(self.pool_file, 'r') as f:
                pool = json.load(f)
        else:
            pool = {"pool_retry_count": 0, "pool_suspended_until": None, "tasks": []}
        
        # Create task
        task = {
            "prompt": prompt,
            "directory": str(directory),
            "args": ["--model", model, "--effort", effort]
        }
        
        pool["tasks"].append(task)
        
        # Save pool
        with open(self.pool_file, 'w') as f:
            json.dump(pool, f, indent=2)
        
        return len(pool["tasks"]) - 1  # Return task index
    
    def wait_for_task(self, task_index, timeout=600, poll_interval=5):
        """Wait for a task to complete and return the result"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with open(self.pool_file, 'r') as f:
                pool = json.load(f)
            
            task = pool["tasks"][task_index]
            
            if task["status"] == "success":
                return {
                    "success": True,
                    "result": task["json_output"]["result"],
                    "code_blocks": task["json_output"].get("code_blocks", []),
                    "files_changed": task["json_output"].get("files_changed", []),
                    "tokens_used": task["json_output"].get("tokens_used", 0),
                    "duration_ms": task["duration_ms"]
                }
            elif task["status"] == "failed":
                return {
                    "success": False,
                    "error": task["json_output"].get("result", "Unknown error"),
                    "exit_code": task["exit_code"]
                }
            
            time.sleep(poll_interval)
        
        return {"success": False, "error": "Timeout waiting for task"}

# Usage
client = ClaudePoolClient("pool.json")

# Add task
task_idx = client.add_task(
    prompt="Review this code and suggest improvements",
    directory="/home/user/my-project",
    model="sonnet",
    effort="high"
)

# Wait for result
result = client.wait_for_task(task_idx, timeout=300)

if result["success"]:
    print(f"Result: {result['result']}")
    print(f"Tokens used: {result['tokens_used']:,}")
    print(f"Files changed: {result['files_changed']}")
else:
    print(f"Task failed: {result['error']}")
```

## Rate Limiting

TeamCLI handles rate limits automatically:

- Pool suspends when rate limits are hit
- Exponential backoff (up to 5 hours)
- Automatic resume after suspension
- Check `pool_suspended_until` to know when execution will resume

```python
if pool.get("pool_suspended_until"):
    from datetime import datetime
    resume_time = datetime.fromisoformat(pool["pool_suspended_until"])
    print(f"Pool suspended until {resume_time}")
```

## Task Cleanup

Old completed tasks should be cleaned up regularly to keep pool.json manageable.

### Automatic Cleanup Function

```python
from datetime import datetime, timedelta

def cleanup_old_tasks(pool_file, max_age_hours=48):
    """Remove completed/failed tasks older than max_age_hours.
    
    Only removes tasks with status: success, failed, or skipped.
    Pending and running tasks are never removed.
    """
    with open(pool_file, 'r') as f:
        pool = json.load(f)
    
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    initial_count = len(pool["tasks"])
    
    # Keep tasks that are:
    # - pending or running (regardless of age)
    # - OR created within the max_age window
    pool["tasks"] = [
        task for task in pool["tasks"]
        if task["status"] in ("pending", "running", "rate_limit_retry")
        or datetime.fromisoformat(task["created_at"]) > cutoff_time
    ]
    
    removed_count = initial_count - len(pool["tasks"])
    
    if removed_count > 0:
        with open(pool_file, 'w') as f:
            json.dump(pool, f, indent=2)
        print(f"Cleaned up {removed_count} old tasks")
    
    return removed_count

# Usage: run daily or weekly
cleanup_old_tasks("pool.json", max_age_hours=48)
```

### When to Clean

- **Daily**: For high-volume automation (100+ tasks/day)
- **Weekly**: For moderate use (10-50 tasks/day)
- **Monthly**: For occasional use (<10 tasks/day)
- **Before adding tasks**: If pool.json is getting large (>1MB)

## Best Practices

1. **Set your own task ID**: Use format `task_YYYYMMDD_HHMMSS_<uuid>` for easy retrieval
2. **Always read before write**: Load existing pool.json before adding tasks
3. **Use appropriate models**: `haiku` for simple tasks, `sonnet` for most work, `opus` for complex analysis
4. **Set effort levels**: Use `low` for quick responses, `high` for thorough analysis
5. **Monitor session usage**: Check `session_usage_percent` to avoid rate limits
6. **Handle failures**: Check `status` and `exit_code` for error handling
7. **Poll wisely**: Don't poll too frequently (5-10 second intervals are good)
8. **Use absolute paths**: For `directory` field to avoid ambiguity
9. **Clean up regularly**: Remove old completed tasks to keep pool.json manageable
10. **Track created_at**: The `created_at` timestamp is auto-generated for all tasks

## Integration Examples

### n8n Workflow

```
[Trigger] → [Read File: pool.json] → [Set Data: add task] → 
[Write File: pool.json] → [Wait 10s] → [Loop until success]
```

### OpenClaw/Hermes

Use the Python example above as a custom skill/tool.

### REST API (via wrapper)

Create a simple Flask/FastAPI wrapper around the ClaudePoolClient class.

## Troubleshooting

### Task stuck in "pending"
- Check if TeamCLI TUI is running: `./claude-pool.sh --pool pool.json`
- Check pool suspension: look at `pool_suspended_until`

### Task failed immediately
- Check `exit_code` and `json_output.result` for error message
- Verify `directory` path exists and is accessible
- Ensure Claude CLI is authenticated

### Can't find completed task
- Tasks may have auto-generated IDs
- Search by prompt text or use task index
- Check all tasks in the array

## Support

For issues or questions:
- GitHub: https://github.com/MrLouix/Claude_pool
- Check logs with: `./claude-pool.sh --pool pool.json --debug`
