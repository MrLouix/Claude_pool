# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.2.2] - 2026-05-29

### Fixed
- Event Log panel moved above Completed panel in dashboard
- Task cards no longer overflow outside the Completed panel on mobile (`overflow: hidden` on `.section`, `min-width: 0` on `.task-info`)
- WebSocket generic error (`[object Event]`) suppressed — reconnect message is sufficient

## [1.2.0] - 2026-05-27

### Added
- **Priority system** (1 = High, 2 = Normal, 3 = Low) for tasks
  - `priority` field on `Task` dataclass (default 2), persisted in `pool.json`
  - Executor sorts pending tasks by `(priority ASC, created_at ASC)` before each iteration (sequential and concurrent modes)
  - All API endpoints expose and accept `priority`: `TaskInput`, `TaskResponse`, `TaskDetailResponse`, `TaskPatchInput`, `MessageInput`
  - Task creation form: priority dropdown (default Normal)
  - Task list: priority badge (P1/P2/P3) displayed next to status
  - Task detail view: read-only priority field; edit mode includes priority dropdown
  - Run Dev Plan modal: priority dropdown; orchestrator prompt passes `priority` to enqueued subtasks
- **Running List** panel: tasks ordered by execution priority (non-success tasks only)
- **Completed** panel: separate list of `success` tasks sorted by completion time (newest first)

### Fixed
- Back navigation from task detail inside a chat now returns to the chat view (not the dashboard)
- Chat bucket badge in task list no longer also opens the task detail (event propagation fix)
- `created_at` field now correctly populated in task detail view
- WebSocket keepalive ping (every 30 s) prevents mobile disconnects

### Changed
- Dashboard stats: simplified to show only the pending task count
- Chat send button replaced with compact ⬆ arrow button
- "Recent Tasks" panel renamed to "Running List"

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2025-XX-XX

### Fixed
- Hotfixes and minor stability improvements

## [1.1.0] - 2025-XX-XX

### Added
- Chat tabs in dashboard with shared pool execution
  - `pool.json` v2 schema: `buckets` dict + `bucket_id` per task, with automatic migration from v1/v0
  - `Bucket` dataclass (id, type, label, directory, created_at); `"main"` bucket always present
  - `TaskExecutor.delete_bucket()`: removes bucket + all its tasks, skips running task if needed
  - REST API for chats: `GET/POST /api/chats`, `DELETE /api/chats/{id}`, `GET/POST /api/chats/{id}/messages`
  - Directory allow-list validation (must be under `/home` or `/mnt`)
  - WebSocket events: `chat_created`, `chat_deleted`, `chat_message`; `task_updated` includes `bucket_id`
  - Dashboard: Chats section, New Chat modal, bucket badge on Recent Tasks rows
  - Hash-based SPA router (`#chat/<id>`) with chat view: message thread, optimistic send, in-place WS updates
  - Auto-scroll only when already at bottom of message thread
  - `renderText`: markdown-lite rendering (code fences, inline code, bold, newlines) with correct code block isolation
  - Suspended-pool banner inside chat view (from `pool_status` WS event)

## [1.0.0] - 2024-01-XX

### Added
- Initial release of Claude Pool TUI
- Sequential task execution with Claude Code CLI integration
- Interactive TUI built with Textual framework
- Rate-limit detection and exponential backoff retry logic
- Task management: pause, skip, delete operations
- JSON-based task persistence (pool.json)
- Structured output parsing from Claude CLI
- CLI mode (--no-tui) for headless execution
- Comprehensive test suite (42 tests, 36% coverage)
- Support for Unicode and complex JSON outputs
- Keyboard shortcuts for all operations
- Real-time status monitoring and logging
- Detailed JSON output view (modal dialog)
- Graceful shutdown on SIGINT/SIGTERM

### Technical Details
- Python 3.11+ required
- English-only interface and JSON keys
- Task timeout: 30 minutes
- Maximum 5 retries per rate-limit
- Exponential backoff: up to 5 hours
