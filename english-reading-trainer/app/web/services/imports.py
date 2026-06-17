"""Import workflow services for the FastAPI web interface."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.db_connection import DatabaseConnection
from app.importers.epub_importer import DuplicateBookError as EpubDuplicateBookError
from app.importers.epub_importer import calculate_epub_file_hash, import_epub
from app.importers.pdf_importer import calculate_pdf_file_hash, import_pdf
from app.importers.txt_importer import DuplicateBookError, import_text
from app.web.queries import _lookup_book_id_by_hash
from app.web.utils import _resolve_title


@dataclass(frozen=True)
class ImportOutcome:
    """Result of an import workflow, independent of HTTP rendering."""

    book_id: int | None = None
    duplicate_book_id: int | None = None
    error: str | None = None
    status_code: int = 200

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_book_id is not None

    @property
    def is_error(self) -> bool:
        return self.error is not None


def import_text_bytes(
    db: DatabaseConnection,
    raw: bytes,
    *,
    form_title: str,
    author: str,
) -> ImportOutcome:
    """Import raw TXT bytes and return a routing-neutral outcome."""
    title = _resolve_title(form_title, raw)
    try:
        result = import_text(db, raw, title=title, author=author.strip())
    except DuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, hashlib.sha256(raw).hexdigest())
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except ValueError as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)


def import_epub_file(
    db: DatabaseConnection,
    file_path: str | Path,
    *,
    form_title: str,
    author: str,
) -> ImportOutcome:
    """Import an EPUB file and return a routing-neutral outcome."""
    try:
        file_hash = calculate_epub_file_hash(file_path)
        result = import_epub(
            db,
            file_path,
            title=form_title.strip() or None,
            author=author.strip() or None,
        )
    except EpubDuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, file_hash)
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except (ValueError, FileNotFoundError) as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)


def import_pdf_file(
    db: DatabaseConnection,
    file_path: str | Path,
    *,
    form_title: str,
    author: str,
) -> ImportOutcome:
    """Import a PDF file and return a routing-neutral outcome."""
    try:
        file_hash = calculate_pdf_file_hash(file_path)
        result = import_pdf(
            db,
            file_path,
            title=form_title.strip() or None,
            author=author.strip() or None,
        )
    except EpubDuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, file_hash)
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except (ValueError, FileNotFoundError) as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)
