"""Tests for cards page script rendering."""

from __future__ import annotations

from app.web.views.cards_script import _def_edit_script


def test_def_edit_script_contains_note_edit_contracts() -> None:
    script = _def_edit_script()

    assert "note-edit-btn" in script
    assert "PATCH" in script
    assert "user_note" in script


def test_def_edit_script_contains_translation_edit_contracts() -> None:
    script = _def_edit_script()

    assert "sentence-field-edit-btn" in script
    assert "sentence-field-input" in script
    assert "/mark/sentence/" in script
    assert "/translation" in script
    assert "user_translation" in script
    assert "user_note" in script
    assert "Enter a translation first." in script
    assert "Update translation" not in script
    assert "Add translation" not in script


def test_def_edit_script_contains_word_delete_contracts() -> None:
    script = _def_edit_script()

    assert "data-delete-word-card" in script
    assert "DELETE" in script
    assert "/mark/word/" in script
    assert "row.remove()" in script
