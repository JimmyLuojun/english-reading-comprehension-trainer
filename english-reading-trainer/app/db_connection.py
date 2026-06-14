"""
SQLite connection management and migration runner.

Usage:
    db = DatabaseConnection("data/reading_trainer.db")
    db.apply_migrations("migrations/")
    with db.get_connection() as conn:
        conn.execute(...)
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator


class DatabaseConnection:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Connection factory
    # ------------------------------------------------------------------

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Migration runner — idempotent, ordered by filename
    # ------------------------------------------------------------------

    def apply_migrations(self, migrations_dir: str | Path) -> list[str]:
        """
        Apply all *.sql files in migrations_dir in lexicographic order.
        Skips files already recorded in schema_migrations.
        Returns list of filenames applied in this call.
        """
        migrations_dir = Path(migrations_dir)
        sql_files = sorted(migrations_dir.glob("*.sql"))

        applied: list[str] = []

        with self.get_connection() as conn:
            # Bootstrap: schema_migrations table may not exist yet.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename    TEXT    NOT NULL UNIQUE,
                    applied_at  TEXT    NOT NULL
                )
            """)

            already_applied: set[str] = {
                row["filename"]
                for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()
            }

            for sql_file in sql_files:
                if sql_file.name in already_applied:
                    continue

                sql_text = sql_file.read_text(encoding="utf-8")
                conn.executescript(sql_text)

                conn.execute(
                    "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                    (sql_file.name, _utcnow()),
                )
                applied.append(sql_file.name)

        return applied

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def table_exists(self, table_name: str) -> bool:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
        return row is not None

    def get_applied_migrations(self) -> list[str]:
        if not self.table_exists("schema_migrations"):
            return []
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT filename FROM schema_migrations ORDER BY id"
            ).fetchall()
        return [row["filename"] for row in rows]

    def get_table_columns(self, table_name: str) -> list[str]:
        with self.get_connection() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] for row in rows]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
