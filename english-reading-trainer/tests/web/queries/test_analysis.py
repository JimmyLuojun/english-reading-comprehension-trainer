"""Tests for AI analysis query helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.ai_response_cache import compute_content_hash
from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import (
    create_sentence_card,
    save_sentence_structure,
    save_sentence_translation,
)
from app.cards.word_card_service import create_or_update_word_card
from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.importers.txt_importer import import_txt
from app.web.queries.analysis import (
    _active_sentence_prompt_version,
    _active_word_prompt_version,
    _fetch_cache_metadata,
    _fetch_paragraph_for_logic,
    _fetch_paragraph_logic_payload,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
    _sentence_context_text,
    _update_word_card_analysis_id,
)
from app.web.queries import analysis as analysis_queries

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


def _seed_sentences(db: DatabaseConnection, tmp_path: Path, text: str) -> list[int]:
    source = tmp_path / "sentences.txt"
    source.write_text(text, encoding="utf-8")
    book = import_txt(db, source, title="Book", author="")
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY idx",
            (book.book_id,),
        ).fetchall()
    return [row["id"] for row in rows]


def _insert_cache(
    db: DatabaseConnection,
    payload: dict[str, object],
    *,
    content_hash: str = "hash",
    input_translation: str | None = None,
    input_structure: str | None = None,
) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid,
                created_at, input_translation, input_structure)
               VALUES (?, 'v1', 'model', ?, 1, '2026-06-17T00:00:00+00:00',
                       ?, ?)""",
            (content_hash, json.dumps(payload), input_translation, input_structure),
        ).lastrowid


def _diagnosed_payload(code: str, evidence: str) -> dict[str, object]:
    return {
        "subject_skeleton": "The contrast matters",
        "clauses": [
            {
                "type": "main",
                "text": "the contrast matters",
                "role": "main predication",
            }
        ],
        "modifiers": [],
        "logic_markers": [
            {"marker": "although", "function": "concession"},
        ],
        "anaphora": [],
        "simplified_en": "The contrast matters.",
        "chinese_gloss": "重点在对比关系。",
        "predicted_error_types": [],
        "diagnosis_basis": "user_translation",
        "diagnosed_error_types": [code],
        "diagnosis_evidence": [
            {"error_type": code, "evidence": evidence},
        ],
        "confidence": 0.9,
    }


def test_fetch_sentence_for_analysis_and_missing_error(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)

    assert _fetch_sentence_for_analysis(db, sentence_id)["text"] == "The cat sat."
    with pytest.raises(ValueError):
        _fetch_sentence_for_analysis(db, 999)


def test_fetch_paragraph_for_logic_returns_text_sentences_and_context(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text(
        "Previous setup.\n\nFirst claim. Second evidence.\n\nNext turn.",
        encoding="utf-8",
    )
    book = import_txt(db, source, title="Book", author="")
    with db.get_connection() as conn:
        paragraph_id = conn.execute(
            """SELECT p.id
                 FROM paragraphs p
                 JOIN sentences s ON s.paragraph_id = p.id
                WHERE s.text = ?
                LIMIT 1""",
            ("First claim.",),
        ).fetchone()["id"]

    paragraph = _fetch_paragraph_for_logic(db, paragraph_id)

    assert paragraph["book_id"] == book.book_id
    assert paragraph["text"] == "First claim. Second evidence."
    assert [row["text"] for row in paragraph["sentences"]] == [
        "First claim.",
        "Second evidence.",
    ]
    assert "Previous paragraph: Previous setup." in paragraph["context"]
    assert "Next paragraph: Next turn." in paragraph["context"]


def test_fetch_paragraph_for_logic_missing_error(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)

    with pytest.raises(ValueError, match="Paragraph id=999 not found"):
        _fetch_paragraph_for_logic(db, 999)


def test_fetch_paragraph_logic_payload_returns_saved_cache(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text(
        "Previous setup.\n\nFirst claim. Second evidence.\n\nNext turn.",
        encoding="utf-8",
    )
    import_txt(db, source, title="Book", author="")
    analysis = {
        "paragraph_main_claim": "First claim.",
        "argument_flow": [
            {
                "sentence_id": 1,
                "sentence_text": "First claim.",
                "role": "claim",
                "reason": "States the point.",
            }
        ],
    }
    with db.get_connection() as conn:
        paragraph_id = conn.execute(
            """SELECT p.id
                 FROM paragraphs p
                 JOIN sentences s ON s.paragraph_id = p.id
                WHERE s.text = ?
                LIMIT 1""",
            ("First claim.",),
        ).fetchone()["id"]
        cache_id = conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES (?, 'paragraph_logic_lens.v4', 'external-ai', ?, 1,
                       '2026-06-19T00:00:00+00:00')""",
            (
                compute_content_hash(
                    "First claim. Second evidence.",
                    "Previous paragraph: Previous setup.\n\nNext paragraph: Next turn.",
                ),
                json.dumps(analysis),
            ),
        ).lastrowid

    payload = _fetch_paragraph_logic_payload(db, paragraph_id)

    assert payload is not None
    assert payload["ok"] is True
    assert payload["paragraph_id"] == paragraph_id
    assert payload["cache_id"] == cache_id
    assert payload["prompt_version"] == "paragraph_logic_lens.v4"
    assert payload["active_prompt_version"] == "paragraph_logic_lens.v4"
    assert payload["from_cache"] is True
    assert payload["is_stale"] is False
    assert payload["paragraph_text"] == "First claim. Second evidence."
    assert [row["text"] for row in payload["sentences"]] == [
        "First claim.",
        "Second evidence.",
    ]
    assert payload["analysis"] == analysis


def test_fetch_paragraph_logic_payload_returns_none_without_cache(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text("First claim. Second evidence.", encoding="utf-8")
    import_txt(db, source, title="Book", author="")
    with db.get_connection() as conn:
        paragraph_id = conn.execute("SELECT id FROM paragraphs LIMIT 1").fetchone()["id"]

    assert _fetch_paragraph_logic_payload(db, paragraph_id) is None


def test_sentence_context_text_returns_empty_when_context_builder_fails(
    monkeypatch,
) -> None:
    def fail_context(db, sentence_id):
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(analysis_queries, "get_sentence_info", fail_context)

    assert _sentence_context_text(object(), 1) == ""


def test_fetch_sentence_for_analysis_uses_archived_translation(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    save_sentence_translation(db, sentence_id, "猫坐着。")

    sentence = _fetch_sentence_for_analysis(db, sentence_id)

    assert sentence["user_translation"] == "猫坐着。"


def test_fetch_sentence_for_analysis_includes_takeaway_note(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    save_sentence_translation(db, sentence_id, "猫坐着。", user_note="注意 sat 的状态")

    sentence = _fetch_sentence_for_analysis(db, sentence_id)

    assert sentence["user_note"] == "注意 sat 的状态"


def test_fetch_sentence_for_analysis_includes_user_structure(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    save_sentence_structure(db, sentence_id, "主干：The cat sat")

    sentence = _fetch_sentence_for_analysis(db, sentence_id)

    assert sentence["user_structure"] == "主干：The cat sat"


def test_sentence_and_word_analysis_payloads(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    create_sentence_card(db, sentence_id, user_translation="猫坐着。")
    cache_id = _insert_cache(
        db,
        {"ok": True},
        content_hash=compute_content_hash("The cat sat.", "", "猫坐着。"),
    )
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
    assert sentence_payload["user_note"] == ""
    assert sentence_payload["analyzed_translation"] == ""
    assert sentence_payload["analyzed_structure"] == ""
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


def test_sentence_analysis_payload_is_stale_when_translation_changes(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    card_id = create_sentence_card(db, sentence_id, user_translation="旧译文。")
    cache_id = _insert_cache(
        db,
        {"ok": True},
        content_hash=compute_content_hash("The cat sat.", "", "旧译文。"),
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    save_sentence_translation(db, sentence_id, "新译文。")

    sentence_payload = _fetch_sentence_analysis_payload(db, sentence_id)

    assert sentence_payload["cache_id"] == cache_id
    assert sentence_payload["is_stale"] is True
    assert sentence_payload["user_translation"] == "新译文。"


def test_sentence_analysis_payload_includes_translation_snapshot_when_changed(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    card_id = create_sentence_card(db, sentence_id, user_translation="旧译文。")
    cache_id = _insert_cache(
        db,
        {"ok": True},
        content_hash=compute_content_hash("The cat sat.", "", "旧译文。"),
        input_translation="旧译文。",
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    save_sentence_translation(db, sentence_id, "新译文。")

    sentence_payload = _fetch_sentence_analysis_payload(db, sentence_id)

    assert sentence_payload["analyzed_translation"] == "旧译文。"
    assert sentence_payload["user_translation"] == "新译文。"


def test_sentence_analysis_payload_survives_cleared_translation(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    card_id = create_sentence_card(db, sentence_id, user_translation="旧译文。")
    cache_id = _insert_cache(
        db,
        {"ok": True},
        content_hash=compute_content_hash("The cat sat.", "", "旧译文。"),
        input_translation="旧译文。",
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )

    save_sentence_translation(db, sentence_id, "")

    sentence_payload = _fetch_sentence_analysis_payload(db, sentence_id)

    assert sentence_payload["cache_id"] == cache_id
    assert sentence_payload["is_stale"] is True
    assert sentence_payload["analyzed_translation"] == "旧译文。"
    assert sentence_payload["user_translation"] == ""


def test_sentence_analysis_payload_is_stale_when_structure_changes(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    card_id = create_sentence_card(db, sentence_id)
    cache_id = _insert_cache(
        db,
        {"ok": True},
        content_hash=compute_content_hash("The cat sat.", "", None),
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    save_sentence_structure(db, sentence_id, "主干：The cat sat")

    sentence_payload = _fetch_sentence_analysis_payload(db, sentence_id)

    assert sentence_payload["cache_id"] == cache_id
    assert sentence_payload["is_stale"] is True
    assert sentence_payload["user_structure"] == "主干：The cat sat"


def test_sentence_analysis_payload_includes_structure_snapshot_when_changed(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence(db, tmp_path)
    card_id = create_sentence_card(db, sentence_id)
    cache_id = _insert_cache(
        db,
        {"ok": True},
        content_hash=compute_content_hash("The cat sat.", "", None, "旧结构。"),
        input_structure="旧结构。",
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    save_sentence_structure(db, sentence_id, "新结构。")

    sentence_payload = _fetch_sentence_analysis_payload(db, sentence_id)

    assert sentence_payload["analyzed_structure"] == "旧结构。"
    assert sentence_payload["user_structure"] == "新结构。"


def test_sentence_analysis_payload_includes_similar_translation_mistakes(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_ids = _seed_sentences(
        db,
        tmp_path,
        (
            "Although it rained, we left. "
            "While the premise sounds simple, the conclusion differs."
        ),
    )
    save_sentence_translation(db, sentence_ids[0], "我这次误读了对比。")
    save_sentence_translation(db, sentence_ids[1], "我之前也误读了对比。")
    save_sentence_analysis(
        db,
        sentence_ids[0],
        json.dumps(_diagnosed_payload("D02", "Current contrast evidence.")),
    )
    save_sentence_analysis(
        db,
        sentence_ids[1],
        json.dumps(_diagnosed_payload("D02", "Past contrast evidence.")),
    )

    payload = _fetch_sentence_analysis_payload(db, sentence_ids[0])

    assert payload is not None
    assert len(payload["similar_mistakes"]) == 1
    mistake = payload["similar_mistakes"][0]
    assert mistake["sentence_id"] == sentence_ids[1]
    assert mistake["match_layer"] == "error_tag"
    assert mistake["score"] == 0.6
    assert mistake["shared_error_codes"] == ["D02"]
    assert mistake["sentence_text"] == (
        "While the premise sounds simple, the conclusion differs."
    )
    assert mistake["user_translation"] == "我之前也误读了对比。"
    assert mistake["diagnosis_evidence"] == [
        {"error_type": "D02", "evidence": "Past contrast evidence."},
    ]
    assert mistake["confidence"] == 0.9


def test_active_prompt_versions_fallback_when_registry_empty(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)

    assert _active_sentence_prompt_version(db, None).startswith("v")
    assert _active_word_prompt_version(db).startswith("v")
