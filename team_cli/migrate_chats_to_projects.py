#!/usr/bin/env python
"""Migration script: Convert chat buckets to projects.

Usage:
    python -m team_cli.migrate_chats_to_projects /path/to/pool.db
    OR
    python team_cli/migrate_chats_to_projects.py /path/to/pool.db

This script:
1. Finds all buckets of type 'chat' in the database
2. Creates a Project for each chat bucket with allow_cli_switch=False
3. Migrates all tasks in each chat bucket to ProjectMessage entries
4. Preserves all metadata in message metadata field
"""

import sys
from pathlib import Path

from .storage import migrate_chats_to_projects, load_projects


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m team_cli.migrate_chats_to_projects <db_path>")
        print("  db_path: Path to the pool.db file")
        sys.exit(1)

    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)

    if not db_path.name == "pool.db" and not db_path.suffix == ".db":
        print(f"Warning: Expected a .db file, got: {db_path}")

    print(f"Starting migration for database: {db_path}")
    print("-" * 60)

    count = migrate_chats_to_projects(db_path)

    print("-" * 60)
    print(f"Migration complete! Created {count} projects from chat buckets.")

    # Verify
    projects = load_projects(db_path)
    print(f"Total projects in database: {len(projects)}")
    for p in projects:
        print(f"  - {p.name} ({p.id}): allow_cli_switch={p.allow_cli_switch}")


if __name__ == "__main__":
    main()
