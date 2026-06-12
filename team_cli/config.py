"""Configuration management for CLI tools."""

import json
import os
from pathlib import Path
from typing import Any

from team_cli.models import CLIConfig

DEFAULT_CLIS_PATH: Path = Path.home() / ".team_cli" / "clis.json"


def get_clis_path() -> Path:
    """Get the path to the clis.json configuration file.

    Respects the TEAM_CLI_CLIS_PATH environment variable override.
    """
    env_path = os.environ.get("TEAM_CLI_CLIS_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_CLIS_PATH


def load_cli_configs() -> list[CLIConfig]:
    """Load CLI configurations from clis.json.

    Returns:
        List of CLIConfig objects. Returns empty list if file doesn't exist
        or contains invalid JSON.
    """
    clis_path = get_clis_path()

    if not clis_path.exists():
        return []

    try:
        with open(clis_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, dict):
        return []

    configs = []
    for name, config_dict in data.items():
        try:
            if not isinstance(config_dict, dict):
                continue

            config = CLIConfig(
                name=name,
                path=str(config_dict.get("path", "")),
                models=list(config_dict.get("models", [])),
                cli_type=str(config_dict.get("cli_type", "")),
                default_model=str(config_dict.get("default_model", "")),
                args_template=str(config_dict.get("args_template", "")),
                enabled=config_dict.get("enabled", True),
            )
            configs.append(config)
        except (TypeError, ValueError):
            continue

    return configs


def save_cli_configs(configs: list[CLIConfig]) -> None:
    """Save CLI configurations to clis.json.

    Creates parent directories if needed.

    Args:
        configs: List of CLIConfig objects to serialize.
    """
    clis_path = get_clis_path()
    clis_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, dict[str, Any]] = {}
    for config in configs:
        data[config.name] = {
            "path": config.path,
            "models": config.models,
            "cli_type": config.cli_type,
        }
        if config.default_model:
            data[config.name]["default_model"] = config.default_model
        if config.args_template:
            data[config.name]["args_template"] = config.args_template
        if not config.enabled:
            data[config.name]["enabled"] = config.enabled

    with open(clis_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
