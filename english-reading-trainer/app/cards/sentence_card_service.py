"""
Sentence card CRUD — create, fetch, list.

SM-2 initial state matches §7.1 of design.md:
  ef=2.5, interval_days=0, repetitions=0, mastery_state='new', due_at=now.
"""

from datetime import datetime, timezone
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import (
    MasteryState,
    SM2_DEFAULT_EF,
    SM2_INITIAL_INTERVAL_DAYS,
    SM2_INITIAL_REPETITIONS,
)


class SentenceCardAlreadyExistsError(Exception):
    """Raised when a sentence_card for the given sentence_id already exists."""


def create_sentence_card(
    db: DatabaseConnection,
    sentence_id: int,
    user_note: str = "",
) -> int:
    """
    Create a new sentence card for *sentence_id* with SM-2 defaults.

    Returns the new card's id.
    Raises SentenceCardAlreadyExistsError if a card already exists.
    Raises ValueError if sentence_id does not exist.
    """
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            "SELECT id FROM sentence_cards WHERE sentence_id = ?", (sentence_id,)
        ).fetchone()
        if existing:
            raise SentenceCardAlreadyExistsError(
                f"A card already exists for sentence id={sentence_id} "
                f"(card id={existing['id']})."
            )

        now = _utcnow()
        card_id: int = conn.execute(
            """INSERT INTO sentence_cards
               (sentence_id, created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at, user_note)
               VALUES (?, ?, NULL, 0, ?, ?, ?, ?, ?, ?)""",
            (
                sentence_id, now,
                MasteryState.NEW.value,
                SM2_DEFAULT_EF,
                SM2_INITIAL_INTERVAL_DAYS,
                SM2_INITIAL_REPETITIONS,
                now,
                user_note,
            ),
        ).lastrowid

    return card_id


def get_sentence_card(
    db: DatabaseConnection, card_id: int
) -> dict[str, Any] | None:
    """Return the sentence card row as a dict, or None if not found."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT sc.*, s.text AS sentence_text
               FROM sentence_cards sc
               JOIN sentences s ON sc.sentence_id = s.id
               WHERE sc.id = ?""",
            (card_id,),
        ).fetchone()
    return dict(row) if row else None


def get_sentence_card_by_sentence(
    db: DatabaseConnection, sentence_id: int
) -> dict[str, Any] | None:
    """Return the sentence card for a given sentence_id, or None."""
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sentence_cards WHERE sentence_id = ?", (sentence_id,)
        ).fetchone()
    return dict(row) if row else None


def list_sentence_cards(
    db: DatabaseConnection,
    book_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Return sentence cards, optionally filtered to a single book.
    Ordered by created_at DESC.
    """
    with db.get_connection() as conn:
        if book_id is not None:
            rows = conn.execute(
                """SELECT sc.*, s.text AS sentence_text
                   FROM sentence_cards sc
                   JOIN sentences s ON sc.sentence_id = s.id
                   WHERE s.book_id = ?
                   ORDER BY sc.created_at DESC
                   LIMIT ? OFFSET ?""",
                (book_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT sc.*, s.text AS sentence_text
                   FROM sentence_cards sc
                   JOIN sentences s ON sc.sentence_id = s.id
                   ORDER BY sc.created_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
    return [dict(r) for r in rows]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
