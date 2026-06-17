"""Tests for reader browser interaction script rendering."""

from __future__ import annotations

from app.web.views.reader_script import _selection_script


def test_selection_script_contains_reader_toolbar_contracts() -> None:
    script = _selection_script()

    assert "selection-toolbar" in script
    assert "toolbar-analysis-word-form" in script
    assert "restoreProgress" in script
    assert "analysisHistory" in script
