"""Tests for subtask extraction in parse_claude_output (Step 6 — parser extension)."""

import json

from team_cli.parser import ParsedOutput, parse_claude_output


def _make_legacy(result_text: str, session_id: str | None = None) -> bytes:
    """Build a legacy-format stdout bytes with the given result text."""
    data: dict = {
        "result": result_text,
        "code_blocks": [],
        "files_changed": [],
        "tokens_used": 0,
        "session_usage_percent": 0.0,
    }
    if session_id:
        data["session_id"] = session_id
    return json.dumps(data).encode()


def _make_new_format(result_text: str, session_id: str | None = None) -> bytes:
    """Build a new-format (type=result) stdout bytes."""
    data: dict = {
        "type": "result",
        "result": result_text,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    if session_id:
        data["session_id"] = session_id
    return json.dumps(data).encode()


# ── 1. result_with_subtasks_block ─────────────────────────────────────────────

class TestResultWithSubtasksBlock:
    def test_subtasks_extracted(self):
        block = '{"subtasks": [{"prompt": "p1", "model": "m1"}, {"prompt": "p2"}]}'
        stdout = _make_legacy(f"Do something.\n{block}")
        result = parse_claude_output(stdout)
        assert result["subtasks"] == [
            {"prompt": "p1", "model": "m1"},
            {"prompt": "p2", "model": None},
        ]

    def test_block_removed_from_result(self):
        block = '{"subtasks": [{"prompt": "p1", "model": "m1"}]}'
        stdout = _make_legacy(f"Do something.\n{block}")
        result = parse_claude_output(stdout)
        assert block not in result["result"]

    def test_result_text_cleaned(self):
        """7. result_text_cleaned: subtasks JSON block does not appear in ParsedOutput.result."""
        block = '{"subtasks": [{"prompt": "clean me out"}]}'
        stdout = _make_legacy(f"Preamble text. {block} Trailing text.")
        result = parse_claude_output(stdout)
        assert "subtasks" not in result["result"]
        assert "Preamble text." in result["result"]

    def test_new_format_subtasks_extracted(self):
        block = '{"subtasks": [{"prompt": "task A", "model": "claude-3"}]}'
        stdout = _make_new_format(f"Output here.\n{block}")
        result = parse_claude_output(stdout)
        assert len(result["subtasks"]) == 1
        assert result["subtasks"][0]["prompt"] == "task A"
        assert result["subtasks"][0]["model"] == "claude-3"


# ── 2. result_without_subtasks_block ─────────────────────────────────────────

class TestResultWithoutSubtasksBlock:
    def test_subtasks_empty(self):
        stdout = _make_legacy("Normal output with no subtasks block.")
        result = parse_claude_output(stdout)
        assert result["subtasks"] == []

    def test_result_unchanged(self):
        text = "Normal output with no subtasks block."
        stdout = _make_legacy(text)
        result = parse_claude_output(stdout)
        assert result["result"] == text


# ── 3. malformed_subtasks_json — "subtasks" value is not a list ──────────────

class TestMalformedSubtasksValue:
    def test_subtasks_empty_when_not_list(self):
        """3. malformed_subtasks_json: {"subtasks": "not-a-list"} -> subtasks=[]."""
        block = '{"subtasks": "not-a-list"}'
        stdout = _make_legacy(f"Output. {block}")
        result = parse_claude_output(stdout)
        assert result["subtasks"] == []

    def test_integer_subtasks_value(self):
        block = '{"subtasks": 42}'
        stdout = _make_legacy(f"Output. {block}")
        result = parse_claude_output(stdout)
        assert result["subtasks"] == []


# ── 4. invalid_json_block — broken JSON ──────────────────────────────────────

class TestInvalidJsonBlock:
    def test_broken_json_ignored(self):
        """4. invalid_json_block: broken JSON -> subtasks=[], result unchanged."""
        text = "Output. {subtasks: broken json"
        stdout = _make_legacy(text)
        result = parse_claude_output(stdout)
        assert result["subtasks"] == []
        assert result["result"] == text

    def test_truncated_json_ignored(self):
        text = 'Output. {"subtasks": [{"prompt": "incomplete"'
        stdout = _make_legacy(text)
        result = parse_claude_output(stdout)
        assert result["subtasks"] == []


# ── 5. subtasks_items_without_prompt_skipped ─────────────────────────────────

class TestSubtasksItemsWithoutPromptSkipped:
    def test_items_missing_prompt_dropped(self):
        """5. Items missing 'prompt' key are dropped."""
        block = json.dumps({
            "subtasks": [
                {"prompt": "valid", "model": "m1"},
                {"model": "m2"},          # no prompt
                {"task": "no prompt"},    # no prompt
                {"prompt": "also valid"},
            ]
        })
        stdout = _make_legacy(f"Do stuff.\n{block}")
        result = parse_claude_output(stdout)
        assert len(result["subtasks"]) == 2
        assert result["subtasks"][0]["prompt"] == "valid"
        assert result["subtasks"][1]["prompt"] == "also valid"

    def test_all_items_missing_prompt_gives_empty_list(self):
        block = json.dumps({"subtasks": [{"x": 1}, {"y": 2}]})
        stdout = _make_legacy(f"Do stuff.\n{block}")
        result = parse_claude_output(stdout)
        assert result["subtasks"] == []


# ── 6. session_id_still_parsed ───────────────────────────────────────────────

class TestSessionIdStillParsed:
    def test_session_id_present_with_subtasks(self):
        """6. session_id is still returned correctly when subtasks are present."""
        block = '{"subtasks": [{"prompt": "sub1"}]}'
        stdout = _make_legacy(f"Output.\n{block}", session_id="sess_abc123")
        result = parse_claude_output(stdout)
        assert result.get("session_id") == "sess_abc123"
        assert len(result["subtasks"]) == 1

    def test_session_id_new_format(self):
        block = '{"subtasks": [{"prompt": "sub1", "model": "claude-3"}]}'
        stdout = _make_new_format(f"Output.\n{block}", session_id="sess_xyz789")
        result = parse_claude_output(stdout)
        assert result.get("session_id") == "sess_xyz789"
        assert result["subtasks"][0]["prompt"] == "sub1"


# ── Edge: subtasks block in the middle of result text ─────────────────────────

class TestSubtasksBlockPosition:
    def test_block_at_start(self):
        block = '{"subtasks": [{"prompt": "first"}]}'
        stdout = _make_legacy(f"{block} Trailing text.")
        result = parse_claude_output(stdout)
        assert len(result["subtasks"]) == 1
        assert block not in result["result"]
        assert "Trailing text." in result["result"]

    def test_block_in_middle(self):
        block = '{"subtasks": [{"prompt": "middle"}]}'
        stdout = _make_legacy(f"Before. {block} After.")
        result = parse_claude_output(stdout)
        assert len(result["subtasks"]) == 1
        assert "Before." in result["result"]
        assert "After." in result["result"]

    def test_only_first_subtasks_block_extracted(self):
        """If multiple subtasks blocks exist, only the first is used."""
        block1 = '{"subtasks": [{"prompt": "from block1"}]}'
        block2 = '{"subtasks": [{"prompt": "from block2"}]}'
        stdout = _make_legacy(f"Text. {block1} Middle. {block2} End.")
        result = parse_claude_output(stdout)
        assert result["subtasks"][0]["prompt"] == "from block1"


# ── ParsedOutput TypedDict is importable ─────────────────────────────────────

def test_parsed_output_type_importable():
    """ParsedOutput TypedDict can be imported from team_cli.parser."""
    assert ParsedOutput is not None
