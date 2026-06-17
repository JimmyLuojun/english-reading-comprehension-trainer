"""Tests for shared HTML components."""

from __future__ import annotations

from app.web.views.components import (
    _hover_popover,
    _pronunciation_cell,
    _safe_source_href,
    _source_link,
    _speak_button,
)


def test_source_link_accepts_only_local_paths() -> None:
    assert _safe_source_href("/read/1") == "/read/1"
    assert _safe_source_href("//evil.test") == ""
    assert _safe_source_href("https://evil.test") == ""
    assert '<a class="source-link" href="/read/1">Book</a>' == _source_link(
        "Book",
        "/read/1",
    )
    assert _source_link("Book", "https://evil.test") == "Book"


def test_hover_popover_and_pronunciation_escape_content() -> None:
    popover = _hover_popover("<Reveal>", "<p>Safe</p>", align="right")
    cell = _pronunciation_cell("<cat>", speak_text="cat", href="/read/1")

    assert "hover-popover-right" in popover
    assert "&lt;Reveal&gt;" in popover
    assert "<p>Safe</p>" in popover
    assert 'data-speak-text="cat"' in cell
    assert "&lt;cat&gt;" in cell
    assert _speak_button("   ") == ""
