"""AI analysis payload query helpers."""

from __future__ import annotations

import json
from typing import Any

from app.ai.ai_response_cache import compute_content_hash
from app.cards.similar_card_finder import (
    SimilarSentenceMistake,
    find_similar_sentence_mistakes,
)
from app.db_connection import DatabaseConnection
from app.web.config import (
    _DEFAULT_SENTENCE_PROMPT_VERSION,
    _DEFAULT_WORD_PROMPT_VERSION,
    _DIAGNOSE_SENTENCE_PROMPT,
    _PREDICT_SENTENCE_PROMPT,
    _WORD_ANALYSIS_PROMPT,
)


def _fetch_sentence_for_analysis(
    db: DatabaseConnection,
    sentence_id: int,
) -> dict[str, Any]:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT s.id, s.text,
                      COALESCE(sc.user_translation, '') AS user_translation,
                      COALESCE(sc.user_note, '') AS user_note,
                      COALESCE(sc.user_structure, '') AS user_structure
                 FROM sentences s
                 LEFT JOIN sentence_cards sc
                   ON sc.sentence_id = s.id
                WHERE s.id = ?""",
            (sentence_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Sentence id={sentence_id} not found.")
    return dict(row)


def _fetch_sentence_analysis_payload(
    db: DatabaseConnection,
    sentence_id: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT s.text, sc.id AS card_id, sc.user_translation, sc.user_note,
                      sc.user_structure,
                      ac.id AS cache_id, ac.content_hash, ac.prompt_version, ac.model,
                      ac.response_json, ac.is_valid, ac.created_at,
                      ac.input_translation, ac.input_structure
                 FROM sentences s
                 JOIN sentence_cards sc
                   ON sc.sentence_id = s.id AND sc.archived_at IS NULL
                 JOIN ai_cache ac
                   ON ac.id = sc.ai_analysis_id
                WHERE s.id = ? AND ac.is_valid = 1""",
            (sentence_id,),
        ).fetchone()
    if row is None:
        return None

    analysis = json.loads(row["response_json"])
    active_version = _active_sentence_prompt_version(
        db,
        row["user_translation"] or None,
    )
    current_content_hash = compute_content_hash(
        row["text"] or "",
        "",
        row["user_translation"] or None,
        row["user_structure"] or None,
    )
    similar_mistakes = [
        _serialize_similar_mistake(item)
        for item in find_similar_sentence_mistakes(db, row["card_id"])
    ]
    return {
        "ok": True,
        "sentence_id": sentence_id,
        "card_id": row["card_id"],
        "cache_id": row["cache_id"],
        "user_translation": row["user_translation"] or "",
        "analyzed_translation": row["input_translation"] or "",
        "user_note": row["user_note"] or "",
        "user_structure": row["user_structure"] or "",
        "analyzed_structure": row["input_structure"] or "",
        "prompt_version": row["prompt_version"],
        "active_prompt_version": active_version,
        "model": row["model"],
        "created_at": row["created_at"],
        "is_stale": (
            row["prompt_version"] != active_version
            or row["content_hash"] != current_content_hash
        ),
        "from_cache": True,
        "analysis": analysis,
        "similar_mistakes": similar_mistakes,
    }


def _fetch_word_analysis_payload(
    db: DatabaseConnection,
    card_id: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT wc.id AS card_id, wc.surface_form, wc.lemma,
                      wc.first_sentence_id,
                      ac.id AS cache_id, ac.prompt_version, ac.model,
                      ac.response_json, ac.created_at
                 FROM word_cards wc
                 JOIN ai_cache ac ON ac.id = wc.ai_analysis_id
                WHERE wc.id = ? AND wc.archived_at IS NULL AND ac.is_valid = 1""",
            (card_id,),
        ).fetchone()
    if row is None:
        return None
    active_version = _active_word_prompt_version(db)
    return {
        "ok": True,
        "card_id": row["card_id"],
        "sentence_id": row["first_sentence_id"],
        "surface_form": row["surface_form"],
        "lemma": row["lemma"],
        "cache_id": row["cache_id"],
        "prompt_version": row["prompt_version"],
        "active_prompt_version": active_version,
        "model": row["model"],
        "created_at": row["created_at"],
        "is_stale": row["prompt_version"] != active_version,
        "from_cache": True,
        "analysis": json.loads(row["response_json"]),
    }


def _update_word_card_analysis_id(
    db: DatabaseConnection,
    card_id: int,
    cache_id: int,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )


def _serialize_similar_mistake(item: SimilarSentenceMistake) -> dict[str, Any]:
    return {
        "card_id": item.card_id,
        "sentence_id": item.sentence_id,
        "match_layer": item.match_layer,
        "score": item.score,
        "shared_error_codes": list(item.shared_error_codes),
        "sentence_text": item.sentence_text,
        "user_translation": item.user_translation,
        "diagnosis_evidence": list(item.diagnosis_evidence),
        "confidence": item.confidence,
    }


def _fetch_cache_metadata(
    db: DatabaseConnection,
    cache_id: int,
) -> dict[str, str]:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT prompt_version, model FROM ai_cache WHERE id = ?",
            (cache_id,),
        ).fetchone()
    return dict(row) if row else {}

def _active_sentence_prompt_version(
    db: DatabaseConnection,
    user_translation: str | None,
) -> str:
    prompt_name = (
        _DIAGNOSE_SENTENCE_PROMPT
        if user_translation and user_translation.strip()
        else _PREDICT_SENTENCE_PROMPT
    )
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT version
                 FROM prompt_versions
                WHERE name = ? AND is_active = 1
                ORDER BY id DESC LIMIT 1""",
            (prompt_name,),
        ).fetchone()
    return row["version"] if row else _DEFAULT_SENTENCE_PROMPT_VERSION

def _active_word_prompt_version(db: DatabaseConnection) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT version
                 FROM prompt_versions
                WHERE name = ? AND is_active = 1
                ORDER BY id DESC LIMIT 1""",
            (_WORD_ANALYSIS_PROMPT,),
        ).fetchone()
    return row["version"] if row else _DEFAULT_WORD_PROMPT_VERSION
