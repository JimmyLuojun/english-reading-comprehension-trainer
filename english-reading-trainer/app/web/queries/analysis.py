"""AI analysis payload query helpers."""

from __future__ import annotations

import json
from typing import Any

from app.ai.ai_response_cache import compute_content_hash
from app.ai.context_builder import get_sentence_info
from app.cards.similar_card_finder import (
    SimilarSentenceMistake,
    find_similar_sentence_mistakes,
)
from app.cards.word_sense_service import get_word_source, list_word_senses
from app.db_connection import DatabaseConnection
from app.web.config import (
    _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION,
    _DEFAULT_SENTENCE_PROMPT_VERSION,
    _DEFAULT_WORD_PROMPT_VERSION,
    _DIAGNOSE_SENTENCE_PROMPT,
    _PREDICT_SENTENCE_PROMPT,
    _WORD_ANALYSIS_PROMPT,
)

_PARAGRAPH_LOGIC_PROMPT_VERSION = _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION


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


def _fetch_paragraph_for_logic(
    db: DatabaseConnection,
    paragraph_id: int,
) -> dict[str, Any]:
    """Return paragraph text, ordered sentence ids, and local paragraph context."""
    with db.get_connection() as conn:
        paragraph = conn.execute(
            """SELECT p.id, p.chapter_id, p.idx, c.book_id
                 FROM paragraphs p
                 JOIN chapters c ON c.id = p.chapter_id
                WHERE p.id = ?""",
            (paragraph_id,),
        ).fetchone()
        if paragraph is None:
            raise ValueError(f"Paragraph id={paragraph_id} not found.")

        sentence_rows = conn.execute(
            """SELECT id, idx, text
                 FROM sentences
                WHERE paragraph_id = ?
                ORDER BY idx""",
            (paragraph_id,),
        ).fetchall()
        previous_rows = conn.execute(
            """SELECT s.text
                 FROM paragraphs p
                 JOIN sentences s ON s.paragraph_id = p.id
                WHERE p.chapter_id = ? AND p.idx = ?
                ORDER BY s.idx""",
            (paragraph["chapter_id"], paragraph["idx"] - 1),
        ).fetchall()
        next_rows = conn.execute(
            """SELECT s.text
                 FROM paragraphs p
                 JOIN sentences s ON s.paragraph_id = p.id
                WHERE p.chapter_id = ? AND p.idx = ?
                ORDER BY s.idx""",
            (paragraph["chapter_id"], paragraph["idx"] + 1),
        ).fetchall()

    sentences = [dict(row) for row in sentence_rows]
    paragraph_text = " ".join(str(row["text"] or "").strip() for row in sentences).strip()
    previous_text = " ".join(str(row["text"] or "").strip() for row in previous_rows).strip()
    next_text = " ".join(str(row["text"] or "").strip() for row in next_rows).strip()
    context_parts = []
    if previous_text:
        context_parts.append(f"Previous paragraph: {previous_text}")
    if next_text:
        context_parts.append(f"Next paragraph: {next_text}")
    return {
        "paragraph_id": paragraph["id"],
        "chapter_id": paragraph["chapter_id"],
        "book_id": paragraph["book_id"],
        "idx": paragraph["idx"],
        "text": paragraph_text,
        "sentences": sentences,
        "previous_text": previous_text,
        "next_text": next_text,
        "context": "\n\n".join(context_parts),
    }


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
        _sentence_context_text(db, sentence_id),
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


def _fetch_paragraph_logic_payload(
    db: DatabaseConnection,
    paragraph_id: int,
) -> dict[str, Any] | None:
    paragraph = _fetch_paragraph_for_logic(db, paragraph_id)
    current_content_hash = compute_content_hash(paragraph["text"], paragraph["context"])
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT id, prompt_version, model, response_json, created_at
                 FROM ai_cache
                WHERE content_hash = ?
                  AND prompt_version LIKE 'paragraph_logic_lens.%'
                  AND is_valid = 1
                ORDER BY CASE WHEN prompt_version = ? THEN 0 ELSE 1 END,
                         id DESC
                LIMIT 1""",
            (current_content_hash, _PARAGRAPH_LOGIC_PROMPT_VERSION),
        ).fetchone()
    if row is None:
        return None
    return {
        "ok": True,
        "paragraph_id": paragraph_id,
        "cache_id": row["id"],
        "prompt_version": row["prompt_version"],
        "active_prompt_version": _PARAGRAPH_LOGIC_PROMPT_VERSION,
        "model": row["model"],
        "created_at": row["created_at"],
        "is_stale": row["prompt_version"] != _PARAGRAPH_LOGIC_PROMPT_VERSION,
        "from_cache": True,
        "paragraph_text": paragraph["text"],
        "sentences": paragraph["sentences"],
        "context": paragraph["context"],
        "analysis": json.loads(row["response_json"]),
    }


def _fetch_word_analysis_payload(
    db: DatabaseConnection,
    card_id: int,
    source_id: int | None = None,
) -> dict[str, Any] | None:
    source = get_word_source(db, source_id) if source_id is not None else None
    if source_id is not None and (
        source is None or int(source["card_id"]) != int(card_id)
    ):
        return None
    with db.get_connection() as conn:
        if source is not None and source.get("context_analysis_id"):
            row = conn.execute(
                """SELECT wc.id AS card_id, wc.surface_form, wc.lemma,
                          wcs.sentence_id,
                          ac.id AS cache_id, ac.prompt_version, ac.model,
                          ac.response_json, ac.created_at
                     FROM word_cards wc
                     JOIN word_card_sources wcs
                       ON wcs.id = ? AND wcs.card_id = wc.id
                     JOIN ai_cache ac
                       ON ac.id = wcs.context_analysis_id AND ac.is_valid = 1
                    WHERE wc.id = ? AND wc.archived_at IS NULL""",
                (source_id, card_id),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT wc.id AS card_id, wc.surface_form, wc.lemma,
                          wc.first_sentence_id AS sentence_id,
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
    analysis = json.loads(row["response_json"])
    senses = list_word_senses(db, card_id)
    sense_ids = {int(item["id"]) for item in senses}
    resolution = analysis.get("sense_resolution")
    if isinstance(resolution, dict):
        matched_id = resolution.get("matched_sense_id")
        if matched_id is not None and int(matched_id) not in sense_ids:
            resolution = {
                **resolution,
                "decision": "uncertain",
                "matched_sense_id": None,
                "reason": "The suggested saved meaning is no longer available.",
            }
    return {
        "ok": True,
        "card_id": row["card_id"],
        "source_id": source_id,
        "source": source,
        "sentence_id": (
            source["sentence_id"] if source is not None else row["sentence_id"]
        ),
        "surface_form": row["surface_form"],
        "lemma": row["lemma"],
        "cache_id": row["cache_id"],
        "prompt_version": row["prompt_version"],
        "active_prompt_version": active_version,
        "model": row["model"],
        "created_at": row["created_at"],
        "is_stale": row["prompt_version"] != active_version,
        "from_cache": True,
        "analysis": analysis,
        "senses": senses,
        "current_sense_id": source.get("sense_id") if source else None,
        "sense_resolution": resolution,
        "sense_confirmation_required": bool(
            source
            and senses
            and isinstance(resolution, dict)
            and source.get("resolution_status") == "uncertain"
        ),
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

def _sentence_context_text(db: DatabaseConnection, sentence_id: int) -> str:
    try:
        return str(get_sentence_info(db, sentence_id).get("context") or "")
    except Exception:
        return ""

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
