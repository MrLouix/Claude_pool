# Roadmap — What's Next

**v1.0.0 shipped** — skip fix, TUI tests, Web API, parallel execution, n8n workflows are all done.

Below are future ideas ranked by effort/impact. Nothing is planned actively — these are reference notes if someone wants to tackle them.

---

## Quick Wins (1–4 hours each)

- **Task filtering/search** — `Ctrl+F` text filter on DataTable (prompt, status, directory)
- **Task priority** — optional `priority` field (1-5) to sort pending tasks
- **Task grouping** — tag tasks with `group: "docs"`, `group: "tests"` for filtering
- **Export to CSV/JSON** — download task history

## Medium Features (1–3 days each)

- **Dependency graph (DAG)** — declare `depends_on: task_id`, only run when dependencies are `success`
- **Batch operations** — multi-select to retry/delete multiple tasks at once
- **Task templates** — pre-filled prompts for common patterns (code review, test generation, docs update)
- **Prometheus metrics** — expose `/metrics` with task duration, success rate, token usage

## Architecture Ideas

- **Ollama fallback** — run open-weight models when Claude rate-limited
- **Multi-pool** — manage separate pools per project in one TUI
- **Web dashboard** — full React/Vue frontend instead of HTML static page
- **Plugin system** — hooks for custom post-task actions (lint, commit, deploy)
