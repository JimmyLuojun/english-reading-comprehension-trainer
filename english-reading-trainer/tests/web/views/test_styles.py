"""Tests for global CSS rendering."""

from __future__ import annotations

from app.web.views.styles import _css


def test_css_contains_reader_and_popover_selectors() -> None:
    css = _css()

    assert ".reader-sentence" in css
    assert ".hover-popover-panel" in css
    assert "bottom: calc(100% + 8px)" in css
    assert "right: 0" in css
    assert ".analysis-panel" in css
    assert ".analysis-section h4" in css
    assert "#sentence-panel-note-accept" in css
    assert "--analysis-panel-width: 520px" in css
    assert "@media (min-width: 1180px)" in css
    assert "padding-right: var(--analysis-panel-width)" in css
    assert "@media (max-width: 1179px)" in css
    assert ".analysis-panel-tab" in css
    assert ".analysis-open .analysis-panel-tab" in css
    assert "#toolbar-analysis-word-status" in css
    assert "[data-sentence-id].translated" in css
    assert "text-decoration-style: dotted" in css
    assert ".speak-button" in css
    assert ".word-card-delete" in css
    assert ".metric-link:hover" in css
    assert ".reader-header-actions" in css
    assert ".sentence-field-cell" in css
    assert ".sentence-field-input" in css
    assert ".sentence-field-edit[hidden]" in css
    assert "max-height: min(52vh, 360px)" in css
    assert ".similar-mistakes" in css
    assert ".similar-mistake-comparison" in css
