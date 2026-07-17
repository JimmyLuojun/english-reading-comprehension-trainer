"""Tests for book and chapter rendering helpers."""

from __future__ import annotations

from app.web.views.books import (
    _appendix_letter,
    _books_table,
    _chapters_table,
    _library_filters,
    _library_item_form,
    _primary_read_idx,
    _section_label,
    _strip_appendix_ordinal,
    _strip_section_ordinal,
)


def test_books_table_renders_rows_and_empty_state() -> None:
    assert _books_table([]) == '<p class="empty">No Library Items found.</p>'

    html = _books_table(
        [
            {
                "id": 1,
                "title": "<Book>",
                "author": "Author",
                "source_format": "txt",
                "content_kind": "article",
                "library_status": "reading",
                "tags": "Trade",
                "total_chapters": 2,
                "total_sentences": 3,
            }
        ],
        return_to="/books?content_kind=article&tag=%3Cunsafe%3E",
    )

    assert "&lt;Book&gt;" in html
    assert 'class="library-table"' in html
    assert 'id="library-item-form-1"' in html
    assert 'name="content_kind" form="library-item-form-1"' in html
    assert 'value="article" selected' in html
    assert 'name="library_status" form="library-item-form-1"' in html
    assert 'value="reading" selected' in html
    assert 'name="tags" form="library-item-form-1" value="Trade"' in html
    assert 'name="title" value="&lt;Book&gt;"' in html
    assert (
        'name="return_to" '
        'value="/books?content_kind=article&amp;tag=%3Cunsafe%3E"'
    ) in html
    assert ">Save</button>" in html
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
    assert _section_label({"idx": 4, "title": "Extra Data", "section_kind": "appendix"}) == (
        "Appendix: Extra Data"
    )
    assert _strip_section_ordinal("Chapter 10 - Title") == "Title"
    assert _strip_section_ordinal("Chapter 1") == ""
    assert _strip_section_ordinal("Chapter One: A New Way") == "A New Way"
    assert _section_label(
        {
            "idx": 1,
            "title": "Chapter 1",
            "section_kind": "chapter",
            "chapter_number": None,
        }
    ) == "Chapter 1"
    assert _section_label(
        {
            "idx": 1,
            "title": "Chapter One: A New Way of Learning",
            "section_kind": "chapter",
            "chapter_number": 1,
        }
    ) == "Chapter 1: A New Way of Learning"
    assert _appendix_letter("Appendix B") == "B"
    assert _strip_appendix_ordinal("Appendix B: Notes") == "Notes"
    assert _primary_read_idx(rows) == 2
    assert _primary_read_idx([]) is None


def test_chapters_table_makes_every_readable_section_row_clickable() -> None:
    assert _chapters_table(7, []) == '<p class="empty">No readable sections found.</p>'

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
            },
            {
                "idx": 2,
                "title": "Appendix A: Sources",
                "section_kind": "appendix",
                "chapter_number": None,
                "sentence_start": 2,
                "sentence_end": 3,
            },
        ],
    )

    assert 'class="chapter-table"' in html
    assert '<th>Chapter</th><th>Sentences</th></tr>' in html
    assert html.count('class="chapter-row chapter-row-readable"') == 2
    assert '<a class="chapter-row-link" href="/read/7?chapter=1">Chapter 1</a>' in html
    assert (
        '<a class="chapter-row-link" href="/read/7?chapter=2">'
        "Appendix A: Sources</a>"
    ) in html
    assert ">Read</a>" not in html
    assert "<td>2</td>" in html


def test_chapters_table_disables_sections_without_sentences() -> None:
    html = _chapters_table(
        7,
        [
            {
                "idx": 1,
                "title": "Cover",
                "section_kind": "frontmatter",
                "chapter_number": None,
                "sentence_start": 0,
                "sentence_end": 0,
            }
        ],
    )

    assert (
        '<tr class="chapter-row chapter-row-unavailable" aria-disabled="true">'
        "<td>Cover</td><td>0</td></tr>"
    ) in html
    assert "/read/7?chapter=1" not in html
    assert "chapter-row-link" not in html


def test_type_aware_section_labels_hide_artificial_headings() -> None:
    unnamed = {
        "idx": 1,
        "title": "Chapter 1",
        "section_kind": "chapter",
        "chapter_number": 1,
        "sentence_start": 0,
        "sentence_end": 2,
    }
    named = {**unnamed, "title": "Methods"}

    assert _section_label(unnamed, content_kind="article", total_sections=1) == ""
    assert _section_label(named, content_kind="article", total_sections=1) == (
        "Section 1: Methods"
    )
    assert _section_label(unnamed, content_kind="unclassified") == "Section 1"
    assert _section_label(named, content_kind="excerpt") == ""
    article_html = _chapters_table(7, [unnamed], content_kind="article")
    excerpt_html = _chapters_table(7, [unnamed], content_kind="excerpt")
    assert ">Read article</a>" in article_html
    assert "Chapter 1" not in article_html
    assert ">Read excerpt</a>" in excerpt_html
    assert "Section 1" not in excerpt_html


def test_library_filters_and_metadata_form_escape_and_select_values() -> None:
    filters = _library_filters(
        ["Trade", "<unsafe>"],
        selected_kind="article",
        selected_status="reading",
        selected_tag="<unsafe>",
    )
    form = _library_item_form(
        {
            "id": 4,
            "title": '<Article "One">',
            "author": "Writer",
            "content_kind": "article",
            "library_status": "reading",
            "tags": "Trade, <unsafe>",
            "source_format": "md",
            "import_method": "url",
            "source_uri": "https://example.com/?a=<b>",
        }
    )

    assert 'value="article" selected' in filters
    assert 'value="reading" selected' in filters
    assert 'value="&lt;unsafe&gt;" selected' in filters
    assert 'action="/books/4/metadata"' in form
    assert '&lt;Article &quot;One&quot;&gt;' in form
    assert 'value="article" selected' in form
    assert 'value="reading" selected' in form
    assert "https://example.com/?a=&lt;b&gt;" in form
