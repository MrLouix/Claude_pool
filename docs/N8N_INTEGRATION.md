# n8n Integration Guide

> **v2.0.0 Migration Notice** — Several v1 endpoints have been deprecated. See the [Migration Guide](#migration-guide-v1--v2) section below before upgrading. Deprecated endpoints will be removed in v3.0.0.

This document describes how to integrate TeamCLI with n8n, a workflow automation platform. Four pre-built workflows are provided to automate common tasks based on TeamCLI task completions.

---

## Migration Guide: v1 → v2

### Deprecated v1 Endpoints

The following v1 endpoints are deprecated as of v2.0.0 and will be **removed in v3.0.0**:

| Deprecated (v1) | Reason |
|-----------------|--------|
| `GET /api/chats` | Replaced by project-scoped chats |
| `POST /api/chats` | Replaced by `POST /api/projects/{id}/chats` |
| `GET /api/tasks` (unfiltered, no project scope) | Now requires explicit filters for performance |
| `DELETE /api/tasks/{id}` (for bulk cleanup) | Replaced by `DELETE /api/tasks?status=completed` |

### v2 Replacement Endpoints

| Old (v1) | New (v2) | Notes |
|----------|----------|-------|
| `GET /api/chats` | `GET /api/projects/{id}/chats` | Chats are now project-scoped |
| `POST /api/chats` | `POST /api/projects/{id}/chats` | Create project first via `POST /api/projects` |
| `GET /api/tasks` | `GET /api/tasks?status=completed` | Use `status`, `project_id`, `kind` filters |
| `POST /api/tasks` (if used) | `POST /api/projects/{id}/chats/{cid}/messages` | Task creation via chat message |

### Example: Poll for completed tasks (v2)

```http
GET /api/tasks?status=completed
```

Response items now include `project_id`, `kind` (`request` | `subtask`), and `parent_task_id`.

### Example: Create a task in a project (v2)

```http
POST /api/projects/{project_id}/chats/{chat_id}/messages
Content-Type: application/json

{ "content": "Refactor auth module to use JWT", "cli_id": "claude" }
```

---

## Overview

n8n workflows allow you to:
- **Read Completed Tasks**: Poll TeamCLI for successful task completions
- **Create GitHub PRs**: Automatically generate pull requests from Claude's code output
- **Notify Slack**: Send notifications when tasks complete
- **Trigger CI/CD**: Launch CI pipelines when code changes are detected

## Prerequisites

- **n8n Installation**: Docker, self-hosted, or cloud version (https://n8n.io)
- **TeamCLI API**: Running on `http://localhost:8000` (with `--serve` flag)
- **Environment Variables**: Credentials for GitHub, Slack, and CI/CD integrations
- **pool.json**: Properly formatted TeamCLI task file

## Installation

### 1. Start TeamCLI API Server

```bash
python -m team_cli --pool pool.json --serve --port 8000
```

This starts the FastAPI server with endpoints:
- `GET /api/tasks` - List all tasks
- `GET /api/status` - Pool status
- `GET /ws/events` - WebSocket event stream

### 2. Import Workflows into n8n

1. Open n8n dashboard
2. Click **Workflows** → **Create New**
3. For each workflow file:
   - Click **Menu** (three dots) → **Import from file**
   - Select the workflow JSON from `n8n_workflows/`
   - Click **Save** and **Activate** when ready

Alternatively, use the n8n API:

```bash
curl -X POST http://localhost:5678/api/v1/workflows \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -H "Content-Type: application/json" \
  -d @n8n_workflows/read_completed_tasks.json
```

### 3. Configure Environment Variables

Create a `.env` file or configure n8n environment variables:

```bash
# TeamCLI API (used by workflows)
CLAUDE_POOL_API_URL=http://localhost:8000

# GitHub Integration
GITHUB_OWNER=your-github-org
GITHUB_REPO=your-repo-name
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# Slack Integration
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# CI/CD Integration (e.g., GitHub Actions, GitLab CI)
CI_WEBHOOK_URL=https://your-ci-provider.com/webhook
CI_TOKEN=your-ci-token
```

## Workflows

### 1. Read Completed Tasks

**File**: `n8n_workflows/read_completed_tasks.json`

**Purpose**: Poll `pool.json` and extract all successfully completed tasks.

**Flow**:
1. Read pool.json file
2. Parse JSON content
3. Split tasks array into individual items
4. Filter for `status == "success"`
5. Format output with task ID, prompt, directory, exit code, and output

**Output Example**:
```json
{
  "id": "task_20260521_120000_a1b2c3d4",
  "prompt": "Fix authentication bug",
  "directory": "/home/user/project",
  "status": "success",
  "exit_code": 0,
  "duration_ms": 45000,
  "output": { "result": "Authentication fixed" }
}
```

**Usage**: Use as a trigger for other workflows to process completed tasks.

### 2. Create GitHub PR

**File**: `n8n_workflows/create_github_pr.json`

**Purpose**: Automatically create GitHub pull requests from completed Claude tasks with code output.

**Prerequisites**:
- GitHub OAuth2 credentials configured in n8n
- `GITHUB_OWNER` and `GITHUB_REPO` environment variables
- Task output containing `code_blocks` array (from Claude's JSON output)

**Flow**:
1. Poll API endpoint `/api/tasks?status=success`
2. Split tasks from response
3. Filter tasks containing code changes
4. Extract PR metadata:
   - Title: First 50 characters of prompt
   - Body: Task details + code blocks
   - Branch: `claude-pool/{task-id}`
   - Base: `main`
5. Create PR via GitHub API

**Code Block Format** (expected in task `json_output`):
```json
{
  "code_blocks": [
    {
      "language": "python",
      "filename": "src/auth.py",
      "code": "def verify_token(token):\n  ..."
    }
  ]
}
```

**Configuration**:
- Set **GITHUB_OWNER** to your GitHub organization or username
- Set **GITHUB_REPO** to the target repository name
- Add GitHub OAuth2 credentials via n8n UI

**Example PR Creation**:
```
Title: [Claude] Fix authentication bug in login flow...
Branch: claude-pool/20260521_120000_a1b2c3d4
Base: main

Generated by TeamCLI

Task: task_20260521_120000_a1b2c3d4
Directory: /home/user/project

## Changes
```python
def verify_token(token):
  ...
```
```

### 3. Notify Slack

**File**: `n8n_workflows/notify_slack.json`

**Purpose**: Send Slack notifications when tasks complete (success, failure, or skip).

**Prerequisites**:
- Slack Incoming Webhook URL
- `SLACK_WEBHOOK_URL` environment variable

**Flow**:
1. Listen to WebSocket `/ws/events` for task updates
2. Filter for completion events (success, failed, skipped)
3. Format message with emoji and status color:
   - ✅ Success (green #36a64f)
   - ❌ Failed (red #ff0000)
   - ⏭️ Skipped (orange #ffa500)
4. Send formatted message to Slack

**Slack Message Format**:
```
✅ Task `task_20260521_120000_a1b2c3d4` - **success**
```

**Configuration**:
1. Create Slack App: https://api.slack.com/apps
2. Enable Incoming Webhooks
3. Create Webhook URL for your channel
4. Set `SLACK_WEBHOOK_URL` environment variable

**Advanced**: Modify the **Format Message** node to add:
- Task details (prompt, directory)
- Duration and performance metrics
- Output preview (first 100 chars)
- Links to task in TeamCLI dashboard

### 4. Trigger CI Pipeline

**File**: `n8n_workflows/trigger_ci.json`

**Purpose**: Automatically trigger CI/CD pipelines when completed tasks contain code changes.

**Prerequisites**:
- CI/CD provider webhook URL (GitHub Actions, GitLab CI, Jenkins, etc.)
- `CI_WEBHOOK_URL` and `CI_TOKEN` environment variables
- Tasks with `files_changed` in their JSON output

**Flow**:
1. Read pool.json file
2. Parse JSON content
3. Split tasks
4. Filter for successful tasks with file changes
5. Extract CI data:
   - Branch name: `claude-pool/{task-id}`
   - Commit message: Task ID and description
   - Changed files list
   - Source: "claude-pool"
6. POST to CI webhook with branch, files, and metadata

**Files Changed Format** (expected in task `json_output`):
```json
{
  "files_changed": [
    "src/auth.py",
    "tests/test_auth.py",
    "docs/authentication.md"
  ]
}
```

**Webhook Payload** (sent to CI_WEBHOOK_URL):
```json
{
  "event": "code_changes",
  "branch": "claude-pool/20260521_120000_a1b2c3d4",
  "files": ["src/auth.py", "tests/test_auth.py"],
  "source": "claude-pool"
}
```

**Configuration Examples**:

**GitHub Actions Webhook**:
```bash
CI_WEBHOOK_URL=https://api.github.com/repos/org/repo/dispatches
CI_TOKEN=ghp_xxxxxxxxxxxx
```

**GitLab CI Pipeline Trigger**:
```bash
CI_WEBHOOK_URL=https://gitlab.com/api/v4/projects/{id}/trigger/pipeline
CI_TOKEN=your-gitlab-token
```

**Jenkins**:
```bash
CI_WEBHOOK_URL=https://jenkins.example.com/generic-webhook-trigger/invoke
CI_TOKEN=jenkins-token
```

## Usage Examples

### Example 1: Automated PR Generation

1. **Run TeamCLI** with tasks containing code generation prompts
2. **Activate Workflow**: "Create GitHub PR"
3. **Result**: When task completes successfully and contains `code_blocks`, a PR is automatically created
4. **Review**: Check GitHub for new PR, review Claude's changes, merge if approved

### Example 2: Real-Time Slack Notifications

1. **Start TeamCLI API**: `python -m team_cli --pool pool.json --serve`
2. **Activate Workflow**: "Notify Slack"
3. **Result**: Team receives instant Slack notification for each task completion
4. **Integration**: Link to task details, performance metrics, or manual actions

### Example 3: Automated Testing Pipeline

1. **Configure CI Webhook** pointing to your test runner
2. **Activate Workflow**: "Trigger CI Pipeline"
3. **Result**: When Claude generates code changes, CI runs tests automatically
4. **Feedback**: Test results sent back to TeamCLI for visibility

### Example 4: Task Aggregation Report

Combine workflows to create a daily summary:
1. Use **Read Completed Tasks** to get all successful tasks
2. Group by directory/project
3. Send aggregated report to Slack with:
   - Number of tasks completed
   - Total time spent
   - Files modified
   - Generated PRs created

## Environment Variables Reference

| Variable | Required | Example | Used By |
|----------|----------|---------|---------|
| `CLAUDE_POOL_API_URL` | Yes | `http://localhost:8000` | All HTTP/WebSocket triggers |
| `GITHUB_OWNER` | GitHub PR | `anthropics` | Create GitHub PR |
| `GITHUB_REPO` | GitHub PR | `claude-pool` | Create GitHub PR |
| `GITHUB_TOKEN` | GitHub PR | `ghp_...` | GitHub OAuth |
| `SLACK_WEBHOOK_URL` | Slack notify | `https://hooks.slack.com/...` | Notify Slack |
| `CI_WEBHOOK_URL` | CI trigger | `https://api.github.com/...` | Trigger CI |
| `CI_TOKEN` | CI trigger | `token123` | CI authentication |

## Monitoring

### Check Workflow Status

In n8n UI:
- Click **Workflows** → Select workflow
- View **Execution History** tab
- Check logs, errors, and execution time

### API Health Check

```bash
curl http://localhost:8000/api/status | jq .

# Expected response:
{
  "total_tasks": 42,
  "pending_tasks": 5,
  "running_tasks": 1,
  "completed_tasks": 36,
  "failed_tasks": 0,
  "skipped_tasks": 1,
  "suspended_until": null
}
```

### WebSocket Event Stream

```bash
# Test WebSocket connection (requires wscat)
wscat -c http://localhost:8000/ws/events

# Example events:
{"type":"task_update","task_id":"task_001","status":"running"}
{"type":"task_update","task_id":"task_001","status":"success"}
```

## Troubleshooting

### Workflow Not Triggering

**Issue**: Scheduled trigger not executing
- Check n8n instance is running: `curl http://localhost:5678`
- Verify workflow is **Activated** (toggle in UI)
- Check **Execution History** for errors
- Review environment variables are set

### API Connection Failed

**Issue**: `connection refused` or `network error`
- Verify TeamCLI API is running: `curl http://localhost:8000/api/status`
- Check firewall allows port 8000
- Verify URL matches: `CLAUDE_POOL_API_URL=http://localhost:8000`

### GitHub PR Not Created

**Issue**: Workflow executes but PR is not created
- Verify GitHub token has `repo` scope
- Check task contains `json_output.code_blocks` array
- Review n8n logs: **Workflows** → workflow → **Execution History**
- Test GitHub API manually:
  ```bash
  curl -H "Authorization: token $GITHUB_TOKEN" \
    https://api.github.com/repos/$GITHUB_OWNER/$GITHUB_REPO
  ```

### Slack Message Not Sent

**Issue**: Task completes but Slack message doesn't arrive
- Verify webhook URL is active: `curl -X POST $SLACK_WEBHOOK_URL -d '{"text":"test"}'`
- Check n8n Slack node credentials
- Review WebSocket connection: subscribe to `/ws/events` manually
- Verify task status is one of: `success`, `failed`, `skipped`

### WebSocket Connection Drops

**Issue**: Real-time notifications not working
- Verify TeamCLI running with `--serve` flag
- Check network connectivity to port 8000
- Review n8n logs for connection timeouts
- Increase WebSocket timeout in n8n settings

## Advanced Customization

### Modify Workflow Nodes

1. Open workflow in n8n UI
2. Click on node to edit
3. Update parameters (code, conditions, credentials)
4. Click **Save** to apply changes
5. Test with **Execute** button

### Add Custom Filters

Example: Only notify Slack for tasks longer than 5 minutes:

```javascript
// In "Filter Completion Events" node
return item.json.duration_ms > 300000;
```

### Extend Code Extraction

Example: Include git diff in PR body:

```javascript
// In "Extract PR Data" node
const diffOutput = task.json_output.git_diff || 'No diff available';
return {
  title: `[Claude] ${task.prompt.substring(0, 50)}...`,
  body: `## Changes\n\n${diffOutput}`,
  // ... rest of PR data
};
```

### Add Retry Logic

For workflows calling external APIs, add retry nodes:

1. Right-click on node → **Add node** → **Error Workflow**
2. Configure retry conditions
3. Set exponential backoff delays

## Integration with TeamCLI

### API Endpoints Used

The workflows leverage these TeamCLI endpoints:

```
GET  /api/tasks                    # List all tasks (Read Completed Tasks)
GET  /api/tasks?status=success     # Filter by status (Create GitHub PR)
GET  /api/status                   # Pool status (monitoring)
GET  /ws/events                    # Event stream (Notify Slack)
```

### Task Output Format

Workflows expect task `json_output` to contain:

```json
{
  "code_blocks": [
    {
      "language": "python",
      "filename": "src/file.py",
      "code": "..."
    }
  ],
  "files_changed": ["src/file.py", "tests/..."],
  "git_diff": "--- a/...",
  "duration_ms": 45000,
  "result": "..."
}
```

Not all fields are required — workflows check existence before using them.

## Security Considerations

1. **Credentials**: Store tokens in n8n's secure credential storage, not in code
2. **Webhooks**: Use authentication headers (X-CI-Token, Authorization)
3. **Logging**: Avoid logging sensitive data in n8n execution history
4. **Network**: Run n8n and TeamCLI on same secure network (production)
5. **Audit**: Enable n8n audit logs to track workflow executions

## Next Steps

- **Monitor Workflows**: Set up n8n alerts for failed executions
- **Customize Output**: Modify nodes to match your specific needs
- **Add Workflows**: Create new workflows for additional automation (e.g., database logging, archive tasks)
- **Integration Testing**: Test with sample tasks before running in production
- **Documentation**: Document your custom workflows for team reference

## Support

For n8n issues: https://docs.n8n.io
For TeamCLI issues: Check project README and GitHub issues
