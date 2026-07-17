"""Book workflow services for the FastAPI web interface."""

from __future__ import annotations

from app.db_connection import DatabaseConnection
from app.web.models import DeleteBookResult
from app.web.queries import (
    _delete_book,
    _fetch_book,
    _purge_book_assets_dir,
    _update_library_item,
)


def delete_book_and_assets(
    db: DatabaseConnection,
    book_id: int,
) -> DeleteBookResult | None:
    """Delete a book and purge its asset directory after the DB commit."""
    if _fetch_book(db, book_id) is None:
        return None
    db.create_backup(reason=f"pre-book-delete-{book_id}")
    result = _delete_book(db, book_id)
    assert result is not None
    _purge_book_assets_dir(db, book_id)
    return result


def update_library_item(
    db: DatabaseConnection,
    book_id: int,
    *,
    title: str,
    author: str,
    content_kind: str,
    library_status: str,
    tags_text: str,
) -> bool:
    """Update editable Library Item metadata from the detail form."""
    return _update_library_item(
        db,
        book_id,
        title=title,
        author=author,
        content_kind=content_kind,
        library_status=library_status,
        tags=tags_text.split(","),
    )
