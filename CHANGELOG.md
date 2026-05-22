# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- feat: chat tabs in dashboard with shared pool execution
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

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
