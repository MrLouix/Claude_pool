# Changelog

All notable changes to this project will be documented in this file.

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
