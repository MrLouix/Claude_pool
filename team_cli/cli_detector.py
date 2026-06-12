"""Detection of installed AI CLI binaries."""

import functools
import shutil
import subprocess

from team_cli.config import load_cli_configs
from team_cli.models import CLIConfig

KNOWN_CLIS = [
    {"name": "claude", "cli_type": "anthropic", "probe_args": ["--version"]},
    {"name": "vibe-acp", "cli_type": "mistral", "probe_args": ["--version"]},
    {"name": "llama", "cli_type": "llama", "probe_args": ["--version"]},
    {"name": "agy", "cli_type": "antigravity", "probe_args": ["--version"]},
    {"name": "openai", "cli_type": "openai", "probe_args": ["--version"]},
    {"name": "opencode", "cli_type": "opencode", "probe_args": ["--version"]},
    {"name": "hermes", "cli_type": "hermes", "probe_args": ["--version"]},
]

# Common fallback paths to search
COMMON_PATHS = ["/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"]

# Model mappings for known CLI types
MODEL_MAP = {
    "anthropic": ["haiku", "sonnet", "opus"],
    "mistral": ["mistral-tiny", "mistral-small", "mistral-medium"],
}


def find_binary(name: str) -> str | None:
    """Find the absolute path to a binary.

    Args:
        name: The binary name to search for.

    Returns:
        Absolute path string if found, None otherwise.
    """
    # First try shutil.which
    path = shutil.which(name)
    if path:
        return path

    # Try common paths
    for p in COMMON_PATHS:
        candidate = f"{p}/{name}"
        if shutil.os.path.exists(candidate) and shutil.os.path.isfile(candidate):
            if shutil.os.access(candidate, shutil.os.X_OK):
                return candidate

    return None


def probe_cli(name: str, path: str, cli_type: str) -> CLIConfig | None:
    """Probe a CLI binary to verify it works.

    Args:
        name: The CLI name.
        path: Absolute path to the binary.
        cli_type: The CLI type (e.g., "anthropic", "mistral").

    Returns:
        CLIConfig if the CLI is valid, None otherwise.
    """
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Consider successful if returncode is 0 or there's some output
        if result is not None and (result.returncode == 0 or (result.stdout and result.stdout.strip())):
            models = MODEL_MAP.get(cli_type, [])
            return CLIConfig(
                name=name,
                path=path,
                models=models,
                cli_type=cli_type,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


@functools.cache
def detect_clis() -> list[CLIConfig]:
    """Detect installed AI CLI binaries on the system.

    Result is cached for the lifetime of the process — binary probing is
    expensive (one subprocess per known CLI) and the set of installed CLIs
    does not change at runtime.

    Returns:
        List of CLIConfig objects for detected CLIs, merged with custom configs.
    """
    detected: dict[str, CLIConfig] = {}

    # Probe known CLIs
    for known in KNOWN_CLIS:
        path = find_binary(known["name"])
        if path:
            config = probe_cli(known["name"], path, known["cli_type"])
            if config:
                detected[config.name] = config

    # Load custom configs
    custom_configs = load_cli_configs()
    for config in custom_configs:
        if config.enabled:
            # Custom config overrides detected entry
            detected[config.name] = config

    return list(detected.values())
