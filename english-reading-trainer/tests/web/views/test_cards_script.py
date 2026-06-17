"""Tests for cards page script rendering."""

from __future__ import annotations

from app.web.views.cards_script import _def_edit_script


def test_def_edit_script_contains_note_edit_contracts() -> None:
    script = _def_edit_script()

    assert "note-edit-btn" in script
    assert "PATCH" in script
    assert "user_note" in script
