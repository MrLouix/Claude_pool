"""Unit tests for claude_pool/config.py."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_pool.config import (
    DEFAULT_CLIS_PATH,
    get_clis_path,
    load_cli_configs,
    save_cli_configs,
)
from claude_pool.models import CLIConfig


class TestGetClisPath:
    """Tests for get_clis_path()."""

    def test_default_path(self):
        """get_clis_path returns default path when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAUDE_POOL_CLIS_PATH", None)
            result = get_clis_path()
            assert result == DEFAULT_CLIS_PATH

    def test_respects_env_var(self):
        """get_clis_path respects CLAUDE_POOL_CLIS_PATH env var."""
        custom_path = "/custom/path/clis.json"
        with patch.dict(os.environ, {"CLAUDE_POOL_CLIS_PATH": custom_path}):
            result = get_clis_path()
            assert result == Path(custom_path)


class TestLoadCliConfigs:
    """Tests for load_cli_configs()."""

    def test_returns_empty_list_when_file_missing(self, tmp_path, monkeypatch):
        """load_cli_configs returns empty list when file doesn't exist."""
        clis_path = tmp_path / "clis.json"
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        result = load_cli_configs()
        assert result == []

    def test_deserializes_valid_json(self, tmp_path, monkeypatch):
        """load_cli_configs correctly deserializes valid clis.json."""
        clis_path = tmp_path / "clis.json"
        clis_path.write_text(json.dumps({
            "custom_cli": {
                "path": "/usr/bin/my-ai-cli",
                "models": ["my-model", "my-model-2"],
                "args_template": "--prompt {prompt} --context {context}",
                "cli_type": "custom",
                "enabled": True,
            },
            "claude": {
                "path": "/usr/bin/claude",
                "models": ["sonnet", "haiku"],
                "cli_type": "anthropic",
                "default_model": "sonnet",
            },
        }))
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        result = load_cli_configs()
        
        assert len(result) == 2
        
        custom_cli = next(c for c in result if c.name == "custom_cli")
        assert custom_cli.path == "/usr/bin/my-ai-cli"
        assert custom_cli.models == ["my-model", "my-model-2"]
        assert custom_cli.cli_type == "custom"
        assert custom_cli.args_template == "--prompt {prompt} --context {context}"
        assert custom_cli.enabled is True
        
        claude = next(c for c in result if c.name == "claude")
        assert claude.path == "/usr/bin/claude"
        assert claude.models == ["sonnet", "haiku"]
        assert claude.cli_type == "anthropic"
        assert claude.default_model == "sonnet"
        assert claude.enabled is True

    def test_handles_malformed_json(self, tmp_path, monkeypatch):
        """load_cli_configs handles malformed JSON gracefully."""
        clis_path = tmp_path / "clis.json"
        clis_path.write_text("not valid json {")
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        result = load_cli_configs()
        assert result == []

    def test_handles_non_dict_json(self, tmp_path, monkeypatch):
        """load_cli_configs handles non-dict JSON gracefully."""
        clis_path = tmp_path / "clis.json"
        clis_path.write_text(json.dumps(["not", "a", "dict"]))
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        result = load_cli_configs()
        assert result == []

    def test_handles_invalid_config_entry(self, tmp_path, monkeypatch):
        """load_cli_configs skips invalid config entries."""
        clis_path = tmp_path / "clis.json"
        clis_path.write_text(json.dumps({
            "valid": {
                "path": "/usr/bin/valid",
                "models": ["model1"],
                "cli_type": "anthropic",
            },
            "invalid": "not a dict",
        }))
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        result = load_cli_configs()
        assert len(result) == 1
        assert result[0].name == "valid"


class TestSaveCliConfigs:
    """Tests for save_cli_configs()."""

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        """save_cli_configs creates parent directories if needed."""
        clis_path = tmp_path / "nested" / "dir" / "clis.json"
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        configs = [
            CLIConfig(
                name="test",
                path="/usr/bin/test",
                models=["model1"],
                cli_type="custom",
            ),
        ]
        save_cli_configs(configs)
        
        assert clis_path.exists()
        assert clis_path.parent.exists()

    def test_writes_correct_json(self, tmp_path, monkeypatch):
        """save_cli_configs writes correct JSON format."""
        clis_path = tmp_path / "clis.json"
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        configs = [
            CLIConfig(
                name="custom_cli",
                path="/usr/bin/my-ai-cli",
                models=["my-model"],
                cli_type="custom",
                args_template="--prompt {prompt}",
            ),
        ]
        save_cli_configs(configs)
        
        data = json.loads(clis_path.read_text())
        assert "custom_cli" in data
        assert data["custom_cli"]["path"] == "/usr/bin/my-ai-cli"
        assert data["custom_cli"]["models"] == ["my-model"]
        assert data["custom_cli"]["cli_type"] == "custom"
        assert data["custom_cli"]["args_template"] == "--prompt {prompt}"

    def test_omits_default_values(self, tmp_path, monkeypatch):
        """save_cli_configs omits default/empty values from JSON."""
        clis_path = tmp_path / "clis.json"
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        configs = [
            CLIConfig(
                name="simple",
                path="/usr/bin/simple",
                models=["model1"],
                cli_type="anthropic",
                # default_model, args_template are empty, enabled is True
            ),
        ]
        save_cli_configs(configs)
        
        data = json.loads(clis_path.read_text())
        assert "simple" in data
        assert "default_model" not in data["simple"]
        assert "args_template" not in data["simple"]
        assert "enabled" not in data["simple"]

    def test_includes_disabled_cli(self, tmp_path, monkeypatch):
        """save_cli_configs includes enabled=false when CLI is disabled."""
        clis_path = tmp_path / "clis.json"
        monkeypatch.setenv("CLAUDE_POOL_CLIS_PATH", str(clis_path))
        
        configs = [
            CLIConfig(
                name="disabled_cli",
                path="/usr/bin/disabled",
                models=["model1"],
                cli_type="custom",
                enabled=False,
            ),
        ]
        save_cli_configs(configs)
        
        data = json.loads(clis_path.read_text())
        assert data["disabled_cli"]["enabled"] is False
