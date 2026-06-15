"""
Save AI analysis results (from manual chat or API) into the DB.

Validates JSON against the closed schema before writing, so invalid
responses are never silently stored as card analyses.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.ai.ai_json_schemas import SENTENCE_ANALYSIS_SCHEMA, WORD_ANALYSIS_SCHEMA
from app.ai.ai_response_cache import compute_content_hash, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.db_connection import DatabaseConnection
from app.db_models import (
    LexicalType,
    MasteryState,
    SM2_DEFAULT_EF,
    SM2_INITIAL_INTERVAL_DAYS,
    SM2_INITIAL_REPETITIONS,
    VALID_ERROR_CODES,
)
from jsonschema import ValidationError


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class SaveResult:
    cache_id: int
    card_id: int | None      # None if card was not created/updated
    card_created: bool       # True if a new card was inserted
    is_valid: bool
    error: str               # non-empty if validation failed


# ---------------------------------------------------------------------------
# Sentence analysis
# ---------------------------------------------------------------------------

def save_sentence_analysis(
    db: DatabaseConnection,
    sentence_id: int,
    raw_json: str,
    model: str = "manual",
    prompt_version: str = "v1",
) -> SaveResult:
    """
    Validate *raw_json* against the sentence analysis schema and save to DB.

    - Writes to ai_cache regardless of validation result.
    - On success, creates/updates the sentence_card.ai_analysis_id.
    - Raises ValueError if sentence_id not found.
    """
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")
        sent_text = conn.execute(
            "SELECT text FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone()["text"]
        card_row = conn.execute(
            "SELECT user_translation FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()
        user_translation = card_row["user_translation"] if card_row else None

    is_valid = True
    error = ""
    data: dict = {}

    try:
        data = parse_and_validate(raw_json, SENTENCE_ANALYSIS_SCHEMA)
        response_json = json.dumps(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        is_valid = False
        error = str(exc)
        response_json = raw_json

    content_hash = compute_content_hash(sent_text, "", user_translation)
    cache_id = save_to_cache(
        db, content_hash, prompt_version, model, response_json, is_valid
    )

    card_id: int | None = None
    card_created = False

    if is_valid:
        card_id, card_created = _upsert_sentence_card(db, sentence_id, cache_id)
        _sync_sentence_card_errors(db, card_id, _sentence_error_codes(data))

    return SaveResult(
        cache_id=cache_id,
        card_id=card_id,
        card_created=card_created,
        is_valid=is_valid,
        error=error,
    )


# ---------------------------------------------------------------------------
# Word analysis
# ---------------------------------------------------------------------------

def save_word_analysis(
    db: DatabaseConnection,
    sentence_id: int,
    surface_form: str,
    raw_json: str,
    model: str = "manual",
    prompt_version: str = "v1",
) -> SaveResult:
    """
    Validate *raw_json* against the word analysis schema and save to DB.

    On success, creates/updates the word_card.ai_analysis_id and fills
    in current_meaning / pos from the analysis data.
    Raises ValueError if sentence_id not found or surface_form is empty.
    """
    if not surface_form.strip():
        raise ValueError("surface_form must not be empty.")

    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")
        sent_text = conn.execute(
            "SELECT text FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone()["text"]

    is_valid = True
    error = ""
    data: dict = {}

    try:
        data = parse_and_validate(raw_json, WORD_ANALYSIS_SCHEMA)
        response_json = json.dumps(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        is_valid = False
        error = str(exc)
        response_json = raw_json

    content_hash = compute_content_hash(
        surface_form + " | " + sent_text, ""
    )
    cache_id = save_to_cache(
        db, content_hash, prompt_version, model, response_json, is_valid
    )

    card_id: int | None = None
    card_created = False

    if is_valid:
        card_id, card_created = _upsert_word_card(
            db, sentence_id, surface_form, data, cache_id
        )

    return SaveResult(
        cache_id=cache_id,
        card_id=card_id,
        card_created=card_created,
        is_valid=is_valid,
        error=error,
    )


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------

def _upsert_sentence_card(
    db: DatabaseConnection,
    sentence_id: int,
    cache_id: int,
) -> tuple[int, bool]:
    """Create sentence card if absent; always update ai_analysis_id."""
    now = _utcnow()
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE sentence_cards
                      SET ai_analysis_id = ?,
                          archived_at = NULL
                    WHERE id = ?""",
                (cache_id, existing["id"]),
            )
            return existing["id"], False

        card_id: int = conn.execute(
            """INSERT INTO sentence_cards
               (sentence_id, created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at,
                user_note, ai_analysis_id)
               VALUES (?, ?, NULL, 0, ?, ?, ?, ?, ?, '', ?)""",
            (
                sentence_id, now,
                MasteryState.NEW.value,
                SM2_DEFAULT_EF,
                SM2_INITIAL_INTERVAL_DAYS,
                SM2_INITIAL_REPETITIONS,
                now,
                cache_id,
            ),
        ).lastrowid
    return card_id, True


def _upsert_word_card(
    db: DatabaseConnection,
    sentence_id: int,
    surface_form: str,
    data: dict,
    cache_id: int,
) -> tuple[int, bool]:
    """Create word card if absent; update meaning/pos/ai_analysis_id."""
    lemma = data.get("lemma", surface_form.lower().strip())
    meaning = data.get("meaning_in_context", "")
    pos = data.get("pos", "")
    lt = data.get("lexical_type", "word")
    now = _utcnow()

    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM word_cards WHERE lemma = ?", (lemma,)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE word_cards
                   SET current_meaning   = ?,
                       pos               = ?,
                       ai_analysis_id    = ?,
                       occurrence_count  = occurrence_count + 1,
                       archived_at       = NULL
                   WHERE id = ?""",
                (meaning, pos, cache_id, existing["id"]),
            )
            return existing["id"], False

        card_id: int = conn.execute(
            """INSERT INTO word_cards
               (lemma, surface_form, lexical_type, first_sentence_id,
                current_meaning, pos,
                created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at,
                occurrence_count, user_note, ai_analysis_id)
               VALUES (?, ?, ?, ?, ?, ?,
                       ?, NULL, 0,
                       ?, ?, ?, ?, ?,
                       1, '', ?)""",
            (
                lemma, surface_form, lt, sentence_id,
                meaning, pos,
                now,
                MasteryState.NEW.value,
                SM2_DEFAULT_EF,
                SM2_INITIAL_INTERVAL_DAYS,
                SM2_INITIAL_REPETITIONS,
                now,
                cache_id,
            ),
        ).lastrowid
    return card_id, True


def _sentence_error_codes(data: dict) -> tuple[str, ...]:
    if data.get("diagnosis_basis") == "user_translation":
        return tuple(
            code for code in data.get("diagnosed_error_types", [])
            if code in VALID_ERROR_CODES
        )
    return tuple(
        code for code in data.get("predicted_error_types", [])
        if code in VALID_ERROR_CODES
    )


def _sync_sentence_card_errors(
    db: DatabaseConnection,
    card_id: int,
    error_codes: tuple[str, ...],
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "DELETE FROM sentence_card_errors WHERE card_id = ?",
            (card_id,),
        )
        for code in error_codes:
            row = conn.execute(
                "SELECT id FROM error_types WHERE code = ?",
                (code,),
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO sentence_card_errors
                   (card_id, error_type_id)
                   VALUES (?, ?)""",
                (card_id, row["id"]),
            )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
