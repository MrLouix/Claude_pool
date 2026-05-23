"""Main entry point for Claude Pool TUI."""

import argparse
import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .executor import TaskExecutor


def check_claude_cli() -> bool:
    """Check that the Claude CLI is installed and reachable. Prints a warning if not."""
    if shutil.which("claude") is None:
        print(
            "\n[WARNING] 'claude' command not found in PATH.\n"
            "  Claude Pool requires the Claude CLI to be installed and authenticated.\n"
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
        verbose: Enable verbose logging (INFO level)
        debug: Enable debug logging (DEBUG level)
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
                filename="claude_pool_debug.log",
                filemode="w",
            )
            # Also print to stderr that debug log file is created
            print("Debug logging enabled. Logs written to: claude_pool_debug.log", file=sys.stderr)
        elif verbose:
            level = logging.INFO
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        else:
            level = logging.WARNING
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
    else:
        # CLI mode: normal logging to console
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.INFO
        else:
            level = logging.WARNING

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


async def run_cli(pool_file: Path, max_concurrent: int = 1) -> int:
    """Run in CLI mode (no TUI).

    Args:
        pool_file: Path to pool.json
        max_concurrent: Maximum number of concurrent tasks

    Returns:
        Exit code
    """
    executor = TaskExecutor(pool_file, max_concurrent=max_concurrent)

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
        pool_file: Path to pool.json
        max_concurrent: Maximum number of concurrent tasks (not used in TUI)

    Returns:
        Exit code
    """
    from .tui import run_tui

    try:
        await run_tui(pool_file, max_concurrent=max_concurrent)
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


def run_api_server(pool_file: Path, host: str = "0.0.0.0", port: int = 8000) -> int:
    """Run API server with FastAPI/Uvicorn.

    Args:
        pool_file: Path to pool.json
        host: Host to bind to
        port: Port to bind to

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

        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Claude Pool - Manage sequential Claude Code task pools"
    )
    parser.add_argument(
        "--pool",
        type=Path,
        default=Path("pool.json"),
        help="Path to pool.json file (default: pool.json)",
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
        help="Enable verbose logging (INFO level)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (DEBUG level)",
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

    check_claude_cli()

    try:
        if args.serve:
            exit_code = run_api_server(args.pool, host=args.host, port=args.port)
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
