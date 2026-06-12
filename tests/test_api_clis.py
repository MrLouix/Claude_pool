"""Unit tests for CLI config API endpoints."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from team_cli.api import create_app
from team_cli.models import CLIConfig


def _make_client(tmp_path: Path) -> TestClient:
    pool_file = tmp_path / "test.db"
    app = create_app(pool_file)
    return TestClient(app)


class TestAPIClisEndpoints:
    """Tests for /api/clis endpoints."""

    @patch("team_cli.routers.pools.detect_clis")
    @patch("team_cli.routers.pools.load_cli_configs")
    def test_get_clis_returns_200_with_configs(self, mock_load, mock_detect, tmp_path):
        """GET /api/clis returns 200 with a list of CLIConfigResponse objects."""
        mock_detect.return_value = [
            CLIConfig(
                name="claude",
                path="/usr/bin/claude",
                models=["haiku", "sonnet"],
                cli_type="anthropic",
            ),
        ]
        mock_load.return_value = []

        with _make_client(tmp_path) as test_client:
            response = test_client.get("/api/clis")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "claude"
        assert data[0]["path"] == "/usr/bin/claude"
        assert data[0]["models"] == ["haiku", "sonnet"]
        assert data[0]["cli_type"] == "anthropic"
        assert data[0]["enabled"] is True

    @patch("team_cli.routers.pools.detect_clis")
    def test_get_clis_detect_returns_200_with_detected(self, mock_detect, tmp_path):
        """GET /api/clis/detect returns 200 with detected CLIs."""
        mock_detect.return_value = [
            CLIConfig(
                name="mistral",
                path="/usr/bin/mistral",
                models=["mistral-tiny"],
                cli_type="mistral",
            ),
            CLIConfig(
                name="llama",
                path="/usr/bin/llama",
                models=["llama-70b"],
                cli_type="llama",
            ),
        ]

        with _make_client(tmp_path) as test_client:
            response = test_client.get("/api/clis/detect")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        names = [c["name"] for c in data]
        assert "mistral" in names
        assert "llama" in names

    @patch("team_cli.routers.pools.detect_clis")
    @patch("team_cli.routers.pools.load_cli_configs")
    def test_get_clis_merges_custom_configs(self, mock_load, mock_detect, tmp_path):
        """GET /api/clis merges custom configs with detected, custom overrides."""
        mock_detect.return_value = [
            CLIConfig(
                name="claude",
                path="/usr/bin/claude",
                models=["haiku", "sonnet"],
                cli_type="anthropic",
                enabled=True,
            ),
        ]
        mock_load.return_value = [
            CLIConfig(
                name="claude",
                path="/custom/path/to/claude",
                models=["haiku", "sonnet", "opus"],
                cli_type="anthropic",
                enabled=True,
                default_model="sonnet",
            ),
        ]

        with _make_client(tmp_path) as test_client:
            response = test_client.get("/api/clis")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["path"] == "/custom/path/to/claude"
        assert data[0]["models"] == ["haiku", "sonnet", "opus"]
        assert data[0]["default_model"] == "sonnet"

    @patch("team_cli.routers.pools.detect_clis")
    @patch("team_cli.routers.pools.load_cli_configs")
    def test_get_clis_excludes_disabled(self, mock_load, mock_detect, tmp_path):
        """GET /api/clis excludes disabled custom configs."""
        mock_detect.return_value = []
        mock_load.return_value = [
            CLIConfig(
                name="disabled-cli",
                path="/usr/bin/disabled",
                models=["model1"],
                cli_type="custom",
                enabled=False,
            ),
        ]

        with _make_client(tmp_path) as test_client:
            response = test_client.get("/api/clis")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestTaskExecutorFallback:
    """Tests for TaskExecutor fallback behavior."""

    def test_fallback_cli_manager_when_none_provided(self, tmp_path):
        """TaskExecutor creates fallback CLIManager when none is injected."""
        from team_cli.executor import TaskExecutor

        pool_file = tmp_path / "test.db"
        executor = TaskExecutor(pool_file, install_signal_handlers=False)

        assert hasattr(executor, "cli_manager")
        assert executor.cli_manager is not None
        assert len(executor.cli_manager._executors) == 1
        assert executor.cli_manager._executors[0].config.name == "claude"
        assert executor.cli_manager._executors[0].config.cli_type == "anthropic"

    def test_uses_provided_cli_manager(self, tmp_path):
        """TaskExecutor uses provided CLIManager instead of creating fallback."""
        from team_cli.cli_executors import CLIManager
        from team_cli.executor import TaskExecutor

        pool_file = tmp_path / "test.db"
        custom_config = CLIConfig(
            name="custom",
            path="/custom/path",
            models=["custom-model"],
            cli_type="custom",
            args_template="{prompt}",
        )
        cli_manager = CLIManager([custom_config])

        executor = TaskExecutor(
            pool_file,
            install_signal_handlers=False,
            cli_manager=cli_manager,
        )

        assert executor.cli_manager is cli_manager
        assert len(executor.cli_manager._executors) == 1
        assert executor.cli_manager._executors[0].config.name == "custom"
