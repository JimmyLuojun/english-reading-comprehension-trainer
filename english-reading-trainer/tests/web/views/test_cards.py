"""Tests for cards page rendering helpers."""

from __future__ import annotations

from app.web.views.cards import (
    _ai_meaning_cell,
    _cards_return_script,
    _note_edit_cell,
    _sentence_cards_table,
    _word_cards_table,
)


def test_sentence_and_word_cards_empty_states() -> None:
    assert _sentence_cards_table([]) == '<p class="empty">No sentence cards.</p>'
    assert _word_cards_table([]) == '<p class="empty">No word cards.</p>'


def test_word_cards_table_renders_notes_ai_and_source() -> None:
    card = {
        "id": 1,
        "surface_form": "cat",
        "lexical_type": "word",
        "mastery_state": "new",
        "occurrence_count": 2,
        "user_note": "my note",
        "current_meaning": "definition",
        "ai_meaning": "AI meaning",
        "first_book_title": "Book",
        "source_href": "/read/1#sentence-1",
    }

    html = _word_cards_table([card])

    assert 'id="card-1"' in html
    assert "my note" in _note_edit_cell(card)
    assert "Reveal" in _ai_meaning_cell(card)
    assert "/read/1#sentence-1" in html


def test_note_cell_hides_ai_duplicate_and_return_script_links_back() -> None:
    cell = _note_edit_cell(
        {
            "id": 1,
            "user_note": "same",
            "current_meaning": "same",
            "ai_meaning": "same",
        }
    )

    assert '<span class="note-text" data-card-id="1">—</span>' in cell
    assert "glossary_return_url" in _cards_return_script()


def test_sentence_cards_table_escapes_translation() -> None:
    html = _sentence_cards_table(
        [
            {
                "id": 1,
                "mastery_state": "new",
                "due_at": "2026-06-17T00:00:00",
                "user_translation": "<translation>",
                "sentence_text": "Sentence",
            }
        ]
    )

    assert "&lt;translation&gt;" in html
