"""Book workflow services for the FastAPI web interface."""

from __future__ import annotations

from app.db_connection import DatabaseConnection
from app.web.models import DeleteBookResult
from app.web.queries import _delete_book, _purge_book_assets_dir


def delete_book_and_assets(
    db: DatabaseConnection,
    book_id: int,
) -> DeleteBookResult | None:
    """Delete a book and purge its asset directory after the DB commit."""
    result = _delete_book(db, book_id)
    if result is None:
        return None
    _purge_book_assets_dir(db, book_id)
    return result
