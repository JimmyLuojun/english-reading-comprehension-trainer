"""Tests for global CSS rendering."""

from __future__ import annotations

from app.web.views.styles import _css


def test_css_contains_reader_and_popover_selectors() -> None:
    css = _css()

    assert ".reader-sentence" in css
    assert ".hover-popover-panel" in css
    assert ".analysis-panel" in css
    assert ".speak-button" in css
