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

from app.db_connection import DatabaseConnection
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
                "SELECT sentence_id, is_primary FROM word_card_sources WHERE card_id = ?",
                (card["id"],),
            ).fetchone()
        assert card["occurrence_count"] == 1
        assert source["sentence_id"] == sentence_id
        assert source["is_primary"] == 1

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
            "translation_created_at",
        ]:
            assert col in cols, f"SM-2 field '{col}' missing from sentence_cards"

    def test_word_cards_has_sm2_fields(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("word_cards")
        for col in ["ef", "interval_days", "repetitions", "due_at",
                    "mastery_state", "lexical_type", "lemma", "surface_form",
                    "archived_at"]:
            assert col in cols

    def test_word_card_sources_columns(self, db: DatabaseConnection) -> None:
        cols = db.get_table_columns("word_card_sources")
        for col in [
            "id", "card_id", "sentence_id", "surface_form", "source_key",
            "is_primary", "created_at",
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
    def test_books_source_format_accepts_pdf_and_rejects_invalid(
        self,
        db: DatabaseConnection,
    ) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO books (title, source_format, file_hash, imported_at) "
                "VALUES ('PDF', 'pdf', 'h_pdf', '2026-01-01T00:00:00+00:00')"
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

        assert applied == ["007_pdf_source_format.sql", "008_word_card_sources.sql"]
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
    def test_all_18_error_types_seeded(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM error_types").fetchone()[0]
        assert count == 18

    def test_all_codes_present(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT code FROM error_types").fetchall()
        seeded_codes = {row["code"] for row in rows}
        assert seeded_codes == VALID_ERROR_CODES

    def test_layers_are_valid(self, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT layer FROM error_types").fetchall()
        layers = {row["layer"] for row in rows}
        assert layers == {"grammar", "lexical", "discourse"}

    def test_seed_is_idempotent(self, db: DatabaseConnection) -> None:
        db.apply_migrations(MIGRATIONS_DIR)
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM error_types").fetchone()[0]
        assert count == 18

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
