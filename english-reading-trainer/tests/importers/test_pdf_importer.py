"""Tests for app.importers.pdf_importer."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.importers.pdf_importer import calculate_pdf_file_hash, import_pdf
from app.importers.txt_importer import DuplicateBookError
from tests.importers.pdf_builder import (
    make_chapter_heading_pdf,
    make_empty_pdf,
    make_nonprose_text_pdf,
    make_text_pdf,
    make_vector_figure_pdf,
)


MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


def _sentences_for_book(db: DatabaseConnection, book_id: int) -> list[str]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT text FROM sentences WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()
    return [row["text"] for row in rows]


def test_calculate_pdf_file_hash_reads_file(tmp_path: Path) -> None:
    pdf_path = make_text_pdf(tmp_path)

    assert calculate_pdf_file_hash(pdf_path) == calculate_pdf_file_hash(pdf_path)


def test_import_pdf_inserts_standard_reader_hierarchy(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_text_pdf(
        tmp_path,
        title="Metadata PDF",
        author="Metadata Author",
        pages=[
            [
                "The first imported PDF sentence is readable.",
                "The second imported PDF sentence is useful for training.",
            ],
            ["Another page continues the same imported book."],
        ],
    )

    result = import_pdf(db, pdf_path)

    assert result.book_id > 0
    assert result.chapter_count == 1
    assert result.paragraph_count >= 1
    assert result.sentence_count >= 3
    with db.get_connection() as conn:
        book = conn.execute(
            "SELECT title, author, source_format FROM books WHERE id = ?",
            (result.book_id,),
        ).fetchone()
        blocks = conn.execute(
            "SELECT kind, paragraph_id FROM chapter_blocks WHERE book_id = ?",
            (result.book_id,),
        ).fetchall()
    assert book["title"] == "Metadata PDF"
    assert book["author"] == "Metadata Author"
    assert book["source_format"] == "pdf"
    assert {row["kind"] for row in blocks} == {"prose"}
    assert all(row["paragraph_id"] is not None for row in blocks)


def test_import_pdf_filters_repeated_header_footer(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_text_pdf(
        tmp_path,
        header="CONFIDENTIAL HEADER",
        footer="Page 1",
        pages=[["The body sentence should remain after filtering."]],
    )

    result = import_pdf(db, pdf_path, title="Filtered")

    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "body sentence should remain" in text
    assert "CONFIDENTIAL HEADER" not in text
    assert "Page 1" not in text


def test_import_pdf_merges_hyphenated_line_break(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_text_pdf(
        tmp_path,
        pages=[["The exam-", "ple demonstrates line break cleanup."]],
    )

    result = import_pdf(db, pdf_path, title="Hyphen")

    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "example demonstrates" in text
    assert "exam- ple" not in text


def test_import_pdf_chunks_long_documents_into_virtual_chapters(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pages = [[f"Page {index} has a useful sentence for reading."] for index in range(1, 12)]
    pdf_path = make_text_pdf(tmp_path, pages=pages)

    result = import_pdf(db, pdf_path, title="Long PDF")

    assert result.chapter_count == 2
    with db.get_connection() as conn:
        titles = [
            row["title"]
            for row in conn.execute(
                "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
                (result.book_id,),
            ).fetchall()
        ]
    assert titles == ["Pages 1-10", "Page 11"]


def test_import_pdf_detects_part_and_chapter_headings(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_chapter_heading_pdf(
        tmp_path,
        sections=[
            {
                "heading": "PART I: The Language of Money",
                "body": [],
            },
            {
                "heading": "Chapter One: A New Way of Learning",
                "body": ["The first real chapter sentence remains readable."],
            },
            {
                "heading": "PART II: Rich Dad's Money Secrets",
                "body": [],
            },
            {
                "heading": "Chapter Two: The New Rules for Making Money",
                "body": ["The second real chapter sentence remains readable."],
            },
        ],
    )

    result = import_pdf(db, pdf_path, title="Chaptered PDF")

    assert result.chapter_count == 2
    with db.get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT title, section_kind, chapter_number,
                          sentence_end - sentence_start AS sentences
                     FROM chapters
                    WHERE book_id = ?
                    ORDER BY idx""",
                (result.book_id,),
            ).fetchall()
        ]
        total_chapters = conn.execute(
            "SELECT total_chapters FROM books WHERE id = ?",
            (result.book_id,),
        ).fetchone()["total_chapters"]

    assert total_chapters == 2
    assert rows == [
        {
            "title": "PART I: The Language of Money",
            "section_kind": "frontmatter",
            "chapter_number": None,
            "sentences": 0,
        },
        {
            "title": "Chapter One: A New Way of Learning",
            "section_kind": "chapter",
            "chapter_number": 1,
            "sentences": 1,
        },
        {
            "title": "PART II: Rich Dad's Money Secrets",
            "section_kind": "frontmatter",
            "chapter_number": None,
            "sentences": 0,
        },
        {
            "title": "Chapter Two: The New Rules for Making Money",
            "section_kind": "chapter",
            "chapter_number": 2,
            "sentences": 1,
        },
    ]
    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "first real chapter sentence remains readable" in text
    assert "second real chapter sentence remains readable" in text
    assert "PART I" not in text
    assert "Chapter One" not in text


def test_import_pdf_preserves_vector_figure_and_deduplicates_labels(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_vector_figure_pdf(tmp_path)

    result = import_pdf(db, pdf_path, title="Vector Figure")

    assert result.paragraph_count == 2
    assert result.sentence_count == 2
    sentences = " ".join(_sentences_for_book(db, result.book_id))
    assert "Before the diagram sentence remains readable" in sentences
    assert "After the diagram sentence remains readable" in sentences
    assert "Hash Label" not in sentences
    assert "Block Label" not in sentences
    with db.get_connection() as conn:
        blocks = conn.execute(
            """SELECT cb.kind, cb.paragraph_id, cb.asset_id, cb.text,
                      ba.media_type, ba.storage_path, ba.byte_size, ba.alt_text
                 FROM chapter_blocks cb
                 LEFT JOIN book_assets ba ON ba.id = cb.asset_id
                WHERE cb.book_id = ?
                ORDER BY cb.idx""",
            (result.book_id,),
        ).fetchall()

    assert [row["kind"] for row in blocks] == ["prose", "figure", "prose"]
    figure = blocks[1]
    assert figure["paragraph_id"] is None
    assert figure["asset_id"] is not None
    assert figure["text"] == ""
    assert figure["media_type"] == "image/png"
    assert figure["byte_size"] > 0
    assert figure["alt_text"] == "PDF page 1 figure 1"
    asset_path = tmp_path / "assets" / figure["storage_path"]
    assert asset_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_import_pdf_renders_math_and_code_regions_without_sentence_pollution(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_nonprose_text_pdf(tmp_path)

    result = import_pdf(db, pdf_path, title="Non Prose")

    assert result.paragraph_count == 2
    assert result.sentence_count == 2
    sentences = " ".join(_sentences_for_book(db, result.book_id))
    assert "Before the formula sentence remains readable" in sentences
    assert "After the code sentence remains readable" in sentences
    assert "AttackerSuccessProbability" not in sentences
    assert "#include" not in sentences
    assert "p = z" not in sentences
    with db.get_connection() as conn:
        blocks = conn.execute(
            """SELECT cb.kind, cb.paragraph_id, cb.asset_id,
                      ba.media_type, ba.storage_path, ba.byte_size
                 FROM chapter_blocks cb
                 LEFT JOIN book_assets ba ON ba.id = cb.asset_id
                WHERE cb.book_id = ?
                ORDER BY cb.idx""",
            (result.book_id,),
        ).fetchall()

    assert [row["kind"] for row in blocks] == ["prose", "figure", "figure", "prose"]
    figures = [row for row in blocks if row["kind"] == "figure"]
    assert all(row["paragraph_id"] is None for row in figures)
    assert all(row["asset_id"] is not None for row in figures)
    assert all(row["media_type"] == "image/png" for row in figures)
    assert all(row["byte_size"] > 0 for row in figures)
    for figure in figures:
        assert (tmp_path / "assets" / figure["storage_path"]).read_bytes().startswith(
            b"\x89PNG\r\n\x1a\n"
        )


def test_import_pdf_duplicate_raises_duplicate_book_error(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_text_pdf(tmp_path)

    import_pdf(db, pdf_path, title="First")

    with pytest.raises(DuplicateBookError):
        import_pdf(db, pdf_path, title="Second")


def test_import_pdf_empty_text_raises_value_error(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    pdf_path = make_empty_pdf(tmp_path)

    with pytest.raises(ValueError, match="no extractable text"):
        import_pdf(db, pdf_path)


def test_import_pdf_missing_file_raises_file_not_found(db: DatabaseConnection, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_pdf(db, tmp_path / "missing.pdf")
