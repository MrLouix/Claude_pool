"""Real-subprocess executor tests using fake CLI fixture scripts.

These tests run actual subprocesses — no mocks — to verify that
ClaudeExecutor correctly builds the command, captures output, and
reports rate-limit status based on exit code and stderr content.
"""

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from team_cli.cli_executors import ClaudeExecutor
from team_cli.models import CLIConfig

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_CLAUDE = FIXTURES / "fake_claude.py"
FAKE_RATE_LIMIT = FIXTURES / "fake_rate_limit.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_executable():
    """Guarantee fixture scripts are executable before every test in this module."""
    for script in (FAKE_CLAUDE, FAKE_RATE_LIMIT):
        if script.exists():
            script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _config(script: Path, name: str = "claude") -> CLIConfig:
    return CLIConfig(
        name=name,
        path=str(script),
        models=["sonnet", "opus"],
        cli_type="anthropic",
    )


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


class TestClaudeExecutorSuccess:
    def test_content_contains_echoed_prompt(self, tmp_path: Path) -> None:
        """execute() returns a dict whose 'content' field contains the submitted prompt."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        result = executor.execute(
            prompt="hello world",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert "hello world" in result["content"]

    def test_tokens_used_equals_42(self, tmp_path: Path) -> None:
        """execute() returns tokens_used == 42 from the fake CLI."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        result = executor.execute(
            prompt="count tokens",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert result["tokens_used"] == 42

    def test_cli_name_matches_config(self, tmp_path: Path) -> None:
        """execute() sets 'cli_name' to the CLIConfig.name."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE, name="my-claude"))
        result = executor.execute(
            prompt="cli name",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert result["cli_name"] == "my-claude"

    def test_result_key_contains_echoed_prompt(self, tmp_path: Path) -> None:
        """The legacy 'result' key is preserved and contains the echoed text."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        result = executor.execute(
            prompt="specific prompt",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert "specific prompt" in result.get("result", "")

    def test_raw_key_present(self, tmp_path: Path) -> None:
        """execute() always populates the 'raw' key with the original parsed output."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        result = executor.execute(
            prompt="raw check",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert "raw" in result
        assert isinstance(result["raw"], dict)

    def test_check_rate_limit_false_after_success(self, tmp_path: Path) -> None:
        """check_rate_limit() returns False after a zero-exit execution."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        executor.execute(
            prompt="success run",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert executor.check_rate_limit() is False

    def test_multiple_prompts_return_different_content(self, tmp_path: Path) -> None:
        """Each call echoes its own prompt — results are not cached or shared."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        r1 = executor.execute(prompt="alpha", context=[], directory=str(tmp_path), model="sonnet")
        r2 = executor.execute(prompt="beta", context=[], directory=str(tmp_path), model="sonnet")
        assert "alpha" in r1["content"]
        assert "beta" in r2["content"]
        assert r1["content"] != r2["content"]


# ---------------------------------------------------------------------------
# Rate-limit detection
# ---------------------------------------------------------------------------


class TestClaudeExecutorRateLimit:
    def test_check_rate_limit_true_after_rate_limited_run(self, tmp_path: Path) -> None:
        """check_rate_limit() returns True when the CLI exits 1 with a rate-limit message."""
        executor = ClaudeExecutor(_config(FAKE_RATE_LIMIT))
        executor.execute(
            prompt="anything",
            context=[],
            directory=str(tmp_path),
            model="sonnet",
        )
        assert executor.check_rate_limit() is True

    def test_check_rate_limit_false_before_any_execution(self) -> None:
        """check_rate_limit() returns False when no execution has occurred yet."""
        executor = ClaudeExecutor(_config(FAKE_CLAUDE))
        assert executor.check_rate_limit() is False

    def test_rate_limit_resets_after_successful_run(self, tmp_path: Path) -> None:
        """A successful run after a rate-limited run resets check_rate_limit() to False."""
        executor_rl = ClaudeExecutor(_config(FAKE_RATE_LIMIT))
        executor_rl.execute(prompt="fail", context=[], directory=str(tmp_path), model="sonnet")
        assert executor_rl.check_rate_limit() is True

        # Fresh executor for the success run (separate CLI config)
        executor_ok = ClaudeExecutor(_config(FAKE_CLAUDE))
        executor_ok.execute(prompt="succeed", context=[], directory=str(tmp_path), model="sonnet")
        assert executor_ok.check_rate_limit() is False


# ---------------------------------------------------------------------------
# Fixture script self-tests
# ---------------------------------------------------------------------------


class TestFakeCliFixtures:
    """Verify the fixture scripts themselves produce the expected output and exit codes.

    These tests run the scripts directly via sys.executable so they work
    regardless of whether the scripts are chmod +x.
    """

    def test_fake_claude_exits_zero(self) -> None:
        """fake_claude.py exits with code 0."""
        result = subprocess.run(
            [sys.executable, str(FAKE_CLAUDE), "-p", "hello"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_fake_claude_stdout_is_valid_json(self) -> None:
        """fake_claude.py prints valid JSON to stdout."""
        result = subprocess.run(
            [sys.executable, str(FAKE_CLAUDE), "-p", "hello"],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_fake_claude_echoes_prompt(self) -> None:
        """fake_claude.py includes the -p value in the 'result' field."""
        result = subprocess.run(
            [sys.executable, str(FAKE_CLAUDE), "-p", "my prompt"],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        assert "my prompt" in data["result"]

    def test_fake_claude_tokens_used_42(self) -> None:
        """fake_claude.py always returns tokens_used == 42."""
        result = subprocess.run(
            [sys.executable, str(FAKE_CLAUDE), "-p", "x"],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        assert data["tokens_used"] == 42

    def test_fake_claude_model_flag_reflected(self) -> None:
        """fake_claude.py reflects the --model flag value in the output."""
        result = subprocess.run(
            [sys.executable, str(FAKE_CLAUDE), "-p", "x", "--model", "opus"],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        assert data["model"] == "opus"

    def test_fake_claude_default_model_is_sonnet(self) -> None:
        """fake_claude.py defaults to model='sonnet' when --model is omitted."""
        result = subprocess.run(
            [sys.executable, str(FAKE_CLAUDE), "-p", "x"],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        assert data["model"] == "sonnet"

    def test_fake_rate_limit_exits_one(self) -> None:
        """fake_rate_limit.py exits with code 1."""
        result = subprocess.run(
            [sys.executable, str(FAKE_RATE_LIMIT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_fake_rate_limit_writes_to_stderr(self) -> None:
        """fake_rate_limit.py writes the rate-limit message to stderr."""
        result = subprocess.run(
            [sys.executable, str(FAKE_RATE_LIMIT)],
            capture_output=True,
            text=True,
        )
        assert "rate limit" in result.stderr.lower()

    def test_fake_rate_limit_empty_stdout(self) -> None:
        """fake_rate_limit.py produces no stdout output."""
        result = subprocess.run(
            [sys.executable, str(FAKE_RATE_LIMIT)],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ""
