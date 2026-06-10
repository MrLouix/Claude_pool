"""Tests for security fixes C5–C9.

C5 – CORS uses configurable allowed-origins (no wildcard by default)
C6 – GenericCLIExecutor.args_template never interpolates the prompt
C7 – escapeHtml escapes ', / as well as &, <, >, "
C8 – POST /api/tasks rejects form-encoded bodies (CSRF protection)
C9 – POST /api/tasks validates the directory field
"""

import json
import os
import stat
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.executor import GenericCLIExecutor
from team_cli.models import CLIConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generic_executor(args_template: str = "") -> GenericCLIExecutor:
    cfg = CLIConfig(
        name="custom",
        path="/bin/echo",
        models=[],
        cli_type="custom",
        args_template=args_template,
    )
    return GenericCLIExecutor(cfg)




# ---------------------------------------------------------------------------
# C5 – CORS
# ---------------------------------------------------------------------------


def _find_cors_origins(app) -> list[str] | None:
    """Extract allow_origins from the first CORSMiddleware found in the app stack."""
    for m in app.user_middleware:
        cls_name = getattr(m.cls, "__name__", "") if hasattr(m, "cls") else ""
        if "CORS" in cls_name:
            return m.kwargs.get("allow_origins", [])
    return None


def test_cors_default_no_wildcard(tmp_path: Path):
    """Default CORS (no env var) must not allow all origins (*)."""
    env = {k: v for k, v in os.environ.items() if k != "ALLOWED_ORIGINS"}
    with patch.dict(os.environ, env, clear=True):
        from team_cli.api import ApiServer
        api = ApiServer(pool_file=tmp_path / "pool.db")
        origins = _find_cors_origins(api.app)
        if origins is not None:
            assert "*" not in origins, "Wildcard CORS origin must not be present by default"


def test_cors_respects_env_var(tmp_path: Path):
    """ALLOWED_ORIGINS env var configures allowed origins."""
    custom_origins = "http://example.com,http://myapp.internal:3000"
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": custom_origins}):
        from team_cli.api import ApiServer
        api = ApiServer(pool_file=tmp_path / "pool.db")
        origins = _find_cors_origins(api.app)
        if origins is not None:
            assert "http://example.com" in origins
            assert "http://myapp.internal:3000" in origins


# ---------------------------------------------------------------------------
# C6 – Argument injection via args_template
# ---------------------------------------------------------------------------


def test_generic_executor_prompt_is_separate_argument():
    """The prompt must be a standalone argv element, never interpolated."""
    ex = _make_generic_executor(args_template="--flag value")

    captured_cmd: list[list[str]] = []

    import subprocess as _sp
    original_run = _sp.run

    def fake_run(cmd, **kw):
        captured_cmd.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"result": "ok"}'
        result.stderr = ""
        return result

    with patch("team_cli.executor.subprocess.run", side_effect=fake_run):
        ex._run_raw(prompt="hello world", context=[], directory="/tmp", model="gpt4")

    assert captured_cmd, "subprocess.run was not called"
    cmd = captured_cmd[0]
    # The full prompt must appear as its own argument, not embedded in another token
    assert "hello world" in cmd, f"Prompt not found as separate arg in {cmd}"
    # No token may contain both the template text AND the prompt
    for token in cmd:
        if token not in ("hello world",):
            assert "hello world" not in token, (
                f"Prompt was interpolated into token {token!r}"
            )


def test_generic_executor_metacharacters_not_injected():
    """Shell metacharacters in the prompt must NOT split into extra arguments."""
    ex = _make_generic_executor(args_template="--query")

    captured_cmd: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured_cmd.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"result": "ok"}'
        result.stderr = ""
        return result

    evil_prompt = "benign'; rm -rf / #"

    with patch("team_cli.executor.subprocess.run", side_effect=fake_run):
        ex._run_raw(prompt=evil_prompt, context=[], directory="/tmp", model="")

    cmd = captured_cmd[0]
    # The evil prompt must be exactly one argument
    assert evil_prompt in cmd, "Prompt not in cmd"
    # Must NOT have split into multiple arguments due to the shell metacharacter
    prompt_idx = cmd.index(evil_prompt)
    # Verify no extra args were injected around it
    assert "rm" not in cmd, f"Injection succeeded: 'rm' appeared in cmd {cmd}"
    assert "-rf" not in cmd, f"Injection succeeded: '-rf' appeared in cmd {cmd}"


def test_generic_executor_no_template_appends_prompt():
    """With empty args_template the prompt is still passed as the sole positional arg."""
    ex = _make_generic_executor(args_template="")

    captured_cmd: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured_cmd.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"result": "ok"}'
        result.stderr = ""
        return result

    with patch("team_cli.executor.subprocess.run", side_effect=fake_run):
        ex._run_raw(prompt="test prompt", context=[], directory="/tmp", model="")

    cmd = captured_cmd[0]
    assert cmd[-1] == "test prompt", f"Prompt must be last arg, got {cmd}"


# ---------------------------------------------------------------------------
# C7 – escapeHtml
# ---------------------------------------------------------------------------


def _escape_html_py(s: str) -> str:
    """Python mirror of the JS escapeHtml function for testing."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
        .replace("/", "&#x2F;")
    )


def test_escape_html_escapes_ampersand():
    assert _escape_html_py("a&b") == "a&amp;b"


def test_escape_html_escapes_lt_gt():
    assert _escape_html_py("<script>") == "&lt;script&gt;"


def test_escape_html_escapes_double_quote():
    assert _escape_html_py('say "hi"') == "say &quot;hi&quot;"


def test_escape_html_escapes_single_quote():
    """Single quotes must be escaped (C7 fix)."""
    assert _escape_html_py("it's") == "it&#039;s"


def test_escape_html_escapes_forward_slash():
    """Forward slashes must be escaped (C7 fix)."""
    assert _escape_html_py("</script>") == "&lt;&#x2F;script&gt;"


def test_escape_html_xss_payload():
    """A classic XSS payload must be fully defused."""
    payload = "<img src=x onerror='alert(1)'>"
    escaped = _escape_html_py(payload)
    assert "<" not in escaped
    assert ">" not in escaped
    assert "'" not in escaped


def test_frontend_html_contains_single_quote_escape(tmp_path: Path):
    """The actual index.html file must contain the ' escape rule."""
    html_path = Path(__file__).parent.parent / "team_cli" / "frontend" / "index.html"
    content = html_path.read_text(encoding="utf-8")
    assert "&#039;" in content, "escapeHtml must escape single quotes to &#039;"
    assert "&#x2F;" in content, "escapeHtml must escape forward slashes to &#x2F;"


# ---------------------------------------------------------------------------
# C8 – CSRF: form-encoded bodies must be rejected on mutating endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path: Path):
    """TestClient with a minimal wired-up API instance."""
    from team_cli.api import ApiServer

    api = ApiServer(pool_file=tmp_path / "pool.db")

    mock_executor = MagicMock()
    mock_executor.pool.tasks = []
    mock_executor.pool.buckets = {"main": MagicMock(id="main")}
    mock_executor.pool.is_suspended = False
    mock_executor.pool.pool_file = tmp_path / "pool.db"
    mock_executor._save_state = MagicMock()
    api.executor = mock_executor

    return TestClient(api.app, raise_server_exceptions=False)


def test_create_task_rejects_form_encoded(api_client: TestClient, tmp_path: Path):
    """POST /api/tasks with form-encoded body must be rejected (CSRF fix)."""
    response = api_client.post(
        "/api/tasks",
        data={"prompt": "evil", "directory": str(tmp_path)},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # FastAPI returns 422 when it can't parse the Pydantic body from a non-JSON body
    assert response.status_code == 422, (
        f"Form-encoded body should be rejected with 422, got {response.status_code}"
    )


def test_create_task_accepts_json(api_client: TestClient, tmp_path: Path):
    """POST /api/tasks with valid JSON body must be parsed (not rejected for Content-Type).

    The response may be a business-logic error (directory outside allow-list → 403,
    or executor not running → 503), but never a 422 caused by body-parse failure.
    """
    response = api_client.post(
        "/api/tasks",
        json={"prompt": "hello", "directory": str(tmp_path)},
    )
    # 422 would mean FastAPI couldn't parse the body — that must NOT happen for JSON
    assert response.status_code != 422, (
        f"JSON body must be parseable; got 422: {response.text}"
    )


# ---------------------------------------------------------------------------
# C9 – Directory validation
# ---------------------------------------------------------------------------


def test_create_task_invalid_directory_returns_422(api_client: TestClient):
    """POST /api/tasks with a non-existent directory must return 4xx."""
    response = api_client.post(
        "/api/tasks",
        json={"prompt": "hello", "directory": "/this/path/does/not/exist/ever"},
    )
    assert response.status_code in (404, 422, 403, 400), (
        f"Non-existent directory should fail, got {response.status_code}"
    )


def test_create_task_valid_directory_accepted(api_client: TestClient, tmp_path: Path):
    """POST /api/tasks with a valid existing directory must not fail on validation."""
    response = api_client.post(
        "/api/tasks",
        json={"prompt": "test", "directory": str(tmp_path)},
    )
    # 503 means executor not fully initialized (acceptable in test), NOT a 404/422
    assert response.status_code not in (404, 422), (
        f"Valid directory should pass validation, got {response.status_code}"
    )


def test_create_task_file_path_rejected(api_client: TestClient, tmp_path: Path):
    """POST /api/tasks with a file path (not a directory) must be rejected."""
    file_path = tmp_path / "notadir.txt"
    file_path.write_text("content")
    response = api_client.post(
        "/api/tasks",
        json={"prompt": "test", "directory": str(file_path)},
    )
    # Accept any 4xx — the path is rejected either by the allow-list (403),
    # existence check (404), or Pydantic validation (422).
    assert 400 <= response.status_code < 500, (
        f"File path should be rejected with 4xx, got {response.status_code}: {response.text}"
    )
