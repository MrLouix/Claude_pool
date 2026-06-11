"""Re-export shim — preserves backward-compatibility with existing imports.

All executor logic lives in:
  team_cli/cli_executors.py  — BaseCLIExecutor, concrete executors, CLIManager
  team_cli/pool_driver.py    — TaskExecutor, execute_message, _meta_hash
  team_cli/signal_handler.py — install_handlers()
"""

# Module-level imports preserved so that `patch("team_cli.executor.signal.signal")`,
# `patch("team_cli.executor.subprocess.run")`, etc. continue to work in tests.
import asyncio   # noqa: F401 — patchable via team_cli.executor.asyncio
import signal    # noqa: F401 — patchable via team_cli.executor.signal
import subprocess  # noqa: F401 — patchable via team_cli.executor.subprocess
import tempfile  # noqa: F401 — patchable via team_cli.executor.tempfile

from .parser import parse_claude_output  # noqa: F401 — patchable via team_cli.executor.parse_claude_output
from .storage import build_context, save_pool  # noqa: F401 — patchable via team_cli.executor.build_context etc.

from .cli_executors import (
    BaseCLIExecutor,
    ClaudeExecutor,
    CLIManager,
    create_executor,
    GemmaExecutor,
    GenericCLIExecutor,
    LlamaExecutor,
    MAX_RETRIES,
    MistralExecutor,
    NoCLIAvailableError,
    NormalizedOutput,
    _RATE_LIMIT_PATTERNS,
    truncate_context_messages,
)
from .pool_driver import (
    _meta_hash,
    execute_message,
    TaskExecutor,
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
