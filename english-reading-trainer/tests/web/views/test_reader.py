"""Tests for reader page rendering helpers."""

from __future__ import annotations

from app.web.views.reader import (
    _analysis_panel,
    _group_sentence_paragraphs,
    _highlight_word_cards,
    _reader_boundary_link,
    _reader_media_block,
    _reader_sentence_span,
    _reader_view,
    _selection_toolbar,
    _word_cards_by_sentence,
)


def test_group_sentence_paragraphs_and_word_card_index() -> None:
    rows = [
        {"id": 1, "paragraph_id": 10},
        {"id": 2, "paragraph_id": 10},
        {"id": 3, "paragraph_id": 11},
    ]
    cards = [{"id": 7, "first_sentence_id": 1}, {"id": 8, "first_sentence_id": 1}]

    assert [[row["id"] for row in group] for group in _group_sentence_paragraphs(rows)] == [
        [1, 2],
        [3],
    ]
    assert [card["id"] for card in _word_cards_by_sentence(cards)[1]] == [7, 8]


def test_highlight_word_cards_prefers_long_non_overlapping_match() -> None:
    html = _highlight_word_cards(
        "long term memory",
        [
            {"id": 1, "surface_form": "long", "current_meaning": "", "user_note": ""},
            {"id": 2, "surface_form": "long term", "current_meaning": "phrase", "user_note": ""},
        ],
    )

    assert 'data-word-card="2"' in html
    assert 'data-word-card="1"' not in html


def test_reader_sentence_span_marks_state_and_escapes_translation() -> None:
    html = _reader_sentence_span(
        {
            "id": 1,
            "text": "The cat sat.",
            "has_card": 1,
            "has_analysis": 1,
            "analysis_is_stale": 1,
            "user_translation": "<translation>",
            "user_note": "<takeaway>",
            "ai_analysis_id": 9,
        },
        2,
        [{"id": 3, "surface_form": "cat", "current_meaning": "meaning", "user_note": ""}],
    )

    assert 'class="reader-sentence marked translated analyzed-stale"' in html
    assert 'title="Translation saved"' in html
    assert 'data-translation="&lt;translation&gt;"' in html
    assert 'data-note="&lt;takeaway&gt;"' in html
    assert 'data-word-card="3"' in html


def test_reader_sentence_span_can_show_translation_without_marked_state() -> None:
    html = _reader_sentence_span(
        {
            "id": 1,
            "text": "The cat sat.",
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "猫坐着。",
            "ai_analysis_id": None,
        },
        2,
        [],
    )

    assert 'class="reader-sentence translated"' in html
    assert 'class="reader-sentence marked' not in html
    assert 'data-marked="0"' in html
    assert 'data-translation="猫坐着。"' in html


def test_selection_toolbar_contains_delete_translation_action() -> None:
    html = _selection_toolbar("/read/1", [])

    assert 'id="toolbar-translation-delete"' in html
    assert "Delete translation" in html
    assert "hidden" in html


def test_reader_view_has_book_and_chapter_navigation() -> None:
    html = _reader_view(
        rows=[],
        return_to="/read/7",
        chapter_id=9,
        word_cards=[],
        book_id=7,
        book_title="Book",
        chapter_idx=1,
        chapter_title="Chapter 1",
        section_kind="chapter",
        chapter_number=1,
        restore_progress=False,
    )

    assert '<a class="button small" href="/books">All books</a>' in html
    assert '<a class="button small" href="/books/7">Chapters</a>' in html


def test_analysis_panel_contains_translation_and_takeaway_editors() -> None:
    html = _analysis_panel()

    assert 'id="sentence-panel-translation"' in html
    assert "Your translation" in html
    assert 'id="sentence-panel-note"' in html
    assert "Takeaway" in html
    assert "Save takeaway" in html
    assert 'id="analysis-panel-tab"' in html
    assert 'aria-controls="analysis-panel"' in html
    assert html.index("Subject skeleton") < html.index("Your translation")
    assert html.index("Your translation") < html.index("Takeaway")


def test_reader_media_and_boundary_links() -> None:
    assert "/read/5?chapter=2#chapter-end" in _reader_boundary_link(
        5,
        {"idx": 2, "title": "Chapter 2", "section_kind": "chapter", "chapter_number": 2},
        "previous",
    )
    assert "reader-missing-asset" in _reader_media_block(
        {"kind": "missing_asset", "text": "Missing", "asset_is_missing": 1},
        5,
    )
    assert "/assets/books/5/9" in _reader_media_block(
        {
            "kind": "image",
            "asset_id": 9,
            "text": "Caption",
            "asset_alt_text": "Alt",
            "asset_is_missing": 0,
        },
        5,
    )
