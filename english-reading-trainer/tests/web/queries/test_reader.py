"""Tests for reader page query helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cards.sentence_card_service import create_sentence_card, save_sentence_translation
from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from app.web.queries.reader import (
    _asset_storage_path,
    _fetch_active_word_cards,
    _fetch_chapter_blocks,
    _fetch_chapter_sentences,
)

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def test_reader_queries_fetch_sentences_and_blocks(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text("One sentence.", encoding="utf-8")
    book = import_txt(db, source, title="Book", author="")
    with db.get_connection() as conn:
        chapter_id = conn.execute(
            "SELECT id FROM chapters WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()["id"]
        sentence_id = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()["id"]
        paragraph_id = conn.execute(
            "SELECT paragraph_id FROM sentences WHERE id = ?",
            (sentence_id,),
        ).fetchone()["paragraph_id"]
        conn.execute(
            """INSERT INTO chapter_blocks
               (book_id, chapter_id, idx, kind, paragraph_id, text)
               VALUES (?, ?, 1, 'prose', ?, '')""",
            (book.book_id, chapter_id, paragraph_id),
        )
    create_sentence_card(db, sentence_id, user_translation="一句话。")

    sentences = _fetch_chapter_sentences(db, chapter_id)
    blocks = _fetch_chapter_blocks(db, chapter_id)

    assert sentences[0]["has_card"] == 1
    assert sentences[0]["user_translation"] == "一句话。"
    assert blocks[0]["kind"] == "prose"
    assert _fetch_active_word_cards(db) == []


def test_reader_query_preserves_archived_translation_without_active_card(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text("One sentence.", encoding="utf-8")
    book = import_txt(db, source, title="Book", author="")
    with db.get_connection() as conn:
        chapter_id = conn.execute(
            "SELECT id FROM chapters WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()["id"]
        sentence_id = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()["id"]
    save_sentence_translation(db, sentence_id, "一句话。")

    sentences = _fetch_chapter_sentences(db, chapter_id)

    assert sentences[0]["has_card"] == 0
    assert sentences[0]["user_translation"] == "一句话。"
    assert sentences[0]["has_analysis"] == 0


def test_asset_storage_path_stays_under_assets_root(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)

    path = _asset_storage_path(db, "books/1/image.png")

    assert path == (tmp_path / "assets" / "books" / "1" / "image.png").resolve()
    with pytest.raises(ValueError):
        _asset_storage_path(db, "../escape.png")
    with pytest.raises(ValueError):
        _asset_storage_path(db, str(tmp_path / "absolute.png"))
