"""API-level integration tests: directory validation and injection-safety.

These tests verify that the path allow-list (only /home and /mnt on Linux)
is enforced at every endpoint that accepts a 'directory' argument, and that
prompt text containing shell metacharacters is stored as plain text without
any execution.
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from team_cli.api import ApiServer
from team_cli.models import PoolState
from team_cli.storage import save_pool


# ---------------------------------------------------------------------------
# Fixture helpers (same pattern as test_api_phase5_backend.py)
# ---------------------------------------------------------------------------


@contextmanager
def _make_api(pool_file: Path):
    with (
        patch("team_cli.executor.TaskExecutor.run_pool", new=AsyncMock(return_value=None)),
        patch("team_cli.executor.signal.signal"),
    ):
        server = ApiServer(pool_file)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            yield client, server


def _pool(tmp_path: Path) -> Path:
    pf = tmp_path / "pool.db"
    save_pool(PoolState(tasks=[], pool_file=pf))
    return pf


# ---------------------------------------------------------------------------
# Directory validation — tasks endpoint
# ---------------------------------------------------------------------------


class TestTaskDirectoryValidation:
    def test_etc_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/tasks with directory='/etc' → 403 (outside allow-list)."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "test", "directory": "/etc"},
            )
        assert resp.status_code == 403

    def test_tmp_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/tasks with directory='/tmp' → 403 (outside allow-list)."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "test", "directory": "/tmp"},
            )
        assert resp.status_code == 403

    def test_path_traversal_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/tasks with directory='/tmp/../../etc' → 403 (resolves outside allow-list)."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "test", "directory": "/tmp/../../etc"},
            )
        assert resp.status_code == 403

    def test_root_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/tasks with directory='/' → 403."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "test", "directory": "/"},
            )
        assert resp.status_code == 403

    def test_usr_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/tasks with directory='/usr/bin' → 403."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "test", "directory": "/usr/bin"},
            )
        assert resp.status_code == 403

    def test_home_directory_accepted(self, tmp_path: Path) -> None:
        """POST /api/tasks with directory=str(Path.home()) → 200 (inside allow-list)."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": "test", "directory": str(Path.home())},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Directory validation — chats endpoint
# ---------------------------------------------------------------------------


class TestChatDirectoryValidation:
    def test_tmp_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/chats with directory='/tmp' → 403."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/chats",
                json={"directory": "/tmp", "label": "bad chat"},
            )
        assert resp.status_code == 403

    def test_etc_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/chats with directory='/etc' → 403."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/chats",
                json={"directory": "/etc", "label": "bad chat"},
            )
        assert resp.status_code == 403

    def test_path_traversal_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/chats with traversal path → 403."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/chats",
                json={"directory": "/tmp/../../etc", "label": "bad chat"},
            )
        assert resp.status_code == 403

    def test_home_directory_accepted(self, tmp_path: Path) -> None:
        """POST /api/chats with directory=str(Path.home()) → 201."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/chats",
                json={"directory": str(Path.home()), "label": "good chat"},
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Directory validation — projects endpoint
# ---------------------------------------------------------------------------


class TestProjectDirectoryValidation:
    def test_etc_directory_rejected_with_403(self, tmp_path: Path) -> None:
        """POST /api/projects with directory='/etc' → 403."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/projects",
                json={"name": "bad project", "directory": "/etc"},
            )
        assert resp.status_code == 403

    def test_home_directory_accepted(self, tmp_path: Path) -> None:
        """POST /api/projects with directory=str(Path.home()) → 201."""
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/projects",
                json={"name": "good project", "directory": str(Path.home())},
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Injection safety — prompt is stored as plain text
# ---------------------------------------------------------------------------


class TestPromptInjectionSafety:
    def test_shell_metacharacters_accepted_as_text(self, tmp_path: Path) -> None:
        """A prompt containing '; rm -rf /' is accepted and returned verbatim — not executed."""
        dangerous_prompt = "; rm -rf /"
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": dangerous_prompt, "directory": str(Path.home())},
            )
        assert resp.status_code == 200
        assert resp.json()["prompt"] == dangerous_prompt

    def test_backtick_injection_stored_verbatim(self, tmp_path: Path) -> None:
        """A prompt with backtick command substitution is stored verbatim."""
        dangerous_prompt = "`id`; echo pwned"
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": dangerous_prompt, "directory": str(Path.home())},
            )
        assert resp.status_code == 200
        assert resp.json()["prompt"] == dangerous_prompt

    def test_dollar_sign_expansion_stored_verbatim(self, tmp_path: Path) -> None:
        """A prompt with $(...) expansion syntax is stored as plain text."""
        dangerous_prompt = "$(cat /etc/passwd)"
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": dangerous_prompt, "directory": str(Path.home())},
            )
        assert resp.status_code == 200
        assert resp.json()["prompt"] == dangerous_prompt

    def test_newline_in_prompt_stored_verbatim(self, tmp_path: Path) -> None:
        """A prompt with embedded newlines is stored verbatim."""
        prompt_with_newline = "first line\nsecond line\nthird line"
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": prompt_with_newline, "directory": str(Path.home())},
            )
        assert resp.status_code == 200
        assert resp.json()["prompt"] == prompt_with_newline

    def test_unicode_prompt_stored_verbatim(self, tmp_path: Path) -> None:
        """A prompt with unicode/emoji is stored and returned without corruption."""
        unicode_prompt = "Tell me about 日本語 and 🎉 and <script>alert('xss')</script>"
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            resp = client.post(
                "/api/tasks",
                json={"prompt": unicode_prompt, "directory": str(Path.home())},
            )
        assert resp.status_code == 200
        assert resp.json()["prompt"] == unicode_prompt

    def test_shell_metacharacters_appear_in_task_list(self, tmp_path: Path) -> None:
        """The injected prompt stored in POST /api/tasks is retrievable via GET /api/tasks."""
        dangerous_prompt = "; rm -rf /"
        pool_file = _pool(tmp_path)
        with _make_api(pool_file) as (client, _):
            client.post(
                "/api/tasks",
                json={"prompt": dangerous_prompt, "directory": str(Path.home())},
            )
            tasks = client.get("/api/tasks").json()
        assert any(t["prompt"] == dangerous_prompt for t in tasks)
