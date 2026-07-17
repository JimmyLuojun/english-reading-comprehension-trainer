"""Tests for import query helpers."""

from __future__ import annotations

from pathlib import Path

from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from app.web.queries.imports import (
    _lookup_book_id_by_hash,
    _update_book_import_metadata,
)

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def test_lookup_book_id_by_hash_returns_existing_book(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text("One sentence.", encoding="utf-8")
    result = import_txt(db, source, title="Book", author="")

    with db.get_connection() as conn:
        file_hash = conn.execute(
            "SELECT file_hash FROM books WHERE id = ?",
            (result.book_id,),
        ).fetchone()["file_hash"]

    assert _lookup_book_id_by_hash(db, file_hash) == result.book_id
    assert _lookup_book_id_by_hash(db, "missing") is None

    _update_book_import_metadata(
        db,
        result.book_id,
        content_kind="article",
        import_method="url",
        source_uri="https://example.com/article",
    )
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT content_kind, import_method, source_uri
                 FROM books WHERE id = ?""",
            (result.book_id,),
        ).fetchone()
    assert dict(row) == {
        "content_kind": "article",
        "import_method": "url",
        "source_uri": "https://example.com/article",
    }


def test_update_book_import_metadata_rejects_missing_item(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)

    try:
        _update_book_import_metadata(
            db,
            999,
            content_kind="article",
            import_method="url",
            source_uri="https://example.com",
        )
    except LookupError as exc:
        assert "no longer exists" in str(exc)
    else:
        raise AssertionError("Expected LookupError")
