"""Tests for page layout helpers."""

from __future__ import annotations

from app.web.views.layout import (
    _active,
    _date,
    _escape,
    _html_page,
    _metric,
)


def test_html_page_escapes_title_and_marks_active_nav() -> None:
    response = _html_page("<Title>", "<p>Body</p>", active="books", page_class="reader")

    body = response.body.decode()
    assert response.status_code == 200
    assert "&lt;Title&gt; - English Reading Trainer" in body
    assert '<body class="reader">' in body
    assert '<a class="active" href="/books">Books</a>' in body
    assert "reader:last-book-id" not in body


def test_formatting_helpers() -> None:
    assert _metric("<Cards>", 3) == '<div class="metric"><span>&lt;Cards&gt;</span><strong>3</strong></div>'
    assert _metric("Books", 8, href="/books") == (
        '<a class="metric metric-link" href="/books" aria-label="Books: 8">'
        "<span>Books</span><strong>8</strong></a>"
    )
    assert _date("2026-06-17T12:34:00+00:00") == "2026-06-17"
    assert _date("bad-value") == "bad-value"
    assert _active("cards", "cards") == "active"
    assert _active("cards", "books") == ""
    assert _escape('"quoted"') == "&quot;quoted&quot;"
