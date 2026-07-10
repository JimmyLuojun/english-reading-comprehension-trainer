"""Verify docs/state/schema.sql matches a database built from current migrations."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_REPOSITORY_ROOT = _PROJECT_ROOT.parent
_MIGRATIONS = _PROJECT_ROOT / "migrations"
_SCHEMA_PATH = _REPOSITORY_ROOT / "docs" / "state" / "schema.sql"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.db_connection import DatabaseConnection  # noqa: E402


def generated_schema() -> str:
    """Build a temporary SQLite database and return sqlite3's canonical schema."""
    with tempfile.TemporaryDirectory() as temporary_dir:
        db_path = Path(temporary_dir) / "schema.db"
        DatabaseConnection(db_path).apply_migrations(_MIGRATIONS)
        completed = subprocess.run(
            ["sqlite3", str(db_path), ".schema"],
            check=True,
            capture_output=True,
            text=True,
        )
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=_SCHEMA_PATH)
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the schema file instead of checking it",
    )
    args = parser.parse_args(argv)
    actual = generated_schema()
    if args.write:
        args.schema.write_text(actual, encoding="utf-8")
        print(f"Schema regenerated: {args.schema}")
        return 0
    expected = args.schema.read_text(encoding="utf-8")
    if actual == expected:
        print("Schema parity: ok")
        return 0
    print("Schema parity failed. Regenerate docs/state/schema.sql from a clean database.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
