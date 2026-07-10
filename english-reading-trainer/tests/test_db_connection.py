"""
Integration tests for db_connection.py and the initial SQL schema.

All tests use a real SQLite database (tmp_path fixture) — nothing is mocked.
Covers: connection, WAL mode, FK enforcement, migration runner idempotency,
all tables/columns from §1 of design.md, constraint violations, seed data.
"""

import sqlite3
import shutil
from pathlib import Path

import pytest

from app.db_connection import (
    DatabaseConnection,
    DatabaseIntegrityReport,
    DatabaseRestoreError,
    MigrationChecksumError,
    _migration_statements,
)
from app.db_models import VALID_ERROR_CODES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

class TestMigrationRunner:
    def test_apply_migrations_returns_applied_filenames(self, tmp_path: Path) -> None:
        db = DatabaseConnection(tmp_path / "fresh.db")
        applied = db.apply_migrations(MIGRATIONS_DIR)
        assert "001_initial_schema.sql" in applied
        assert "002_seed_error_types.sql" in applied
        assert "003_archive_cards.sql" in applied
        assert "004_sentence_user_translation.sql" in applied
        assert "005_chapter_section_metadata.sql" in applied
        assert "006_epub_assets_and_blocks.sql" in applied
        assert "007_pdf_source_format.sql" in applied
        assert "008_word_card_sources.sql" in applied
        assert "009_inference_error_layer.sql" in applied
        assert "010_sentence_user_structure.sql" in applied
        assert "011_ai_cache_input_snapshot.sql" in applied
        assert "012_word_card_diagnosis.sql" in applied
        assert "013_markdown_source_format.sql" in applied
        assert "014_markdown_reader_blocks.sql" in applied
        assert "015_word_card_source_offsets.sql" in applied
        assert "016_migration_checksums.sql" in applied

    def test_migrations_are_idempotent(self, db: DatabaseConnection) -> None:
        applied_second = db.apply_migrations(MIGRATIONS_DIR)
        assert applied_second == [], "Re-running migrations should apply nothing"

    def test_applied_migrations_recorded(self, db: DatabaseConnection) -> None:
        recorded = db.get_applied_migrations()
        assert "001_initial_schema.sql" in recorded
        assert "002_seed_error_types.sql" in recorded
        assert "003_archive_cards.sql" in recorded
        assert "004_sentence_user_translation.sql" in recorded
        assert "005_chapter_section_metadata.sql" in recorded
        assert "006_epub_assets_and_blocks.sql" in recorded
        assert "007_pdf_source_format.sql" in recorded
        assert "008_word_card_sources.sql" in recorded
        assert "009_inference_error_layer.sql" in recorded
        assert "010_sentence_user_structure.sql" in recorded
        assert "011_ai_cache_input_snapshot.sql" in recorded
        assert "012_word_card_diagnosis.sql" in recorded
        assert "013_markdown_source_format.sql" in recorded
        assert "014_markdown_reader_blocks.sql" in recorded
        assert "015_word_card_source_offsets.sql" in recorded
        assert "016_migration_checksums.sql" in recorded

    def test_malformed_migration_rolls_back_schema_and_tracking_row(
        self, tmp_path: Path
    ) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "001_bad.sql").write_text(
            "CREATE TABLE partial_state (id INTEGER);\nTHIS IS NOT SQL;\n",
            encoding="utf-8",
        )
        db = DatabaseConnection(tmp_path / "broken.db")

        with pytest.raises(sqlite3.OperationalError):
            db.apply_migrations(migrations)

        assert db.table_exists("partial_state") is False
        assert db.get_applied_migrations() == []

    def test_existing_database_is_backed_up_before_pending_migration(
        self, tmp_path: Path
    ) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        first = migrations / "001_initial.sql"
        first.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
        db = DatabaseConnection(tmp_path / "backup.db")
        db.apply_migrations(migrations)
        with db.get_connection() as conn:
            conn.execute("INSERT INTO sample (id) VALUES (1)")

        (migrations / "002_upgrade.sql").write_text(
            "ALTER TABLE sample ADD COLUMN label TEXT NOT NULL DEFAULT '';\n",
            encoding="utf-8",
        )
        db.apply_migrations(migrations)

        backups = list(db.backup_dir.glob("backup.pre-migration.*.db"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(sample)")]
            assert columns == ["id"]
            assert conn.execute("SELECT id FROM sample").fetchone()[0] == 1

    def test_modified_applied_migration_is_rejected(self, tmp_path: Path) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        migration = migrations / "001_initial.sql"
        migration.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
        checksum_migration = migrations / "002_checksums.sql"
        checksum_migration.write_text(
            "ALTER TABLE schema_migrations ADD COLUMN checksum TEXT;\n",
            encoding="utf-8",
        )
        db = DatabaseConnection(tmp_path / "checksums.db")
        db.apply_migrations(migrations)

        migration.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY, changed TEXT);\n", encoding="utf-8")

        with pytest.raises(MigrationChecksumError, match="modified"):
            db.apply_migrations(migrations)

    def test_create_backup_and_restore_backup(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('Before restore', 'txt', 'restore-hash', '2026-01-01T00:00:00+00:00')"
            )
        backup = db.create_backup(reason="manual-test")
        with db.get_connection() as conn:
            conn.execute("UPDATE books SET title = 'Changed after backup'")

        pre_restore = db.restore_backup(backup)

        assert pre_restore.exists()
        with db.get_connection() as conn:
            assert conn.execute("SELECT title FROM books").fetchone()[0] == "Before restore"

    def test_backup_requires_existing_database(self, tmp_path: Path) -> None:
        db = DatabaseConnection(tmp_path / "missing.db")

        with pytest.raises(FileNotFoundError, match="Database does not exist"):
            db.create_backup()

    def test_restore_requires_existing_backup(self, db: DatabaseConnection, tmp_path: Path) -> None:
        with pytest.raises(DatabaseRestoreError, match="Backup does not exist"):
            db.restore_backup(tmp_path / "missing-backup.db")

    def test_restore_rejects_non_sqlite_file(self, db: DatabaseConnection, tmp_path: Path) -> None:
        bad_backup = tmp_path / "not-a-database.db"
        bad_backup.write_text("not sqlite", encoding="utf-8")

        with pytest.raises(DatabaseRestoreError, match="readable SQLite"):
            db.restore_backup(bad_backup)

    def test_restore_removes_temporary_file_when_replacement_fails(
        self, db: DatabaseConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = db.create_backup(reason="replacement-failure")
        temporary_path = db.db_path.with_name(f".{db.db_path.name}.restore")

        def fail_replace(source: Path, destination: Path) -> None:
            raise OSError("replacement failed")

        monkeypatch.setattr("app.db_connection.os.replace", fail_replace)

        with pytest.raises(OSError, match="replacement failed"):
            db.restore_backup(backup)

        assert not temporary_path.exists()

    def test_integrity_report_is_healthy_for_migrated_database(
        self, db: DatabaseConnection
    ) -> None:
        assert db.check_integrity() == DatabaseIntegrityReport(("ok",), ())

    def test_checksum_verification_rejects_missing_applied_migration(self, tmp_path: Path) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        initial = migrations / "001_initial.sql"
        initial.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
        checksum = migrations / "002_checksums.sql"
        checksum.write_text(
            "ALTER TABLE schema_migrations ADD COLUMN checksum TEXT;\n",
            encoding="utf-8",
        )
        db = DatabaseConnection(tmp_path / "missing-migration.db")
        db.apply_migrations(migrations)
        initial.unlink()

        with pytest.raises(MigrationChecksumError, match="missing from disk"):
            db.apply_migrations(migrations)

    def test_backup_retention_zero_leaves_existing_backups(self, db: DatabaseConnection) -> None:
        db._backup_retention = 0
        first = db.create_backup(reason="retention")
        second = db.create_backup(reason="retention")

        assert first.exists()
        assert second.exists()

    def test_incomplete_migration_statement_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="incomplete SQL"):
            _migration_statements("CREATE TABLE example (id INTEGER);\nSELECT")

    def test_word_card_sources_migration_backfills_and_recounts(
        self, tmp_path: Path
    ) -> None:
        partial_dir = tmp_path / "partial_migrations"
        partial_dir.mkdir()
        for sql_file in sorted(MIGRATIONS_DIR.glob("00[1-7]_*.sql")):
            shutil.copy(sql_file, partial_dir / sql_file.name)
        db = DatabaseConnection(tmp_path / "recount.db")
        db.apply_migrations(partial_dir)
        with db.get_connection() as conn:
            book_id = conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('B', 'txt', 'h_recount', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            chapter_id = conn.execute(
                "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                "VALUES (?, 1, 'Ch', 0, 1)",
                (book_id,),
            ).lastrowid
            paragraph_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                "VALUES (?, 1, 0, 1)",
                (chapter_id,),
            ).lastrowid
            sentence_id = conn.execute(
                "INSERT INTO sentences "
                "(book_id, chapter_id, paragraph_id, idx, text, text_hash, "
                "char_offset_start, char_offset_end) "
                "VALUES (?, ?, ?, 0, 'intangible asset.', 'h_s', 0, 17)",
                (book_id, chapter_id, paragraph_id),
            ).lastrowid
            conn.execute(
                """INSERT INTO word_cards
                   (lemma, surface_form, lexical_type, first_sentence_id,
                    created_at, mastery_state, ef, interval_days, repetitions,
                    due_at, occurrence_count)
                   VALUES ('intangible', 'intangible', 'word', ?,
                           '2026-01-01T00:00:00+00:00', 'new', 2.5, 0, 0,
                           '2026-01-01T00:00:00+00:00', 11)""",
                (sentence_id,),
            )

        db.apply_migrations(MIGRATIONS_DIR)

        with db.get_connection() as conn:
            card = conn.execute("SELECT id, occurrence_count FROM word_cards").fetchone()
            source = conn.execute(
                """SELECT sentence_id, is_primary, start_offset, end_offset, selected_text
                     FROM word_card_sources
                    WHERE card_id = ?""",
                (card["id"],),
            ).fetchone()
        assert card["occurrence_count"] == 1
        assert source["sentence_id"] == sentence_id
        assert source["is_primary"] == 1
        assert source["start_offset"] == 0
        assert source["end_offset"] == len("intangible")
        assert source["selected_text"] == "intangible"

    def test_word_card_diagnosis_migration_defaults_existing_rows(
        self, tmp_path: Path
    ) -> None:
        partial_dir = tmp_path / "partial_012"
        partial_dir.mkdir()
        for sql_file in sorted(MIGRATIONS_DIR.glob("0[01][0-9]_*.sql")):
            if sql_file.name >= "012_":
                continue
            shutil.copy(sql_file, partial_dir / sql_file.name)
        db = DatabaseConnection(tmp_path / "diag.db")
        db.apply_migrations(partial_dir)
        with db.get_connection() as conn:
            book_id = conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('B', 'txt', 'h_diag', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            chapter_id = conn.execute(
                "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                "VALUES (?, 1, 'Ch', 0, 1)",
                (book_id,),
            ).lastrowid
            paragraph_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                "VALUES (?, 1, 0, 1)",
                (chapter_id,),
            ).lastrowid
            sentence_id = conn.execute(
                "INSERT INTO sentences "
                "(book_id, chapter_id, paragraph_id, idx, text, text_hash, "
                "char_offset_start, char_offset_end) "
                "VALUES (?, ?, ?, 0, 'a tie.', 'h_tie', 0, 6)",
                (book_id, chapter_id, paragraph_id),
            ).lastrowid
            conn.execute(
                """INSERT INTO word_cards
                   (lemma, surface_form, lexical_type, first_sentence_id,
                    created_at, mastery_state, ef, interval_days, repetitions,
                    due_at, occurrence_count)
                   VALUES ('tie', 'tie', 'word', ?,
                           '2026-01-01T00:00:00+00:00', 'new', 2.5, 0, 0,
                           '2026-01-01T00:00:00+00:00', 1)""",
                (sentence_id,),
            )

        db.apply_migrations(MIGRATIONS_DIR)

        cols = db.get_table_columns("word_cards")
        assert "note_status" in cols
        assert "note_correction" in cols
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT note_status, note_correction FROM word_cards"
            ).fetchone()
        assert row["note_status"] == ""
        assert row["note_correction"] == ""

    def test_ai_cache_input_snapshot_migration_preserves_existing_cache_rows(
        self,
        tmp_path: Path,
    ) -> None:
        old_migrations = tmp_path / "old_migrations"
        old_migrations.mkdir()
        for sql_file in sorted(MIGRATIONS_DIR.glob("0[0-1][0-9]_*.sql")):
            if sql_file.name <= "010_sentence_user_structure.sql":
                shutil.copy(sql_file, old_migrations / sql_file.name)

        db = DatabaseConnection(tmp_path / "snapshot_upgrade.db")
        db.apply_migrations(old_migrations)
        with db.get_connection() as conn:
            cache_id = conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json, is_valid, created_at)
                   VALUES ('h', 'v1', 'model', '{}', 1, '2026-01-01T00:00:00+00:00')"""
            ).lastrowid

        applied = db.apply_migrations(MIGRATIONS_DIR)

        assert applied == [
            "011_ai_cache_input_snapshot.sql",
            "012_word_card_diagnosis.sql",
            "013_markdown_source_format.sql",
            "014_markdown_reader_blocks.sql",
            "015_word_card_source_offsets.sql",
            "016_migration_checksums.sql",
        ]
        assert "input_translation" in db.get_table_columns("ai_cache")
        assert "input_structure" in db.get_table_columns("ai_cache")
        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT input_translation, input_structure
                   FROM ai_cache
                   WHERE id = ?""",
                (cache_id,),
            ).fetchone()
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()

        assert row["input_translation"] is None
        assert row["input_structure"] is None
        assert fk_errors == []

    def test_inference_layer_migration_preserves_error_type_foreign_keys(
        self,
        tmp_path: Path,
    ) -> None:
        old_migrations = tmp_path / "old_migrations"
        old_migrations.mkdir()
        for sql_file in sorted(MIGRATIONS_DIR.glob("00[1-8]_*.sql")):
            shutil.copy(sql_file, old_migrations / sql_file.name)

        db = DatabaseConnection(tmp_path / "inference_upgrade.db")
        db.apply_migrations(old_migrations)
        with db.get_connection() as conn:
            book_id = conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('B', 'txt', 'h_inference', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            chapter_id = conn.execute(
                "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                "VALUES (?, 1, 'Ch', 0, 1)",
                (book_id,),
            ).lastrowid
            paragraph_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                "VALUES (?, 1, 0, 1)",
                (chapter_id,),
            ).lastrowid
            sentence_id = conn.execute(
                "INSERT INTO sentences "
                "(book_id, chapter_id, paragraph_id, idx, text, text_hash, "
                "char_offset_start, char_offset_end) "
                "VALUES (?, ?, ?, 0, 'A sentence.', 'h_sentence', 0, 11)",
                (book_id, chapter_id, paragraph_id),
            ).lastrowid
            sentence_card_id = conn.execute(
                "INSERT INTO sentence_cards (sentence_id, created_at, due_at) "
                "VALUES (?, '2026-01-01T00:00:00+00:00', "
                "'2026-01-01T00:00:00+00:00')",
                (sentence_id,),
            ).lastrowid
            word_card_id = conn.execute(
                """INSERT INTO word_cards
                   (lemma, surface_form, lexical_type, first_sentence_id,
                    created_at, mastery_state, ef, interval_days, repetitions,
                    due_at, occurrence_count)
                   VALUES ('sentence', 'sentence', 'word', ?,
                           '2026-01-01T00:00:00+00:00', 'new', 2.5, 0, 0,
                           '2026-01-01T00:00:00+00:00', 1)""",
                (sentence_id,),
            ).lastrowid
            g01_id = conn.execute(
                "SELECT id FROM error_types WHERE code = 'G01'"
            ).fetchone()["id"]
            g02_id = conn.execute(
                "SELECT id FROM error_types WHERE code = 'G02'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO sentence_card_errors (card_id, error_type_id) VALUES (?, ?)",
                (sentence_card_id, g01_id),
            )
            conn.execute(
                "INSERT INTO word_card_errors (card_id, error_type_id) VALUES (?, ?)",
                (word_card_id, g02_id),
            )

        applied = db.apply_migrations(MIGRATIONS_DIR)

        assert applied == [
            "009_inference_error_layer.sql",
            "010_sentence_user_structure.sql",
            "011_ai_cache_input_snapshot.sql",
            "012_word_card_diagnosis.sql",
            "013_markdown_source_format.sql",
            "014_markdown_reader_blocks.sql",
            "015_word_card_source_offsets.sql",
            "016_migration_checksums.sql",
        ]
        with db.get_connection() as conn:
            sentence_code = conn.execute(
                """SELECT et.code
                   FROM sentence_card_errors sce
                   JOIN error_types et ON et.id = sce.error_type_id"""
            ).fetchone()["code"]
            word_code = conn.execute(
                """SELECT et.code
                   FROM word_card_errors wce
                   JOIN error_types et ON et.id = wce.error_type_id"""
            ).fetchone()["code"]
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()

        assert sentence_code == "G01"
        assert word_code == "G02"
        assert fk_errors == []

    def test_migrations_dir_empty_returns_empty(self, tmp_path: Path) -> None:
        db = DatabaseConnection(tmp_path / "a.db")
        applied = db.apply_migrations(tmp_path / "empty_migrations")
        assert applied == []

    def test_db_file_created_if_not_exists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "nested" / "new.db"
        db = DatabaseConnection(db_path)
        db.apply_migrations(MIGRATIONS_DIR)
        assert db_path.exists()


# ---------------------------------------------------------------------------
# WAL mode and foreign keys
# ---------------------------------------------------------------------------

class TestPragmas:
    def test_wal_mode_enabled(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enforced(self, db: DatabaseConnection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                    "VALUES (9999, 1, 'orphan', 0, 0)"
                )

    def test_connection_rolls_back_on_error(self, db: DatabaseConnection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
                    "VALUES ('A', '', 'txt', 'hash1', '2026-01-01T00:00:00+00:00')"
                )
                # Second insert with same file_hash violates UNIQUE
                conn.execute(
                    "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
                    "VALUES ('B', '', 'txt', 'hash1', '2026-01-01T00:00:00+00:00')"
                )
        # First row must not have been committed
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "books", "chapters", "paragraphs", "sentences",
    "sentence_cards", "word_cards", "review_logs",
    "word_card_sources",
    "tags", "error_types",
    "sentence_card_tags", "sentence_card_errors",
    "word_card_tags", "word_card_errors",
    "ai_cache", "learner_profile_snapshots", "prompt_versions",
    "book_assets", "chapter_blocks",
    "schema_migrations",
]


class TestTableExistence:
    @pytest.mark.parametrize("table", EXPECTED_TABLES)
    def test_table_exists(self, db: DatabaseConnection, table: str) -> None:
        assert db.table_exists(table), f"Table '{table}' not found"


# ---------------------------------------------------------------------------
# Column presence (spot-check critical tables)
# ---------------------------------------------------------------------------

class TestColumns:
    def test_books_columns(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("books")
        for col in ["id", "title", "author", "language", "source_format",
                    "file_hash", "imported_at", "total_chapters", "total_sentences"]:
            assert col in cols

    def test_chapters_has_section_metadata(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("chapters")
        for col in ["section_kind", "chapter_number"]:
            assert col in cols

    def test_sentence_cards_has_sm2_fields(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("sentence_cards")
        for col in [
            "ef", "interval_days", "repetitions", "due_at",
            "mastery_state", "archived_at", "user_translation",
            "translation_created_at", "user_structure", "structure_created_at",
        ]:
            assert col in cols, f"SM-2 field '{col}' missing from sentence_cards"

    def test_word_cards_has_sm2_fields(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("word_cards")
        for col in ["ef", "interval_days", "repetitions", "due_at",
                    "mastery_state", "lexical_type", "lemma", "surface_form",
                    "archived_at"]:
            assert col in cols

    def test_word_cards_has_diagnosis_fields(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("word_cards")
        for col in ["note_status", "note_correction"]:
            assert col in cols

    def test_word_card_sources_columns(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("word_card_sources")
        for col in [
            "id", "card_id", "sentence_id", "surface_form", "source_key",
            "start_offset", "end_offset", "selected_text", "is_primary", "created_at",
        ]:
            assert col in cols

    def test_review_logs_has_sm2_before_after_fields(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("review_logs")
        for col in ["quality", "outcome", "ef_before", "ef_after",
                    "interval_before", "interval_after",
                    "repetitions_before", "repetitions_after"]:
            assert col in cols

    def test_ai_cache_columns(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("ai_cache")
        for col in ["content_hash", "prompt_version", "model",
                    "response_json", "is_valid", "created_at"]:
            assert col in cols

    def test_sentences_has_text_hash(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("sentences")
        assert "text_hash" in cols

    def test_book_assets_columns(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("book_assets")
        for col in [
            "book_id", "source_href", "media_type", "storage_path",
            "sha256", "byte_size", "alt_text", "is_missing",
        ]:
            assert col in cols

    def test_chapter_blocks_columns(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("chapter_blocks")
        for col in [
            "book_id", "chapter_id", "idx", "kind", "paragraph_id",
            "asset_id", "text", "payload_json",
        ]:
            assert col in cols


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------

class TestConstraints:
    def test_books_source_format_accepts_pdf_markdown_and_rejects_invalid(
        self,
        db: DatabaseConnection,
    ) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('PDF', 'pdf', 'h_pdf', '2026-01-01T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('Markdown', 'md', 'h_md', '2026-01-01T00:00:00+00:00')"
            )

        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO books (title, source_format, file_hash, imported_at) "
                    "VALUES ('X', 'html', 'h_html', '2026-01-01T00:00:00+00:00')"
                )

    def test_pdf_source_format_migration_preserves_existing_related_data(
        self,
        tmp_path: Path,
    ) -> None:
        old_migrations = tmp_path / "old_migrations"
        old_migrations.mkdir()
        for filename in [
            "001_initial_schema.sql",
            "002_seed_error_types.sql",
            "003_archive_cards.sql",
            "004_sentence_user_translation.sql",
            "005_chapter_section_metadata.sql",
            "006_epub_assets_and_blocks.sql",
        ]:
            shutil.copy(MIGRATIONS_DIR / filename, old_migrations / filename)

        db = DatabaseConnection(tmp_path / "old.db")
        db.apply_migrations(old_migrations)
        with db.get_connection() as conn:
            txt_book_id = conn.execute(
                "INSERT INTO books "
                "(title, author, source_format, file_hash, imported_at) "
                "VALUES ('TXT', '', 'txt', 'h_txt', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            epub_book_id = conn.execute(
                "INSERT INTO books "
                "(title, author, source_format, file_hash, imported_at) "
                "VALUES ('EPUB', '', 'epub', 'h_epub', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            chapter_id = conn.execute(
                "INSERT INTO chapters "
                "(book_id, idx, title, section_kind, chapter_number) "
                "VALUES (?, 1, 'Chapter 1', 'chapter', 1)",
                (epub_book_id,),
            ).lastrowid
            paragraph_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx) VALUES (?, 1)",
                (chapter_id,),
            ).lastrowid
            sentence_id = conn.execute(
                """INSERT INTO sentences
                   (book_id, chapter_id, paragraph_id, idx, text, text_hash)
                   VALUES (?, ?, ?, 0, 'Existing EPUB sentence.', 'hash')""",
                (epub_book_id, chapter_id, paragraph_id),
            ).lastrowid
            asset_id = conn.execute(
                """INSERT INTO book_assets
                   (book_id, source_href, media_type, storage_path, sha256, byte_size)
                   VALUES (?, 'image.png', 'image/png', 'books/2/image.png', 'asset-hash', 10)""",
                (epub_book_id,),
            ).lastrowid
            conn.execute(
                """INSERT INTO chapter_blocks
                   (book_id, chapter_id, idx, kind, paragraph_id, asset_id)
                   VALUES (?, ?, 1, 'figure', ?, ?)""",
                (epub_book_id, chapter_id, paragraph_id, asset_id),
            )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO books "
                    "(title, source_format, file_hash, imported_at) "
                    "VALUES ('PDF Before', 'pdf', 'h_pdf_before', '2026-01-01')"
                )

            assert sentence_id > 0
            assert txt_book_id > 0

        applied = db.apply_migrations(MIGRATIONS_DIR)

        assert applied == [
            "007_pdf_source_format.sql",
            "008_word_card_sources.sql",
            "009_inference_error_layer.sql",
            "010_sentence_user_structure.sql",
            "011_ai_cache_input_snapshot.sql",
            "012_word_card_diagnosis.sql",
            "013_markdown_source_format.sql",
            "014_markdown_reader_blocks.sql",
            "015_word_card_source_offsets.sql",
            "016_migration_checksums.sql",
        ]
        with db.get_connection() as conn:
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "books",
                    "chapters",
                    "paragraphs",
                    "sentences",
                    "book_assets",
                    "chapter_blocks",
                )
            }
            conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('PDF After', 'pdf', 'h_pdf_after', '2026-01-01')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO books (title, source_format, file_hash, imported_at) "
                    "VALUES ('Duplicate', 'pdf', 'h_pdf_after', '2026-01-01')"
                )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO books (title, source_format, file_hash, imported_at) "
                    "VALUES ('Bad', 'html', 'h_bad', '2026-01-01')"
                )
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            sentence = conn.execute(
                "SELECT text FROM sentences WHERE id = ?",
                (sentence_id,),
            ).fetchone()

        assert counts == {
            "books": 2,
            "chapters": 1,
            "paragraphs": 1,
            "sentences": 1,
            "book_assets": 1,
            "chapter_blocks": 1,
        }
        assert sentence["text"] == "Existing EPUB sentence."

    def test_markdown_source_format_migration_preserves_existing_related_data(
        self,
        tmp_path: Path,
    ) -> None:
        old_migrations = tmp_path / "old_migrations"
        old_migrations.mkdir()
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if sql_file.name not in {
                "013_markdown_source_format.sql",
                "014_markdown_reader_blocks.sql",
                "015_word_card_source_offsets.sql",
                "016_migration_checksums.sql",
            }:
                shutil.copy(sql_file, old_migrations / sql_file.name)

        db = DatabaseConnection(tmp_path / "before_md.db")
        db.apply_migrations(old_migrations)
        with db.get_connection() as conn:
            book_id = conn.execute(
                "INSERT INTO books "
                "(title, author, source_format, file_hash, imported_at) "
                "VALUES ('PDF', '', 'pdf', 'h_pdf_before_md', '2026-01-01')"
            ).lastrowid
            chapter_id = conn.execute(
                "INSERT INTO chapters "
                "(book_id, idx, title, section_kind, chapter_number) "
                "VALUES (?, 1, 'Chapter 1', 'chapter', 1)",
                (book_id,),
            ).lastrowid
            paragraph_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx) VALUES (?, 1)",
                (chapter_id,),
            ).lastrowid
            sentence_id = conn.execute(
                """INSERT INTO sentences
                   (book_id, chapter_id, paragraph_id, idx, text, text_hash)
                   VALUES (?, ?, ?, 0, 'Existing PDF sentence.', 'hash-md-upgrade')""",
                (book_id, chapter_id, paragraph_id),
            ).lastrowid

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO books "
                    "(title, source_format, file_hash, imported_at) "
                    "VALUES ('Markdown Before', 'md', 'h_md_before', '2026-01-01')"
                )

        applied = db.apply_migrations(MIGRATIONS_DIR)

        assert applied == [
            "013_markdown_source_format.sql",
            "014_markdown_reader_blocks.sql",
            "015_word_card_source_offsets.sql",
            "016_migration_checksums.sql",
        ]
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('Markdown After', 'md', 'h_md_after', '2026-01-01')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO books (title, source_format, file_hash, imported_at) "
                    "VALUES ('Bad', 'html', 'h_bad_md', '2026-01-01')"
                )
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            sentence = conn.execute(
                "SELECT text FROM sentences WHERE id = ?",
                (sentence_id,),
            ).fetchone()

        assert sentence["text"] == "Existing PDF sentence."

    def test_sentence_user_structure_migration_preserves_existing_cards(
        self,
        tmp_path: Path,
    ) -> None:
        old_migrations = tmp_path / "old_migrations"
        old_migrations.mkdir()
        for sql_file in sorted(MIGRATIONS_DIR.glob("00[1-9]_*.sql")):
            shutil.copy(sql_file, old_migrations / sql_file.name)

        db = DatabaseConnection(tmp_path / "structure_upgrade.db")
        db.apply_migrations(old_migrations)
        with db.get_connection() as conn:
            book_id = conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('B', 'txt', 'h_structure', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            chapter_id = conn.execute(
                "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                "VALUES (?, 1, 'Ch', 0, 1)",
                (book_id,),
            ).lastrowid
            paragraph_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                "VALUES (?, 1, 0, 1)",
                (chapter_id,),
            ).lastrowid
            sentence_id = conn.execute(
                """INSERT INTO sentences
                   (book_id, chapter_id, paragraph_id, idx, text, text_hash,
                    char_offset_start, char_offset_end)
                   VALUES (?, ?, ?, 0, 'A sentence.', 'h_structure_sentence', 0, 11)""",
                (book_id, chapter_id, paragraph_id),
            ).lastrowid
            card_id = conn.execute(
                """INSERT INTO sentence_cards
                   (sentence_id, created_at, due_at, user_translation)
                   VALUES (?, '2026-01-01T00:00:00+00:00',
                           '2026-01-01T00:00:00+00:00', '一句话。')""",
                (sentence_id,),
            ).lastrowid

        applied = db.apply_migrations(MIGRATIONS_DIR)

        assert applied == [
            "010_sentence_user_structure.sql",
            "011_ai_cache_input_snapshot.sql",
            "012_word_card_diagnosis.sql",
            "013_markdown_source_format.sql",
            "014_markdown_reader_blocks.sql",
            "015_word_card_source_offsets.sql",
            "016_migration_checksums.sql",
        ]
        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT user_translation, user_structure, structure_created_at
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()

        assert row["user_translation"] == "一句话。"
        assert row["user_structure"] is None
        assert row["structure_created_at"] is None
        assert fk_errors == []

    def test_chapter_blocks_kind_check(self, db: DatabaseConnection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                book_id = conn.execute(
                    "INSERT INTO books (title, source_format, file_hash, imported_at) "
                    "VALUES ('X', 'txt', 'h1', '2026-01-01T00:00:00+00:00')"
                ).lastrowid
                chapter_id = conn.execute(
                    "INSERT INTO chapters (book_id, idx, title) VALUES (?, 1, 'C')",
                    (book_id,),
                ).lastrowid
                conn.execute(
                    "INSERT INTO chapter_blocks (book_id, chapter_id, idx, kind) "
                    "VALUES (?, ?, 1, 'video')",
                    (book_id, chapter_id),
                )

    def test_sentence_cards_mastery_state_check(self, db: DatabaseConnection) -> None:
        book_id = self._insert_book(db, "hash_sc")
        ch_id   = self._insert_chapter(db, book_id)
        par_id  = self._insert_paragraph(db, ch_id)
        sent_id = self._insert_sentence(db, book_id, ch_id, par_id)
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO sentence_cards "
                    "(sentence_id, created_at, mastery_state, ef, interval_days, repetitions, due_at) "
                    "VALUES (?, '2026-01-01', 'invalid_state', 2.5, 0, 0, '2026-01-01')",
                    (sent_id,),
                )

    def test_review_logs_quality_range_check(self, db: DatabaseConnection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO review_logs "
                    "(card_type, card_id, reviewed_at, quality, outcome, "
                    " ef_before, ef_after, interval_before, interval_after, "
                    " repetitions_before, repetitions_after) "
                    "VALUES ('sentence', 1, '2026-01-01', 6, 'pass', "
                    " 2.5, 2.5, 0, 1, 0, 1)"
                )

    def test_review_logs_outcome_check(self, db: DatabaseConnection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO review_logs "
                    "(card_type, card_id, reviewed_at, quality, outcome, "
                    " ef_before, ef_after, interval_before, interval_after, "
                    " repetitions_before, repetitions_after) "
                    "VALUES ('sentence', 1, '2026-01-01', 5, 'great', "
                    " 2.5, 2.5, 0, 1, 0, 1)"
                )

    def test_word_cards_unique_lemma(self, db: DatabaseConnection) -> None:
        book_id = self._insert_book(db, "hash_wc_uniq")
        ch_id   = self._insert_chapter(db, book_id)
        par_id  = self._insert_paragraph(db, ch_id)
        sent_id = self._insert_sentence(db, book_id, ch_id, par_id)
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO word_cards "
                "(lemma, surface_form, lexical_type, first_sentence_id, "
                " created_at, mastery_state, ef, interval_days, repetitions, due_at) "
                "VALUES ('run', 'running', 'word', ?, '2026-01-01', 'new', 2.5, 0, 0, '2026-01-01')",
                (sent_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO word_cards "
                    "(lemma, surface_form, lexical_type, first_sentence_id, "
                    " created_at, mastery_state, ef, interval_days, repetitions, due_at) "
                    "VALUES ('run', 'ran', 'word', ?, '2026-01-01', 'new', 2.5, 0, 0, '2026-01-01')",
                    (sent_id,),
                )

    def test_ai_cache_unique_key(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO ai_cache (content_hash, prompt_version, model, response_json, is_valid, created_at) "
                "VALUES ('abc', 'v1', 'gpt-4', '{}', 1, '2026-01-01')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO ai_cache (content_hash, prompt_version, model, response_json, is_valid, created_at) "
                    "VALUES ('abc', 'v1', 'gpt-4', '{}', 1, '2026-01-01')"
                )

    # ------------------------------------------------------------------
    # Helpers for building a minimal valid hierarchy
    # ------------------------------------------------------------------

    def _insert_book(self, db: DatabaseConnection, file_hash: str) -> int:
        with db.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
                "VALUES ('Test Book', 'Author', 'txt', ?, '2026-01-01T00:00:00+00:00')",
                (file_hash,),
            )
        return cur.lastrowid

    def _insert_chapter(self, db: DatabaseConnection, book_id: int) -> int:
        with db.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                "VALUES (?, 1, 'Ch1', 0, 10)",
                (book_id,),
            )
        return cur.lastrowid

    def _insert_paragraph(self, db: DatabaseConnection, chapter_id: int) -> int:
        with db.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                "VALUES (?, 1, 0, 5)",
                (chapter_id,),
            )
        return cur.lastrowid

    def _insert_sentence(
        self, db: DatabaseConnection, book_id: int, chapter_id: int, paragraph_id: int
    ) -> int:
        with db.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO sentences "
                "(book_id, chapter_id, paragraph_id, idx, text, text_hash, "
                " char_offset_start, char_offset_end) "
                "VALUES (?, ?, ?, 1, 'Hello world.', 'deadbeef', 0, 12)",
                (book_id, chapter_id, paragraph_id),
            )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Error type seed (migration 002)
# ---------------------------------------------------------------------------

class TestErrorTypeSeed:
    def test_all_20_error_types_seeded(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM error_types").fetchone()[0]
        assert count == 20

    def test_all_codes_present(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT code FROM error_types").fetchall()
        seeded_codes = {row["code"] for row in rows}
        assert seeded_codes == VALID_ERROR_CODES

    def test_layers_are_valid(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT layer FROM error_types").fetchall()
        layers = {row["layer"] for row in rows}
        assert layers == {"grammar", "lexical", "discourse", "inference"}

    def test_inference_error_types_seeded(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT code, name, layer FROM error_types WHERE layer = 'inference'"
            ).fetchall()
        assert {(row["code"], row["name"], row["layer"]) for row in rows} == {
            ("I01", "隐含关系推断失败", "inference"),
            ("I02", "言外之意 / 立场推断失败", "inference"),
        }

    def test_inference_layer_check_accepts_inference_and_rejects_unknown(
        self,
        db: DatabaseConnection,
    ) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO error_types (code, name, layer) "
                "VALUES ('I99', '临时推理测试', 'inference')"
            )

        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO error_types (code, name, layer) "
                    "VALUES ('Z99', '未知层测试', 'unknown')"
                )

    def test_seed_is_idempotent(self, db: DatabaseConnection) -> None:
        db.apply_migrations(MIGRATIONS_DIR)
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM error_types").fetchone()[0]
        assert count == 20

    @pytest.mark.parametrize("code", list(VALID_ERROR_CODES))
    def test_each_error_code_exists(self, db: DatabaseConnection, code: str) -> None:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT code FROM error_types WHERE code = ?", (code,)
            ).fetchone()
        assert row is not None, f"Error code '{code}' not found in DB"


# ---------------------------------------------------------------------------
# Full hierarchy round-trip
# ---------------------------------------------------------------------------

class TestFullHierarchy:
    def test_insert_and_cascade_delete(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            book_id = conn.execute(
                "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
                "VALUES ('Cascade Book', '', 'epub', 'cascade_hash', '2026-01-01T00:00:00+00:00')"
            ).lastrowid
            ch_id = conn.execute(
                "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                "VALUES (?, 1, 'Ch1', 0, 5)", (book_id,)
            ).lastrowid
            par_id = conn.execute(
                "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                "VALUES (?, 1, 0, 5)", (ch_id,)
            ).lastrowid
            conn.execute(
                "INSERT INTO sentences "
                "(book_id, chapter_id, paragraph_id, idx, text, text_hash, "
                " char_offset_start, char_offset_end) "
                "VALUES (?, ?, ?, 1, 'A sentence.', 'hash_cascade', 0, 10)",
                (book_id, ch_id, par_id),
            )

        # Deleting the book should cascade to chapters, paragraphs, sentences
        with db.get_connection() as conn:
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))

        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?", (book_id,)
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?", (book_id,)
            ).fetchone()[0] == 0

    def test_text_hash_allows_duplicate_across_books(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            for fhash in ("book_a_hash", "book_b_hash"):
                book_id = conn.execute(
                    "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
                    "VALUES ('Book', '', 'txt', ?, '2026-01-01T00:00:00+00:00')",
                    (fhash,),
                ).lastrowid
                ch_id = conn.execute(
                    "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
                    "VALUES (?, 1, 'Ch', 0, 1)", (book_id,)
                ).lastrowid
                par_id = conn.execute(
                    "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
                    "VALUES (?, 1, 0, 1)", (ch_id,)
                ).lastrowid
                conn.execute(
                    "INSERT INTO sentences "
                    "(book_id, chapter_id, paragraph_id, idx, text, text_hash, "
                    " char_offset_start, char_offset_end) "
                    "VALUES (?, ?, ?, 1, 'Same sentence.', 'shared_hash', 0, 14)",
                    (book_id, ch_id, par_id),
                )

        with db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE text_hash = 'shared_hash'"
            ).fetchone()[0]
        assert count == 2, "Same text_hash must be allowed across different books"
