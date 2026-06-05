"""Tests for Claude output parser."""

import json

import pytest

from team_cli.parser import (
    _TOKEN_FIELDS,
    _extract_json,
    _extract_session_id,
    _make_error_result,
    _parse_legacy_format,
    _parse_new_format,
    parse_claude_output,
)


def test_parse_valid_json():
    """Test parsing valid JSON output from Claude."""
    output_data = {
        "result": "Fixed the login bug successfully",
        "code_blocks": [
            {
                "language": "python",
                "filename": "auth.py",
                "content": "def login(user, password):\n    return authenticate(user, password)",
            }
        ],
        "files_changed": ["/home/user/app/auth.py"],
        "tokens_used": 1500,
        "session_usage_percent": 25.5,
        "reasoning": "This is internal reasoning that should be stripped",
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert result["result"] == "Fixed the login bug successfully"
    assert len(result["code_blocks"]) == 1
    assert result["code_blocks"][0]["language"] == "python"
    assert result["code_blocks"][0]["filename"] == "auth.py"
    assert result["files_changed"] == ["/home/user/app/auth.py"]
    assert result["tokens_used"] == 1500
    assert result["session_usage_percent"] == 25.5
    assert "reasoning" not in result
    assert "parse_error" not in result


def test_parse_json_in_markdown():
    """Test parsing JSON wrapped in markdown code fence."""
    output_data = {
        "result": "Task completed",
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 500,
        "session_usage_percent": 10.0,
    }

    markdown = f"Here is the output:\n```json\n{json.dumps(output_data)}\n```\nDone!"
    stdout = markdown.encode("utf-8")

    result = parse_claude_output(stdout)

    assert result["result"] == "Task completed"
    assert result["tokens_used"] == 500
    assert "parse_error" not in result


def test_parse_json_with_code_fence_no_language():
    """Test parsing JSON in code fence without language marker."""
    output_data = {
        "result": "Success",
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 100,
        "session_usage_percent": 5.0,
    }

    markdown = f"```\n{json.dumps(output_data)}\n```"
    stdout = markdown.encode("utf-8")

    result = parse_claude_output(stdout)

    assert result["result"] == "Success"
    assert "parse_error" not in result


def test_parse_minimal_json():
    """Test parsing JSON with minimal fields."""
    output_data = {
        "result": "Done",
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert result["result"] == "Done"
    assert result["code_blocks"] == []
    assert result["files_changed"] == []
    assert result["tokens_used"] == 0
    assert result["session_usage_percent"] == 0.0


def test_parse_code_blocks_with_lang_field():
    """Test parsing code blocks that use 'lang' instead of 'language'."""
    output_data = {
        "result": "Code generated",
        "code_blocks": [
            {
                "lang": "javascript",
                "content": "console.log('hello');",
            }
        ],
        "tokens_used": 200,
        "session_usage_percent": 5.0,
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert len(result["code_blocks"]) == 1
    assert result["code_blocks"][0]["language"] == "javascript"
    assert result["code_blocks"][0]["filename"] == "code_0.txt"
    assert "hello" in result["code_blocks"][0]["content"]


def test_parse_multiple_code_blocks():
    """Test parsing multiple code blocks."""
    output_data = {
        "result": "Generated multiple files",
        "code_blocks": [
            {"language": "python", "filename": "main.py", "content": "print('main')"},
            {"language": "python", "filename": "utils.py", "content": "def helper(): pass"},
        ],
        "tokens_used": 800,
        "session_usage_percent": 15.0,
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert len(result["code_blocks"]) == 2
    assert result["code_blocks"][0]["filename"] == "main.py"
    assert result["code_blocks"][1]["filename"] == "utils.py"


def test_parse_non_json_text():
    """Test parsing plain text (no JSON)."""
    text = "This is just plain text output from a command."
    stdout = text.encode("utf-8")

    result = parse_claude_output(stdout)

    assert result["parse_error"] is True
    assert "plain text" in result["result"]
    assert result["code_blocks"] == []
    assert result["tokens_used"] == 0


def test_parse_invalid_json():
    """Test parsing malformed JSON."""
    invalid_json = b'{"result": "incomplete'

    result = parse_claude_output(invalid_json)

    assert result["parse_error"] is True
    assert result["code_blocks"] == []


def test_parse_empty_output():
    """Test parsing empty output."""
    result = parse_claude_output(b"")

    assert result["parse_error"] is True
    assert result["result"] == ""


def test_parse_long_text_truncation():
    """Test that long non-JSON text is truncated."""
    long_text = "x" * 2000
    stdout = long_text.encode("utf-8")

    result = parse_claude_output(stdout)

    assert result["parse_error"] is True
    assert len(result["result"]) == 1000


def test_parse_with_unicode():
    """Test parsing output with Unicode characters."""
    output_data = {
        "result": "Réussi avec succès! 🎉",
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 300,
        "session_usage_percent": 8.0,
    }

    stdout = json.dumps(output_data, ensure_ascii=False).encode("utf-8")
    result = parse_claude_output(stdout)

    assert "Réussi" in result["result"]
    assert "🎉" in result["result"]


def test_parse_files_changed_not_list():
    """Test handling of files_changed when it's not a list."""
    output_data = {
        "result": "Done",
        "files_changed": "not a list",
        "tokens_used": 100,
        "session_usage_percent": 5.0,
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert result["files_changed"] == []


def test_parse_code_blocks_not_list():
    """Test handling of code_blocks when it's not a list."""
    output_data = {
        "result": "Done",
        "code_blocks": "not a list",
        "tokens_used": 100,
        "session_usage_percent": 5.0,
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert result["code_blocks"] == []


def test_parse_with_session_id():
    """Test extraction of session_id from Claude output."""
    test_session_id = "sess_abc123def456"
    output_data = {
        "result": "Task completed with session",
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 100,
        "session_usage_percent": 5.0,
        "session_id": test_session_id,
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert result["session_id"] == test_session_id


def test_parse_new_format_with_session_id():
    """Test extraction of session_id from new format output."""
    test_session_id = "sess_new_format_123"
    output_data = {
        "type": "result",
        "result": "Success with new format",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
        },
        "session_id": test_session_id,
    }

    stdout = json.dumps(output_data).encode("utf-8")
    result = parse_claude_output(stdout)

    assert result["session_id"] == test_session_id
    assert result["result"] == "Success with new format"


# ── Helper function tests ──────────────────────────────────────────────────────


class TestExtractJson:
    def test_direct_json(self):
        data = {"key": "value"}
        assert _extract_json(json.dumps(data)) == data

    def test_json_in_markdown_fence_with_language(self):
        data = {"result": "ok"}
        text = f"Some text\n```json\n{json.dumps(data)}\n```\nMore text"
        assert _extract_json(text) == data

    def test_json_in_markdown_fence_without_language(self):
        data = {"result": "ok"}
        text = f"```\n{json.dumps(data)}\n```"
        assert _extract_json(text) == data

    def test_raw_json_object_embedded_in_text(self):
        data = {"x": 1}
        text = f"prefix {json.dumps(data)} suffix"
        assert _extract_json(text) == data

    def test_raises_value_error_when_no_json(self):
        with pytest.raises(ValueError, match="no JSON found"):
            _extract_json("plain text with no JSON here")

    def test_raises_json_decode_error_for_malformed_fence_json(self):
        text = "```json\n{bad json\n```"
        with pytest.raises(json.JSONDecodeError):
            _extract_json(text)


class TestExtractSessionId:
    def test_returns_session_id_field(self):
        assert _extract_session_id({"session_id": "abc"}) == "abc"

    def test_returns_session_key_field(self):
        assert _extract_session_id({"sessionKey": "xyz"}) == "xyz"

    def test_session_id_takes_priority_over_session_key(self):
        assert _extract_session_id({"session_id": "sid", "sessionKey": "sk"}) == "sid"

    def test_returns_none_when_neither_present(self):
        assert _extract_session_id({}) is None

    def test_returns_none_when_both_falsy(self):
        assert _extract_session_id({"session_id": "", "sessionKey": ""}) is None


class TestMakeErrorResult:
    def test_without_error_message(self):
        result = _make_error_result("some text")
        assert result["parse_error"] is True
        assert result["result"] == "some text"
        assert result["code_blocks"] == []
        assert result["files_changed"] == []
        assert result["tokens_used"] == 0
        assert result["session_usage_percent"] == 0.0
        assert "error_message" not in result

    def test_with_error_message(self):
        result = _make_error_result("text", "something broke")
        assert result["parse_error"] is True
        assert result["error_message"] == "something broke"

    def test_text_truncated_to_1000_chars(self):
        long_text = "x" * 2000
        result = _make_error_result(long_text)
        assert len(result["result"]) == 1000


class TestParseNewFormat:
    def test_basic_result(self):
        data = {"type": "result", "result": "hello", "usage": {}}
        result = _parse_new_format(data)
        assert result["result"] == "hello"
        assert result["files_changed"] == []
        assert result["code_blocks"] == []

    def test_token_sum_uses_all_fields(self):
        data = {
            "type": "result",
            "result": "",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 25,
                "cache_creation_input_tokens": 10,
            },
        }
        result = _parse_new_format(data)
        assert result["tokens_used"] == 185

    def test_token_fields_tuple_covers_all_usage_keys(self):
        assert "input_tokens" in _TOKEN_FIELDS
        assert "output_tokens" in _TOKEN_FIELDS
        assert "cache_read_input_tokens" in _TOKEN_FIELDS
        assert "cache_creation_input_tokens" in _TOKEN_FIELDS

    def test_session_usage_percent_capped_at_100(self):
        data = {
            "type": "result",
            "result": "",
            "usage": {"input_tokens": 2_000_000},
        }
        result = _parse_new_format(data)
        assert result["session_usage_percent"] == 100.0

    def test_extracts_code_blocks_from_result_text(self):
        data = {
            "type": "result",
            "result": "Here:\n```python\nprint('hi')\n```",
            "usage": {},
        }
        result = _parse_new_format(data)
        assert len(result["code_blocks"]) == 1
        assert result["code_blocks"][0]["language"] == "python"

    def test_session_id_included_when_present(self):
        data = {"type": "result", "result": "", "usage": {}, "session_id": "s123"}
        result = _parse_new_format(data)
        assert result["session_id"] == "s123"

    def test_session_id_absent_when_not_in_data(self):
        data = {"type": "result", "result": "", "usage": {}}
        result = _parse_new_format(data)
        assert "session_id" not in result

    def test_non_dict_usage_yields_zero_tokens(self):
        data = {"type": "result", "result": "", "usage": "bad"}
        result = _parse_new_format(data)
        assert result["tokens_used"] == 0


class TestParseLegacyFormat:
    def test_basic_result(self):
        data = {"result": "done", "tokens_used": 100, "session_usage_percent": 5.0}
        result = _parse_legacy_format(data)
        assert result["result"] == "done"
        assert result["tokens_used"] == 100
        assert result["session_usage_percent"] == 5.0

    def test_code_blocks_with_lang_alias(self):
        data = {
            "result": "",
            "code_blocks": [{"lang": "js", "content": "x()"}],
        }
        result = _parse_legacy_format(data)
        assert result["code_blocks"][0]["language"] == "js"

    def test_non_list_files_changed_becomes_empty(self):
        data = {"result": "", "files_changed": "not-a-list"}
        result = _parse_legacy_format(data)
        assert result["files_changed"] == []

    def test_non_list_code_blocks_becomes_empty(self):
        data = {"result": "", "code_blocks": "not-a-list"}
        result = _parse_legacy_format(data)
        assert result["code_blocks"] == []

    def test_session_id_via_session_key(self):
        data = {"result": "", "sessionKey": "sk_abc"}
        result = _parse_legacy_format(data)
        assert result["session_id"] == "sk_abc"

    def test_session_id_absent_when_not_in_data(self):
        data = {"result": ""}
        result = _parse_legacy_format(data)
        assert "session_id" not in result
