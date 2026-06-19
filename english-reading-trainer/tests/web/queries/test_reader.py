"""Tests for reader page query helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.ai_response_cache import compute_content_hash
from app.cards.sentence_card_service import (
    create_sentence_card,
    save_sentence_structure,
    save_sentence_translation,
)
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
    create_sentence_card(db, sentence_id, user_note="先找主谓", user_translation="一句话。")

    sentences = _fetch_chapter_sentences(db, chapter_id)
    blocks = _fetch_chapter_blocks(db, chapter_id)

    assert sentences[0]["has_card"] == 1
    assert sentences[0]["user_translation"] == "一句话。"
    assert sentences[0]["user_note"] == "先找主谓"
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


def test_reader_query_marks_analysis_stale_when_translation_changes(
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
        sentence = conn.execute(
            "SELECT id, text FROM sentences WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()
    card_id = create_sentence_card(db, sentence["id"], user_translation="旧译文。")
    old_hash = compute_content_hash(sentence["text"], "", "旧译文。")
    with db.get_connection() as conn:
        cache_id = conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES (?, 'v3', 'manual', '{}', 1, '2026-06-19T00:00:00+00:00')""",
            (old_hash,),
        ).lastrowid
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    save_sentence_translation(db, sentence["id"], "新译文。")

    sentences = _fetch_chapter_sentences(db, chapter_id)

    assert sentences[0]["has_analysis"] == 1
    assert sentences[0]["analysis_is_stale"] == 1
    assert sentences[0]["ai_analysis_id"] == cache_id


def test_reader_query_marks_analysis_stale_when_structure_changes(
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
        sentence = conn.execute(
            "SELECT id, text FROM sentences WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()
    card_id = create_sentence_card(db, sentence["id"])
    old_hash = compute_content_hash(sentence["text"], "", None)
    with db.get_connection() as conn:
        cache_id = conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES (?, 'v3', 'manual', '{}', 1, '2026-06-19T00:00:00+00:00')""",
            (old_hash,),
        ).lastrowid
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    save_sentence_structure(db, sentence["id"], "主干：One sentence")

    sentences = _fetch_chapter_sentences(db, chapter_id)

    assert sentences[0]["has_analysis"] == 1
    assert sentences[0]["analysis_is_stale"] == 1
    assert sentences[0]["user_structure"] == "主干：One sentence"


def test_asset_storage_path_stays_under_assets_root(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)

    path = _asset_storage_path(db, "books/1/image.png")

    assert path == (tmp_path / "assets" / "books" / "1" / "image.png").resolve()
    with pytest.raises(ValueError):
        _asset_storage_path(db, "../escape.png")
    with pytest.raises(ValueError):
        _asset_storage_path(db, str(tmp_path / "absolute.png"))
