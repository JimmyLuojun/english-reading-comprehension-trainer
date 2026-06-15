"""
Word card CRUD — create, fetch, list, increment occurrence.

The `lemma` field is the deduplication key (UNIQUE constraint).
On first encounter → create card.
On repeat encounter → increment occurrence_count only.

Lemma normalisation in this step: surface_form.lower().strip().
The English lemmatizer (step 7) will refine this to true lemmas.
"""

from datetime import datetime, timezone
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import (
    LexicalType,
    MasteryState,
    SM2_DEFAULT_EF,
    SM2_INITIAL_INTERVAL_DAYS,
    SM2_INITIAL_REPETITIONS,
)


class WordCardNotFoundError(ValueError):
    """Raised when an active word card cannot be found."""


def _default_lemma(surface_form: str) -> str:
    """Temporary lemma: lowercased + stripped surface form."""
    return surface_form.lower().strip()


def create_or_update_word_card(
    db: DatabaseConnection,
    sentence_id: int,
    surface_form: str,
    lexical_type: LexicalType = LexicalType.WORD,
    user_note: str = "",
) -> tuple[int, bool]:
    """
    Create a new word card or increment occurrence_count on an existing one.

    Returns (card_id, created):
      created=True  → new card was inserted
      created=False → existing card's occurrence_count was incremented

    Raises ValueError if sentence_id does not exist or surface_form is empty.
    """
    surface_form = surface_form.strip()
    if not surface_form:
        raise ValueError("surface_form must not be empty.")

    lemma = _default_lemma(surface_form)

    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            "SELECT id, occurrence_count, archived_at FROM word_cards WHERE lemma = ?",
            (lemma,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE word_cards
                      SET occurrence_count = occurrence_count + 1,
                          archived_at = NULL
                    WHERE id = ?""",
                (existing["id"],),
            )
            return existing["id"], False

        now = _utcnow()
        card_id: int = conn.execute(
            """INSERT INTO word_cards
               (lemma, surface_form, lexical_type, first_sentence_id,
                current_meaning, pos,
                created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at,
                occurrence_count, user_note)
               VALUES (?, ?, ?, ?, '', '',
                       ?, NULL, 0,
                       ?, ?, ?, ?, ?,
                       1, ?)""",
            (
                lemma,
                surface_form,
                lexical_type.value,
                sentence_id,
                now,
                MasteryState.NEW.value,
                SM2_DEFAULT_EF,
                SM2_INITIAL_INTERVAL_DAYS,
                SM2_INITIAL_REPETITIONS,
                now,
                user_note,
            ),
        ).lastrowid

    return card_id, True


def get_word_card(
    db: DatabaseConnection, card_id: int
) -> dict[str, Any] | None:
    """Return the word card row as a dict, or None if not found."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT wc.*, s.text AS first_sentence_text
               FROM word_cards wc
               JOIN sentences s ON wc.first_sentence_id = s.id
               WHERE wc.id = ? AND wc.archived_at IS NULL""",
            (card_id,),
        ).fetchone()
    return dict(row) if row else None


def get_word_card_by_lemma(
    db: DatabaseConnection, lemma: str
) -> dict[str, Any] | None:
    """Return the word card for a given lemma, or None."""
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM word_cards WHERE lemma = ? AND archived_at IS NULL",
            (lemma,),
        ).fetchone()
    return dict(row) if row else None


def list_word_cards(
    db: DatabaseConnection,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return word cards ordered by occurrence_count DESC, then created_at DESC."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM word_cards
               WHERE archived_at IS NULL
               ORDER BY occurrence_count DESC, created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def archive_word_card(db: DatabaseConnection, card_id: int) -> int:
    """
    Soft-delete an active word card.

    Returns the archived card id. Review logs and SM-2 state are preserved.
    Raises WordCardNotFoundError if no active card exists.
    """
    now = _utcnow()
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM word_cards WHERE id = ? AND archived_at IS NULL",
            (card_id,),
        ).fetchone()
        if existing is None:
            raise WordCardNotFoundError(f"Active word card id={card_id} not found.")

        conn.execute(
            "UPDATE word_cards SET archived_at = ? WHERE id = ?",
            (now, existing["id"]),
        )
    return existing["id"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
