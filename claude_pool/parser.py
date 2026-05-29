"""Parser for Claude Code CLI output."""

import json
import re
from typing import Any


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

        # Try to parse as direct JSON first
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block - could be wrapped in markdown code fence
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                data = json.loads(json_str)
            else:
                # Try to find raw JSON (look for object starting with {)
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    data = json.loads(json_str)
                else:
                    # No JSON found, return text as-is
                    return {
                        "result": text[:1000],
                        "code_blocks": [],
                        "files_changed": [],
                        "tokens_used": 0,
                        "session_usage_percent": 0.0,
                        "parse_error": True,
                    }

        # Handle new format: {"type":"result","result":"...","usage":{...}}
        if data.get("type") == "result":
            result_text = data.get("result", "")
            # Extract code from markdown if present
            code_blocks = []
            code_matches = re.findall(r"```(\w+)?\n(.*?)```", result_text, re.DOTALL)
            for i, (lang, content) in enumerate(code_matches):
                code_blocks.append(
                    {
                        "language": lang or "text",
                        "filename": f"code_{i}.txt",
                        "content": content.strip(),
                    }
                )

            # Extract token usage from usage field
            usage = data.get("usage", {})
            total_tokens = 0
            if isinstance(usage, dict):
                # Sum all token types
                total_tokens += usage.get("input_tokens", 0)
                total_tokens += usage.get("output_tokens", 0)
                total_tokens += usage.get("cache_read_input_tokens", 0)
                total_tokens += usage.get("cache_creation_input_tokens", 0)

            # Calculate session usage (estimate based on 1M context window)
            session_usage_percent = (
                min(100.0, (total_tokens / 1000000) * 100) if total_tokens > 0 else 0.0
            )

            # Extract session_id if present
            session_id = data.get("session_id") or data.get("sessionKey")

            result = {
                "result": result_text,
                "code_blocks": code_blocks,
                "files_changed": [],
                "tokens_used": total_tokens,
                "session_usage_percent": round(session_usage_percent, 2),
            }
            if session_id:
                result["session_id"] = session_id
            return result

        # Original format handling
        # Extract code blocks
        code_blocks = []
        raw_blocks = data.get("code_blocks", [])
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

        # Extract files changed
        files_changed = data.get("files_changed", [])
        if not isinstance(files_changed, list):
            files_changed = []

        # Extract session_id if present
        session_id = data.get("session_id") or data.get("sessionKey")

        result = {
            "result": str(data.get("result", "")),
            "code_blocks": code_blocks,
            "files_changed": files_changed,
            "tokens_used": int(data.get("tokens_used", 0)),
            "session_usage_percent": float(data.get("session_usage_percent", 0.0)),
        }
        if session_id:
            result["session_id"] = session_id
        return result

    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        # If parsing fails, return raw text with error flag
        try:
            text = stdout.decode("utf-8", errors="replace")
        except Exception:
            text = str(stdout)

        return {
            "result": text[:1000],
            "code_blocks": [],
            "files_changed": [],
            "tokens_used": 0,
            "session_usage_percent": 0.0,
            "parse_error": True,
            "error_message": str(e),
        }
