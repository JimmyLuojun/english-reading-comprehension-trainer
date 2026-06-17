"""
Word card CRUD — create, fetch, list, and source tracking.

The `lemma` field is the deduplication key (UNIQUE constraint).
On first encounter → create card.
On repeat encounter → record a distinct source location if it is new.

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


class WordCardSourceNotFoundError(ValueError):
    """Raised when a word card source cannot be found."""


def _default_lemma(surface_form: str) -> str:
    """Temporary lemma: lowercased + stripped surface form."""
    return surface_form.lower().strip()


def _source_key(surface_form: str) -> str:
    return surface_form.lower().strip()


def _record_word_card_source_conn(
    conn: Any,
    *,
    card_id: int,
    sentence_id: int,
    surface_form: str,
    is_primary: bool = False,
) -> bool:
    now = _utcnow()
    key = _source_key(surface_form)
    if is_primary:
        conn.execute(
            "UPDATE word_card_sources SET is_primary = 0 WHERE card_id = ?",
            (card_id,),
        )
    cursor = conn.execute(
        """INSERT OR IGNORE INTO word_card_sources
           (card_id, sentence_id, surface_form, source_key, is_primary, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (card_id, sentence_id, surface_form, key, 1 if is_primary else 0, now),
    )
    inserted = cursor.rowcount > 0
    if is_primary and not inserted:
        conn.execute(
            """UPDATE word_card_sources
                  SET is_primary = 1
                WHERE card_id = ? AND sentence_id = ? AND source_key = ?""",
            (card_id, sentence_id, key),
        )
    elif inserted and not _has_primary_source_conn(conn, card_id):
        conn.execute(
            "UPDATE word_card_sources SET is_primary = 1 WHERE card_id = ? AND id = last_insert_rowid()",
            (card_id,),
        )
    _sync_occurrence_count_conn(conn, card_id)
    return inserted


def _has_primary_source_conn(conn: Any, card_id: int) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM word_card_sources WHERE card_id = ? AND is_primary = 1",
            (card_id,),
        ).fetchone()
    )


def _sync_occurrence_count_conn(conn: Any, card_id: int) -> None:
    conn.execute(
        """UPDATE word_cards
              SET occurrence_count = (
                  SELECT COUNT(*) FROM word_card_sources WHERE card_id = ?
              )
            WHERE id = ?""",
        (card_id, card_id),
    )


def _href(book_id: int, chapter_idx: int, sentence_id: int, card_id: int, analyzed: bool) -> str:
    word_param = f"&word_card={card_id}" if analyzed else ""
    return f"/read/{book_id}?chapter={chapter_idx}{word_param}#sentence-{sentence_id}"


def create_or_update_word_card(
    db: DatabaseConnection,
    sentence_id: int,
    surface_form: str,
    lexical_type: LexicalType = LexicalType.WORD,
    user_note: str = "",
) -> tuple[int, bool]:
    """
    Create a word card or record a distinct source location on an existing one.

    Returns (card_id, created):
      created=True  → new card was inserted
      created=False → existing card was reused

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
            card_id = int(existing["id"])
            conn.execute(
                """UPDATE word_cards
                      SET archived_at = NULL
                    WHERE id = ?""",
                (card_id,),
            )
            _record_word_card_source_conn(
                conn,
                card_id=card_id,
                sentence_id=sentence_id,
                surface_form=surface_form,
            )
            return card_id, False

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
        _record_word_card_source_conn(
            conn,
            card_id=card_id,
            sentence_id=sentence_id,
            surface_form=surface_form,
            is_primary=True,
        )

    return card_id, True


def record_word_card_source(
    db: DatabaseConnection,
    card_id: int,
    sentence_id: int,
    surface_form: str,
    *,
    is_primary: bool = False,
) -> bool:
    """Record one distinct source location for an active word card."""
    surface_form = surface_form.strip()
    if not surface_form:
        raise ValueError("surface_form must not be empty.")
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM word_cards WHERE id = ? AND archived_at IS NULL",
            (card_id,),
        ).fetchone()
        if existing is None:
            raise WordCardNotFoundError(f"Active word card id={card_id} not found.")
        if not conn.execute(
            "SELECT 1 FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone():
            raise ValueError(f"Sentence id={sentence_id} not found.")
        return _record_word_card_source_conn(
            conn,
            card_id=card_id,
            sentence_id=sentence_id,
            surface_form=surface_form,
            is_primary=is_primary,
        )


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
    """Return word cards with book source and AI meaning, ordered by occurrence_count DESC."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT wc.*,
                      b.title AS first_book_title,
                      s.id AS source_sentence_id,
                      s.book_id AS source_book_id,
                      c.idx AS source_chapter_idx,
                      s.text AS source_sentence_text,
                      CASE
                        WHEN s.id IS NULL OR c.idx IS NULL THEN ''
                        WHEN wc.ai_analysis_id IS NOT NULL
                          THEN '/read/' || s.book_id || '?chapter=' || c.idx || '&word_card=' || wc.id || '#sentence-' || s.id
                        ELSE '/read/' || s.book_id || '?chapter=' || c.idx || '#sentence-' || s.id
                      END AS source_href,
                      json_extract(ac.response_json, '$.meaning_in_context') AS ai_meaning
               FROM word_cards wc
               LEFT JOIN sentences s  ON s.id  = wc.first_sentence_id
               LEFT JOIN chapters  c  ON c.id  = s.chapter_id
               LEFT JOIN books     b  ON b.id  = s.book_id
               LEFT JOIN ai_cache  ac ON ac.id = wc.ai_analysis_id
               WHERE wc.archived_at IS NULL
               ORDER BY wc.occurrence_count DESC, wc.created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def list_word_card_sources(
    db: DatabaseConnection,
    card_id: int,
) -> list[dict[str, Any]]:
    """Return recorded sources for a word card."""
    card = get_word_card(db, card_id)
    if card is None:
        raise WordCardNotFoundError(f"Active word card id={card_id} not found.")
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT wcs.*,
                      b.title AS book_title,
                      s.book_id,
                      c.idx AS chapter_idx,
                      s.text AS sentence_text,
                      CASE
                        WHEN wc.ai_analysis_id IS NOT NULL
                          THEN '/read/' || s.book_id || '?chapter=' || c.idx || '&word_card=' || wc.id || '#sentence-' || s.id
                        ELSE '/read/' || s.book_id || '?chapter=' || c.idx || '#sentence-' || s.id
                      END AS source_href
                 FROM word_card_sources wcs
                 JOIN word_cards wc ON wc.id = wcs.card_id
                 JOIN sentences s ON s.id = wcs.sentence_id
                 JOIN chapters c ON c.id = s.chapter_id
                 JOIN books b ON b.id = s.book_id
                WHERE wcs.card_id = ?
                ORDER BY wcs.is_primary DESC, wcs.created_at ASC, wcs.id ASC""",
            (card_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def find_word_card_occurrence_candidates(
    db: DatabaseConnection,
    card_id: int,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find sentence-level candidate sources by scanning for the card surface text."""
    card = get_word_card(db, card_id)
    if card is None:
        raise WordCardNotFoundError(f"Active word card id={card_id} not found.")
    surface_form = str(card["surface_form"]).strip()
    key = _source_key(surface_form)
    pattern = f"%{key}%"
    analyzed = card.get("ai_analysis_id") is not None
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT s.id AS sentence_id,
                      s.text AS sentence_text,
                      s.book_id,
                      c.idx AS chapter_idx,
                      b.title AS book_title,
                      EXISTS (
                          SELECT 1
                            FROM word_card_sources wcs
                           WHERE wcs.card_id = ?
                             AND wcs.sentence_id = s.id
                             AND wcs.source_key = ?
                      ) AS is_recorded,
                      EXISTS (
                          SELECT 1
                            FROM word_card_sources wcs
                           WHERE wcs.card_id = ?
                             AND wcs.sentence_id = s.id
                             AND wcs.source_key = ?
                             AND wcs.is_primary = 1
                      ) AS is_primary
                 FROM sentences s
                 JOIN chapters c ON c.id = s.chapter_id
                 JOIN books b ON b.id = s.book_id
                WHERE lower(s.text) LIKE ?
                ORDER BY b.title ASC, c.idx ASC, s.idx ASC
                LIMIT ?""",
            (card_id, key, card_id, key, pattern, limit),
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["surface_form"] = surface_form
        item["source_href"] = _href(
            int(item["book_id"]),
            int(item["chapter_idx"]),
            int(item["sentence_id"]),
            card_id,
            analyzed,
        )
        candidates.append(item)
    return candidates


def add_word_card_source(
    db: DatabaseConnection,
    card_id: int,
    sentence_id: int,
) -> bool:
    """Add a candidate sentence as a source for the word card."""
    card = get_word_card(db, card_id)
    if card is None:
        raise WordCardNotFoundError(f"Active word card id={card_id} not found.")
    return record_word_card_source(
        db,
        card_id,
        sentence_id,
        str(card["surface_form"]),
    )


def set_primary_word_card_source(
    db: DatabaseConnection,
    card_id: int,
    source_id: int,
) -> int:
    """Set a recorded word-card source as primary and update first_sentence_id."""
    with db.get_connection() as conn:
        source = conn.execute(
            """SELECT id, sentence_id
                 FROM word_card_sources
                WHERE id = ? AND card_id = ?""",
            (source_id, card_id),
        ).fetchone()
        if source is None:
            raise WordCardSourceNotFoundError(
                f"Source id={source_id} not found for word card id={card_id}."
            )
        if not conn.execute(
            "SELECT 1 FROM word_cards WHERE id = ? AND archived_at IS NULL",
            (card_id,),
        ).fetchone():
            raise WordCardNotFoundError(f"Active word card id={card_id} not found.")
        conn.execute(
            "UPDATE word_card_sources SET is_primary = 0 WHERE card_id = ?",
            (card_id,),
        )
        conn.execute(
            "UPDATE word_card_sources SET is_primary = 1 WHERE id = ?",
            (source_id,),
        )
        conn.execute(
            "UPDATE word_cards SET first_sentence_id = ? WHERE id = ?",
            (source["sentence_id"], card_id),
        )
    return card_id


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


def update_word_card_note(
    db: DatabaseConnection,
    card_id: int,
    current_meaning: str = "",
    user_note: str = "",
) -> int:
    """
    Update current_meaning and user_note on an active word card.

    Returns the card id. Raises WordCardNotFoundError if not found.
    """
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM word_cards WHERE id = ? AND archived_at IS NULL",
            (card_id,),
        ).fetchone()
        if existing is None:
            raise WordCardNotFoundError(f"Active word card id={card_id} not found.")
        conn.execute(
            "UPDATE word_cards SET current_meaning = ?, user_note = ? WHERE id = ?",
            (current_meaning.strip(), user_note.strip(), card_id),
        )
    return card_id


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
