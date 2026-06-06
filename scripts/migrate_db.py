#!/usr/bin/env python3
"""Standalone database migration script for TeamCLI.

Usage:
    python scripts/migrate_db.py [--db-path pool.db]

Creates a timestamped backup before applying any changes, then runs all
schema migrations idempotently. Safe to run multiple times.

Exit codes: 0 = success, 1 = failure.
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Allow running directly from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from team_cli.migrations import MIGRATIONS, apply_migrations  # noqa: E402

DEFAULT_DB = Path(__file__).parent.parent / "pool.db"


def create_backup(db_path: Path) -> Path:
    """Copy *db_path* to a timestamped sibling file and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.name}.bak.{timestamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def run_migration(db_path: Path) -> int:
    """Backup + migrate.  Returns 0 on success, 1 on any failure."""
    if not db_path.exists():
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        return 1

    # ── Backup ────────────────────────────────────────────────────────────
    try:
        backup_path = create_backup(db_path)
        print(f"Backup created: {backup_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"Error creating backup: {exc}", file=sys.stderr)
        return 1

    # ── Migrations ────────────────────────────────────────────────────────
    try:
        results = apply_migrations(str(db_path))
    except Exception as exc:  # noqa: BLE001
        print(f"Error running migrations: {exc}", file=sys.stderr)
        return 1

    # ── Report ────────────────────────────────────────────────────────────
    print("\nMigration report:")
    for r in results:
        label = "APPLIED " if r["status"] == "applied" else "SKIPPED "
        short_sql = r["sql"][:70] + ("…" if len(r["sql"]) > 70 else "")
        print(f"  [{label}] {r['id']}: {short_sql}")

    n_applied = sum(1 for r in results if r["status"] == "applied")
    n_skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"\nDone: {n_applied} applied, {n_skipped} skipped. Backup at {backup_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate TeamCLI SQLite database schema"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB,
        metavar="PATH",
        help="Path to pool.db (default: pool.db in project root)",
    )
    args = parser.parse_args()
    sys.exit(run_migration(args.db_path))


if __name__ == "__main__":
    main()
