"""Tests for AI analysis query helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cards.sentence_card_service import create_sentence_card
from app.cards.word_card_service import create_or_update_word_card
from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.importers.txt_importer import import_txt
from app.web.queries.analysis import (
    _active_sentence_prompt_version,
    _active_word_prompt_version,
    _fetch_cache_metadata,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
    _update_word_card_analysis_id,
)

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _seed_sentence(db: DatabaseConnection, tmp_path: Path) -> int:
    source = tmp_path / "book.txt"
    source.write_text("The cat sat.", encoding="utf-8")
    book = import_txt(db, source, title="Book", author="")
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT id FROM sentences WHERE book_id = ?",
            (book.book_id,),
        ).fetchone()["id"]


def _insert_cache(db: DatabaseConnection, payload: dict[str, object]) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES ('hash', 'v1', 'model', ?, 1, '2026-06-17T00:00:00+00:00')""",
            (json.dumps(payload),),
        ).lastrowid


def test_fetch_sentence_for_analysis_and_missing_error(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)

    assert _fetch_sentence_for_analysis(db, sentence_id)["text"] == "The cat sat."
    with pytest.raises(ValueError):
        _fetch_sentence_for_analysis(db, 999)


def test_sentence_and_word_analysis_payloads(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    create_sentence_card(db, sentence_id, user_translation="猫坐着。")
    cache_id = _insert_cache(db, {"ok": True})
    with db.get_connection() as conn:
        card_id = conn.execute(
            "SELECT id FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()["id"]
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )

    sentence_payload = _fetch_sentence_analysis_payload(db, sentence_id)

    assert sentence_payload["ok"] is True
    assert sentence_payload["analysis"] == {"ok": True}
    assert _fetch_cache_metadata(db, cache_id) == {
        "prompt_version": "v1",
        "model": "model",
    }

    word_card_id, _created = create_or_update_word_card(
        db,
        sentence_id=sentence_id,
        surface_form="cat",
        lexical_type=LexicalType.WORD,
    )
    _update_word_card_analysis_id(db, word_card_id, cache_id)

    word_payload = _fetch_word_analysis_payload(db, word_card_id)

    assert word_payload["surface_form"] == "cat"
    assert word_payload["analysis"] == {"ok": True}


def test_active_prompt_versions_fallback_when_registry_empty(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)

    assert _active_sentence_prompt_version(db, None).startswith("v")
    assert _active_word_prompt_version(db).startswith("v")
