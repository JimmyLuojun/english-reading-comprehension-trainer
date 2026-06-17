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
    _find_phrase_reanchor_sentence_id,
    _find_word_reanchor_sentence_id,
    _normalize_phrase_text,
    _sql_placeholders,
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
    assert _fetch_book(db, result.book_id)["author"] == "Author"
    assert _fetch_book(db, 999) is None
    assert [chapter["idx"] for chapter in chapters] == [1, 2]
    assert _default_read_idx(db, result.book_id) == 1
    assert _fetch_chapter_by_idx(db, result.book_id, 2)["title"] == "Chapter 2"

    adjacent = _fetch_adjacent_chapters(db, result.book_id, 1)
    assert adjacent["previous"] is None
    assert adjacent["next"]["idx"] == 2


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
