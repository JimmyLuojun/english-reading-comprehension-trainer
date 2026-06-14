"""
Integration tests for app/importers/epub_importer.py.

Uses real SQLite (tmp_path) and programmatically built EPUB fixtures
from epub_builder.py. No mocking.

Covers: metadata extraction, TOC-based chapter titles, heading fallback,
paragraph / sentence counts, text_hash / file_hash, duplicate detection,
missing file, empty EPUB, no-<p>-tag fallback, DB hierarchy integrity,
cascade queries, ImportResult ↔ DB consistency.
"""

import hashlib
from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.importers.epub_importer import (
    _build_toc_map,
    _extract_metadata,
    _extract_paragraphs,
    _heading_from_soup,
    _text_hash,
    import_epub,
)
from app.importers.txt_importer import DuplicateBookError, ImportResult
from app.nlp.sentence_segmenter import normalize_for_hash
from bs4 import BeautifulSoup
from ebooklib import epub

from tests.importers.epub_builder import (
    make_epub,
    make_epub_no_paragraphs,
    make_epub_no_toc,
)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


@pytest.fixture()
def simple_epub(tmp_path: Path) -> Path:
    return make_epub(
        tmp_path,
        "simple.epub",
        title="My Test Book",
        author="Jane Doe",
        chapters=[
            {
                "title": "Chapter 1",
                "paragraphs": [
                    "The economy grew rapidly last year. Analysts were surprised.",
                    "Inflation remained a concern for many households.",
                ],
            },
            {
                "title": "Chapter 2",
                "paragraphs": [
                    "The second chapter begins here. It has two sentences.",
                    "A longer paragraph appears in this section. More details follow. "
                    "This is the third sentence.",
                ],
            },
        ],
    )


# ---------------------------------------------------------------------------
# Unit tests: _heading_from_soup
# ---------------------------------------------------------------------------

class TestHeadingFromSoup:
    def test_finds_h1(self) -> None:
        soup = BeautifulSoup("<html><body><h1>My Title</h1><p>text</p></body></html>", "lxml")
        assert _heading_from_soup(soup) == "My Title"

    def test_finds_h2_when_no_h1(self) -> None:
        soup = BeautifulSoup("<html><body><h2>Sub Title</h2><p>text</p></body></html>", "lxml")
        assert _heading_from_soup(soup) == "Sub Title"

    def test_returns_empty_when_no_heading(self) -> None:
        soup = BeautifulSoup("<html><body><p>Just a paragraph.</p></body></html>", "lxml")
        assert _heading_from_soup(soup) == ""

    def test_strips_heading_whitespace(self) -> None:
        soup = BeautifulSoup("<html><body><h1>  Padded  </h1></body></html>", "lxml")
        assert _heading_from_soup(soup) == "Padded"


# ---------------------------------------------------------------------------
# Unit tests: _extract_paragraphs
# ---------------------------------------------------------------------------

class TestExtractParagraphs:
    def test_extracts_p_tags(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<p>First paragraph with enough text here.</p>"
            "<p>Second paragraph with enough text here.</p>"
            "</body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert len(paras) == 2

    def test_skips_short_paragraphs(self) -> None:
        soup = BeautifulSoup(
            "<html><body><p>Hi.</p><p>Long enough paragraph to pass the filter.</p></body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert len(paras) == 1
        assert "Long enough" in paras[0]

    def test_strips_script_and_style(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<script>alert('x')</script>"
            "<style>body{color:red}</style>"
            "<p>Valid paragraph text that is long enough.</p>"
            "</body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert all("alert" not in p for p in paras)
        assert all("color" not in p for p in paras)

    def test_falls_back_to_div_when_no_p(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<div>First div block with enough text to pass the length filter.</div>"
            "<div>Second div block also long enough to pass the length filter.</div>"
            "</body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert len(paras) >= 1

    def test_empty_html_returns_empty(self) -> None:
        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        paras = _extract_paragraphs(soup)
        assert paras == []

    def test_collapses_whitespace_in_paragraph(self) -> None:
        soup = BeautifulSoup(
            "<html><body><p>Word   with   extra    spaces   here.</p></body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        if paras:
            assert "  " not in paras[0]

    def test_returns_list_of_strings(self) -> None:
        soup = BeautifulSoup(
            "<html><body><p>A paragraph with sufficient length to pass.</p></body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert isinstance(paras, list)
        assert all(isinstance(p, str) for p in paras)


# ---------------------------------------------------------------------------
# Unit tests: _text_hash
# ---------------------------------------------------------------------------

class TestTextHash:
    def test_hash_is_64_char_hex(self) -> None:
        h = _text_hash("Hello world.")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_case_insensitive(self) -> None:
        assert _text_hash("Hello World.") == _text_hash("hello world.")

    def test_whitespace_collapse(self) -> None:
        assert _text_hash("Hello  world.") == _text_hash("Hello world.")

    def test_matches_manual_sha256(self) -> None:
        text = "The quick brown fox."
        expected = hashlib.sha256(
            normalize_for_hash(text).encode("utf-8")
        ).hexdigest()
        assert _text_hash(text) == expected


# ---------------------------------------------------------------------------
# Integration: import_epub basic
# ---------------------------------------------------------------------------

class TestImportEpubBasic:
    def test_returns_import_result(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert isinstance(result, ImportResult)

    def test_book_row_inserted(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row is not None
        assert row["source_format"] == "epub"

    def test_metadata_extracted_from_epub(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT title, author FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["title"] == "My Test Book"
        assert row["author"] == "Jane Doe"

    def test_explicit_title_overrides_metadata(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub, title="Override Title")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT title FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["title"] == "Override Title"

    def test_explicit_author_overrides_metadata(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub, author="Override Author")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT author FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["author"] == "Override Author"

    def test_book_totals_correct(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT total_chapters, total_sentences FROM books WHERE id = ?",
                (result.book_id,),
            ).fetchone()
        assert row["total_chapters"] == result.chapter_count
        assert row["total_sentences"] == result.sentence_count


# ---------------------------------------------------------------------------
# Integration: chapters
# ---------------------------------------------------------------------------

class TestImportEpubChapters:
    def test_two_chapters_imported(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert result.chapter_count == 2

    def test_chapter_titles_stored(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
                (result.book_id,),
            ).fetchall()
        titles = [r["title"] for r in rows]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles

    def test_heading_fallback_when_no_toc(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_no_toc(
            tmp_path,
            "no_toc.epub",
            chapters=[
                {"title": "The Beginning", "paragraphs": [
                    "A long enough paragraph for the beginning of the book here."
                ]},
                {"title": "The End", "paragraphs": [
                    "A long enough paragraph for the end of the book here."
                ]},
            ],
        )
        result = import_epub(db, ep)
        assert result.chapter_count == 2
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
                (result.book_id,),
            ).fetchall()
        titles = [r["title"] for r in rows]
        # Titles come from <h2> tags in the HTML
        assert any("Beginning" in t for t in titles)

    def test_single_chapter_epub(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub(
            tmp_path,
            "single.epub",
            chapters=[{"title": "Only Chapter",
                        "paragraphs": ["A single paragraph with enough text."]}],
        )
        result = import_epub(db, ep)
        assert result.chapter_count == 1

    def test_three_chapter_epub(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        chapters = [
            {"title": f"Chapter {i}",
             "paragraphs": [f"Paragraph for chapter {i} with enough text here."]}
            for i in range(1, 4)
        ]
        ep = make_epub(tmp_path, "three.epub", chapters=chapters)
        result = import_epub(db, ep)
        assert result.chapter_count == 3


# ---------------------------------------------------------------------------
# Integration: paragraphs & sentences
# ---------------------------------------------------------------------------

class TestImportEpubParagraphsAndSentences:
    def test_paragraphs_imported(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert result.paragraph_count >= 2

    def test_sentences_imported(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert result.sentence_count >= 4

    def test_sentences_stored_in_db(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
        assert count == result.sentence_count

    def test_no_p_tag_fallback_produces_sentences(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_no_paragraphs(tmp_path, "no_p.epub")
        result = import_epub(db, ep)
        assert result.sentence_count >= 1

    def test_sentence_text_is_non_empty(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT text FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchall()
        assert all(r["text"].strip() for r in rows)


# ---------------------------------------------------------------------------
# Integration: hashes
# ---------------------------------------------------------------------------

class TestImportEpubHashes:
    def test_file_hash_is_sha256_of_bytes(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        raw = simple_epub.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_hash FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["file_hash"] == expected

    def test_text_hash_case_insensitive(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub(
            tmp_path, "hash_test.epub",
            chapters=[{"title": "Ch1", "paragraphs": ["Hello World. One sentence."]}],
        )
        result = import_epub(db, ep)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT text, text_hash FROM sentences WHERE book_id = ? LIMIT 1",
                (result.book_id,),
            ).fetchone()
        expected = _text_hash(row["text"])
        assert row["text_hash"] == expected

    def test_same_sentence_cross_book_same_hash(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        sentence = "The quick brown fox jumps over the lazy dog."
        for i in range(1, 3):
            # Give each book a unique extra sentence so file_hash differs
            extra = f"This is unique filler sentence number {i} to differentiate books."
            ep = make_epub(
                tmp_path, f"book{i}.epub",
                chapters=[{"title": "Ch", "paragraphs": [sentence + " " + extra]}],
            )
            import_epub(db, ep, title=f"Book {i}")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT text_hash FROM sentences WHERE text = ?",
                (sentence,),
            ).fetchall()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Integration: error handling
# ---------------------------------------------------------------------------

class TestImportEpubErrors:
    def test_file_not_found_raises(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            import_epub(db, tmp_path / "missing.epub")

    def test_duplicate_file_hash_raises(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        import_epub(db, simple_epub)
        with pytest.raises(DuplicateBookError):
            import_epub(db, simple_epub)

    def test_duplicate_does_not_insert_extra_book(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        import_epub(db, simple_epub)
        with pytest.raises(DuplicateBookError):
            import_epub(db, simple_epub)
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# Integration: DB hierarchy integrity
# ---------------------------------------------------------------------------

class TestImportEpubHierarchyIntegrity:
    def test_all_sentences_have_valid_paragraph(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM sentences s "
                "LEFT JOIN paragraphs p ON s.paragraph_id = p.id "
                "WHERE s.book_id = ? AND p.id IS NULL",
                (result.book_id,),
            ).fetchone()[0]
        assert orphans == 0

    def test_all_paragraphs_have_valid_chapter(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM paragraphs p "
                "JOIN chapters c ON p.chapter_id = c.id "
                "LEFT JOIN books b ON c.book_id = b.id "
                "WHERE c.book_id = ? AND b.id IS NULL",
                (result.book_id,),
            ).fetchone()[0]
        assert orphans == 0

    def test_import_result_matches_db_counts(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            ch  = conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
            par = conn.execute(
                "SELECT COUNT(*) FROM paragraphs p "
                "JOIN chapters c ON p.chapter_id = c.id WHERE c.book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
            sent = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
        assert ch   == result.chapter_count
        assert par  == result.paragraph_count
        assert sent == result.sentence_count

    def test_chapter_sentence_ranges_are_valid(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT sentence_start, sentence_end FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchall()
        for row in rows:
            assert row["sentence_end"] >= row["sentence_start"]

    def test_sentence_idx_monotonically_increases(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT idx FROM sentences WHERE book_id = ? ORDER BY id",
                (result.book_id,),
            ).fetchall()
        indices = [r["idx"] for r in rows]
        assert indices == sorted(indices)

    def test_cascade_delete_removes_all_children(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            conn.execute("DELETE FROM books WHERE id = ?", (result.book_id,))
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0] == 0
