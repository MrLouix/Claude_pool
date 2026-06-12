"""Unit tests for team_cli/cli_detector.py."""

import subprocess
from unittest.mock import MagicMock, patch

from team_cli.cli_detector import (
    detect_clis,
    find_binary,
    probe_cli,
)
from team_cli.models import CLIConfig


class TestFindBinary:
    """Tests for find_binary()."""

    def test_returns_none_for_nonexistent_binary(self):
        """find_binary returns None when binary is not found."""
        with patch("team_cli.cli_detector.shutil.which", return_value=None):
            with patch("team_cli.cli_detector.shutil.os.path.exists", return_value=False):
                with patch("team_cli.cli_detector.shutil.os.path.isfile", return_value=False):
                    with patch("team_cli.cli_detector.shutil.os.access", return_value=False):
                        result = find_binary("nonexistent-cli")
                        assert result is None

    def test_returns_path_when_shutil_which_finds_it(self):
        """find_binary returns path when shutil.which finds the binary."""
        expected_path = "/usr/bin/my-cli"
        with patch("team_cli.cli_detector.shutil.which", return_value=expected_path):
            result = find_binary("my-cli")
            assert result == expected_path

    def test_fallback_to_common_paths(self):
        """find_binary tries common paths when shutil.which returns None."""
        with patch("team_cli.cli_detector.shutil.which", return_value=None):
            with patch("team_cli.cli_detector.shutil.os.path.exists", return_value=True):
                with patch("team_cli.cli_detector.shutil.os.path.isfile", return_value=True):
                    with patch("team_cli.cli_detector.shutil.os.access", return_value=True):
                        # Mock exists to return True only for our test path
                        def mock_exists(path):
                            return path == "/usr/local/bin/custom-cli"

                        with patch("team_cli.cli_detector.shutil.os.path.exists", side_effect=mock_exists):
                            result = find_binary("custom-cli")
                            assert result == "/usr/local/bin/custom-cli"


class TestProbeCli:
    """Tests for probe_cli()."""

    def test_returns_none_on_timeout(self):
        """probe_cli returns None when subprocess times out."""
        with patch("team_cli.cli_detector.subprocess.run", side_effect=subprocess.TimeoutExpired("test", 5)):
            result = probe_cli("claude", "/usr/bin/claude", "anthropic")
            assert result is None

    def test_returns_none_on_file_not_found(self):
        """probe_cli returns None when binary is not found."""
        with patch("team_cli.cli_detector.subprocess.run", side_effect=FileNotFoundError()):
            result = probe_cli("claude", "/usr/bin/nonexistent", "anthropic")
            assert result is None

    def test_returns_cli_config_for_anthropic(self):
        """probe_cli returns valid CLIConfig with correct models for anthropic."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Claude CLI v1.0"

        with patch("team_cli.cli_detector.subprocess.run", return_value=mock_result):
            result = probe_cli("claude", "/usr/bin/claude", "anthropic")

            assert result is not None
            assert isinstance(result, CLIConfig)
            assert result.name == "claude"
            assert result.path == "/usr/bin/claude"
            assert result.cli_type == "anthropic"
            assert result.models == ["haiku", "sonnet", "opus"]

    def test_returns_cli_config_for_mistral(self):
        """probe_cli returns valid CLIConfig with correct models for mistral."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Mistral CLI v1.0"

        with patch("team_cli.cli_detector.subprocess.run", return_value=mock_result):
            result = probe_cli("mistral", "/usr/bin/mistral", "mistral")

            assert result is not None
            assert isinstance(result, CLIConfig)
            assert result.name == "mistral"
            assert result.cli_type == "mistral"
            assert result.models == ["mistral-tiny", "mistral-small", "mistral-medium"]

    def test_returns_cli_config_for_unknown_type(self):
        """probe_cli returns CLIConfig with empty models for unknown cli_type."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Custom CLI v1.0"

        with patch("team_cli.cli_detector.subprocess.run", return_value=mock_result):
            result = probe_cli("custom", "/usr/bin/custom", "custom")

            assert result is not None
            assert isinstance(result, CLIConfig)
            assert result.models == []

    def test_returns_cli_config_on_nonzero_exit_with_output(self):
        """probe_cli returns CLIConfig when exit code is non-zero but output exists."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Some output"

        with patch("team_cli.cli_detector.subprocess.run", return_value=mock_result):
            result = probe_cli("claude", "/usr/bin/claude", "anthropic")

            assert result is not None
            assert isinstance(result, CLIConfig)


class TestDetectClis:
    """Tests for detect_clis()."""

    def setup_method(self):
        """Clear lru_cache so each test runs against fresh mocks."""
        detect_clis.cache_clear()

    def test_detects_known_clis(self):
        """detect_clis returns configs for detected known CLIs."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.0"

        with patch("team_cli.cli_detector.shutil.which", return_value="/usr/bin/claude"):
            with patch("team_cli.cli_detector.subprocess.run", return_value=mock_result):
                with patch("team_cli.cli_detector.load_cli_configs", return_value=[]):
                    results = detect_clis()

                    names = [c.name for c in results]
                    assert "claude" in names

    def test_merges_custom_configs(self):
        """detect_clis merges custom configs from load_cli_configs."""
        custom_config = CLIConfig(
            name="custom-cli",
            path="/custom/path",
            models=["custom-model"],
            cli_type="custom",
            enabled=True,
        )

        with patch("team_cli.cli_detector.shutil.which", return_value=None):
            with patch("team_cli.cli_detector.subprocess.run", return_value=None):
                with patch("team_cli.cli_detector.load_cli_configs", return_value=[custom_config]):
                    results = detect_clis()

                    names = [c.name for c in results]
                    assert "custom-cli" in names

    def test_custom_config_overrides_detected(self):
        """detect_clis: custom config overrides detected entry with same name."""
        # Mock a detected claude
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.0"

        custom_claude = CLIConfig(
            name="claude",
            path="/custom/claude",
            models=["custom-model"],
            cli_type="custom",
            enabled=True,
        )

        with patch("team_cli.cli_detector.shutil.which", return_value="/usr/bin/claude"):
            with patch("team_cli.cli_detector.subprocess.run", return_value=mock_result):
                with patch("team_cli.cli_detector.load_cli_configs", return_value=[custom_claude]):
                    results = detect_clis()

                    claude_configs = [c for c in results if c.name == "claude"]
                    assert len(claude_configs) == 1
                    # Should use custom config, not detected
                    assert claude_configs[0].path == "/custom/claude"
                    assert claude_configs[0].models == ["custom-model"]

    def test_disabled_custom_config_not_included(self):
        """detect_clis excludes disabled custom configs."""
        disabled_config = CLIConfig(
            name="disabled-cli",
            path="/some/path",
            models=["model"],
            cli_type="custom",
            enabled=False,
        )

        with patch("team_cli.cli_detector.shutil.which", return_value=None):
            with patch("team_cli.cli_detector.subprocess.run", return_value=None):
                with patch("team_cli.cli_detector.load_cli_configs", return_value=[disabled_config]):
                    results = detect_clis()

                    names = [c.name for c in results]
                    assert "disabled-cli" not in names
