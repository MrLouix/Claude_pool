"""Tests for routing.resolve_command and resolve_command_chain."""

import pytest

from team_cli.models import CliCommand
from team_cli.routing import NoCLICommandError, resolve_command, resolve_command_chain


def _cmd(id: str, priority_requests: int = 100, priority_subtasks: int = 100, enabled: bool = True) -> CliCommand:
    return CliCommand(
        id=id,
        name=id,
        binary=id,
        args_template='["{prompt}"]',
        priority_requests=priority_requests,
        priority_subtasks=priority_subtasks,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# resolve_command — ordering
# ---------------------------------------------------------------------------

class TestResolveCommandOrdering:
    def test_returns_lowest_priority_requests_first(self) -> None:
        cmds = [_cmd("b", priority_requests=20), _cmd("a", priority_requests=10)]
        result = resolve_command("request", None, cmds)
        assert result.id == "a"

    def test_returns_lowest_priority_subtasks_first_for_subtask_kind(self) -> None:
        cmds = [_cmd("b", priority_subtasks=5), _cmd("a", priority_subtasks=50)]
        result = resolve_command("subtask", None, cmds)
        assert result.id == "b"

    def test_request_kind_uses_priority_requests_not_subtasks(self) -> None:
        # "a" has lower subtasks priority but higher requests priority
        cmds = [
            _cmd("a", priority_requests=50, priority_subtasks=1),
            _cmd("b", priority_requests=10, priority_subtasks=99),
        ]
        result = resolve_command("request", None, cmds)
        assert result.id == "b"

    def test_tiebreak_by_id(self) -> None:
        cmds = [_cmd("z", priority_requests=1), _cmd("a", priority_requests=1)]
        result = resolve_command("request", None, cmds)
        assert result.id == "a"


# ---------------------------------------------------------------------------
# resolve_command — requested_cli_id promoted to front
# ---------------------------------------------------------------------------

class TestResolveCommandRequestedId:
    def test_requested_id_goes_to_front(self) -> None:
        cmds = [_cmd("first", priority_requests=1), _cmd("second", priority_requests=2)]
        result = resolve_command("request", "second", cmds)
        assert result.id == "second"

    def test_unknown_requested_id_ignored(self) -> None:
        cmds = [_cmd("only", priority_requests=1)]
        result = resolve_command("request", "nonexistent", cmds)
        assert result.id == "only"

    def test_disabled_requested_id_not_promoted(self) -> None:
        cmds = [_cmd("enabled", priority_requests=1), _cmd("disabled", priority_requests=2, enabled=False)]
        result = resolve_command("request", "disabled", cmds)
        assert result.id == "enabled"


# ---------------------------------------------------------------------------
# resolve_command — disabled commands skipped
# ---------------------------------------------------------------------------

class TestResolveCommandDisabled:
    def test_disabled_command_skipped(self) -> None:
        cmds = [_cmd("disabled", priority_requests=1, enabled=False), _cmd("ok", priority_requests=2)]
        result = resolve_command("request", None, cmds)
        assert result.id == "ok"

    def test_all_disabled_raises(self) -> None:
        cmds = [_cmd("x", enabled=False), _cmd("y", enabled=False)]
        with pytest.raises(NoCLICommandError):
            resolve_command("request", None, cmds)

    def test_empty_list_raises(self) -> None:
        with pytest.raises(NoCLICommandError):
            resolve_command("request", None, [])


# ---------------------------------------------------------------------------
# resolve_command_chain — exclude_ids
# ---------------------------------------------------------------------------

class TestResolveCommandChain:
    def test_full_chain_ordered(self) -> None:
        cmds = [_cmd("c", priority_requests=3), _cmd("a", priority_requests=1), _cmd("b", priority_requests=2)]
        chain = resolve_command_chain("request", None, cmds)
        assert [c.id for c in chain] == ["a", "b", "c"]

    def test_excluded_id_removed(self) -> None:
        cmds = [_cmd("a", priority_requests=1), _cmd("b", priority_requests=2)]
        chain = resolve_command_chain("request", None, cmds, exclude_ids=["a"])
        assert len(chain) == 1
        assert chain[0].id == "b"

    def test_all_excluded_returns_empty(self) -> None:
        cmds = [_cmd("a"), _cmd("b")]
        chain = resolve_command_chain("request", None, cmds, exclude_ids=["a", "b"])
        assert chain == []

    def test_requested_id_not_promoted_when_excluded(self) -> None:
        cmds = [_cmd("a", priority_requests=1), _cmd("b", priority_requests=2)]
        chain = resolve_command_chain("request", "b", cmds, exclude_ids=["b"])
        assert len(chain) == 1
        assert chain[0].id == "a"
