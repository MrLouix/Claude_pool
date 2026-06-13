"""CLI executor classes and manager — extracted from executor.py."""

import logging
import shlex
import subprocess
import tomllib
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from .models import CLIConfig

logger = logging.getLogger(__name__)

MAX_RETRIES = 5

_PROFILES_PATH = Path(__file__).parent / "cli_profiles.toml"


@lru_cache(maxsize=1)
def _load_profiles() -> dict:
    with open(_PROFILES_PATH, "rb") as f:
        return tomllib.load(f)


def build_cmd_from_profile(
    cli_path: str,
    profile_name: str,
    prompt: str,
    model: str = "",
    extra_flags: list[str] | None = None,
) -> list[str]:
    """Build a CLI command list from a named profile in cli_profiles.toml.

    Construction order:
      binary [subcommand] [prompt_flag prompt] [output_flags]
             [model_flag model] [fixed_flags] [extra_flags]
             [prompt]  ← only when prompt_flag is empty (positional)
    """
    profiles = _load_profiles()
    if profile_name not in profiles:
        raise ValueError(
            f"Unknown CLI profile {profile_name!r}. "
            f"Available: {list(profiles)}"
        )
    p = profiles[profile_name]

    cmd: list[str] = [cli_path]

    if p.get("subcommand"):
        cmd.append(p["subcommand"])

    prompt_flag = p.get("prompt_flag", "")
    if prompt_flag:
        cmd.extend([prompt_flag, prompt])

    cmd.extend(p.get("output_flags", []))

    model_flag = p.get("model_flag", "")
    if model and model_flag:
        cmd.extend([model_flag, model])

    cmd.extend(p.get("fixed_flags", []))

    if extra_flags:
        cmd.extend(extra_flags)

    if not prompt_flag:  # positional: append last
        cmd.append(prompt)

    return cmd


# Backward-compat alias used by the multi-step planner skills
def build_claude_cmd(cli_path: str, prompt: str, model: str) -> list[str]:
    return build_cmd_from_profile(cli_path, "claude", prompt, model)

# Rate limit patterns (used by both pool_driver and CLI executors)
_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "session limit",
    "quota exceeded",
    "you've hit your limit",
    "hit your limit",
    "rate limited",
    "too many requests",
)


class NoCLIAvailableError(Exception):
    """Raised when no CLI executor is available (all rate-limited or excluded)."""


class NormalizedOutput(TypedDict):
    """Standard output shape returned by every CLI executor's execute()."""

    content: str          # Main text response
    model: str | None  # Model name used, if available
    cli_name: str         # Name of the CLI that produced this output
    tokens_used: int | None   # Token count if available
    duration_ms: int | None   # Execution duration if available
    raw: dict             # Original unmodified output from the CLI


class BaseCLIExecutor(ABC):
    """Abstract base class for CLI executors."""

    def __init__(self, config: CLIConfig):
        self.config = config

    @abstractmethod
    def _run_raw(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run the CLI and return the raw parsed output dict."""
        ...

    @abstractmethod
    def normalize_output(self, raw_output: dict) -> NormalizedOutput:
        """Map CLI-specific raw output to the standard NormalizedOutput shape."""
        ...

    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run the CLI, normalize output, and return a merged result dict.

        The returned dict contains all raw keys (backward compat) plus the
        six standardized NormalizedOutput fields: content, model, cli_name,
        tokens_used, duration_ms, raw.
        """
        raw = self._run_raw(prompt, context, directory, model)
        # Strip reasoning field once centrally (per spec)
        raw.pop("reasoning", None)
        logger.info(
            "[%s] CLI result — exit_code=%s content=%r",
            self.config.name,
            raw.get("exit_code", raw.get("returncode", "?")),
            str(raw.get("result", raw.get("content", "")))[:2000],
        )
        if raw.get("parse_error"):
            logger.warning("[%s] CLI output parse error — raw stdout: %r", self.config.name, str(raw.get("result", ""))[:500])
        norm = self.normalize_output(raw)
        # Merge: start with raw for backward compat, then overlay normalized fields.
        result = dict(raw)
        result["content"] = norm["content"]
        result["cli_name"] = norm["cli_name"]
        result["raw"] = norm["raw"]
        # Only overlay optional fields when the normalized value is not None,
        # so existing raw values (e.g. tokens_used=0 from Claude) are preserved.
        if norm.get("model") is not None:
            result["model"] = norm["model"]
        if norm.get("tokens_used") is not None:
            result["tokens_used"] = norm["tokens_used"]
        if norm.get("duration_ms") is not None:
            result["duration_ms"] = norm["duration_ms"]
        return result

    @abstractmethod
    def format_context(self, messages: list[dict[str, str]]) -> str:
        """Convert context messages to a CLI-specific string for prompt prepending.

        Returns empty string when messages is empty.
        """
        ...

    @abstractmethod
    def check_rate_limit(self) -> bool:
        """Return True if this CLI is currently rate-limited."""
        ...

    def get_model_list(self) -> list[str]:
        """Return the list of available models from the config."""
        return self.config.models


class ClaudeExecutor(BaseCLIExecutor):
    """Executor for Anthropic Claude CLI."""

    def __init__(self, config: CLIConfig):
        """Initialise executor and reset per-call state tracking."""
        super().__init__(config)
        self._last_exit_code: int | None = None
        self._last_stderr: str = ""
        self._last_stdout: str = ""

    def _run_raw(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run Claude CLI and return raw parsed output dict."""
        import json
        import os
        import tempfile

        cmd = build_cmd_from_profile(self.config.path, "claude", prompt, model)

        # Add context if available (for multi-turn conversations)
        ctx_file = None
        if context:
            try:
                ctx_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", dir=directory, delete=False
                )
                json.dump(context, ctx_file)
                ctx_file.close()
                cmd.extend(["--context", ctx_file.name])
            except Exception:
                if ctx_file:
                    try:
                        os.unlink(ctx_file.name)
                    except OSError:
                        pass
                ctx_file = None

        try:
            logger.info("[claude] CLI command: %s", shlex.join(cmd))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,  # 30 minutes
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            self._last_stdout = result.stdout
            self._last_stderr = result.stderr
            logger.info("[claude] exit_code=%d stdout=%r stderr=%r",
                        result.returncode, result.stdout[:2000], result.stderr[:500])

            if result.stdout:
                import team_cli.executor as _exec_mod
                return _exec_mod.parse_claude_output(result.stdout.encode("utf-8"))
            else:
                return {
                    "result": result.stderr or "No output",
                    "parse_error": True,
                }
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            self._last_stderr = "Task timed out after 30 minutes"
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            self._last_stderr = str(e)
            return {"result": f"Execution error: {str(e)}", "parse_error": True}
        finally:
            if ctx_file:
                try:
                    import os
                    os.unlink(ctx_file.name)
                except OSError:
                    pass

    def normalize_output(self, raw_output: dict) -> NormalizedOutput:
        """Normalize Claude's parsed output to the standard shape."""
        tokens = raw_output.get("tokens_used")
        return NormalizedOutput(
            content=str(raw_output.get("result", "")),
            model=raw_output.get("model"),
            cli_name=self.config.name,
            tokens_used=int(tokens) if tokens else None,
            duration_ms=raw_output.get("duration_ms"),
            raw=dict(raw_output),
        )

    def format_context(self, messages: list[dict[str, str]]) -> str:
        """Format context as Claude's Human/Assistant multi-turn format."""
        if not messages:
            return ""
        parts = []
        for msg in messages:
            role = "Human" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content']}")
        return "\n".join(parts) + "\n"

    def check_rate_limit(self) -> bool:
        """Check if the last execution hit a rate limit."""
        if self._last_exit_code == 1 and self._last_stderr:
            stderr_lower = self._last_stderr.lower()
            return any(pattern in stderr_lower for pattern in _RATE_LIMIT_PATTERNS)
        return False


def parse_vibe_output(raw: str) -> dict:
    """Parse a Mistral Vibe JSON output (list of conversation messages).

    Extracts content and message_id from the last assistant message.

    Returns a dict with:
        result     - assistant text content
        message_id - assistant message_id (UUID string)

    # TODO: detect and surface error messages — unclear yet how vibe signals
    # errors (non-zero exit code? error role? specific field?). Needs a real
    # error sample to implement.
    """
    import json

    messages: list[dict] = json.loads(raw)

    assistant_msg = next(
        (m for m in reversed(messages) if m.get("role") == "assistant"),
        None,
    )
    if assistant_msg is None:
        return {"result": "", "parse_error": True, "raw": raw}

    return {
        "result": assistant_msg.get("content") or "",
        "message_id": assistant_msg.get("message_id"),
    }


class MistralExecutor(BaseCLIExecutor):
    """Executor for Mistral CLI."""

    def __init__(self, config: CLIConfig):
        """Initialise executor and reset per-call state tracking."""
        super().__init__(config)
        self._last_exit_code: int | None = None
        self._last_stdout: str = ""
        self._last_stderr: str = ""

    def _run_raw(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run Mistral CLI and return raw parsed output dict."""
        import json
        cmd = build_cmd_from_profile(self.config.path, "mistral", prompt)

        logger.info("[vibe] CLI command: %s", shlex.join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            self._last_stdout = result.stdout
            self._last_stderr = result.stderr
            logger.info("[vibe] exit_code=%d stdout=%r stderr=%r",
                        result.returncode, result.stdout[:2000], result.stderr[:500])

            if result.stdout:
                try:
                    return parse_vibe_output(result.stdout)
                except (json.JSONDecodeError, Exception):
                    return {"result": result.stdout, "parse_error": True}
            else:
                return {"result": result.stderr or "No output", "parse_error": True}
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            return {"result": f"Execution error: {str(e)}", "parse_error": True}

    def normalize_output(self, raw_output: dict) -> NormalizedOutput:
        """Normalize Mistral's output to the standard shape."""
        content = str(raw_output.get("result", raw_output.get("content", "")))
        usage = raw_output.get("usage", {})
        tokens: int | None = None
        if isinstance(usage, dict):
            t = usage.get("total_tokens") or usage.get("tokens_used")
            tokens = int(t) if t else None
        if tokens is None:
            t = raw_output.get("tokens_used")
            tokens = int(t) if t else None
        return NormalizedOutput(
            content=content,
            model=raw_output.get("model"),
            cli_name=self.config.name,
            tokens_used=tokens,
            duration_ms=raw_output.get("duration_ms"),
            raw=dict(raw_output),
        )

    def format_context(self, messages: list[dict[str, str]]) -> str:
        """Format context as a readable conversation block."""
        if not messages:
            return ""
        lines = ["[Previous conversation:]"]
        for msg in messages:
            role = "User" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        lines.append("[End of context]")
        return "\n".join(lines) + "\n"

    def check_rate_limit(self) -> bool:
        """Check if the last execution hit a rate limit."""
        if self._last_exit_code == 1:
            output_text = (self._last_stdout + self._last_stderr).lower()
            return any(p in output_text for p in _RATE_LIMIT_PATTERNS) or "429" in output_text
        return False


class GenericCLIExecutor(BaseCLIExecutor):
    """Executor for custom CLIs configured via clis.json."""

    def __init__(self, config: CLIConfig):
        """Initialise executor and reset per-call state tracking."""
        super().__init__(config)
        self._last_exit_code: int | None = None

    def _run_raw(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        """Run custom CLI using args_template as static flags only.

        args_template is split into a fixed argv list — no string interpolation
        is performed, so a prompt containing shell metacharacters cannot inject
        extra arguments (C6 fix).  The prompt is always appended as the final
        isolated positional argument.
        """
        import json
        import shlex

        template = self.config.args_template or ""
        try:
            static_args = shlex.split(template) if template else []
        except ValueError:
            static_args = template.split() if template else []

        # Prompt is a separate argument, never interpolated into the template
        cmd = [self.config.path] + static_args + [prompt]

        logger.info("[%s] CLI command: %s", self.config.name, shlex.join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            logger.info("[%s] exit_code=%d stdout=%r stderr=%r",
                        self.config.name, result.returncode,
                        result.stdout[:2000], result.stderr[:500])

            if result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"result": result.stdout}
            else:
                return {"result": result.stderr or "No output"}
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            return {"result": f"Execution error: {str(e)}", "parse_error": True}

    def normalize_output(self, raw_output: dict) -> NormalizedOutput:
        """Best-effort normalization for generic CLI output."""
        content = str(
            raw_output.get("result",
            raw_output.get("content",
            raw_output.get("output", "")))
        )
        t = raw_output.get("tokens_used")
        return NormalizedOutput(
            content=content,
            model=raw_output.get("model"),
            cli_name=self.config.name,
            tokens_used=int(t) if t else None,
            duration_ms=raw_output.get("duration_ms"),
            raw=dict(raw_output),
        )

    def format_context(self, messages: list[dict[str, str]]) -> str:
        """Format context as a readable conversation block."""
        if not messages:
            return ""
        lines = ["[Previous conversation:]"]
        for msg in messages:
            role = "User" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        lines.append("[End of context]")
        return "\n".join(lines) + "\n"

    def check_rate_limit(self) -> bool:
        """Custom CLIs are assumed not to rate-limit by default."""
        return False


class LlamaExecutor(GenericCLIExecutor):
    """Executor for Llama CLI (uses GenericCLIExecutor logic)."""
    pass


class GemmaExecutor(GenericCLIExecutor):
    """Executor for Gemma CLI (uses GenericCLIExecutor logic)."""
    pass


class OpenCodeExecutor(BaseCLIExecutor):
    """Executor for opencode CLI.

    opencode's default positional is a project directory, not a prompt.
    Prompts must be sent via the `run` subcommand: opencode run --format json <message..>
    """

    def __init__(self, config: CLIConfig):
        super().__init__(config)
        self._last_exit_code: int | None = None

    def _run_raw(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        import json

        cmd = build_cmd_from_profile(self.config.path, "opencode", prompt, model)

        logger.info("[opencode] CLI command: %s", shlex.join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            logger.info("[opencode] exit_code=%d stdout=%r stderr=%r",
                        result.returncode, result.stdout[:2000], result.stderr[:500])

            if result.stdout:
                # opencode --format json emits newline-delimited JSON events;
                # find the last non-empty line with a "content" or "text" key.
                content = ""
                for line in reversed(result.stdout.splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        text = event.get("content") or event.get("text") or event.get("result", "")
                        if text:
                            content = str(text)
                            break
                    except json.JSONDecodeError:
                        continue
                return {"result": content or result.stdout, "raw_stdout": result.stdout}
            else:
                return {"result": result.stderr or "No output", "parse_error": True}
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            return {"result": f"Execution error: {str(e)}", "parse_error": True}

    def normalize_output(self, raw_output: dict) -> NormalizedOutput:
        content = str(raw_output.get("result", raw_output.get("content", "")))
        return NormalizedOutput(
            content=content,
            model=raw_output.get("model"),
            cli_name=self.config.name,
            tokens_used=None,
            duration_ms=raw_output.get("duration_ms"),
            raw=dict(raw_output),
        )

    def format_context(self, messages: list[dict[str, str]]) -> str:
        if not messages:
            return ""
        lines = ["[Previous conversation:]"]
        for msg in messages:
            role = "User" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        lines.append("[End of context]")
        return "\n".join(lines) + "\n"

    def check_rate_limit(self) -> bool:
        return False


class HermesExecutor(BaseCLIExecutor):
    """Executor for Hermes CLI.

    Hermes treats positional args as subcommands; prompts go via -z/--oneshot.
    Command: hermes -z <prompt> [-m <model>] --yolo
    """

    def __init__(self, config: CLIConfig):
        super().__init__(config)
        self._last_exit_code: int | None = None

    def _run_raw(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str,
    ) -> dict:
        cmd = build_cmd_from_profile(self.config.path, "hermes", prompt, model)

        logger.info("[hermes] CLI command: %s", shlex.join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 * 60,
                cwd=directory,
            )
            self._last_exit_code = result.returncode
            logger.info("[hermes] exit_code=%d stdout=%r stderr=%r",
                        result.returncode, result.stdout[:2000], result.stderr[:500])
            output = result.stdout.strip() if result.stdout else (result.stderr.strip() or "No output")
            return {"result": output}
        except subprocess.TimeoutExpired:
            self._last_exit_code = -1
            return {"result": "Task timed out after 30 minutes", "parse_error": True}
        except Exception as e:
            self._last_exit_code = -1
            return {"result": f"Execution error: {str(e)}", "parse_error": True}

    def normalize_output(self, raw_output: dict) -> NormalizedOutput:
        content = str(raw_output.get("result", ""))
        return NormalizedOutput(
            content=content,
            model=raw_output.get("model"),
            cli_name=self.config.name,
            tokens_used=None,
            duration_ms=raw_output.get("duration_ms"),
            raw=dict(raw_output),
        )

    def format_context(self, messages: list[dict[str, str]]) -> str:
        if not messages:
            return ""
        lines = ["[Previous conversation:]"]
        for msg in messages:
            role = "User" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        lines.append("[End of context]")
        return "\n".join(lines) + "\n"

    def check_rate_limit(self) -> bool:
        return False


def create_executor(config: CLIConfig) -> BaseCLIExecutor:
    """Factory function to create a CLI executor based on config type."""
    if config.cli_type == "anthropic":
        return ClaudeExecutor(config)
    elif config.cli_type == "mistral":
        return MistralExecutor(config)
    elif config.cli_type == "llama":
        return LlamaExecutor(config)
    elif config.cli_type == "gemma":
        return GemmaExecutor(config)
    elif config.cli_type == "opencode":
        return OpenCodeExecutor(config)
    elif config.cli_type == "hermes":
        return HermesExecutor(config)
    elif config.cli_type == "custom":
        return GenericCLIExecutor(config)
    elif config.cli_type in ("antigravity", "openai"):
        return GenericCLIExecutor(config)
    raise ValueError(f"Unsupported CLI type: {config.cli_type}")


class CLIManager:
    """Manages multiple CLI executors with fallback logic."""

    def __init__(self, configs: list[CLIConfig]):
        """Build executor pool from enabled configs."""
        self._executors: list[BaseCLIExecutor] = [
            create_executor(c) for c in configs if c.enabled
        ]

    def execute(
        self,
        prompt: str,
        context: list[dict],
        directory: str,
        model: str = "",
    ) -> dict:
        """Try executors in order; skip any that are currently rate-limited.

        Raises:
            RuntimeError: If all CLI executors are rate-limited or failed.
        """
        if not model:
            for executor in self._executors:
                if executor.config.default_model:
                    model = executor.config.default_model
                    break
            else:
                if self._executors and self._executors[0].config.models:
                    model = self._executors[0].config.models[0]

        available = self.available_executors()
        if not available:
            raise RuntimeError("All CLI executors are rate-limited or failed")

        for executor in available:
            result = executor.execute(prompt, context, directory, model)
            if executor.check_rate_limit():
                continue
            return result

        raise RuntimeError("All CLI executors are rate-limited or failed")

    def available_executors(self) -> list[BaseCLIExecutor]:
        """Return list of executors that are not currently rate-limited."""
        return [e for e in self._executors if not e.check_rate_limit()]

    def get_next_available_cli(self, exclude: list[str]) -> "BaseCLIExecutor | None":
        """Return the first executor that is not excluded and not rate-limited."""
        for executor in self._executors:
            if executor.config.name in exclude:
                continue
            if executor.check_rate_limit():
                continue
            return executor
        return None

    def get_executor_by_name(self, name: str) -> "BaseCLIExecutor | None":
        """Return the executor whose config.name matches *name*, or None."""
        for executor in self._executors:
            if executor.config.name == name:
                return executor
        return None


def truncate_context_messages(
    messages: list[dict[str, str]],
    max_count: int = 3,
) -> list[dict[str, str]]:
    """Return the last *max_count* messages, keeping context bounded."""
    if len(messages) <= max_count:
        return messages
    return messages[-max_count:]
