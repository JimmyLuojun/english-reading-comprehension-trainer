"""Tests for import page rendering helpers."""

from __future__ import annotations

from app.web.views.imports import _duplicate_page, _import_forms


def test_import_forms_expose_file_and_paste_flows() -> None:
    html = _import_forms()

    assert 'action="/import/file"' in html
    assert 'accept=".txt,.epub,text/plain,application/epub+zip"' in html
    assert 'action="/import/paste"' in html


def test_duplicate_page_links_to_existing_book_or_books() -> None:
    existing = _duplicate_page(12)
    missing = _duplicate_page(None)

    assert existing.status_code == 409
    assert b"/read/12" in existing.body
    assert b"/books/12" in existing.body
    assert b"/books" in missing.body
