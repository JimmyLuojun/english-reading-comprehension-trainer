"""Tests for reader page rendering helpers."""

from __future__ import annotations

from app.web.views.reader import (
    _analysis_panel,
    _group_sentence_paragraphs,
    _highlight_word_cards,
    _paragraph_toolbar,
    _book_word_cards_with_terms,
    _reader_content_blocks,
    _reader_boundary_link,
    _reader_media_block,
    _reader_sentence_span,
    _reader_view,
    _selection_toolbar,
    _word_cards_by_sentence,
)


def test_analysis_panel_has_a_real_tools_handle() -> None:
    html = _analysis_panel()

    assert 'id="analysis-tools-handle"' in html
    assert 'aria-controls="analysis-panel-header"' in html
    assert 'id="analysis-panel-header"' in html


def test_group_sentence_paragraphs_and_word_card_index() -> None:
    rows = [
        {"id": 1, "paragraph_id": 10},
        {"id": 2, "paragraph_id": 10},
        {"id": 3, "paragraph_id": 11},
    ]
    cards = [
        {"id": 7, "source_sentence_id": 1},
        {"id": 8, "source_sentence_id": 1},
        {"id": 9},
    ]

    assert [[row["id"] for row in group] for group in _group_sentence_paragraphs(rows)] == [
        [1, 2],
        [3],
    ]
    grouped = _word_cards_by_sentence(cards)
    assert [card["id"] for card in grouped[1]] == [7, 8]
    assert 9 not in grouped


def test_highlight_word_cards_uses_exact_source_offsets() -> None:
    html = _highlight_word_cards(
        "long term memory long",
        [
            {
                "id": 1,
                "source_id": 11,
                "start_offset": 17,
                "end_offset": 21,
                "surface_form": "long",
                "lexical_type": "word",
                "has_analysis": 1,
                "current_meaning": "",
                "user_note": "",
            },
        ],
        7,
    )

    assert html.count('data-word-card="1"') == 1
    assert 'data-source-id="11"' in html
    assert 'data-source-start="17"' in html
    assert 'data-has-analysis="1"' in html
    assert ">long</span>" in html


def test_book_word_cards_are_deduplicated_and_book_scoped() -> None:
    cards = [
        {
            "id": 7,
            "surface_form": "Supposedly",
            "selected_text": "supposedly",
            "source_book_id": 3,
            "has_analysis": 1,
        },
        {
            "id": 7,
            "surface_form": "Supposedly",
            "selected_text": "SUPPOSEDLY",
            "source_book_id": 3,
            "has_analysis": 1,
        },
        {
            "id": 8,
            "surface_form": "elsewhere",
            "source_book_id": 4,
            "has_analysis": 1,
        },
        {
            "id": 9,
            "surface_form": "saved only",
            "source_book_id": 3,
            "has_analysis": 0,
        },
    ]

    result = _book_word_cards_with_terms(cards, 3)

    assert [card["id"] for card in result] == [7, 9]
    assert result[0]["prior_terms"] == ["supposedly"]


def test_highlight_word_cards_marks_unrecorded_repeat_as_prior_analysis() -> None:
    card = {
        "id": 7,
        "source_id": 17,
        "start_offset": 0,
        "end_offset": 10,
        "surface_form": "Supposedly",
        "lexical_type": "word",
        "has_analysis": 1,
        "current_meaning": "according to what is believed",
        "user_note": "",
    }
    html = _highlight_word_cards(
        "Supposedly true, and supposedly false.",
        [card],
        3,
        prior_analysis_cards=[{**card, "prior_terms": ["Supposedly"]}],
    )

    assert html.count('data-word-card="7"') == 1
    assert html.count('data-prior-analysis-card="7"') == 1
    assert 'class="prior-analysis-word"' in html
    assert 'data-has-analysis="1"' in html
    assert 'title="Analyzed earlier in this book — click to view"' in html
    assert ">supposedly</span> false" in html


def test_prior_analysis_matching_uses_whole_terms_and_longest_match() -> None:
    html = _highlight_word_cards(
        "A runaway can run the gauntlet, then run.",
        [],
        3,
        prior_analysis_cards=[
            {
                "id": 1,
                "prior_terms": ["run"],
                "lexical_type": "word",
            },
            {
                "id": 2,
                "prior_terms": ["run the gauntlet"],
                "lexical_type": "collocation",
            },
        ],
    )

    assert "runaway" in html
    assert 'data-prior-analysis-card="2"' in html
    assert ">run the gauntlet</span>" in html
    assert html.count('data-prior-analysis-card="1"') == 1


def test_unanalyzed_repeat_is_dormant_until_analysis_finishes() -> None:
    html = _highlight_word_cards(
        "The cat watched another cat.",
        [
            {
                "id": 7,
                "start_offset": 4,
                "end_offset": 7,
                "surface_form": "cat",
                "lexical_type": "word",
                "has_analysis": 0,
            }
        ],
        3,
        prior_analysis_cards=[
            {
                "id": 7,
                "prior_terms": ["cat"],
                "lexical_type": "word",
                "has_analysis": 0,
            }
        ],
    )

    assert 'data-prior-analysis-card="7"' in html
    assert 'data-has-analysis="0"' in html
    assert "Analyzed earlier in this book" not in html


def test_highlight_word_cards_infers_unique_source_without_offsets() -> None:
    html = _highlight_word_cards(
        "The first count in the indictment...",
        [
            {
                "id": 1,
                "source_id": 11,
                "surface_form": "indictment",
                "lexical_type": "word",
                "current_meaning": "",
                "user_note": "",
            }
        ],
        7,
    )

    assert html.count('data-word-card="1"') == 1
    assert 'data-source-start="23"' in html
    assert 'data-source-end="33"' in html
    assert 'data-has-analysis="0"' in html
    assert ">indictment</span>..." in html


def test_highlight_word_cards_uses_selected_text_when_surface_is_stale() -> None:
    html = _highlight_word_cards(
        "The first count in the indictment...",
        [
            {
                "id": 1,
                "source_id": 11,
                "selected_text": "indictment",
                "surface_form": "count",
                "lemma": "count",
                "lexical_type": "word",
                "current_meaning": "",
                "user_note": "",
            }
        ],
        7,
    )

    assert html.count('data-word-card="1"') == 1
    assert ">indictment</span>..." in html


def test_highlight_word_cards_leaves_ambiguous_no_offset_source_plain() -> None:
    html = _highlight_word_cards(
        "long term memory long",
        [
            {
                "id": 1,
                "surface_form": "long",
                "lexical_type": "word",
                "current_meaning": "",
                "user_note": "",
            }
        ],
        7,
    )

    assert 'data-word-card="1"' not in html
    assert html == "long term memory long"


def test_highlight_word_cards_does_not_infer_inside_larger_word() -> None:
    html = _highlight_word_cards(
        "concatenate values",
        [
            {
                "id": 1,
                "surface_form": "cat",
                "lexical_type": "word",
                "current_meaning": "",
                "user_note": "",
            }
        ],
        7,
    )

    assert 'data-word-card="1"' not in html
    assert html == "concatenate values"


def test_highlight_word_cards_ignores_invalid_and_overlapping_offsets() -> None:
    html = _highlight_word_cards(
        "abcdef",
        [
            {
                "id": 1,
                "source_id": 11,
                "start_offset": -1,
                "end_offset": 2,
                "lexical_type": "word",
            },
            {
                "id": 2,
                "source_id": 12,
                "start_offset": 1,
                "end_offset": 4,
                "lexical_type": "word",
            },
            {
                "id": 3,
                "source_id": 13,
                "start_offset": 2,
                "end_offset": 5,
                "lexical_type": "word",
            },
        ],
        7,
    )

    assert 'data-word-card="1"' not in html
    assert 'data-word-card="2"' in html
    assert 'data-word-card="3"' not in html


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
            "user_structure": "<structure>",
            "ai_analysis_id": 9,
        },
        2,
        [
            {
                "id": 3,
                "source_id": 5,
                "start_offset": 4,
                "end_offset": 7,
                "surface_form": "cat",
                "lexical_type": "word",
                "current_meaning": "meaning",
                "user_note": "",
            }
        ],
        7,
    )

    assert 'class="reader-sentence marked translated analyzed-stale"' in html
    assert 'title="Translation saved"' in html
    assert 'data-translation="&lt;translation&gt;"' in html
    assert 'data-note="&lt;takeaway&gt;"' in html
    assert 'data-structure="&lt;structure&gt;"' in html
    assert 'data-analysis-id="9"' in html
    assert 'data-word-card="3"' in html
    assert 'data-source-id="5"' in html
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
        7,
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
        7,
    )

    assert 'class="reader-sentence translated"' in html
    assert 'class="reader-sentence marked' not in html
    assert 'data-marked="0"' in html
    assert 'data-translation="猫坐着。"' in html


def test_reader_sentence_span_renders_markdown_inline_image_tokens() -> None:
    html = _reader_sentence_span(
        {
            "id": 1,
            "text": "If [[md-image:42]] is true.",
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        },
        2,
        [],
        7,
    )

    assert "[[md-image" not in html
    assert '<img class="reader-inline-image" src="/assets/books/7/42" alt="">' in html


def test_reader_paragraph_includes_paragraph_id() -> None:
    html = _reader_content_blocks(
        rows=[
            {
                "id": 1,
                "idx": 0,
                "text": "The cat sat.",
                "paragraph_id": 77,
                "has_card": 0,
                "has_analysis": 0,
                "analysis_is_stale": 0,
                "user_translation": "",
                "ai_analysis_id": None,
            }
        ],
        blocks=[],
        chapter_id=5,
        cards_by_sentence={},
        book_id=7,
    )

    assert '<p class="reader-para" data-paragraph-id="77">' in html


def test_reader_paragraph_marks_saved_logic_analysis() -> None:
    html = _reader_content_blocks(
        rows=[
            {
                "id": 1,
                "idx": 0,
                "text": "The cat sat.",
                "paragraph_id": 77,
                "has_card": 0,
                "has_analysis": 0,
                "analysis_is_stale": 0,
                "user_translation": "",
                "ai_analysis_id": None,
                "paragraph_has_analysis": 1,
                "paragraph_ai_analysis_id": 42,
                "paragraph_analysis_is_stale": 0,
            }
        ],
        blocks=[],
        chapter_id=5,
        cards_by_sentence={},
        book_id=7,
    )

    assert 'class="reader-para logic-analyzed"' in html
    assert 'data-paragraph-analysis-id="42"' in html
    assert 'data-paragraph-analysis-state="current"' in html
    assert 'title="Paragraph AI analysis saved"' in html


def test_paragraph_toolbar_is_separate_from_selection_toolbar() -> None:
    html = _paragraph_toolbar()

    assert 'id="paragraph-toolbar"' in html
    assert 'id="paragraph-analyze"' in html
    assert 'id="paragraph-copy-prompt"' in html
    assert "Analyze argument" in html
    assert "Copy prompt" in html
    assert 'id="selection-toolbar"' not in html


def test_selection_toolbar_contains_translation_editor_without_delete_action() -> None:
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

    assert 'id="toolbar-translation-delete"' not in html
    assert "Delete translation" not in html
    assert 'id="toolbar-translation-open"' in html
    assert "Write translation" in html
    assert 'id="toolbar-structure-open"' in html
    assert 'id="toolbar-external-prompt"' in html
    assert 'id="toolbar-word-analyze"' in html
    assert 'id="toolbar-word-copy-prompt"' in html
    assert 'id="toolbar-word-note"' in html
    assert 'aria-label="Meaning and usage note"' in html
    assert 'id="toolbar-word-save" type="submit"' in html
    assert ">Save to review</button>" in html
    assert 'id="toolbar-word-status"' in html
    assert 'class="word-toolbar-segment"' in html
    assert 'type="button" name="lexical_type" value="word" data-word-lexical="word"' in html
    assert (
        'type="button" name="lexical_type" value="phrase" data-word-lexical="phrase"'
        in html
    )
    assert (
        'type="button" name="lexical_type" value="collocation" '
        'data-word-lexical="collocation"'
    ) in html
    assert ">AI analysis</button>" in html
    assert ">Copy prompt</button>" in html
    assert "Copy AI prompt" in html
    assert 'id="toolbar-structure-editor"' in html
    assert "Write structure" in html
    assert "指代逻辑：" in html
    assert ">Close</button>" in html
    assert "Save and AI check" in html
    assert "hidden" in html
    assert '"lexical_type": "word"' in html
    assert 'data-analysis-mark="word">Mark word</button>' in html
    assert 'type="button" name="lexical_type" value="word" data-analysis-mark="word"' in html


def test_selection_toolbar_word_detail_uses_takeaway_label() -> None:
    html = _selection_toolbar("/read/1", [])

    assert 'class="word-detail-heading"' in html
    assert 'id="toolbar-word-detail-pronunciation"' in html
    assert 'data-speak-text=""' in html
    assert 'aria-label="Play pronunciation"' in html
    assert "▶ Listen</button>" in html
    assert ">Takeaway\n" in html
    assert 'id="toolbar-word-detail-note"' in html
    assert "What I should remember" in html
    assert ">Note\n" not in html
    assert "Your note…" not in html


def test_analysis_panel_wraps_optional_structure_sections() -> None:
    html = _analysis_panel()

    assert 'id="analysis-modifiers-section"' in html
    assert 'id="analysis-logic-markers-section"' in html
    assert 'id="analysis-anaphora-section"' in html
    assert 'id="analysis-copy-all"' in html
    assert 'id="analysis-copy-prompt"' in html
    assert 'id="analysis-copy-source"' in html
    assert 'id="analysis-copy-analysis"' in html
    assert 'id="analysis-copy-status"' in html
    assert 'id="analysis-external-section"' in html
    assert 'id="analysis-external-result"' in html
    assert 'id="analysis-external-save"' in html
    assert "Paste external result" in html
    assert "Enter saves · Shift+Enter adds a line" in html
    assert "Copy all" in html
    assert "Copy source" in html
    assert "Copy analysis" in html
    assert html.index('id="analysis-modifiers-section"') < html.index(
        'id="analysis-modifiers"'
    )


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

    assert '<a class="button small" href="/books">Library</a>' in html
    assert '<a class="button small" href="/books/7">Item details</a>' in html


def test_reader_view_uses_type_aware_heading_and_navigation() -> None:
    common = {
        "rows": [],
        "return_to": "/read/7",
        "chapter_id": 9,
        "word_cards": [],
        "book_id": 7,
        "book_title": "Reading",
        "chapter_idx": 1,
        "chapter_title": "Chapter 1",
        "section_kind": "chapter",
        "chapter_number": 1,
        "restore_progress": False,
        "total_sections": 1,
    }

    article = _reader_view(**common, content_kind="article")
    excerpt = _reader_view(**common, content_kind="excerpt")
    unclassified = _reader_view(**common, content_kind="unclassified")

    assert 'class="reader-chapter"' not in article
    assert '>Item details</a>' in article
    assert 'class="reader-chapter"' not in excerpt
    assert '>Item details</a>' in excerpt
    assert '<h2 class="reader-chapter">Section 1</h2>' in unclassified

    multi_section = _reader_view(**{**common, "total_sections": 2}, content_kind="book")
    assert '<a class="button small" href="/books/7/contents">Contents</a>' in multi_section
    multi_but_not_meaningful = _reader_view(
        **{**common, "total_sections": 2},
        content_kind="book",
        has_contents=False,
    )
    assert '>Item details</a>' in multi_but_not_meaningful


def test_reader_content_blocks_render_markdown_headings_and_lists() -> None:
    rows = [
        {
            "id": 1,
            "idx": 0,
            "text": "First item sentence.",
            "paragraph_id": 10,
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        },
        {
            "id": 2,
            "idx": 1,
            "text": "Second item sentence.",
            "paragraph_id": 11,
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        },
        {
            "id": 3,
            "idx": 2,
            "text": "Normal paragraph.",
            "paragraph_id": 12,
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        },
    ]
    blocks = [
        {
            "kind": "heading",
            "text": "7.1: Rules of Implication I",
            "payload_json": '{"level": 3}',
        },
        {"kind": "list_item", "paragraph_id": 10, "payload_json": '{"ordered": true}'},
        {"kind": "list_item", "paragraph_id": 11, "payload_json": '{"ordered": true}'},
        {"kind": "prose", "paragraph_id": 12, "payload_json": ""},
    ]

    html = _reader_content_blocks(
        rows=rows,
        blocks=blocks,
        chapter_id=5,
        cards_by_sentence={},
        book_id=7,
    )

    assert '<h5 class="reader-md-heading reader-md-heading-level-3">' in html
    assert "7.1: Rules of Implication I" in html
    assert '<ol class="reader-md-list">' in html
    assert html.count('<li class="reader-md-list-item">') == 2
    assert 'data-sentence-id="1"' in html
    assert 'data-sentence-id="2"' in html
    assert '<p class="reader-para" data-paragraph-id="12">' in html
    assert 'data-sentence-id="3"' in html


def test_reader_content_blocks_flushes_when_list_mode_changes() -> None:
    rows = [
        {
            "id": 1,
            "idx": 0,
            "text": "Ordered item.",
            "paragraph_id": 10,
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        },
        {
            "id": 2,
            "idx": 1,
            "text": "Unordered item.",
            "paragraph_id": 11,
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        },
    ]
    blocks = [
        {"kind": "list_item", "paragraph_id": 10, "payload_json": '{"ordered": true}'},
        {"kind": "list_item", "paragraph_id": 11, "payload_json": '{"ordered": false}'},
    ]

    html = _reader_content_blocks(
        rows=rows,
        blocks=blocks,
        chapter_id=5,
        cards_by_sentence={},
        book_id=7,
    )

    assert '<ol class="reader-md-list">' in html
    assert '<ul class="reader-md-list">' in html


def test_reader_content_blocks_treats_malformed_payload_as_unordered() -> None:
    rows = [
        {
            "id": 1,
            "idx": 0,
            "text": "Malformed list payload.",
            "paragraph_id": 10,
            "has_card": 0,
            "has_analysis": 0,
            "analysis_is_stale": 0,
            "user_translation": "",
            "ai_analysis_id": None,
        }
    ]
    blocks = [{"kind": "list_item", "paragraph_id": 10, "payload_json": "{bad json"}]

    html = _reader_content_blocks(
        rows=rows,
        blocks=blocks,
        chapter_id=5,
        cards_by_sentence={},
        book_id=7,
    )

    assert '<ul class="reader-md-list">' in html


def test_reader_content_blocks_uses_default_heading_payload_on_malformed_json() -> None:
    html = _reader_content_blocks(
        rows=[],
        blocks=[{"kind": "heading", "text": "Broken heading", "payload_json": "{bad"}],
        chapter_id=5,
        cards_by_sentence={},
        book_id=7,
    )

    assert '<h4 class="reader-md-heading reader-md-heading-level-2">' in html
    assert "Broken heading" in html


def test_analysis_panel_contains_translation_and_takeaway_editors() -> None:
    html = _analysis_panel()

    assert 'id="sentence-panel-translation"' in html
    assert 'id="sentence-panel-analyzed-translation-section"' in html
    assert 'id="sentence-panel-analyzed-translation"' in html
    assert 'id="sentence-panel-translation-diff"' in html
    assert 'id="sentence-panel-translation-diff-count"' in html
    assert 'id="sentence-panel-translation-diff-list"' in html
    assert "Initial translation analyzed" in html
    assert "Changes since this analysis" in html
    assert "Your translation" in html
    assert 'id="analysis-paragraph-sections"' in html
    assert 'id="analysis-paragraph-main-claim"' in html
    assert 'id="analysis-paragraph-flow"' in html
    assert 'id="analysis-paragraph-evidence"' in html
    assert "Paragraph main claim" in html
    assert "Argument flow" in html
    assert "Hidden assumption" in html
    assert 'id="sentence-panel-structure"' in html
    assert 'id="sentence-panel-analyzed-structure-section"' in html
    assert 'id="sentence-panel-analyzed-structure"' in html
    assert 'id="sentence-panel-structure-diff"' in html
    assert 'id="sentence-panel-structure-diff-count"' in html
    assert 'id="sentence-panel-structure-diff-list"' in html
    assert "Initial structure analyzed" in html
    assert 'id="analysis-structure-attempt-section"' in html
    assert 'id="analysis-structure-feedback-section"' in html
    assert "Your structure attempt" in html
    assert "Structure feedback" in html
    assert 'id="analysis-blocking-point"' in html
    assert 'id="analysis-argument-role"' in html
    assert 'id="analysis-argument-role-reason"' in html
    assert 'id="analysis-argument-role-check"' in html
    assert "Argument role" in html
    assert "Why this role" in html
    assert "Reading check" in html
    assert 'id="analysis-clauses"' in html
    assert 'id="analysis-back-to-whole"' in html
    assert 'id="sentence-panel-note"' in html
    assert 'id="sentence-panel-note-suggestion"' in html
    assert 'id="sentence-panel-note-accept"' in html
    assert "Takeaway" in html
    assert "Save takeaway" in html
    assert 'id="analysis-word-role"' in html
    assert 'id="analysis-panel-tab"' in html
    assert 'id="analysis-external-clear"' in html
    assert 'id="analysis-external-status"' in html
    assert 'aria-controls="analysis-panel"' in html
    assert html.index("Simplified English") < html.index("Blocking point")
    assert html.index("Blocking point") < html.index("Structure")
    assert html.index("Structure") < html.index("Diagnosis")
    assert html.index("Diagnosis") < html.index("Back to whole sentence")
    assert html.index("Back to whole sentence") < html.index('id="sentence-panel-translation"')
    assert html.index('id="sentence-panel-analyzed-translation-section"') < html.index(
        'id="sentence-panel-translation"'
    )
    assert html.index('id="sentence-panel-translation"') < html.index(
        'id="sentence-panel-structure"'
    )
    assert html.index('id="sentence-panel-analyzed-structure-section"') < html.index(
        'id="sentence-panel-structure"'
    )
    assert html.index("Your structure attempt") < html.index("Structure feedback")
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
    assert _reader_media_block({"kind": "image", "asset_id": None, "text": ""}, 5) == ""
