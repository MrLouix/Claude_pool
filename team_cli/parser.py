"""Parser for Claude Code CLI output."""

import json
import re
from typing import Any

# Estimate context window size for session usage calculation
_SESSION_CONTEXT_WINDOW = 1_000_000

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _make_error_result(text: str, error_message: str | None = None) -> dict[str, Any]:
    """Build a uniform error result dict."""
    result: dict[str, Any] = {
        "result": text[:1000],
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 0,
        "session_usage_percent": 0.0,
        "parse_error": True,
    }
    if error_message is not None:
        result["error_message"] = error_message
    return result


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from text.

    Tries in order: direct parse, markdown code fence, raw ``{...}`` object.

    Raises:
        ValueError: if no JSON object is found anywhere in the text.
        json.JSONDecodeError: if a JSON object is found but is malformed.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    raw = re.search(r"\{.*\}", text, re.DOTALL)
    if raw:
        return json.loads(raw.group(0))
    raise ValueError("no JSON found in output")


def _extract_session_id(data: dict[str, Any]) -> str | None:
    """Return session_id from either the session_id or sessionKey field."""
    return data.get("session_id") or data.get("sessionKey") or None


def _parse_new_format(data: dict[str, Any]) -> dict[str, Any]:
    """Parse the new Claude format: ``{"type":"result","result":"...","usage":{...}}``."""
    result_text = data.get("result", "")

    code_matches = re.findall(r"```(\w+)?\n(.*?)```", result_text, re.DOTALL)
    code_blocks = [
        {
            "language": lang or "text",
            "filename": f"code_{i}.txt",
            "content": content.strip(),
        }
        for i, (lang, content) in enumerate(code_matches)
    ]

    usage = data.get("usage", {})
    total_tokens = (
        sum(usage.get(f, 0) for f in _TOKEN_FIELDS) if isinstance(usage, dict) else 0
    )
    session_usage_percent = (
        round(min(100.0, (total_tokens / _SESSION_CONTEXT_WINDOW) * 100), 2)
        if total_tokens > 0
        else 0.0
    )

    result: dict[str, Any] = {
        "result": result_text,
        "code_blocks": code_blocks,
        "files_changed": [],
        "tokens_used": total_tokens,
        "session_usage_percent": session_usage_percent,
    }
    session_id = _extract_session_id(data)
    if session_id:
        result["session_id"] = session_id
    return result


def _parse_legacy_format(data: dict[str, Any]) -> dict[str, Any]:
    """Parse the original Claude format with explicit code_blocks / files_changed fields."""
    raw_blocks = data.get("code_blocks", [])
    code_blocks = []
    if isinstance(raw_blocks, list):
        for i, block in enumerate(raw_blocks):
            if isinstance(block, dict):
                code_blocks.append(
                    {
                        "language": block.get("language") or block.get("lang", "unknown"),
                        "filename": block.get("filename", f"code_{i}.txt"),
                        "content": block.get("content", ""),
                    }
                )

    files_changed = data.get("files_changed", [])
    if not isinstance(files_changed, list):
        files_changed = []

    result: dict[str, Any] = {
        "result": str(data.get("result", "")),
        "code_blocks": code_blocks,
        "files_changed": files_changed,
        "tokens_used": int(data.get("tokens_used", 0)),
        "session_usage_percent": float(data.get("session_usage_percent", 0.0)),
    }
    session_id = _extract_session_id(data)
    if session_id:
        result["session_id"] = session_id
    return result


def parse_claude_output(stdout: bytes) -> dict[str, Any]:
    """Parse Claude --output-format json structured output.

    Extracts the JSON block from Claude's output and returns a compact
    structure without the 'reasoning' field.

    Args:
        stdout: Raw stdout bytes from claude command

    Returns:
        Compact dict with:
        - result: str
        - code_blocks: list of dicts with language, filename, content
        - files_changed: list of file paths
        - tokens_used: int
        - session_usage_percent: float
        - parse_error: bool (only present if parsing failed)
    """
    try:
        text = stdout.decode("utf-8", errors="replace")
        try:
            data = _extract_json(text)
        except ValueError:
            # No JSON object found anywhere — return text as-is
            return _make_error_result(text)
        # Strip reasoning field once centrally (per spec)
        data.pop("reasoning", None)
        if data.get("type") == "result":
            return _parse_new_format(data)
        return _parse_legacy_format(data)
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        try:
            text = stdout.decode("utf-8", errors="replace")
        except Exception:
            text = str(stdout)
        return _make_error_result(text, str(e))
