"""Tests for import page rendering helpers."""

from __future__ import annotations

from app.web.views.imports import _duplicate_page, _import_forms


def test_import_forms_expose_file_and_paste_flows() -> None:
    html = _import_forms()

    assert 'action="/import/file"' in html
    assert ".txt" in html
    assert ".md" in html
    assert ".markdown" in html
    assert ".epub" in html
    assert ".pdf" in html
    assert "text/markdown" in html
    assert "application/pdf" in html
    assert 'action="/import/paste"' in html
    assert 'action="/import/url"' in html
    assert 'type="url"' in html
    assert "Import URL" in html
    assert html.count('name="content_kind"') == 3
    assert html.count('<option value="auto" selected>Auto</option>') == 3
    assert '<option value="book">Book</option>' in html
    assert '<option value="article">Article</option>' in html
    assert '<option value="excerpt">Excerpt</option>' in html


def test_duplicate_page_links_to_existing_book_or_books() -> None:
    existing = _duplicate_page(12)
    missing = _duplicate_page(None)

    assert existing.status_code == 409
    assert b"/read/12" in existing.body
    assert b"/books/12" in existing.body
    assert b"/books" in missing.body
