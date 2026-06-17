"""Tests for page layout helpers."""

from __future__ import annotations

from app.web.views.layout import (
    _active,
    _date,
    _escape,
    _html_page,
    _metric,
    _reader_resume_script,
)


def test_html_page_escapes_title_and_marks_active_nav() -> None:
    response = _html_page("<Title>", "<p>Body</p>", active="books", page_class="reader")

    body = response.body.decode()
    assert response.status_code == 200
    assert "&lt;Title&gt; - English Reading Trainer" in body
    assert '<body class="reader">' in body
    assert '<a class="active" href="/books">Books</a>' in body
    assert "reader:last-book-id" in body


def test_reader_resume_script_redirects_books_nav_to_last_book() -> None:
    script = _reader_resume_script()

    assert 'nav a[href="/books"]' in script
    assert "reader:last-book-id" in script
    assert 'window.location.href = "/read/"' in script


def test_formatting_helpers() -> None:
    assert _metric("<Cards>", 3) == '<div class="metric"><span>&lt;Cards&gt;</span><strong>3</strong></div>'
    assert _date("2026-06-17T12:34:00+00:00") == "2026-06-17"
    assert _date("bad-value") == "bad-value"
    assert _active("cards", "cards") == "active"
    assert _active("cards", "books") == ""
    assert _escape('"quoted"') == "&quot;quoted&quot;"
