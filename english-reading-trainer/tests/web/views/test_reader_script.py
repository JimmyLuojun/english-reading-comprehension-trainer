"""Tests for reader browser interaction script rendering."""

from __future__ import annotations

from app.web.views.reader_script import _selection_script


def test_selection_script_contains_reader_toolbar_contracts() -> None:
    script = _selection_script()

    assert "selection-toolbar" in script
    assert "toolbar-analysis-word-form" in script
    assert "restoreProgress" in script
    assert "analysisHistory" in script


def test_analysis_selection_toolbar_uses_cancellable_deferred_hide() -> None:
    script = _selection_script()

    assert "let toolbarHideTimer = null;" in script
    assert "function clearScheduledToolbarHide()" in script
    assert "function scheduleToolbarHide(delay)" in script
    assert "scheduleToolbarHide(650);" in script
    assert "window.setTimeout(() => {\n            hideToolbar();" not in script

    hide_toolbar = script[script.index("function hideToolbar()"):]
    hide_toolbar = hide_toolbar[:hide_toolbar.index("function setVisible")]
    assert "clearScheduledToolbarHide();" in hide_toolbar
    assert hide_toolbar.index("clearScheduledToolbarHide();") < hide_toolbar.index("hideAllPanels();")

    position_toolbar = script[script.index("function positionToolbar(anchor)"):]
    position_toolbar = position_toolbar[:position_toolbar.index("function showToolbar")]
    assert "clearScheduledToolbarHide();" in position_toolbar
    assert position_toolbar.index("clearScheduledToolbarHide();") < position_toolbar.index(
        "toolbar.hidden = false;"
    )


def test_analysis_selection_toolbar_reenables_buttons_when_shown() -> None:
    script = _selection_script()
    show_toolbar = script[script.index("function showAnalysisWordToolbar"):]
    show_toolbar = show_toolbar[:show_toolbar.index("function applyGlossaryHighlights")]

    assert "setAnalysisWordButtonsDisabled(false);" in show_toolbar
    assert show_toolbar.index("setAnalysisWordButtonsDisabled(false);") < show_toolbar.index(
        "setVisible(analysisWordForm, true);"
    )
