"""Tests for routing.build_command."""

from pathlib import Path

from team_cli.models import CliCommand, Task
from team_cli.routing import build_command


def _cli(
    id: str = "test",
    binary: str = "mycli",
    args_template: str = '["-p","{prompt}"]',
    resume_template: str | None = None,
    model_flag: str | None = None,
    parser: str = "claude_json",
) -> CliCommand:
    return CliCommand(
        id=id,
        name=id,
        binary=binary,
        args_template=args_template,
        resume_template=resume_template,
        model_flag=model_flag,
        parser=parser,
    )


def _task(
    prompt: str = "hello",
    session_id: str | None = None,
    model: str = "",
    args: list[str] | None = None,
) -> Task:
    return Task(
        id="t1",
        prompt=prompt,
        directory=Path("/tmp"),
        session_id=session_id,
        model=model,
        args=args or [],
    )


# ---------------------------------------------------------------------------
# Basic template substitution
# ---------------------------------------------------------------------------

class TestBuildCommandBasic:
    def test_binary_is_first_element(self) -> None:
        cmd = build_command(_task(), _cli(binary="mymycli"))
        assert cmd[0] == "mymycli"

    def test_prompt_substituted_in_args(self) -> None:
        cmd = build_command(_task(prompt="do something"), _cli())
        assert "do something" in cmd

    def test_prompt_replaces_placeholder(self) -> None:
        cli = _cli(args_template='["-p","{prompt}","--json"]')
        cmd = build_command(_task(prompt="run tests"), cli)
        assert cmd[cmd.index("-p") + 1] == "run tests"

    def test_multi_arg_template(self) -> None:
        cli = _cli(args_template='["--prompt","{prompt}","--output","json"]')
        cmd = build_command(_task(prompt="q"), cli)
        assert cmd == ["mycli", "--prompt", "q", "--output", "json"]

    def test_no_session_id_no_resume_args(self) -> None:
        cli = _cli(resume_template='["--resume","{session_id}"]')
        cmd = build_command(_task(session_id=None), cli)
        assert "--resume" not in cmd

    def test_invalid_args_template_falls_back(self) -> None:
        cli = _cli(args_template="not-json")
        cmd = build_command(_task(prompt="hi"), cli)
        assert cmd[0] == "mycli"
        assert "hi" in cmd


# ---------------------------------------------------------------------------
# Session ID / resume template
# ---------------------------------------------------------------------------

class TestBuildCommandSession:
    def test_resume_args_inserted_after_binary(self) -> None:
        cli = _cli(resume_template='["--resume","{session_id}"]')
        cmd = build_command(_task(session_id="sess_abc"), cli)
        assert cmd[1] == "--resume"
        assert cmd[2] == "sess_abc"

    def test_session_id_substituted_in_resume_template(self) -> None:
        cli = _cli(resume_template='["--session","{session_id}"]')
        cmd = build_command(_task(session_id="XYZ"), cli)
        assert "XYZ" in cmd

    def test_resume_args_come_before_prompt_args(self) -> None:
        cli = _cli(
            args_template='["-p","{prompt}"]',
            resume_template='["--resume","{session_id}"]',
        )
        cmd = build_command(_task(prompt="hi", session_id="S1"), cli)
        resume_idx = cmd.index("--resume")
        prompt_idx = cmd.index("-p")
        assert resume_idx < prompt_idx

    def test_no_resume_template_session_id_ignored(self) -> None:
        cli = _cli(resume_template=None)
        cmd = build_command(_task(session_id="S1"), cli)
        assert "S1" not in cmd


# ---------------------------------------------------------------------------
# Model flag
# ---------------------------------------------------------------------------

class TestBuildCommandModel:
    def test_model_flag_appended(self) -> None:
        cli = _cli(model_flag="--model")
        cmd = build_command(_task(model="opus"), cli)
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "opus"

    def test_no_model_no_flag_appended(self) -> None:
        cli = _cli(model_flag="--model")
        cmd = build_command(_task(model=""), cli)
        assert "--model" not in cmd

    def test_model_flag_none_not_appended(self) -> None:
        cli = _cli(model_flag=None)
        cmd = build_command(_task(model="sonnet"), cli)
        assert "sonnet" not in cmd


# ---------------------------------------------------------------------------
# Plain-text CLI (parser='plain') — command building is identical
# ---------------------------------------------------------------------------

class TestBuildCommandPlain:
    def test_plain_cli_no_json_flags_in_template(self) -> None:
        cli = _cli(
            args_template='["{prompt}"]',
            parser="plain",
        )
        cmd = build_command(_task(prompt="summarise this"), cli)
        assert "--output-format" not in cmd
        assert "--json" not in cmd
        assert "summarise this" in cmd

    def test_plain_cli_command_structure(self) -> None:
        cli = _cli(binary="llm", args_template='["{prompt}"]', parser="plain")
        cmd = build_command(_task(prompt="hello"), cli)
        assert cmd == ["llm", "hello"]
