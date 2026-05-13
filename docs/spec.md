# Claude Pool TUI Specification (English‑only)

## 1. Overview

This document defines the specification for a TUI (Text User Interface) script that manages a **sequential pool of requests** forwarded to `claude -p` (Claude Code CLI).  
The script:

- Loads a pool of tasks from an English‑key JSON file (`pool.json`).
- Executes each task in the specified directory (`cd $directory && claude -p ...`).
- Parses the structured JSON output from Claude Code.
- Stores the result (including `exit_code`, `status`, and compact JSON output) back into `pool.json` in English.
- Allows manual deletion of tasks from the TUI.
- Detects rate‑limit / session‑limit conditions and suspends/restarts the pool after the limit expires.

All keys in the JSON and UI labels are in **English only**; there is no French or retro‑compatibility layer.

---

## 2. Requirements

### 2.1 Functional requirements

- Read a task pool from `pool.json` (English keys).
- Run `claude -p <prompt> --output-format json [args]` inside the specified `directory`.
- Capture:
  - `exit_code`
  - `json_output` (parsed, compacted, without `reasoning`)
  - `status` (e.g., `pending`, `running`, `success`, `failed`, `rate_limit_retry`)
  - `duration_ms`
- Save the updated task state back into `pool.json` in English.
- Detect and react to:
  - Return code `1` with rate‑limit/session‑limit messages.
  - Exponential backoff (up to 5 hours) and automatic resume.
- Provide a TUI that:
  - Displays a tree/list of tasks with status.
  - Shows a compact JSON output for the selected task.
  - Allows manual deletion of tasks (with confirm dialog).
  - Logs execution events (timestamped, last 20 lines).

### 2.2 Non‑functional requirements

- **Format**: English‑only keys in `pool.json` and TUI labels.
- **Performance**:
  - Per‑task setup under 2 seconds.
  - Task timeout: 30 minutes.
- **Robustness**:
  - Retry up to 5 times on rate‑limit‑like failures.
  - Graceful shutdown (save state on `SIGINT`).
- **UI**:
  - TUI built with `textual` (Python).
  - Status colors: green (success), red (failed), yellow (running/retry), gray (pending).
- **Security**:
  - Isolated `chdir` per task.
  - No execution of arbitrary user‑supplied code.
  - Logs must not leak secrets.
- **Compatibility**:
  - WSL2 / Ubuntu / macOS.
  - Python 3.11+.
  - `claude` CLI installed and authenticated.

---

## 3. JSON schema: `pool.json`

### 3.1 Top‑level structure

```json
{
  "pool_retry_count": 0,
  "pool_suspended_until": null,
  "tasks": [
    {
      "id": "string",
      "prompt": "string",
      "directory": "string",
      "args": ["string", ...],
      "status": "string",
      "exit_code": "integer|null",
      "duration_ms": "integer|null",
      "json_output": "object|null"
    },
    ...
  ]
}
```

### 3.2 Pool metadata fields

| Field                  | Description                                                                 |
|------------------------|-----------------------------------------------------------------------------|
| `pool_retry_count`     | Global rate‑limit retry counter across the entire pool. Max 5. Reset to 0 on successful task after suspension. |
| `pool_suspended_until` | ISO‑8601 timestamp of when the pool suspension expires. `null` when not suspended. |

### 3.3 Task field descriptions

| Field              | Description                                                                 |
|--------------------|-----------------------------------------------------------------------------|
| `id`              | Unique identifier for the task.                                             |
| `prompt`          | Command‑line prompt text passed to `claude -p`.                            |
| `directory`       | Working directory in which the task runs (`cd $directory`).                |
| `args`            | Additional CLI arguments (e.g., `["--model", "sonnet‑4"]`).               |
| `status`          | Current status: `pending`, `running`, `success`, `failed`, `rate_limit_retry`. |
| `exit_code`       | Claude exit code (e.g., `0`, `1`, ...). `null` if not run yet.            |
| `duration_ms`     | Execution duration in milliseconds. `null` if not run yet.                 |
| `json_output`     | Parsed JSON output (compact, without `reasoning`). `null` if not run yet. |

### 3.4 Example `pool.json` (initial)

```json
{
  "pool_retry_count": 0,
  "pool_suspended_until": null,
  "tasks": [
    {
      "id": "task_001",
      "prompt": "Fix login bug in FastAPI auth endpoint",
      "directory": "/home/user/fastapi-repo",
      "args": ["--model", "sonnet-4", "--max-turns", "10"],
      "status": "pending",
      "exit_code": null,
      "duration_ms": null,
      "json_output": null
    },
    {
      "id": "task_002",
      "prompt": "Review Docker configuration",
      "directory": "/home/user/fastapi-repo",
      "args": ["--model", "sonnet-4"],
      "status": "pending",
      "exit_code": null,
      "duration_ms": null,
      "json_output": null
    }
  ]
}
```

### 3.5 Example `pool.json` (during suspension)

```json
{
  "pool_retry_count": 2,
  "pool_suspended_until": "2025-06-15T22:34:00",
  "tasks": [
    {
      "id": "task_001",
      "prompt": "Fix login bug in FastAPI auth endpoint",
      "directory": "/home/user/fastapi-repo",
      "args": ["--model", "sonnet-4", "--max-turns", "10"],
      "status": "rate_limit_retry",
      "exit_code": 1,
      "duration_ms": 42300,
      "json_output": null
    },
    {
      "id": "task_002",
      "prompt": "Review Docker configuration",
      "directory": "/home/user/fastapi-repo",
      "args": ["--model", "sonnet-4"],
      "status": "pending",
      "exit_code": null,
      "duration_ms": null,
      "json_output": null
    }
  ]
}
```

### 3.6 `json_output` compact structure

Claude is called with `--output-format json --structured-output`; the script **drops** `reasoning` and other verbose fields.

```json
{
  "result": "string",
  "code_blocks": [
    {
      "language": "string",
      "filename": "string",
      "content": "string"
    }
  ],
  "files_changed": ["string", ...],
  "tokens_used": "number",
  "session_usage_percent": "number"
}
```

- `result`: Concise summary of Claude’s action.
- `code_blocks`: List of code snippets produced.
- `files_changed`: Paths of files modified.
- `tokens_used`: Approximate tokens used in the session.
- `session_usage_percent`: Session usage (for rate‑limit‑aware logic).

---

## 4. Command format and execution

### 4.1 Command template

```bash
cd "$directory" &&
claude -p "$prompt" --output-format json --structured-output [args...]
```

### 4.2 Example command line

```bash
cd /home/user/fastapi-repo &&
claude -p "Fix login bug" --output-format json --structured-output \
  --model sonnet-4 --max-turns 10
```

### 4.3 Exit code handling

| Exit code | Meaning / action |
|-----------|------------------|
| `0`      | Success; mark status as `success`. |
| `1`      | Likely rate‑limit or session‑limit; mark as `rate_limit_retry`, retry with exponential backoff (max 5 hours). |
| `≥2`     | Fatal error; mark as `failed`. |
| Other    | Mark as `failed` and log the error. |

---

## 5. TUI interface

### 5.1 Layout

```text
┌─ Claude Pool TUI v1.0 ─ Current: task_001 ───────────────┐
│ Tasks Tree:                                              │
│ ├─  Fix login bug | running (retry 2/5)             │
│ ├─ [1] Review Docker | pending                         │
│ └─ [2] Deploy config | success (4.5k tokens)           │
│                                                          │
│ JSON Output (selected):                                  │
│ { "result": "Fixed...", "code_blocks": 1 Python }        │
│                                                          │
│ Logs:                                                    │
│ 22:11: Task 001 running in /home/user/fastapi-repo       │
│ 22:12: Rate limit 85%, waiting 120min (backoff)          │
└── Controls: [P]ause [S]kip [Del]ete [Q]uit ───────────────┘
```

### 5.2 Components

- **Tasks Tree / List**:
  - Displays `id`, truncated `prompt`, `status`, and `duration` / `tokens`.
  - Selected item shown in yellow.
- **JSON Output area**:
  - Shows compact JSON of the selected task (no `reasoning`).
  - Can be toggled or expanded with `Enter`.
- **Logs area**:
  - Timestamped log lines (last 20 lines visible).
  - Color‑coded: success (green), warning (yellow), error (red).

### 5.3 Keyboard controls

| Key        | Action |
|-----------|--------|
| `↑` / `↓` | Select previous / next task. |
| `Enter`   | Show detailed JSON output for selected task. |
| `P`       | Pause execution. |
| `S`       | Skip current task. |
| `Del`     | Delete selected task (with confirm dialog). |
| `Q`       | Quit the application (save state before exiting). |

---

## 6. Core logic and classes

### 6.1 `Task` class

```python
class Task:
    def __init__(self, data: dict):
        self.id: str              = data["id"]
        self.prompt: str          = data["prompt"]
        self.directory: Path      = Path(data["directory"])
        self.args: list[str]      = data.get("args", [])
        self.status: str          = data.get("status", "pending")
        self.exit_code: int | None = data.get("exit_code")
        self.duration_ms: int | None = data.get("duration_ms")
        self.json_output: dict | None = data.get("json_output")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "directory": str(self.directory),
            "args": self.args,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "json_output": self.json_output,
        }
```

### 6.2 `PoolState` class

```python
@dataclass
class PoolState:
    retry_count: int = 0
    suspended_until: datetime | None = None
    tasks: list[Task] = field(default_factory=list)
    pool_file: str = "pool.json"

    @property
    def is_suspended(self) -> bool:
        return self.suspended_until is not None and datetime.now() < self.suspended_until

    @property
    def suspension_remaining(self) -> float:
        if not self.suspended_until:
            return 0
        return max(0, (self.suspended_until - datetime.now()).total_seconds())
```

### 6.3 `PoolTUI` (textual app skeleton)

```python
class PoolTUI(App):
    BINDINGS = [
        ("p", "pause", "Pause"),
        ("s", "skip", "Skip"),
        ("delete", "delete_task", "Delete"),
        ("q", "quit", "Quit"),
    ]

    def action_delete_task(self):
        # Confirm dialog, then remove task from self.pool.tasks and update pool.json
        pass
```

---

## 7. JSON parsing function

```python
def parse_claude_output(stdout: bytes) -> dict:
    """Parse Claude --output-format json → compact English structure."""
    try:
        # Extract JSON block
        json_str = stdout.decode().split("JSON OUTPUT:")[-1].split("```")
        data = json.loads(json_str)
        return {
            "result": data.get("result", ""),
            "code_blocks": [
                {
                    "language": b.get("lang", "unknown"),
                    "filename": b.get("filename", f"code_{i}.py"),
                    "content": b.get("content", ""),
                }
                for i, b in enumerate(data.get("code_blocks", []))
            ],
            "files_changed": data.get("files_changed", []),
            "tokens_used": data.get("tokens_used", 0),
            "session_usage_percent": data.get("session_usage_percent", 0),
        }
    except Exception:
        return {"result": stdout.decode()[:1000], "parse_error": True}
```

---

## 8. Save / Load logic (English‑only)

### 8.1 Save pool

```python
def save_pool(state: PoolState):
    data = {
        "pool_retry_count": state.retry_count,
        "pool_suspended_until": state.suspended_until.isoformat() if state.suspended_until else None,
        "tasks": [t.to_dict() for t in state.tasks],
    }
    Path(state.pool_file).write_text(json.dumps(data, indent=2))
```

### 8.2 Load pool

```python
def load_pool(pool_file: str) -> PoolState:
    raw = json.loads(Path(pool_file).read_text())
    state = PoolState(
        retry_count=raw.get("pool_retry_count", 0),
        suspended_until=datetime.fromisoformat(raw["pool_suspended_until"]) if raw.get("pool_suspended_until") else None,
        tasks=[Task(t) for t in raw.get("tasks", [])],
        pool_file=pool_file,
    )
    return state
```

### 8.3 Backward compatibility

If `pool.json` is a bare array (legacy format from before the wrapper), it is automatically migrated on load:

```python
def load_pool(pool_file: str) -> PoolState:
    raw = json.loads(Path(pool_file).read_text())
    # Legacy: bare task array without pool metadata
    if isinstance(raw, list):
        raw = {"pool_retry_count": 0, "pool_suspended_until": None, "tasks": raw}
    # ... proceed as normal
```

---

## 9. Rate limit and retry strategy

### 9.1 Trigger conditions

- `exit_code == 1` and presence of rate‑limit / session‑limit patterns in `json_output` or stderr.
- `session_usage_percent` ≥ 80% (from `json_output`).

### 9.2 Global pool suspension (not per‑task)

When a rate limit is detected, **the entire pool execution is suspended** — not just the current task. All pending tasks are paused. A single global backoff timer is used, because the Claude API rate limit is account‑wide, not per‑task.

- **Global retry counter** (`pool.retry_count`): incremented on each rate‑limit event across the entire pool. Maximum 5 total retries.
- **Global retry delay**: `60 * (2 ** pool.retry_count)` seconds, capped at 5 hours.
- The TUI displays a global countdown banner when suspended.

### 9.3 Suspension flow

```python
# Global state
pool_retry_count = 0
pool_suspended_until = None  # datetime

def on_rate_limit_detected(task: Task):
    global pool_retry_count, pool_suspended_until

    task.status = "rate_limit_retry"
    pool_retry_count += 1

    wait_seconds = min(60 * (2 ** pool_retry_count), 5 * 3600)
    pool_suspended_until = datetime.now() + timedelta(seconds=wait_seconds)

    logging.info(f"Rate limit detected; pool suspended for {wait_seconds}s (retry {pool_retry_count}/5)")

    # Save state immediately
    save_pool(pool_file, tasks)

    # TUI shows: "⏸ POOL SUSPENDED — Rate limit, resuming at HH:MM:SS (retry 2/5)"

async def pool_execution():
    while pool_suspended_until and datetime.now() < pool_suspended_until:
        remaining = (pool_suspended_until - datetime.now()).total_seconds()
        # TUI updates countdown display
        await asyncio.sleep(1)

    if pool_suspended_until:
        logging.info("Pool suspension ended, resuming execution")
        pool_suspended_until = None

    # Resume: re-run the failed task first, then continue the queue
```

### 9.4 Resume behavior

After the suspension expires:
1. The task that triggered the rate limit is **re‑attempted first** (its status is reset to `pending`).
2. If it succeeds → `pool_retry_count` is **reset to 0** (clean rate‑limit window confirmed).
3. If it fails again with rate limit → increment counter, compute new backoff, suspend again.
4. If it fails with exit code ≥2 → mark `failed`, move to next task, **do not reset** the retry counter (rate limit may still be active).
5. After 5 consecutive rate‑limit retries → mark remaining tasks as `failed` with reason `rate_limit_exhausted` and exit gracefully.

### 9.5 Session usage pre‑emptive suspension

If `session_usage_percent` ≥ 80% is returned from a successful task (`exit_code == 0`):
- The pool **does not suspend immediately** (the task succeeded).
- A **warning banner** is displayed in the TUI.
- If the **next** task also triggers a rate limit, the global suspension activates with a **shorter** initial backoff: `30 * (2 ** pool_retry_count)` instead of `60`, accounting for the already-warm session.

---

## 10. Integration with n8n / OpenClaw

### 10.1 n8n usage

- Read `pool.json` with **File** node.
- Use **Function** node to access:
  - `json_output.code_blocks[0].content` (e.g., patch file).
  - `files_changed` (for path handling).
- Trigger `git apply`, `git commit`, or any automation workflow.

### 10.2 OpenClaw / Home Assistant

- Watch `pool.json` for status changes.
- Show `status` and `session_usage_percent` in dashboards.
- Trigger alerts if `session_usage_percent` approaches 100%.

---

## 11. Testing strategy

### 11.1 Unit tests

- `test_task_run_success()` – mock `claude` returning exit code `0`.
- `test_task_rate_limit_retry()` – mock exit code `1` and verify backoff logic.
- `test_parse_claude_output()` – verify JSON parsing and omission of `reasoning`.

### 11.2 Integration tests

- Run a small `pool.json` with real or mocked `claude`.
- Verify `pool.json` is updated correctly after completion.
- Check that manual deletion in the TUI persists to disk.

---

## 12. Future improvements (optional)

- Parallel execution (2 concurrent tasks, respecting rate limits).
- Web UI / API (FastAPI + WebSockets) exposing the pool state.
- Metrics exporter (Prometheus‑style) for `tokens_used` and `session_usage_percent`.
- Integration with local LLMs (e.g., Ollama) as fallback when Claude is rate‑limited.
