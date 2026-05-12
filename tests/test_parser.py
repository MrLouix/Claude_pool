"""Tests for Claude output parser."""

import json

import pytest

from claude_pool.parser import parse_claude_output


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
