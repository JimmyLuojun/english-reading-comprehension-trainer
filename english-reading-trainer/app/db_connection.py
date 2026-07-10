"""SQLite storage, recovery helpers, and checksummed schema migrations."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Iterable


_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_BUSY_TIMEOUT_MS = 30_000
_DEFAULT_BACKUP_RETENTION = 20
_FOREIGN_KEYS_PRAGMA_RE = re.compile(r"^\s*PRAGMA\s+foreign_keys\s*=", re.IGNORECASE)


class MigrationChecksumError(RuntimeError):
    """Raised when an already-applied migration file was changed."""


class DatabaseRestoreError(ValueError):
    """Raised when a requested backup cannot safely replace the active database."""


@dataclass(frozen=True)
class DatabaseIntegrityReport:
    """Results from SQLite's integrity and foreign-key checks."""

    integrity_messages: tuple[str, ...]
    foreign_key_violations: tuple[str, ...]

    @property
    def is_healthy(self) -> bool:
        return self.integrity_messages == ("ok",) and not self.foreign_key_violations


class DatabaseConnection:
    def __init__(
        self,
        db_path: str | Path,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        backup_retention: int = _DEFAULT_BACKUP_RETENTION,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._timeout_seconds = timeout_seconds
        self._backup_retention = backup_retention

    @property
    def db_path(self) -> Path:
        """Return the configured SQLite database path."""
        return self._db_path

    @property
    def backup_dir(self) -> Path:
        """Return the local directory used for SQLite recovery snapshots."""
        return self._db_path.parent / "backups"

    # ------------------------------------------------------------------
    # Connection factory
    # ------------------------------------------------------------------

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, timeout=self._timeout_seconds)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA busy_timeout = {_DEFAULT_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Backup, restore, and health checks
    # ------------------------------------------------------------------

    def create_backup(
        self,
        *,
        reason: str = "manual",
        backup_dir: str | Path | None = None,
    ) -> Path:
        """Create a consistent SQLite snapshot using SQLite's online backup API."""
        if not self._db_path.exists():
            raise FileNotFoundError(f"Database does not exist: {self._db_path}")

        target_dir = Path(backup_dir) if backup_dir is not None else self.backup_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_reason = _safe_backup_reason(reason)
        backup_path = target_dir / f"{self._db_path.stem}.{safe_reason}.{timestamp}.db"
        suffix = 1
        while backup_path.exists():
            backup_path = target_dir / (
                f"{self._db_path.stem}.{safe_reason}.{timestamp}.{suffix}.db"
            )
            suffix += 1

        with sqlite3.connect(self._db_path, timeout=self._timeout_seconds) as source:
            with sqlite3.connect(backup_path) as destination:
                source.backup(destination)

        self._prune_backups(target_dir)
        return backup_path

    def restore_backup(self, backup_path: str | Path) -> Path:
        """Replace the active SQLite database from a verified backup snapshot.

        Callers must ensure the web server is stopped so no other process keeps a
        connection open while the database file and WAL sidecars are replaced.
        """
        source_path = Path(backup_path)
        if not source_path.is_file():
            raise DatabaseRestoreError(f"Backup does not exist: {source_path}")

        self._verify_database_file(source_path)
        pre_restore_backup = self.create_backup(reason="pre-restore")
        temporary_path = self._db_path.with_name(f".{self._db_path.name}.restore")
        try:
            with sqlite3.connect(source_path, timeout=self._timeout_seconds) as source:
                with sqlite3.connect(temporary_path) as destination:
                    source.backup(destination)
            self._verify_database_file(temporary_path)
            os.replace(temporary_path, self._db_path)
            for suffix in ("-wal", "-shm"):
                Path(f"{self._db_path}{suffix}").unlink(missing_ok=True)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return pre_restore_backup

    def check_integrity(self) -> DatabaseIntegrityReport:
        """Run SQLite integrity and foreign-key validation against the database."""
        with self.get_connection() as conn:
            integrity_messages = tuple(
                str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall()
            )
            foreign_key_violations = tuple(
                "|".join(str(value) for value in row)
                for row in conn.execute("PRAGMA foreign_key_check").fetchall()
            )
        return DatabaseIntegrityReport(integrity_messages, foreign_key_violations)

    # ------------------------------------------------------------------
    # Migration runner — ordered, atomic, and checksummed
    # ------------------------------------------------------------------

    def apply_migrations(self, migrations_dir: str | Path) -> list[str]:
        """Apply pending migrations atomically and verify applied file hashes."""
        migrations_dir = Path(migrations_dir)
        sql_files = sorted(migrations_dir.glob("*.sql"))

        with self.get_connection() as conn:
            self._ensure_migration_table(conn)
            conn.commit()
            applied_rows = self._migration_rows(conn)
            self._verify_applied_migration_checksums(applied_rows, sql_files)
            pending_files = [path for path in sql_files if path.name not in applied_rows]

            if pending_files and applied_rows:
                self.create_backup(reason="pre-migration")

            applied: list[str] = []
            for sql_file in pending_files:
                self._apply_single_migration(conn, sql_file)
                applied.append(sql_file.name)

            self._backfill_migration_checksums(conn, sql_files)

        report = self.check_integrity()
        if not report.is_healthy:
            raise RuntimeError(
                "Database integrity validation failed after migration: "
                f"integrity={report.integrity_messages}, foreign_keys={report.foreign_key_violations}"
            )
        return applied

    def _ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT    NOT NULL UNIQUE,
                applied_at  TEXT    NOT NULL
            )
            """
        )

    def _migration_rows(self, conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
        return {
            row["filename"]: row
            for row in conn.execute("SELECT * FROM schema_migrations").fetchall()
        }

    def _verify_applied_migration_checksums(
        self,
        applied_rows: dict[str, sqlite3.Row],
        sql_files: Iterable[Path],
    ) -> None:
        has_checksum_column = "checksum" in self.get_table_columns("schema_migrations")
        if not has_checksum_column:
            return
        known_files = {path.name: path for path in sql_files}
        for filename, row in applied_rows.items():
            expected_checksum = row["checksum"]
            if not expected_checksum:
                continue
            path = known_files.get(filename)
            if path is None:
                raise MigrationChecksumError(
                    f"Applied migration is missing from disk: {filename}"
                )
            actual_checksum = _migration_checksum(path)
            if actual_checksum != expected_checksum:
                raise MigrationChecksumError(
                    f"Applied migration was modified: {filename}"
                )

    def _apply_single_migration(self, conn: sqlite3.Connection, sql_file: Path) -> None:
        statements = _migration_statements(sql_file.read_text(encoding="utf-8"))
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            for statement in statements:
                if _FOREIGN_KEYS_PRAGMA_RE.match(statement):
                    continue
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                (sql_file.name, _utcnow()),
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    def _backfill_migration_checksums(
        self,
        conn: sqlite3.Connection,
        sql_files: Iterable[Path],
    ) -> None:
        if "checksum" not in self.get_table_columns("schema_migrations"):
            return
        for sql_file in sql_files:
            conn.execute(
                """UPDATE schema_migrations
                      SET checksum = ?
                    WHERE filename = ? AND (checksum IS NULL OR checksum = '')""",
                (_migration_checksum(sql_file), sql_file.name),
            )

    def _verify_database_file(self, path: Path) -> None:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                messages = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
                foreign_key_violations = list(conn.execute("PRAGMA foreign_key_check"))
        except sqlite3.Error as exc:
            raise DatabaseRestoreError(f"Backup is not a readable SQLite database: {path}") from exc
        if messages != ["ok"] or foreign_key_violations:
            raise DatabaseRestoreError(f"Backup failed integrity validation: {path}")

    def _prune_backups(self, backup_dir: Path) -> None:
        if self._backup_retention <= 0:
            return
        backups = sorted(
            backup_dir.glob(f"{self._db_path.stem}.*.db"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale_backup in backups[self._backup_retention :]:
            stale_backup.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Query helpers
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
            rows = conn.execute("SELECT filename FROM schema_migrations ORDER BY id").fetchall()
        return [row["filename"] for row in rows]

    def get_table_columns(self, table_name: str) -> list[str]:
        with self.get_connection() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] for row in rows]


def _migration_statements(sql_text: str) -> list[str]:
    """Split a SQLite script into complete statements without using executescript."""
    statements: list[str] = []
    buffer = ""
    for line in sql_text.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer)
            buffer = ""
    if buffer.strip():
        raise ValueError("Migration contains an incomplete SQL statement")
    return statements


def _migration_checksum(sql_file: Path) -> str:
    return hashlib.sha256(sql_file.read_bytes()).hexdigest()


def _safe_backup_reason(reason: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", reason).strip(".-")
    return normalized or "manual"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
