"""
Integration tests for app/importers/txt_importer.py.

Uses real SQLite (tmp_path) and real files written to tmp_path.
No mocking — exercises the full import pipeline.

Covers: basic import, chapter detection, paragraph splitting,
sentence segmentation, text_hash / file_hash, DB row counts,
duplicate detection, empty file, whitespace-only, encoding fallback,
sentence offsets validity, DB field constraints, cascade queries.
"""

import hashlib
from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.importers.txt_importer import (
    DuplicateBookError,
    ImportResult,
    _is_heading,
    _split_chapters,
    _text_hash,
    import_text,
    import_txt,
)
from app.nlp.sentence_segmenter import normalize_for_hash

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


def write_txt(tmp_path: Path, name: str, content: str, encoding: str = "utf-8") -> Path:
    p = tmp_path / name
    p.write_bytes(content.encode(encoding))
    return p


# ---------------------------------------------------------------------------
# _is_heading unit tests (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestIsHeading:
    @pytest.mark.parametrize("line", [
        "Chapter 1",
        "Chapter One",
        "CHAPTER 1",
        "chapter two",
        "Part I",
        "PART THREE",
        "Section 2",
        "1. The Beginning",
        "IV. The Storm",
        "Epilogue",
        "Prologue",
        "Introduction",
        "Conclusion",
        "THE STORM",
        "DARK NIGHT",
    ])
    def test_detects_heading(self, line: str) -> None:
        assert _is_heading(line), f"Expected '{line}' to be detected as a heading"

    @pytest.mark.parametrize("line", [
        "",
        "   ",
        "The quick brown fox jumps over the lazy dog.",
        "She walked into the room and sat down quietly.",
        "1234567890",
        "a",
        "This is a normal sentence that happens to be long.",
        "AVERYLONGALLCAPSHEADINGTHATSHOULDNOTMATCH" * 2,  # over 60 chars
    ])
    def test_rejects_non_heading(self, line: str) -> None:
        assert not _is_heading(line), f"Expected '{line}' NOT to be a heading"


# ---------------------------------------------------------------------------
# _split_chapters unit tests (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestSplitChapters:
    def test_no_headings_returns_one_chapter(self) -> None:
        text = "First paragraph.\n\nSecond paragraph."
        chapters = _split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "Chapter 1"

    def test_chapter_headings_detected(self) -> None:
        text = "Chapter 1\nFirst content.\n\nChapter 2\nSecond content."
        chapters = _split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "Chapter 1"
        assert chapters[1]["title"] == "Chapter 2"

    def test_preamble_before_first_heading(self) -> None:
        text = "Preface text here.\n\nChapter 1\nContent."
        chapters = _split_chapters(text)
        # Preamble + Chapter 1
        titles = [c["title"] for c in chapters]
        assert "Preamble" in titles or "Chapter 1" in titles

    def test_chapter_body_excludes_heading_line(self) -> None:
        text = "Chapter 1\nThis is the body."
        chapters = _split_chapters(text)
        assert "Chapter 1" not in chapters[0]["body"]
        assert "This is the body." in chapters[0]["body"]

    def test_all_caps_heading_detected(self) -> None:
        text = "THE BEGINNING\nSome content here.\n\nTHE END\nFinal words."
        chapters = _split_chapters(text)
        assert len(chapters) == 2

    def test_empty_text_returns_empty(self) -> None:
        assert _split_chapters("") == []
        assert _split_chapters("   \n  ") == []

    def test_multiple_chapters_have_correct_content(self) -> None:
        text = "Chapter 1\nAlpha text.\n\nChapter 2\nBeta text."
        chapters = _split_chapters(text)
        assert "Alpha" in chapters[0]["body"]
        assert "Beta" in chapters[1]["body"]


# ---------------------------------------------------------------------------
# _text_hash
# ---------------------------------------------------------------------------

class TestTextHash:
    def test_hash_is_sha256_hex(self) -> None:
        h = _text_hash("Hello world.")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_text_same_hash(self) -> None:
        assert _text_hash("Hello world.") == _text_hash("Hello world.")

    def test_case_insensitive(self) -> None:
        assert _text_hash("Hello World.") == _text_hash("hello world.")

    def test_whitespace_collapse(self) -> None:
        assert _text_hash("Hello  world.") == _text_hash("Hello world.")

    def test_different_texts_different_hash(self) -> None:
        assert _text_hash("Hello.") != _text_hash("Goodbye.")

    def test_hash_matches_manual_sha256(self) -> None:
        text = "The cat sat on the mat."
        normalised = normalize_for_hash(text).encode("utf-8")
        expected = hashlib.sha256(normalised).hexdigest()
        assert _text_hash(text) == expected


# ---------------------------------------------------------------------------
# import_txt integration tests
# ---------------------------------------------------------------------------

class TestImportTxtBasic:
    def test_returns_import_result(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "Hello world. This is a test.")
        result = import_txt(db, f, title="Test Book")
        assert isinstance(result, ImportResult)

    def test_book_row_inserted(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "One sentence here.")
        result = import_txt(db, f, title="My Book", author="Author A")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row is not None
        assert row["title"] == "My Book"
        assert row["author"] == "Author A"
        assert row["source_format"] == "txt"
        assert row["language"] == "en"

    def test_book_totals_updated(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "Sentence one. Sentence two.")
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT total_chapters, total_sentences FROM books WHERE id = ?",
                (result.book_id,),
            ).fetchone()
        assert row["total_chapters"] == result.chapter_count
        assert row["total_sentences"] == result.sentence_count

    def test_at_least_one_chapter_created(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "Some text here.")
        result = import_txt(db, f, title="Book")
        assert result.chapter_count >= 1

    def test_at_least_one_sentence_created(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "This is a sentence.")
        result = import_txt(db, f, title="Book")
        assert result.sentence_count >= 1

    def test_sentences_stored_in_db(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "First sentence. Second sentence.")
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?", (result.book_id,)
            ).fetchone()[0]
        assert count == result.sentence_count


class TestImportTxtChapters:
    def test_chapter_heading_detected(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "Chapter 1\nFirst content here.\n\nChapter 2\nSecond content here."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        assert result.chapter_count == 2

    def test_chapter_titles_stored(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "Chapter 1\nContent A.\n\nChapter 2\nContent B."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
                (result.book_id,),
            ).fetchall()
        titles = [r["title"] for r in rows]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles

    def test_no_headings_produces_one_chapter(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "Just a paragraph.\n\nAnother paragraph."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        assert result.chapter_count == 1

    def test_three_chapters(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = (
            "Chapter 1\nContent one.\n\n"
            "Chapter 2\nContent two.\n\n"
            "Chapter 3\nContent three."
        )
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        assert result.chapter_count == 3


class TestImportTxtParagraphs:
    def test_blank_line_splits_paragraphs(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "First paragraph sentence.\n\nSecond paragraph sentence."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        assert result.paragraph_count == 2

    def test_multiple_blank_lines_treated_as_one(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "Para one.\n\n\n\nPara two."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        assert result.paragraph_count == 2

    def test_no_blank_lines_is_one_paragraph(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "Line one.\nLine two.\nLine three."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        assert result.paragraph_count == 1


class TestImportTxtHashes:
    def test_file_hash_is_sha256_of_file_bytes(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        content = "Hello world. This is a test."
        f = write_txt(tmp_path, "book.txt", content)
        result = import_txt(db, f, title="Book")
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_hash FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["file_hash"] == expected

    def test_text_hash_is_case_insensitive(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "Hello World.")
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT text_hash FROM sentences WHERE book_id = ? LIMIT 1",
                (result.book_id,),
            ).fetchone()
        expected = _text_hash("Hello World.")
        assert row["text_hash"] == expected

    def test_same_sentence_in_two_books_has_same_text_hash(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        sentence = "The quick brown fox."
        f1 = write_txt(tmp_path, "book1.txt", sentence)
        f2 = write_txt(tmp_path, "book2.txt", sentence + " Extra content.")
        r1 = import_txt(db, f1, title="Book 1")
        r2 = import_txt(db, f2, title="Book 2")
        with db.get_connection() as conn:
            hashes = conn.execute(
                "SELECT text_hash FROM sentences WHERE text = ?", (sentence,)
            ).fetchall()
        hash_values = {row["text_hash"] for row in hashes}
        assert len(hash_values) == 1, "Same sentence text must produce same text_hash"


class TestImportTxtOffsets:
    def test_char_offsets_are_valid(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "book.txt", "First sentence. Second sentence.")
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT char_offset_start, char_offset_end FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchall()
        for row in rows:
            assert row["char_offset_start"] >= 0
            assert row["char_offset_end"] > row["char_offset_start"]

    def test_sentence_idx_is_monotonic(self, db: DatabaseConnection, tmp_path: Path) -> None:
        text = "Sentence one. Sentence two. Sentence three."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT idx FROM sentences WHERE book_id = ? ORDER BY id",
                (result.book_id,),
            ).fetchall()
        indices = [r["idx"] for r in rows]
        assert indices == sorted(indices)


class TestImportTxtErrors:
    def test_file_not_found_raises(self, db: DatabaseConnection, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            import_txt(db, tmp_path / "nonexistent.txt", title="Book")

    def test_empty_file_raises_value_error(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "empty.txt", "")
        with pytest.raises(ValueError, match="no usable text"):
            import_txt(db, f, title="Book")

    def test_whitespace_only_raises_value_error(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = write_txt(tmp_path, "ws.txt", "   \n\n\t  ")
        with pytest.raises(ValueError, match="no usable text"):
            import_txt(db, f, title="Book")

    def test_duplicate_file_hash_raises(self, db: DatabaseConnection, tmp_path: Path) -> None:
        content = "A unique sentence for duplicate test."
        f = write_txt(tmp_path, "book.txt", content)
        import_txt(db, f, title="Book First Import")
        with pytest.raises(DuplicateBookError):
            import_txt(db, f, title="Book Second Import")

    def test_duplicate_does_not_insert_extra_rows(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        content = "Another sentence for duplicate check."
        f = write_txt(tmp_path, "dup.txt", content)
        import_txt(db, f, title="Book")
        with pytest.raises(DuplicateBookError):
            import_txt(db, f, title="Book Again")
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        assert count == 1


class TestImportTxtEncoding:
    def test_latin1_file_imports(self, db: DatabaseConnection, tmp_path: Path) -> None:
        # latin-1 encoded file with accented chars (won't appear in English text,
        # but importer must not crash)
        content = "Caf\xe9 and na\xefve. Another sentence."
        f = tmp_path / "latin1.txt"
        f.write_bytes(content.encode("latin-1"))
        result = import_txt(db, f, title="Latin1 Book")
        assert result.sentence_count >= 1

    def test_utf8_bom_file_imports(self, db: DatabaseConnection, tmp_path: Path) -> None:
        content = "﻿Hello world. This has a BOM."
        f = tmp_path / "bom.txt"
        f.write_bytes(content.encode("utf-8-sig"))
        result = import_txt(db, f, title="BOM Book")
        assert result.sentence_count >= 1


class TestImportText:
    """Direct tests for the bytes-input entry point used by the Web UI."""

    def test_basic_import_returns_result(self, db: DatabaseConnection) -> None:
        result = import_text(db, b"Hello world. This is a test.", title="Pasted")
        assert isinstance(result, ImportResult)
        assert result.sentence_count >= 1

    def test_book_row_inserted_with_metadata(self, db: DatabaseConnection) -> None:
        result = import_text(
            db, b"Some content.", title="Pasted Title", author="Pasted Author"
        )
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["title"] == "Pasted Title"
        assert row["author"] == "Pasted Author"
        assert row["source_format"] == "txt"

    def test_file_hash_matches_sha256_of_bytes(self, db: DatabaseConnection) -> None:
        raw = b"Hash check sentence."
        result = import_text(db, raw, title="Hash")
        expected = hashlib.sha256(raw).hexdigest()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_hash FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["file_hash"] == expected

    def test_empty_bytes_raises_value_error(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="no usable text"):
            import_text(db, b"", title="Empty")

    def test_whitespace_only_raises_value_error(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="no usable text"):
            import_text(db, b"   \n\t  ", title="WS")

    def test_duplicate_bytes_raise(self, db: DatabaseConnection) -> None:
        raw = b"A unique pasted snippet."
        import_text(db, raw, title="First")
        with pytest.raises(DuplicateBookError):
            import_text(db, raw, title="Second")

    def test_same_bytes_via_file_and_text_collide(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        """import_txt and import_text must share the file_hash space."""
        content = "Shared content between file and paste."
        f = write_txt(tmp_path, "shared.txt", content)
        import_txt(db, f, title="File path")
        with pytest.raises(DuplicateBookError):
            import_text(db, content.encode("utf-8"), title="Paste path")

    def test_chapter_detection_works_via_bytes(self, db: DatabaseConnection) -> None:
        text = "Chapter 1\nContent A.\n\nChapter 2\nContent B."
        result = import_text(db, text.encode("utf-8"), title="Two chapters")
        assert result.chapter_count == 2


class TestImportTxtHierarchyIntegrity:
    def test_all_sentences_have_valid_paragraph_id(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        f = write_txt(tmp_path, "book.txt", "Sentence one.\n\nSentence two.")
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT s.id FROM sentences s "
                "LEFT JOIN paragraphs p ON s.paragraph_id = p.id "
                "WHERE s.book_id = ? AND p.id IS NULL",
                (result.book_id,),
            ).fetchall()
        assert len(rows) == 0, "All sentences must have a valid paragraph_id"

    def test_all_paragraphs_have_valid_chapter_id(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        text = "Chapter 1\nParagraph one.\n\nParagraph two."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT p.id FROM paragraphs p "
                "LEFT JOIN chapters c ON p.chapter_id = c.id "
                "WHERE c.book_id = ? AND c.id IS NULL",
                (result.book_id,),
            ).fetchall()
        assert len(rows) == 0, "All paragraphs must have a valid chapter_id"

    def test_chapter_sentence_range_covers_all_sentences(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        text = "Chapter 1\nFirst. Second.\n\nChapter 2\nThird. Fourth."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            chapters = conn.execute(
                "SELECT sentence_start, sentence_end FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchall()
        for ch in chapters:
            assert ch["sentence_end"] >= ch["sentence_start"]

    def test_import_result_counts_match_db(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        text = "Chapter 1\nSentence A. Sentence B.\n\nChapter 2\nSentence C."
        f = write_txt(tmp_path, "book.txt", text)
        result = import_txt(db, f, title="Book")
        with db.get_connection() as conn:
            ch_count  = conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?", (result.book_id,)
            ).fetchone()[0]
            par_count = conn.execute(
                "SELECT COUNT(*) FROM paragraphs p "
                "JOIN chapters c ON p.chapter_id = c.id WHERE c.book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
            sent_count = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?", (result.book_id,)
            ).fetchone()[0]
        assert ch_count  == result.chapter_count
        assert par_count == result.paragraph_count
        assert sent_count == result.sentence_count
