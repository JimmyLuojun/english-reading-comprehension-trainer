"""Import route query helpers."""

from __future__ import annotations


from app.db_connection import DatabaseConnection

def _lookup_book_id_by_hash(db: DatabaseConnection, file_hash: str) -> int | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    return int(row["id"]) if row else None


def _update_book_import_metadata(
    db: DatabaseConnection,
    book_id: int,
    *,
    content_kind: str,
    import_method: str,
    source_uri: str,
) -> None:
    """Record semantic and provenance metadata after a successful import."""
    with db.get_connection() as conn:
        cursor = conn.execute(
            """UPDATE books
                  SET content_kind = ?, import_method = ?, source_uri = ?
                WHERE id = ?""",
            (content_kind, import_method, source_uri, book_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Imported Library Item {book_id} no longer exists.")
