"""Re-export shim — preserves backward-compatibility with existing imports.

All executor logic lives in:
  team_cli/cli_executors.py  — BaseCLIExecutor, concrete executors, CLIManager
  team_cli/pool_driver.py    — TaskExecutor, execute_message, _meta_hash
  team_cli/signal_handler.py — install_handlers()
"""

# Module-level imports preserved so that `patch("team_cli.executor.signal.signal")`,
# `patch("team_cli.executor.subprocess.run")`, etc. continue to work in tests.
import asyncio  # noqa: F401 — patchable via team_cli.executor.asyncio
import signal  # noqa: F401 — patchable via team_cli.executor.signal
import subprocess  # noqa: F401 — patchable via team_cli.executor.subprocess
import tempfile  # noqa: F401 — patchable via team_cli.executor.tempfile

from .cli_executors import (
    _RATE_LIMIT_PATTERNS,
    MAX_RETRIES,
    BaseCLIExecutor,
    ClaudeExecutor,
    CLIManager,
    GemmaExecutor,
    GenericCLIExecutor,
    LlamaExecutor,
    MistralExecutor,
    NoCLIAvailableError,
    NormalizedOutput,
    create_executor,
    truncate_context_messages,
)
from .parser import (
    parse_claude_output,  # noqa: F401 — patchable via team_cli.executor.parse_claude_output
)
from .pool_driver import (
    TaskExecutor,
    _meta_hash,
    execute_message,
)
from .storage import (  # noqa: F401 — patchable via team_cli.executor.build_context etc.
    build_context,
    save_pool,
)

__all__ = [
    "BaseCLIExecutor",
    "ClaudeExecutor",
    "CLIManager",
    "create_executor",
    "GemmaExecutor",
    "GenericCLIExecutor",
    "LlamaExecutor",
    "MAX_RETRIES",
    "MistralExecutor",
    "NoCLIAvailableError",
    "NormalizedOutput",
    "_RATE_LIMIT_PATTERNS",
    "truncate_context_messages",
    "_meta_hash",
    "execute_message",
    "TaskExecutor",
]
