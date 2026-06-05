"""Unit tests for CLI config API endpoints."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from team_cli.api import create_app
from team_cli.models import CLIConfig


class TestAPIClisEndpoints:
    """Tests for /api/clis endpoints."""

    @pytest.fixture
    def app(self, tmp_path):
        """Create a test FastAPI app."""
        pool_file = tmp_path / "test.db"
        return create_app(pool_file)

    @patch("team_cli.api.detect_clis")
    @patch("team_cli.api.load_cli_configs")
    async def test_get_clis_returns_200_with_configs(
        self, mock_load, mock_detect, app, client
    ):
        """GET /api/clis returns 200 with a list of CLIConfigResponse objects."""
        # Setup mocks
        mock_detect.return_value = [
            CLIConfig(
                name="claude",
                path="/usr/bin/claude",
                models=["haiku", "sonnet"],
                cli_type="anthropic",
            ),
        ]
        mock_load.return_value = []
        
        # Need to use the actual test client
        from fastapi.testclient import TestClient
        with TestClient(app) as test_client:
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

    @patch("team_cli.api.detect_clis")
    async def test_get_clis_detect_returns_200_with_detected(
        self, mock_detect, app, client
    ):
        """GET /api/clis/detect returns 200 with detected CLIs."""
        from fastapi.testclient import TestClient
        
        # Setup mocks
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
        
        with TestClient(app) as test_client:
            response = test_client.get("/api/clis/detect")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2
            names = [c["name"] for c in data]
            assert "mistral" in names
            assert "llama" in names

    @patch("team_cli.api.detect_clis")
    @patch("team_cli.api.load_cli_configs")
    async def test_get_clis_merges_custom_configs(
        self, mock_load, mock_detect, app, client
    ):
        """GET /api/clis merges custom configs with detected, custom overrides."""
        from fastapi.testclient import TestClient
        
        # Setup mocks: same name in both, custom should override
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
        
        with TestClient(app) as test_client:
            response = test_client.get("/api/clis")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1  # Only one claude, custom overrides detected
            assert data[0]["path"] == "/custom/path/to/claude"
            assert data[0]["models"] == ["haiku", "sonnet", "opus"]
            assert data[0]["default_model"] == "sonnet"

    @patch("team_cli.api.detect_clis")
    @patch("team_cli.api.load_cli_configs")
    async def test_get_clis_excludes_disabled(
        self, mock_load, mock_detect, app, client
    ):
        """GET /api/clis excludes disabled custom configs."""
        from fastapi.testclient import TestClient
        
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
        
        with TestClient(app) as test_client:
            response = test_client.get("/api/clis")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 0  # Disabled configs are excluded


class TestTaskExecutorFallback:
    """Tests for TaskExecutor fallback behavior."""

    def test_fallback_cli_manager_when_none_provided(self):
        """TaskExecutor creates fallback CLIManager when none is injected."""
        from team_cli.executor import TaskExecutor
        from team_cli.models import CLIConfig
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pool_file = Path(tmpdir) / "test.db"
            
            # Create executor without cli_manager
            executor = TaskExecutor(pool_file, install_signal_handlers=False)
            
            # Check that a fallback CLIManager was created
            assert hasattr(executor, "cli_manager")
            assert executor.cli_manager is not None
            assert len(executor.cli_manager._executors) == 1
            assert executor.cli_manager._executors[0].config.name == "claude"
            assert executor.cli_manager._executors[0].config.cli_type == "anthropic"

    def test_uses_provided_cli_manager(self):
        """TaskExecutor uses provided CLIManager instead of creating fallback."""
        from team_cli.executor import TaskExecutor, CLIManager
        from team_cli.models import CLIConfig
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pool_file = Path(tmpdir) / "test.db"
            
            # Create custom CLIManager
            custom_config = CLIConfig(
                name="custom",
                path="/custom/path",
                models=["custom-model"],
                cli_type="custom",
                args_template="{prompt}",
            )
            cli_manager = CLIManager([custom_config])
            
            # Create executor with custom cli_manager
            executor = TaskExecutor(
                pool_file, 
                install_signal_handlers=False,
                cli_manager=cli_manager
            )
            
            # Check that the custom CLIManager is used
            assert executor.cli_manager is cli_manager
            assert len(executor.cli_manager._executors) == 1
            assert executor.cli_manager._executors[0].config.name == "custom"
