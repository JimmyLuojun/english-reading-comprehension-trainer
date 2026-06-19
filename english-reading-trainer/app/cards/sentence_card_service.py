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


class SentenceCardNotFoundError(ValueError):
    """Raised when an active sentence card cannot be found."""


def create_sentence_card(
    db: DatabaseConnection,
    sentence_id: int,
    user_note: str = "",
    user_translation: str | None = None,
) -> int:
    """
    Create a new sentence card for *sentence_id* with SM-2 defaults.

    Returns the new card's id.
    Raises SentenceCardAlreadyExistsError if a card already exists.
    Raises ValueError if sentence_id does not exist.
    """
    cleaned_translation = _clean_optional_translation(user_translation)
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            "SELECT id, archived_at, user_note FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()
        if existing:
            if existing["archived_at"] is not None:
                note = user_note if user_note else existing["user_note"]
                if cleaned_translation is None:
                    conn.execute(
                        """UPDATE sentence_cards
                              SET archived_at = NULL,
                                  user_note = ?
                            WHERE id = ?""",
                        (note, existing["id"]),
                    )
                else:
                    now = _utcnow()
                    conn.execute(
                        """UPDATE sentence_cards
                              SET archived_at = NULL,
                                  user_note = ?,
                                  user_translation = ?,
                                  translation_created_at = ?
                            WHERE id = ?""",
                        (note, cleaned_translation, now, existing["id"]),
                    )
                    _clear_sentence_card_errors(conn, existing["id"])
                return existing["id"]
            raise SentenceCardAlreadyExistsError(
                f"A card already exists for sentence id={sentence_id} "
                f"(card id={existing['id']})."
            )

        card_id = _insert_sentence_card(
            conn,
            sentence_id=sentence_id,
            user_note=user_note,
            user_translation=cleaned_translation,
        )

    return card_id


def save_sentence_translation(
    db: DatabaseConnection,
    sentence_id: int,
    user_translation: str,
    user_note: str = "",
) -> int:
    """
    Store the latest user translation for *sentence_id* and return the card id.

    Creates an archived translation record if needed. Re-submission overwrites
    the previous translation and clears stale error links so the next analysis
    uses a cache key that includes the latest translation. Existing AI analysis
    remains attached as a stale reference until a fresh check replaces it.
    Saving a translation alone must not add the sentence to the active Review
    queue.
    """
    cleaned_translation = user_translation.strip()
    if not cleaned_translation:
        raise ValueError("user_translation must not be empty.")

    now = _utcnow()
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            "SELECT id, user_note FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()
        if existing:
            note = user_note if user_note else existing["user_note"]
            conn.execute(
                """UPDATE sentence_cards
                      SET user_note = ?,
                          user_translation = ?,
                          translation_created_at = ?
                    WHERE id = ?""",
                (note, cleaned_translation, now, existing["id"]),
            )
            _clear_sentence_card_errors(conn, existing["id"])
            return existing["id"]

        return _insert_sentence_card(
            conn,
            sentence_id=sentence_id,
            user_note=user_note,
            user_translation=cleaned_translation,
            archived_at=now,
        )


def delete_sentence_translation(db: DatabaseConnection, sentence_id: int) -> int:
    """
    Clear the saved translation for *sentence_id* and archive its review card.

    Deleting the translation removes the reason for reviewing this sentence in
    the translation workflow, so the active sentence card is archived as well.
    Review logs and SM-2 history remain preserved on the soft-deleted card.
    """
    now = _utcnow()
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            """SELECT id, user_translation
                 FROM sentence_cards
                WHERE sentence_id = ?""",
            (sentence_id,),
        ).fetchone()
        if existing is None or not (existing["user_translation"] or "").strip():
            raise ValueError(
                f"No saved translation exists for sentence id={sentence_id}."
            )

        conn.execute(
            """UPDATE sentence_cards
                  SET user_translation = NULL,
                      translation_created_at = NULL,
                      ai_analysis_id = NULL,
                      archived_at = ?
                WHERE id = ?""",
            (now, existing["id"]),
        )
        _clear_sentence_card_errors(conn, existing["id"])
    return existing["id"]


def update_sentence_card_note(
    db: DatabaseConnection,
    sentence_id: int,
    user_note: str = "",
) -> int:
    """
    Store the learner's takeaway note for *sentence_id* and return the card id.

    Notes use sentence_cards.user_note. Creating a note-only record keeps it
    archived so a takeaway alone does not add the sentence to Review.
    """
    cleaned_note = user_note.strip()
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            "SELECT id FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sentence_cards SET user_note = ? WHERE id = ?",
                (cleaned_note, existing["id"]),
            )
            return existing["id"]

        return _insert_sentence_card(
            conn,
            sentence_id=sentence_id,
            user_note=cleaned_note,
            user_translation=None,
            archived_at=_utcnow(),
        )


def get_sentence_card(
    db: DatabaseConnection, card_id: int
) -> dict[str, Any] | None:
    """Return the sentence card row as a dict, or None if not found."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT sc.*, s.text AS sentence_text
               FROM sentence_cards sc
               JOIN sentences s ON sc.sentence_id = s.id
               WHERE sc.id = ? AND sc.archived_at IS NULL""",
            (card_id,),
        ).fetchone()
    return dict(row) if row else None


def get_sentence_card_by_sentence(
    db: DatabaseConnection, sentence_id: int
) -> dict[str, Any] | None:
    """Return the sentence card for a given sentence_id, or None."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT *
                 FROM sentence_cards
                WHERE sentence_id = ? AND archived_at IS NULL""",
            (sentence_id,),
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
                """SELECT sc.*, s.text AS sentence_text,
                          s.book_id, c.idx AS chapter_idx,
                          '/read/' || s.book_id || '?chapter=' || c.idx ||
                          '&sentence_id=' || s.id || '&panel=analysis#sentence-' ||
                          s.id AS source_href
                   FROM sentence_cards sc
                   JOIN sentences s ON sc.sentence_id = s.id
                   JOIN chapters c ON c.id = s.chapter_id
                   WHERE s.book_id = ? AND sc.archived_at IS NULL
                   ORDER BY sc.created_at DESC
                   LIMIT ? OFFSET ?""",
                (book_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT sc.*, s.text AS sentence_text,
                          s.book_id, c.idx AS chapter_idx,
                          '/read/' || s.book_id || '?chapter=' || c.idx ||
                          '&sentence_id=' || s.id || '&panel=analysis#sentence-' ||
                          s.id AS source_href
                   FROM sentence_cards sc
                   JOIN sentences s ON sc.sentence_id = s.id
                   JOIN chapters c ON c.id = s.chapter_id
                   WHERE sc.archived_at IS NULL
                   ORDER BY sc.created_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
    return [dict(r) for r in rows]


def archive_sentence_card(db: DatabaseConnection, sentence_id: int) -> int:
    """
    Soft-delete the active sentence card for *sentence_id*.

    Returns the archived card id. Review logs and SM-2 state are preserved.
    Raises SentenceCardNotFoundError if no active card exists.
    Raises ValueError if sentence_id does not exist.
    """
    now = _utcnow()
    with db.get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")

        existing = conn.execute(
            """SELECT id
                 FROM sentence_cards
                WHERE sentence_id = ? AND archived_at IS NULL""",
            (sentence_id,),
        ).fetchone()
        if existing is None:
            raise SentenceCardNotFoundError(
                f"No active sentence card exists for sentence id={sentence_id}."
            )

        conn.execute(
            "UPDATE sentence_cards SET archived_at = ? WHERE id = ?",
            (now, existing["id"]),
        )
    return existing["id"]


def _insert_sentence_card(
    conn: Any,
    *,
    sentence_id: int,
    user_note: str,
    user_translation: str | None,
    archived_at: str | None = None,
) -> int:
    now = _utcnow()
    translation_created_at = now if user_translation is not None else None
    return conn.execute(
        """INSERT INTO sentence_cards
           (sentence_id, created_at, last_reviewed_at, review_count,
            mastery_state, ef, interval_days, repetitions, due_at, user_note,
            user_translation, translation_created_at, archived_at)
           VALUES (?, ?, NULL, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sentence_id, now,
            MasteryState.NEW.value,
            SM2_DEFAULT_EF,
            SM2_INITIAL_INTERVAL_DAYS,
            SM2_INITIAL_REPETITIONS,
            now,
            user_note,
            user_translation,
            translation_created_at,
            archived_at,
        ),
    ).lastrowid


def _clear_sentence_card_errors(conn: Any, card_id: int) -> None:
    conn.execute("DELETE FROM sentence_card_errors WHERE card_id = ?", (card_id,))


def _clean_optional_translation(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
