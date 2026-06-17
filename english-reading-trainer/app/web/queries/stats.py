"""Dashboard statistics query helpers."""

from __future__ import annotations


from app.db_connection import DatabaseConnection
from app.review.daily_review_queue import list_due_cards

def _dashboard_stats(db: DatabaseConnection) -> dict[str, int]:
    with db.get_connection() as conn:
        books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        sentences = conn.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]
        sentence_cards = conn.execute(
            "SELECT COUNT(*) FROM sentence_cards WHERE archived_at IS NULL"
        ).fetchone()[0]
        word_cards = conn.execute(
            "SELECT COUNT(*) FROM word_cards WHERE archived_at IS NULL"
        ).fetchone()[0]
    return {
        "books": books,
        "sentences": sentences,
        "sentence_cards": sentence_cards,
        "word_cards": word_cards,
        "due_cards": len(list_due_cards(db)),
    }
