"""Main entry point for Claude Pool TUI."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .executor import TaskExecutor


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


async def run_cli(pool_file: Path) -> int:
    """Run in CLI mode (no TUI).

    Args:
        pool_file: Path to pool.json

    Returns:
        Exit code
    """
    executor = TaskExecutor(pool_file)

    try:
        await executor.load_tasks()
        await executor.run_pool()
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


async def run_tui_mode(pool_file: Path) -> int:
    """Run in TUI mode.

    Args:
        pool_file: Path to pool.json

    Returns:
        Exit code
    """
    from .tui import run_tui

    try:
        await run_tui(pool_file)
        return 0
    except Exception as e:
        logging.error(f"Error: {e}")
        return 1


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Claude Pool TUI - Manage sequential Claude Code task pools"
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
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        if args.no_tui:
            exit_code = asyncio.run(run_cli(args.pool))
        else:
            exit_code = asyncio.run(run_tui_mode(args.pool))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logging.info("\nInterrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
