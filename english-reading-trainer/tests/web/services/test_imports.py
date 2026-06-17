"""Tests for web import workflow services."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.web.services import imports


def test_import_text_bytes_returns_book_id(monkeypatch) -> None:
    monkeypatch.setattr(
        imports,
        "import_text",
        lambda db, raw, title, author: SimpleNamespace(book_id=7),
    )

    outcome = imports.import_text_bytes(object(), b"Hello.", form_title="", author=" A ")

    assert outcome.book_id == 7
    assert not outcome.is_error
    assert not outcome.is_duplicate


def test_import_text_bytes_maps_duplicate_to_existing_book(monkeypatch) -> None:
    def raise_duplicate(db, raw, title, author):
        raise imports.DuplicateBookError()

    monkeypatch.setattr(imports, "import_text", raise_duplicate)
    monkeypatch.setattr(imports, "_lookup_book_id_by_hash", lambda db, file_hash: 99)

    outcome = imports.import_text_bytes(object(), b"Hello.", form_title="", author="")

    assert outcome.duplicate_book_id == 99
    assert outcome.status_code == 409


def test_import_epub_file_maps_import_errors(monkeypatch, tmp_path: Path) -> None:
    epub_path = tmp_path / "bad.epub"
    epub_path.write_bytes(b"not really epub")

    monkeypatch.setattr(imports, "calculate_epub_file_hash", lambda path: "hash")

    def raise_value_error(*args, **kwargs):
        raise ValueError("bad epub")

    monkeypatch.setattr(imports, "import_epub", raise_value_error)

    outcome = imports.import_epub_file(
        object(),
        epub_path,
        form_title="",
        author="",
    )

    assert outcome.error == "bad epub"
    assert outcome.status_code == 400


def test_import_pdf_file_maps_duplicate_to_existing_book(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "dup.pdf"
    pdf_path.write_bytes(b"%PDF")

    monkeypatch.setattr(imports, "calculate_pdf_file_hash", lambda path: "hash")

    def raise_duplicate(*args, **kwargs):
        raise imports.EpubDuplicateBookError()

    monkeypatch.setattr(imports, "import_pdf", raise_duplicate)
    monkeypatch.setattr(imports, "_lookup_book_id_by_hash", lambda db, file_hash: 55)

    outcome = imports.import_pdf_file(
        object(),
        pdf_path,
        form_title="",
        author="",
    )

    assert outcome.duplicate_book_id == 55
    assert outcome.status_code == 409


def test_import_pdf_file_maps_import_errors(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_bytes(b"not really pdf")

    monkeypatch.setattr(imports, "calculate_pdf_file_hash", lambda path: "hash")

    def raise_value_error(*args, **kwargs):
        raise ValueError("bad pdf")

    monkeypatch.setattr(imports, "import_pdf", raise_value_error)

    outcome = imports.import_pdf_file(
        object(),
        pdf_path,
        form_title="",
        author="",
    )

    assert outcome.error == "bad pdf"
    assert outcome.status_code == 400
