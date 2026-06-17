"""Tests for book and chapter rendering helpers."""

from __future__ import annotations

from app.web.views.books import (
    _appendix_letter,
    _books_table,
    _chapters_table,
    _primary_read_idx,
    _section_label,
    _strip_appendix_ordinal,
    _strip_section_ordinal,
)


def test_books_table_renders_rows_and_empty_state() -> None:
    assert _books_table([]) == '<p class="empty">No books imported yet.</p>'

    html = _books_table(
        [
            {
                "id": 1,
                "title": "<Book>",
                "author": "Author",
                "source_format": "txt",
                "total_chapters": 2,
                "total_sentences": 3,
            }
        ]
    )

    assert "&lt;Book&gt;" in html
    assert "/books/1/delete" in html


def test_chapter_labels_and_primary_read_idx() -> None:
    chapter = {
        "idx": 2,
        "title": "Chapter 2: Methods",
        "section_kind": "chapter",
        "chapter_number": 2,
    }
    appendix = {"idx": 3, "title": "Appendix A. Data", "section_kind": "appendix"}
    rows = [
        {"idx": 1, "title": "Preface", "section_kind": "frontmatter"},
        chapter,
    ]

    assert _section_label(chapter) == "Chapter 2: Methods"
    assert _section_label(appendix) == "Appendix A: Data"
    assert _strip_section_ordinal("Chapter 10 - Title") == "Title"
    assert _appendix_letter("Appendix B") == "B"
    assert _strip_appendix_ordinal("Appendix B: Notes") == "Notes"
    assert _primary_read_idx(rows) == 2
    assert _primary_read_idx([]) is None


def test_chapters_table_renders_read_links() -> None:
    html = _chapters_table(
        7,
        [
            {
                "idx": 1,
                "title": "Chapter 1",
                "section_kind": "chapter",
                "chapter_number": 1,
                "sentence_start": 0,
                "sentence_end": 2,
            }
        ],
    )

    assert "/read/7?chapter=1" in html
    assert "<td>2</td>" in html
