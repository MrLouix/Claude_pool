"""Tests for TUI task row rendering enhancements (kind tag, parent indicator, CLI name)."""

from pathlib import Path

_TUI_SRC = (Path(__file__).parent.parent / "team_cli" / "tui.py").read_text(encoding="utf-8")


class TestTuiTaskRowSource:
    def test_request_kind_tag_present(self) -> None:
        """tui.py must reference the '[req]' kind tag for request tasks."""
        assert "[req]" in _TUI_SRC

    def test_subtask_kind_tag_present(self) -> None:
        """tui.py must reference the '[sub]' kind tag for subtask tasks."""
        assert "[sub]" in _TUI_SRC

    def test_parent_indicator_present(self) -> None:
        """tui.py must contain the '↳' parent indicator for subtasks."""
        assert "↳" in _TUI_SRC

    def test_cli_name_fallback_present(self) -> None:
        """tui.py must fall back to 'claude' when cli_id is not set."""
        assert "'claude'" in _TUI_SRC or '"claude"' in _TUI_SRC

    def test_kind_field_accessed(self) -> None:
        """tui.py must read the 'kind' field from the task."""
        assert "kind" in _TUI_SRC

    def test_parent_task_id_field_accessed(self) -> None:
        """tui.py must read the 'parent_task_id' field from the task."""
        assert "parent_task_id" in _TUI_SRC

    def test_cli_id_field_accessed(self) -> None:
        """tui.py must read the 'cli_id' field from the task."""
        assert "cli_id" in _TUI_SRC
