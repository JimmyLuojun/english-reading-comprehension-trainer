"""Import route query helpers."""

from __future__ import annotations


from app.db_connection import DatabaseConnection

def _lookup_book_id_by_hash(db: DatabaseConnection, file_hash: str) -> int | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    return int(row["id"]) if row else None
