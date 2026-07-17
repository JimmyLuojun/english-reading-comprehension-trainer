"""Tests for book and chapter query helpers."""

from __future__ import annotations

from pathlib import Path

from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.importers.txt_importer import import_txt
from app.web.queries.books import (
    _default_read_idx,
    _fetch_adjacent_chapters,
    _fetch_book,
    _fetch_books,
    _fetch_chapter_by_idx,
    _fetch_chapters,
    _fetch_library_tags,
    _find_reanchor_sentence_id,
    _find_phrase_reanchor_sentence_id,
    _find_word_reanchor_sentence_id,
    _normalize_phrase_text,
    _phrase_card_terms,
    _sql_placeholders,
    _update_library_item,
    _word_card_terms,
    _word_tokens,
)

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _db(tmp_path: Path) -> DatabaseConnection:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    return db


def test_book_and_chapter_queries_return_expected_shapes(tmp_path: Path) -> None:
    db = _db(tmp_path)
    source = tmp_path / "book.txt"
    source.write_text(
        "Chapter 1\nFirst sentence.\n\nChapter 2\nSecond sentence.",
        encoding="utf-8",
    )
    result = import_txt(db, source, title="Book", author="Author")

    books = _fetch_books(db)
    chapters = _fetch_chapters(db, result.book_id)

    assert books[0]["title"] == "Book"
    assert books[0]["content_kind"] == "unclassified"
    assert books[0]["library_status"] == "inbox"
    assert books[0]["tags"] == ""
    assert _fetch_book(db, result.book_id)["author"] == "Author"
    assert _fetch_book(db, 999) is None
    assert [chapter["idx"] for chapter in chapters] == [1, 2]
    assert _default_read_idx(db, result.book_id) == 1
    assert _fetch_chapter_by_idx(db, result.book_id, 2)["title"] == "Chapter 2"

    adjacent = _fetch_adjacent_chapters(db, result.book_id, 1)
    assert adjacent["previous"] is None
    assert adjacent["next"]["idx"] == 2

    assert _update_library_item(
        db,
        result.book_id,
        title="Updated Article",
        author="Writer",
        content_kind="article",
        library_status="reading",
        tags=["Trade", " siemens ", "trade", ""],
    )
    updated = _fetch_book(db, result.book_id)
    assert updated["title"] == "Updated Article"
    assert updated["content_kind"] == "article"
    assert updated["library_status"] == "reading"
    assert set(updated["tags"].split(", ")) == {"Trade", "siemens"}
    assert _fetch_library_tags(db) == ["siemens", "Trade"]
    assert [row["id"] for row in _fetch_books(db, content_kind="article")] == [
        result.book_id
    ]
    assert [row["id"] for row in _fetch_books(db, library_status="reading")] == [
        result.book_id
    ]
    assert [row["id"] for row in _fetch_books(db, tag="TRADE")] == [result.book_id]
    assert _fetch_books(db, tag="missing") == []


def test_update_library_item_validates_fields_and_missing_item(tmp_path: Path) -> None:
    db = _db(tmp_path)

    assert not _update_library_item(
        db,
        999,
        title="Missing",
        author="",
        content_kind="book",
        library_status="inbox",
        tags=[],
    )
    for values, message in (
        ({"title": "", "content_kind": "book", "library_status": "inbox"}, "Title"),
        (
            {"title": "Item", "content_kind": "paragraph", "library_status": "inbox"},
            "content type",
        ),
        (
            {"title": "Item", "content_kind": "book", "library_status": "done"},
            "library status",
        ),
    ):
        try:
            _update_library_item(
                db,
                999,
                author="",
                tags=[],
                **values,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    try:
        _update_library_item(
            db,
            999,
            title="Item",
            author="",
            content_kind="book",
            library_status="inbox",
            tags=["x" * 61],
        )
    except ValueError as exc:
        assert "60 characters" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_reanchor_helpers_match_words_and_phrases() -> None:
    candidates = [
        {"id": 10, "text": "The black cat sleeps."},
        {"id": 11, "text": "A long term memory rule."},
    ]

    assert (
        _find_word_reanchor_sentence_id(
            {
                "surface_form": "Cat",
                "lemma": "cat",
                "lexical_type": LexicalType.WORD.value,
            },
            candidates,
        )
        == 10
    )
    assert (
        _find_phrase_reanchor_sentence_id(
            {
                "surface_form": "long term",
                "lemma": "long term",
                "lexical_type": LexicalType.PHRASE.value,
            },
            candidates,
        )
        == 11
    )
    assert _word_tokens("Cat's cradle, cat.") == ["cat's", "cradle", "cat"]
    assert _normalize_phrase_text(" long   term ") == "long term"
    assert _sql_placeholders([1, 2, 3]) == "?,?,?"


def test_reanchor_helpers_return_none_when_terms_are_empty() -> None:
    candidates = [{"id": 10, "text": "The black cat sleeps."}]

    assert _find_word_reanchor_sentence_id({"surface_form": "", "lemma": ""}, candidates) is None
    assert _find_phrase_reanchor_sentence_id({"surface_form": "", "lemma": ""}, candidates) is None
    assert _find_reanchor_sentence_id(
        {
            "surface_form": "black cat",
            "lemma": "",
            "lexical_type": LexicalType.PHRASE.value,
        },
        candidates,
    ) == 10
    assert _word_card_terms({"surface_form": "Cat", "lemma": "feline"}) == {
        "cat",
        "feline",
    }
    assert _phrase_card_terms({"surface_form": "Long Term", "lemma": "long term"}) == [
        "long term"
    ]


def test_default_read_idx_falls_back_to_first_section(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with db.get_connection() as conn:
        book_id = conn.execute(
            """INSERT INTO books
               (title, author, source_format, file_hash, imported_at)
               VALUES ('Appendix Book', '', 'txt', 'appendix-hash', '2026-01-01')"""
        ).lastrowid
        conn.execute(
            """INSERT INTO chapters
               (book_id, idx, title, sentence_start, sentence_end, section_kind)
               VALUES (?, 7, 'Appendix A', 0, 0, 'appendix')""",
            (book_id,),
        )

    assert _default_read_idx(db, book_id) == 7
    assert _default_read_idx(db, 99999) is None
