"""Book, chapter, deletion, and re-anchor query helpers."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.review.daily_review_queue import list_due_cards
from app.web.config import (
    _DEFAULT_SENTENCE_PROMPT_VERSION,
    _DEFAULT_WORD_PROMPT_VERSION,
    _DIAGNOSE_SENTENCE_PROMPT,
    _PREDICT_SENTENCE_PROMPT,
    _WORD_ANALYSIS_PROMPT,
    _WORD_TOKEN_RE,
)
from app.web.models import DeleteBookResult

def _fetch_books(db: DatabaseConnection) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, title, author, source_format, total_chapters,
                      total_sentences, imported_at
                 FROM books
                ORDER BY id"""
        ).fetchall()
    return [dict(row) for row in rows]

def _fetch_book(db: DatabaseConnection, book_id: int) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None

def _delete_book(db: DatabaseConnection, book_id: int) -> DeleteBookResult | None:
    with db.get_connection() as conn:
        book = conn.execute(
            "SELECT id FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if book is None:
            return None

        sentence_cards_deleted = conn.execute(
            """SELECT COUNT(*)
                 FROM sentence_cards sc
                 JOIN sentences s ON s.id = sc.sentence_id
                WHERE s.book_id = ?""",
            (book_id,),
        ).fetchone()[0]
        sentence_log_delete = conn.execute(
            """DELETE FROM review_logs
                WHERE card_type = 'sentence'
                  AND card_id IN (
                    SELECT sc.id
                      FROM sentence_cards sc
                      JOIN sentences s ON s.id = sc.sentence_id
                     WHERE s.book_id = ?)""",
            (book_id,),
        )
        review_logs_deleted = max(sentence_log_delete.rowcount, 0)

        word_card_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT wc.id, wc.lemma, wc.surface_form, wc.lexical_type
                     FROM word_cards wc
                     JOIN sentences s ON s.id = wc.first_sentence_id
                    WHERE s.book_id = ?
                    ORDER BY wc.id""",
                (book_id,),
            ).fetchall()
        ]
        candidate_rows = _fetch_reanchor_candidate_sentences(conn, book_id)
        word_card_ids_to_delete: list[int] = []
        word_cards_reanchored = 0

        for card in word_card_rows:
            reanchor_sentence_id = _find_reanchor_sentence_id(card, candidate_rows)
            if reanchor_sentence_id is None:
                word_card_ids_to_delete.append(card["id"])
                continue
            conn.execute(
                "UPDATE word_cards SET first_sentence_id = ? WHERE id = ?",
                (reanchor_sentence_id, card["id"]),
            )
            word_cards_reanchored += 1

        if word_card_ids_to_delete:
            placeholders = _sql_placeholders(word_card_ids_to_delete)
            word_log_delete = conn.execute(
                f"""DELETE FROM review_logs
                     WHERE card_type = 'word'
                       AND card_id IN ({placeholders})""",
                word_card_ids_to_delete,
            )
            review_logs_deleted += max(word_log_delete.rowcount, 0)
            conn.execute(
                f"DELETE FROM word_cards WHERE id IN ({placeholders})",
                word_card_ids_to_delete,
            )

        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))

    return DeleteBookResult(
        sentence_cards_deleted=sentence_cards_deleted,
        word_cards_reanchored=word_cards_reanchored,
        word_cards_deleted=len(word_card_ids_to_delete),
        review_logs_deleted=review_logs_deleted,
    )

def _fetch_reanchor_candidate_sentences(
    conn: Any,
    deleted_book_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, text
             FROM sentences
            WHERE book_id != ?
            ORDER BY book_id, chapter_id, paragraph_id, idx, id""",
        (deleted_book_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def _find_reanchor_sentence_id(
    card: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> int | None:
    lexical_type = str(card.get("lexical_type") or LexicalType.WORD.value)
    if lexical_type == LexicalType.WORD.value:
        return _find_word_reanchor_sentence_id(card, candidates)
    return _find_phrase_reanchor_sentence_id(card, candidates)

def _find_word_reanchor_sentence_id(
    card: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> int | None:
    terms = _word_card_terms(card)
    if not terms:
        return None
    for candidate in candidates:
        tokens = set(_word_tokens(str(candidate["text"])))
        if terms & tokens:
            return candidate["id"]
    return None

def _find_phrase_reanchor_sentence_id(
    card: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> int | None:
    phrases = _phrase_card_terms(card)
    if not phrases:
        return None
    for candidate in candidates:
        normalized_text = _normalize_phrase_text(str(candidate["text"]))
        if any(phrase in normalized_text for phrase in phrases):
            return candidate["id"]
    return None

def _word_card_terms(card: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for key in ("surface_form", "lemma"):
        tokens = _word_tokens(str(card.get(key) or ""))
        if len(tokens) == 1:
            terms.add(tokens[0])
    return terms

def _phrase_card_terms(card: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for key in ("surface_form", "lemma"):
        normalized = _normalize_phrase_text(str(card.get(key) or ""))
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)
    return terms

def _word_tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_TOKEN_RE.finditer(text)]

def _normalize_phrase_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())

def _sql_placeholders(values: list[Any]) -> str:
    return ",".join("?" for _ in values)

def _purge_book_assets_dir(db: DatabaseConnection, book_id: int) -> None:
    assets_dir = Path(getattr(db, "_db_path")).parent / "assets" / "books" / str(book_id)
    try:
        shutil.rmtree(assets_dir, ignore_errors=True)
    except OSError:
        pass

def _fetch_chapters(db: DatabaseConnection, book_id: int) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, idx, title, sentence_start, sentence_end,
                      section_kind, chapter_number
                 FROM chapters
                WHERE book_id = ?
                ORDER BY idx""",
            (book_id,),
        ).fetchall()
    return [dict(row) for row in rows]

def _default_read_idx(db: DatabaseConnection, book_id: int) -> int | None:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT idx
                 FROM chapters
                WHERE book_id = ? AND section_kind = 'chapter'
                ORDER BY COALESCE(chapter_number, idx), idx
                LIMIT 1""",
            (book_id,),
        ).fetchone()
        if row:
            return row["idx"]
        row = conn.execute(
            """SELECT idx
                 FROM chapters
                WHERE book_id = ?
                ORDER BY idx
                LIMIT 1""",
            (book_id,),
        ).fetchone()
    return row["idx"] if row else None

def _fetch_chapter_by_idx(
    db: DatabaseConnection,
    book_id: int,
    chapter_idx: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chapters WHERE book_id = ? AND idx = ?",
            (book_id, chapter_idx),
        ).fetchone()
    return dict(row) if row else None

def _fetch_adjacent_chapters(
    db: DatabaseConnection,
    book_id: int,
    chapter_idx: int,
) -> dict[str, dict[str, Any] | None]:
    with db.get_connection() as conn:
        previous_row = conn.execute(
            """SELECT id, idx, title, sentence_start, sentence_end,
                      section_kind, chapter_number
                 FROM chapters
                WHERE book_id = ? AND idx < ?
                ORDER BY idx DESC
                LIMIT 1""",
            (book_id, chapter_idx),
        ).fetchone()
        next_row = conn.execute(
            """SELECT id, idx, title, sentence_start, sentence_end,
                      section_kind, chapter_number
                 FROM chapters
                WHERE book_id = ? AND idx > ?
                ORDER BY idx
                LIMIT 1""",
            (book_id, chapter_idx),
        ).fetchone()
    return {
        "previous": dict(previous_row) if previous_row else None,
        "next": dict(next_row) if next_row else None,
    }
