"""Tests for cards page rendering helpers."""

from __future__ import annotations

from app.web.views.cards import (
    _ai_meaning_cell,
    _cards_return_script,
    _note_edit_cell,
    _sentence_cards_table,
    _sentence_takeaway_cell,
    _sentence_translation_cell,
    _word_card_sources_page,
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
    assert "<th>Takeaway</th>" in html
    assert "<th>Notes</th>" not in html
    assert "<th>Actions</th>" in html
    assert 'data-delete-word-card="1"' in html
    assert 'data-delete-label="cat"' in html
    assert ">Delete</button>" in html
    assert 'href="/cards/word/1/sources"' in html


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


def test_sentence_cards_table_escapes_editable_fields_and_full_text() -> None:
    full_sentence = "This is a long source sentence that must not be truncated " * 3
    html = _sentence_cards_table(
        [
            {
                "id": 1,
                "sentence_id": 3,
                "mastery_state": "new",
                "due_at": "2026-06-17T00:00:00",
                "user_translation": "<translation>",
                "user_note": "<takeaway>",
                "sentence_text": full_sentence,
                "source_href": "/read/1?chapter=2&sentence_id=3&panel=analysis#sentence-3",
            }
        ]
    )

    assert "<th>Takeaway</th>" in html
    assert 'data-sentence-field="translation"' in html
    assert 'data-sentence-field="takeaway"' in html
    assert "&lt;translation&gt;" in html
    assert "&lt;takeaway&gt;" in html
    assert full_sentence in html
    assert (
        'href="/read/1?chapter=2&amp;sentence_id=3&amp;panel=analysis#sentence-3"'
        in html
    )


def test_sentence_translation_and_takeaway_cells_use_pencil_edit_controls() -> None:
    update_cell = _sentence_translation_cell(
        {"sentence_id": 3, "user_translation": "旧译文"}
    )
    add_cell = _sentence_translation_cell({"sentence_id": 4, "user_translation": ""})
    takeaway_cell = _sentence_takeaway_cell({"sentence_id": 5, "user_note": "复盘要点"})

    assert "旧译文" in update_cell
    assert "Update translation" not in update_cell
    assert "Add translation" not in add_cell
    assert 'class="note-edit-btn sentence-field-edit-btn"' in update_cell
    assert ">✎</button>" in update_cell
    assert 'class="sentence-field-input"' in update_cell
    assert 'placeholder="Edit your Chinese understanding"' in update_cell
    assert ">—</span>" in add_cell
    assert "复盘要点" in takeaway_cell
    assert 'data-sentence-field="takeaway"' in takeaway_cell
    assert 'placeholder="Edit your takeaway"' in takeaway_cell


def test_word_card_sources_page_renders_sources_candidates_and_forms() -> None:
    html = _word_card_sources_page(
        {"id": 1, "surface_form": "intangible", "lexical_type": "word"},
        [
            {
                "id": 10,
                "card_id": 1,
                "book_title": "Book",
                "source_href": "/read/1?chapter=1#sentence-2",
                "chapter_idx": 1,
                "sentence_text": "Bitcoin is intangible.",
                "is_primary": 1,
            }
        ],
        [
            {
                "sentence_id": 3,
                "book_title": "Book",
                "source_href": "/read/1?chapter=1#sentence-3",
                "chapter_idx": 1,
                "sentence_text": "Another intangible asset.",
                "is_recorded": 0,
                "is_primary": 0,
            }
        ],
    )

    assert "Sources: intangible" in html
    assert "Recorded Sources" in html
    assert "Find Occurrences" in html
    assert "Primary" in html
    assert 'action="/cards/word/1/sources"' in html
    assert "Add source" in html
