# n8n Workflows for Claude Pool

Four pre-built workflows for automating Claude Pool integrations with external services.

## Workflows

### 1. Read Completed Tasks
**File**: `read_completed_tasks.json`
**Purpose**: Poll pool.json and extract successful tasks
**Nodes**: 5 (File read → JSON parse → Split → Filter → Format)
**Output**: Array of completed tasks with metadata

### 2. Create GitHub PR
**File**: `create_github_pr.json`
**Purpose**: Auto-create GitHub PRs from task code output
**Nodes**: 5 (Poll API → Split → Filter → Extract → Create PR)
**Prerequisites**: GitHub OAuth2, GITHUB_OWNER, GITHUB_REPO env vars

### 3. Notify Slack
**File**: `notify_slack.json`
**Purpose**: Send real-time Slack notifications on task completion
**Nodes**: 4 (WebSocket trigger → Filter → Format → Send message)
**Prerequisites**: SLACK_WEBHOOK_URL env var

### 4. Trigger CI Pipeline
**File**: `trigger_ci.json`
**Purpose**: Auto-trigger CI/CD when tasks generate code changes
**Nodes**: 6 (File read → JSON parse → Split → Filter → Extract → Webhook)
**Prerequisites**: CI_WEBHOOK_URL, CI_TOKEN env vars

## Quick Start

1. **Install n8n**: https://n8n.io/download

2. **Configure Claude Pool API**:
   ```bash
   python -m claude_pool --pool pool.json --serve --port 8000
   ```

3. **Import Workflows**:
   - Open n8n: http://localhost:5678
   - Workflows → Create New → Import from file
   - Select each JSON file from this directory

4. **Set Environment Variables**:
   - Create `.env` file or configure via n8n UI
   - Add credentials: GITHUB_TOKEN, SLACK_WEBHOOK_URL, CI_TOKEN

5. **Activate Workflows**:
   - Toggle each workflow to **Active**
   - Monitor Execution History

## Environment Variables

```bash
# Required for all workflows
CLAUDE_POOL_API_URL=http://localhost:8000

# GitHub PR workflow
GITHUB_OWNER=your-org
GITHUB_REPO=your-repo
GITHUB_TOKEN=ghp_...

# Slack notification workflow
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# CI trigger workflow
CI_WEBHOOK_URL=https://your-ci.com/webhook
CI_TOKEN=token123
```

## Task Output Format

Workflows expect task `json_output` to include:

```json
{
  "code_blocks": [
    {"language": "python", "code": "..."}
  ],
  "files_changed": ["src/file.py"],
  "result": "..."
}
```

Fields are optional — workflows check existence.

## Validation

All workflows are valid n8n JSON:
- ✓ read_completed_tasks.json (5 nodes, 4 connections)
- ✓ create_github_pr.json (5 nodes, 4 connections)
- ✓ notify_slack.json (4 nodes, 3 connections)
- ✓ trigger_ci.json (6 nodes, 5 connections)

## Documentation

Full integration guide: `docs/N8N_INTEGRATION.md`

Includes:
- Detailed setup instructions
- Per-workflow configuration
- Usage examples
- Troubleshooting tips
- Security best practices
- Advanced customization

## Testing

```bash
# Validate all workflows
python -m json.tool read_completed_tasks.json > /dev/null
python -m json.tool create_github_pr.json > /dev/null
python -m json.tool notify_slack.json > /dev/null
python -m json.tool trigger_ci.json > /dev/null

# Test Claude Pool API
curl http://localhost:8000/api/status | jq .

# Test WebSocket
wscat -c http://localhost:8000/ws/events
```

## Next Steps

1. Customize workflows in n8n UI for your specific needs
2. Configure credentials for your GitHub/Slack/CI setup
3. Test with sample tasks in pool.json
4. Enable workflows for production use
5. Monitor execution history for errors
