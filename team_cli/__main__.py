"""Main entry point for TeamCLI TUI."""

import argparse
import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .cli_detector import detect_clis
from .config import load_cli_configs
from .executor import CLIManager, TaskExecutor


def check_claude_cli() -> bool:
    """Check that the Claude CLI is installed and reachable. Prints a warning if not."""
    if shutil.which("claude") is None:
        print(
            "\n[WARNING] 'claude' command not found in PATH.\n"
            "  TeamCLI requires the Claude CLI to be installed and authenticated.\n"
            "  Install it from: https://claude.ai/code\n",
            file=sys.stderr,
        )
        return False

    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            print(
                "\n[WARNING] 'claude --version' returned a non-zero exit code.\n"
                "  The Claude CLI may not be properly installed or authenticated.\n"
                "  Install it from: https://claude.ai/code\n",
                file=sys.stderr,
            )
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print(
            f"\n[WARNING] Could not run 'claude --version': {exc}\n"
            "  The Claude CLI may not be properly installed.\n"
            "  Install it from: https://claude.ai/code\n",
            file=sys.stderr,
        )
        return False

    return True


def setup_logging(verbose: bool = False, debug: bool = False, tui_mode: bool = False) -> None:
    """Setup logging configuration.

    Args:
        verbose: Enable WARNING level logging
        debug: Enable DEBUG level logging (includes INFO, WARNING, ERROR)
        tui_mode: If True, disable console logging (use TUI log widget instead)
    """
    if tui_mode:
        # In TUI mode, write logs to file when debug is enabled
        if debug:
            level = logging.DEBUG
            # Write debug logs to file to avoid polluting TUI
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
                filename="team_cli_debug.log",
                filemode="w",
            )
            # Also print to stderr that debug log file is created
            print("Debug logging enabled. Logs written to: team_cli_debug.log", file=sys.stderr)
        elif verbose:
            level = logging.WARNING
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        else:
            level = logging.ERROR
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        # Suppress third-party library logs
        logging.getLogger("aiosqlite").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    else:
        # CLI mode: normal logging to console
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.WARNING
        else:
            level = logging.ERROR

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        # Suppress third-party library logs
        logging.getLogger("aiosqlite").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


async def run_cli(pool_file: Path, max_concurrent: int = 1) -> int:
    """Run in CLI mode (no TUI).

    Args:
        pool_file: Path to pool.db
        max_concurrent: Maximum number of concurrent tasks

    Returns:
        Exit code
    """
    # Bootstrap CLIManager
    detected = detect_clis()
    custom = load_cli_configs()
    all_configs = {c.name: c for c in detected}
    all_configs.update({c.name: c for c in custom})
    cli_manager = CLIManager(list(all_configs.values()))

    if not cli_manager._executors:
        print(
            "[WARNING] No CLI executors detected or configured. "
            "Tasks will fail until a valid CLI is available.",
            file=sys.stderr,
        )

    executor = TaskExecutor(pool_file, max_concurrent=max_concurrent, cli_manager=cli_manager)

    try:
        await executor.load_tasks()
        await executor.run_pool()
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


async def run_tui_mode(pool_file: Path, max_concurrent: int = 1) -> int:
    """Run in TUI mode.

    Args:
        pool_file: Path to pool.db
        max_concurrent: Maximum number of concurrent tasks (not used in TUI)

    Returns:
        Exit code
    """
    from .tui import run_tui

    # Bootstrap CLIManager
    detected = detect_clis()
    custom = load_cli_configs()
    all_configs = {c.name: c for c in detected}
    all_configs.update({c.name: c for c in custom})
    cli_manager = CLIManager(list(all_configs.values()))

    if not cli_manager._executors:
        print(
            "[WARNING] No CLI executors detected or configured. "
            "Tasks will fail until a valid CLI is available.",
            file=sys.stderr,
        )

    try:
        await run_tui(pool_file, max_concurrent=max_concurrent, cli_manager=cli_manager)
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


def run_api_server(pool_file: Path, host: str = "0.0.0.0", port: int = 8000, log_level: str = "info") -> int:
    """Run API server with FastAPI/Uvicorn.

    Args:
        pool_file: Path to pool.db
        host: Host to bind to
        port: Port to bind to
        log_level: Uvicorn log level (debug, info, warning, error)

    Returns:
        Exit code
    """
    try:
        import uvicorn

        from .api import create_app

        app = create_app(pool_file)
        logging.info(f"Starting API server on http://{host}:{port}")
        logging.info(f"Dashboard: http://{host}:{port}")
        logging.info(f"WebSocket: ws://{host}:{port}/ws/events")

        uvicorn.run(app, host=host, port=port, log_level=log_level)
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="TeamCLI - Manage sequential Claude Code task pools"
    )
    parser.add_argument(
        "--pool",
        type=Path,
        default=Path("pool.db"),
        help="Path to pool database (default: pool.db)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run in CLI mode without TUI",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run API server with FastAPI (default: 0.0.0.0:8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="API server host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API server port (default: 8000)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable WARNING level logging (WARNING + ERROR)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG level logging (DEBUG + INFO + WARNING + ERROR)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Run up to N tasks concurrently (default: 1, sequential)",
    )

    args = parser.parse_args()

    # Setup logging based on mode
    setup_logging(
        verbose=args.verbose, debug=args.debug, tui_mode=not args.no_tui and not args.serve
    )

    db_path = args.pool if args.pool.suffix == ".db" else args.pool.with_suffix(".db")
    logging.info(f"Using database: {db_path.resolve()}")

    check_claude_cli()

    try:
        if args.serve:
            # Map CLI log flags to uvicorn log levels
            if args.debug:
                uvicorn_log_level = "debug"
            elif args.verbose:
                uvicorn_log_level = "warning"
            else:
                uvicorn_log_level = "error"
            exit_code = run_api_server(args.pool, host=args.host, port=args.port, log_level=uvicorn_log_level)
        elif args.no_tui:
            if args.parallel > 1:
                logging.info(f"Running with {args.parallel} concurrent tasks")
            exit_code = asyncio.run(run_cli(args.pool, max_concurrent=args.parallel))
        else:
            if args.parallel > 1:
                logging.warning(
                    "Parallel execution not supported in TUI mode, using sequential execution"
                )
            exit_code = asyncio.run(run_tui_mode(args.pool))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logging.info("\nInterrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
