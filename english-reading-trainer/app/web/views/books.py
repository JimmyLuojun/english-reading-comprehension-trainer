"""Book and chapter table rendering helpers."""

from __future__ import annotations

import re
from typing import Any

from app.web.views.layout import _escape

_CHAPTER_ORDINAL_RE = re.compile(
    r"^\s*(?:"
    r"(?:chapter\s+)?\d+|"
    r"chapter\s+(?:[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty)"
    r")(?:[\s.:)-]+|$)",
    re.I,
)

def _books_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No Library Items found.</p>'
    body = "\n".join(
        "<tr>"
        f"<td><a href=\"/books/{row['id']}\">{_escape(row['title'])}</a></td>"
        f"<td>{_escape(_display_value(row.get('content_kind')))}</td>"
        f"<td>{_escape(_display_value(row.get('library_status')))}</td>"
        f"<td>{_escape(row.get('tags') or '')}</td>"
        f"<td>{_escape(row['author'] or '')}</td>"
        f"<td>{_escape(str(row['source_format']).upper())}</td>"
        f"<td>{row['total_chapters']}</td>"
        f"<td>{row['total_sentences']}</td>"
        f"<td>{_delete_book_form(row['id'])}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>Title</th><th>Type</th><th>Status</th><th>Tags</th><th>Author</th><th>Source</th><th>Sections</th><th>Sentences</th><th>Actions</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _library_filters(
    tags: list[str],
    *,
    selected_kind: str = "",
    selected_status: str = "",
    selected_tag: str = "",
) -> str:
    tag_options = "".join(
        f'<option value="{_escape(tag)}"{_selected(tag, selected_tag)}>'
        f"{_escape(tag)}</option>"
        for tag in tags
    )
    return f"""
    <form method="get" action="/books" class="library-filters">
      <label>Type
        <select name="content_kind">
          <option value="">All</option>
          <option value="book"{_selected('book', selected_kind)}>Book</option>
          <option value="article"{_selected('article', selected_kind)}>Article</option>
          <option value="excerpt"{_selected('excerpt', selected_kind)}>Excerpt</option>
          <option value="unclassified"{_selected('unclassified', selected_kind)}>Unclassified</option>
        </select>
      </label>
      <label>Status
        <select name="library_status">
          <option value="">All</option>
          <option value="inbox"{_selected('inbox', selected_status)}>Inbox</option>
          <option value="reading"{_selected('reading', selected_status)}>Reading</option>
          <option value="finished"{_selected('finished', selected_status)}>Finished</option>
          <option value="archived"{_selected('archived', selected_status)}>Archived</option>
        </select>
      </label>
      <label>Tag
        <select name="tag">
          <option value="">All</option>
          {tag_options}
        </select>
      </label>
      <button type="submit">Filter</button>
      <a class="button" href="/books">Clear</a>
    </form>
    """


def _library_item_form(book: dict[str, Any]) -> str:
    return f"""
    <section class="band">
      <h2>Library metadata</h2>
      <form method="post" action="/books/{book['id']}/metadata" class="stack-form">
        <label for="item-title">Title</label>
        <input id="item-title" name="title" value="{_escape(book['title'])}" required>
        <label for="item-author">Author</label>
        <input id="item-author" name="author" value="{_escape(book.get('author') or '')}">
        <label for="item-content-kind">Content type</label>
        <select id="item-content-kind" name="content_kind">
          <option value="book"{_selected('book', book.get('content_kind'))}>Book</option>
          <option value="article"{_selected('article', book.get('content_kind'))}>Article</option>
          <option value="excerpt"{_selected('excerpt', book.get('content_kind'))}>Excerpt</option>
          <option value="unclassified"{_selected('unclassified', book.get('content_kind'))}>Unclassified</option>
        </select>
        <label for="item-library-status">Library status</label>
        <select id="item-library-status" name="library_status">
          <option value="inbox"{_selected('inbox', book.get('library_status'))}>Inbox</option>
          <option value="reading"{_selected('reading', book.get('library_status'))}>Reading</option>
          <option value="finished"{_selected('finished', book.get('library_status'))}>Finished</option>
          <option value="archived"{_selected('archived', book.get('library_status'))}>Archived</option>
        </select>
        <label for="item-tags">Tags <span class="muted">(comma-separated)</span></label>
        <input id="item-tags" name="tags" value="{_escape(book.get('tags') or '')}">
        <button type="submit">Save metadata</button>
      </form>
      <dl class="source-metadata">
        <dt>Source format</dt><dd>{_escape(str(book['source_format']).upper())}</dd>
        <dt>Import method</dt><dd>{_escape(_display_value(book.get('import_method'), fallback='Unknown'))}</dd>
        <dt>Source reference</dt><dd>{_escape(book.get('source_uri') or 'Not recorded')}</dd>
      </dl>
    </section>
    """

def _delete_book_form(book_id: int) -> str:
    confirm = (
        "Delete this Library Item and all related sentence cards? Word cards that also "
        "appear in other items will be kept and re-anchored."
    )
    return (
        f'<form method="post" action="/books/{book_id}/delete" class="inline-form">'
        f'<button class="danger" type="submit" onclick="return confirm(\'{_escape(confirm)}\')">'
        "Delete</button></form>"
    )

def _chapters_table(
    book_id: int,
    rows: list[dict[str, Any]],
    *,
    content_kind: str = "book",
) -> str:
    if not rows:
        return '<p class="empty">No readable sections found.</p>'
    total_sections = len(rows)
    body = "\n".join(
        _chapter_row(
            book_id,
            row,
            content_kind=content_kind,
            total_sections=total_sections,
        )
        for row in rows
    )
    heading = "Chapter" if content_kind == "book" else "Section"
    if content_kind == "excerpt":
        heading = "Content"
    return f"""
    <table class="chapter-table">
      <thead><tr><th>{heading}</th><th>Sentences</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _chapter_row(
    book_id: int,
    row: dict[str, Any],
    *,
    content_kind: str = "book",
    total_sections: int = 1,
) -> str:
    sentence_count = row["sentence_end"] - row["sentence_start"]
    label_text = _section_label(
        row,
        content_kind=content_kind,
        total_sections=total_sections,
    )
    if not label_text:
        label_text = "Read excerpt" if content_kind == "excerpt" else "Read article"
    label = _escape(label_text)
    if sentence_count <= 0:
        return (
            '<tr class="chapter-row chapter-row-unavailable" aria-disabled="true">'
            f"<td>{label}</td><td>{sentence_count}</td></tr>"
        )

    href = f"/read/{book_id}?chapter={row['idx']}"
    return (
        '<tr class="chapter-row chapter-row-readable">'
        f'<td><a class="chapter-row-link" href="{href}">{label}</a></td>'
        f"<td>{sentence_count}</td></tr>"
    )

def _primary_read_idx(rows: list[dict[str, Any]]) -> int | None:
    for row in rows:
        if row.get("section_kind") == "chapter":
            return row["idx"]
    return rows[0]["idx"] if rows else None

def _section_label(
    row: dict[str, Any],
    *,
    content_kind: str = "book",
    total_sections: int = 1,
) -> str:
    title = str(row.get("title") or "").strip()
    kind = row.get("section_kind") or "chapter"
    if content_kind == "excerpt":
        return ""
    if content_kind in {"article", "unclassified"}:
        section_number = row.get("chapter_number") or row.get("idx") or 1
        clean_title = _strip_section_ordinal(title)
        if content_kind == "article" and total_sections == 1 and not clean_title:
            return ""
        return (
            f"Section {section_number}: {clean_title}"
            if clean_title
            else f"Section {section_number}"
        )
    if kind == "chapter":
        chapter_number = row.get("chapter_number") or row.get("idx")
        clean_title = _strip_section_ordinal(title)
        return (
            f"Chapter {chapter_number}: {clean_title}"
            if clean_title
            else f"Chapter {chapter_number}"
        )
    if kind == "appendix":
        clean_title = _strip_appendix_ordinal(title)
        appendix_letter = _appendix_letter(title)
        if appendix_letter:
            return (
                f"Appendix {appendix_letter}: {clean_title}"
                if clean_title
                else f"Appendix {appendix_letter}"
            )
        return f"Appendix: {title}" if title else "Appendix"
    return title or kind.title()


def _selected(value: str, selected: Any) -> str:
    return " selected" if value == str(selected or "") else ""


def _display_value(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text.replace("_", " ").title() if text else fallback

def _strip_section_ordinal(title: str) -> str:
    return _CHAPTER_ORDINAL_RE.sub("", title).strip()

def _appendix_letter(title: str) -> str:
    match = re.match(r"^\s*(?:appendix\s+)?([A-Z])(?:[\s.:)-]+|$)", title, re.I)
    return match.group(1) if match else ""

def _strip_appendix_ordinal(title: str) -> str:
    return re.sub(r"^\s*(?:appendix\s+)?[A-Z](?:[\s.:)-]+)", "", title, flags=re.I).strip()
