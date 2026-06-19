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
            {"id": 1, "surface_form": "long", "lexical_type": "word", "current_meaning": "", "user_note": ""},
            {"id": 2, "surface_form": "long term", "current_meaning": "phrase", "user_note": ""},
        ],
    )

    assert 'data-word-card="2"' in html
    assert 'data-lexical-type=""' in html
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
        [
            {
                "id": 3,
                "surface_form": "cat",
                "lexical_type": "word",
                "current_meaning": "meaning",
                "user_note": "",
            }
        ],
    )

    assert 'class="reader-sentence marked translated analyzed-stale"' in html
    assert 'title="Translation saved"' in html
    assert 'data-translation="&lt;translation&gt;"' in html
    assert 'data-note="&lt;takeaway&gt;"' in html
    assert 'data-analysis-id="9"' in html
    assert 'data-word-card="3"' in html
    assert 'data-lexical-type="word"' in html


def test_reader_sentence_span_omits_invalid_analysis_id() -> None:
    html = _reader_sentence_span(
        {
            "id": 1,
            "text": "The cat sat.",
            "has_card": 1,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "user_note": "",
            "ai_analysis_id": 9,
        },
        2,
        [],
    )

    assert 'class="reader-sentence marked"' in html
    assert 'data-analysis-id=""' in html
    assert "analyzed" not in html


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
    html = _selection_toolbar(
        "/read/1",
        [
            {
                "id": 3,
                "lemma": "cat",
                "surface_form": "cat",
                "lexical_type": "word",
                "current_meaning": "",
                "user_note": "",
            }
        ],
    )

    assert 'id="toolbar-translation-delete"' in html
    assert "Delete translation" in html
    assert "hidden" in html
    assert '"lexical_type": "word"' in html
    assert 'data-analysis-mark="word">Mark word</button>' in html
    assert 'type="button" name="lexical_type" value="word" data-analysis-mark="word"' in html


def test_selection_toolbar_word_detail_uses_takeaway_label() -> None:
    html = _selection_toolbar("/read/1", [])

    assert ">Takeaway\n" in html
    assert 'id="toolbar-word-detail-note"' in html
    assert "What I should remember" in html
    assert ">Note\n" not in html
    assert "Your note…" not in html


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
    assert 'id="analysis-blocking-point"' in html
    assert 'id="analysis-clauses"' in html
    assert 'id="analysis-back-to-whole"' in html
    assert 'id="sentence-panel-note"' in html
    assert 'id="sentence-panel-note-suggestion"' in html
    assert 'id="sentence-panel-note-accept"' in html
    assert "Takeaway" in html
    assert "Save takeaway" in html
    assert 'id="analysis-word-role"' in html
    assert 'id="analysis-panel-tab"' in html
    assert 'aria-controls="analysis-panel"' in html
    assert html.index("Simplified English") < html.index("Blocking point")
    assert html.index("Blocking point") < html.index("Structure")
    assert html.index("Structure") < html.index("Diagnosis")
    assert html.index("Diagnosis") < html.index("Back to whole sentence")
    assert html.index("Back to whole sentence") < html.index("Your translation")
    assert html.index("Your translation") < html.index("Takeaway")


def test_analysis_panel_word_card_uses_takeaway_not_notes() -> None:
    html = _analysis_panel()

    assert "Takeaway check" in html
    assert "My word card" in html
    assert 'id="word-panel-note"' in html
    assert 'id="analysis-word-note-check"' in html
    # Stale "Note(s)" labels must not leak back into the Word Analysis panel.
    assert "My notes" not in html
    assert "Your note check" not in html
    assert "My understanding" not in html
    assert 'class="word-notes-label">Notes' not in html


def test_analysis_panel_labels_are_bilingual() -> None:
    html = _analysis_panel()
    assert '<span class="section-label-zh">简化英文</span>' in html
    assert '<span class="section-label-en">Simplified English</span>' in html
    assert '<span class="section-label-zh">中文释义</span>' in html
    assert '<span class="section-label-en">Chinese meaning</span>' in html
    assert '<span class="section-label-zh">阅读卡点</span>' in html
    assert '<span class="section-label-zh">收获</span>' in html
    # The legacy jargon label must be gone.
    assert "Chinese gloss" not in html


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
