"""Stable word senses and occurrence-specific analysis assignments."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db_connection import DatabaseConnection

VALID_RESOLUTION_STATUSES = frozenset({"matched", "new", "uncertain", "manual"})


def list_word_senses(
    db: DatabaseConnection,
    card_id: int,
) -> list[dict[str, Any]]:
    """Return every active meaning saved under a lemma-level word card."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT ws.id, ws.card_id, ws.meaning_en, ws.meaning_zh, ws.pos,
                      ws.representative_analysis_id, ws.created_at, ws.updated_at,
                      ac.response_json AS representative_response_json,
                      source.id AS representative_source_id,
                      sentence.id AS representative_sentence_id,
                      sentence.text AS representative_sentence,
                      book.id AS representative_book_id,
                      book.title AS representative_book_title
                 FROM word_senses ws
                 LEFT JOIN ai_cache ac
                   ON ac.id = ws.representative_analysis_id AND ac.is_valid = 1
                 LEFT JOIN word_card_sources source
                   ON source.id = (
                       SELECT candidate.id
                         FROM word_card_sources candidate
                        WHERE candidate.sense_id = ws.id
                        ORDER BY candidate.is_primary DESC, candidate.id
                        LIMIT 1
                   )
                 LEFT JOIN sentences sentence ON sentence.id = source.sentence_id
                 LEFT JOIN books book ON book.id = sentence.book_id
                WHERE ws.card_id = ?
                ORDER BY ws.id""",
            (card_id,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw = item.pop("representative_response_json", None)
        item["analysis"] = json.loads(raw) if raw else None
        result.append(item)
    return result


def get_word_source(
    db: DatabaseConnection,
    source_id: int,
) -> dict[str, Any] | None:
    """Return one exact occurrence with its assigned sense and analysis."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT wcs.*, s.text AS sentence_text, s.book_id,
                      b.title AS book_title,
                      ac.response_json AS context_response_json,
                      ac.prompt_version AS context_prompt_version,
                      ac.model AS context_model,
                      ac.created_at AS context_created_at
                 FROM word_card_sources wcs
                 JOIN sentences s ON s.id = wcs.sentence_id
                 JOIN books b ON b.id = s.book_id
                 LEFT JOIN ai_cache ac
                   ON ac.id = wcs.context_analysis_id AND ac.is_valid = 1
                WHERE wcs.id = ?""",
            (source_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    raw = result.pop("context_response_json", None)
    result["analysis"] = json.loads(raw) if raw else None
    return result


def create_word_sense(
    db: DatabaseConnection,
    card_id: int,
    analysis_id: int,
    analysis: dict[str, Any],
) -> int:
    """Create a stable canonical meaning from a validated contextual analysis."""
    meaning_en = str(analysis.get("meaning_in_context") or "").strip()
    if not meaning_en:
        raise ValueError("A word sense requires meaning_in_context.")
    now = _utcnow()
    with db.get_connection() as conn:
        if conn.execute(
            "SELECT 1 FROM word_cards WHERE id = ? AND archived_at IS NULL",
            (card_id,),
        ).fetchone() is None:
            raise ValueError("Word card not found.")
        if conn.execute(
            "SELECT 1 FROM ai_cache WHERE id = ? AND is_valid = 1",
            (analysis_id,),
        ).fetchone() is None:
            raise ValueError("Valid word analysis not found.")
        sense_id = conn.execute(
            """INSERT INTO word_senses
               (card_id, meaning_en, meaning_zh, pos,
                representative_analysis_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                card_id,
                meaning_en,
                str(analysis.get("chinese_meaning") or "").strip(),
                str(analysis.get("pos") or "").strip(),
                analysis_id,
                now,
                now,
            ),
        ).lastrowid
    return int(sense_id)


def record_source_analysis(
    db: DatabaseConnection,
    source_id: int,
    analysis_id: int,
    *,
    status: str = "uncertain",
    confidence: float | None = None,
) -> None:
    """Attach current-context analysis while leaving sense choice reversible."""
    _validate_status(status)
    _validate_confidence(confidence)
    with db.get_connection() as conn:
        if conn.execute(
            "SELECT 1 FROM word_card_sources WHERE id = ?",
            (source_id,),
        ).fetchone() is None:
            raise ValueError("Word source not found.")
        if conn.execute(
            "SELECT 1 FROM ai_cache WHERE id = ? AND is_valid = 1",
            (analysis_id,),
        ).fetchone() is None:
            raise ValueError("Valid word analysis not found.")
        conn.execute(
            """UPDATE word_card_sources
                  SET context_analysis_id = ?,
                      resolution_status = ?,
                      resolution_confidence = ?
                WHERE id = ?""",
            (analysis_id, status, confidence, source_id),
        )


def assign_source_sense(
    db: DatabaseConnection,
    source_id: int,
    sense_id: int,
    *,
    status: str,
    confidence: float | None = None,
) -> None:
    """Assign an occurrence to a sense belonging to the same word card."""
    _validate_status(status)
    _validate_confidence(confidence)
    with db.get_connection() as conn:
        source = conn.execute(
            "SELECT card_id FROM word_card_sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        if source is None:
            raise ValueError("Word source not found.")
        sense = conn.execute(
            "SELECT card_id FROM word_senses WHERE id = ?",
            (sense_id,),
        ).fetchone()
        if sense is None or int(sense["card_id"]) != int(source["card_id"]):
            raise ValueError("Word sense does not belong to this card.")
        conn.execute(
            """UPDATE word_card_sources
                  SET sense_id = ?,
                      resolution_status = ?,
                      resolution_confidence = ?
                WHERE id = ?""",
            (sense_id, status, confidence, source_id),
        )


def create_and_assign_source_sense(
    db: DatabaseConnection,
    source_id: int,
    *,
    status: str = "new",
    confidence: float | None = None,
) -> int:
    """Promote the source's saved contextual analysis into a new stable sense."""
    _validate_status(status)
    source = get_word_source(db, source_id)
    if source is None:
        raise ValueError("Word source not found.")
    analysis_id = source.get("context_analysis_id")
    analysis = source.get("analysis")
    if not analysis_id or not isinstance(analysis, dict):
        raise ValueError("Analyze this occurrence before creating a new meaning.")
    sense_id = create_word_sense(
        db,
        int(source["card_id"]),
        int(analysis_id),
        analysis,
    )
    assign_source_sense(
        db,
        source_id,
        sense_id,
        status=status,
        confidence=confidence,
    )
    return sense_id


def existing_senses_prompt_text(
    db: DatabaseConnection,
    card_id: int,
) -> str:
    """Render compact, ID-addressable candidates for the AI prompt."""
    senses = list_word_senses(db, card_id)
    if not senses:
        return "(none — this analysis will create the first saved meaning)"
    lines = []
    for sense in senses:
        label = f"SENSE {sense['id']}: {sense['meaning_en']}"
        details = [
            str(sense.get("meaning_zh") or "").strip(),
            str(sense.get("pos") or "").strip(),
        ]
        suffix = " | ".join(value for value in details if value)
        lines.append(f"- {label}" + (f" | {suffix}" if suffix else ""))
    return "\n".join(lines)


def _validate_status(status: str) -> None:
    if status not in VALID_RESOLUTION_STATUSES:
        raise ValueError(f"Invalid word sense resolution status: {status}")


def _validate_confidence(confidence: float | None) -> None:
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError("Word sense confidence must be between 0 and 1.")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
