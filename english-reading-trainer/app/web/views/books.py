"""Book and chapter table rendering helpers."""

from __future__ import annotations

import json
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

def _books_table(
    rows: list[dict[str, Any]],
    *,
    available_tags: list[str] | None = None,
    return_to: str = "/books",
) -> str:
    if not rows:
        return '<p class="empty">No Library Items found.</p>'
    tag_choices = available_tags or []
    body = "\n".join(
        _library_item_row(
            row,
            available_tags=tag_choices,
            return_to=return_to,
        )
        for row in rows
    )
    return f"""
    <div class="library-table-wrap">
    <table class="library-table">
      <thead><tr><th>Title</th><th>Type</th><th>Status</th><th>Tags</th><th>Author</th><th>Source</th><th>Sections</th><th>Sentences</th><th>Actions</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    </div>
    <script src="/static/library-tags.js"></script>
    """


def _library_item_row(
    row: dict[str, Any],
    *,
    available_tags: list[str],
    return_to: str,
) -> str:
    book_id = int(row["id"])
    form_id = f"library-item-form-{book_id}"
    title = str(row["title"])
    author = str(row.get("author") or "")
    content_kind = str(row.get("content_kind") or "unclassified")
    library_status = str(row.get("library_status") or "inbox")
    tags = str(row.get("tags") or "")
    classification_form = (
        f'<form id="{form_id}" method="post" action="/books/{book_id}/metadata" '
        'class="library-inline-form">'
        f'<input type="hidden" name="title" value="{_escape(title)}">'
        f'<input type="hidden" name="author" value="{_escape(author)}">'
        f'<input type="hidden" name="return_to" value="{_escape(return_to)}">'
        '<button class="primary small" type="submit">Save</button>'
        "</form>"
    )
    type_select = f"""
      <select name="content_kind" form="{form_id}"
              aria-label="Content type for {_escape(title)}" class="library-inline-select">
        <option value="book"{_selected('book', content_kind)}>Book</option>
        <option value="article"{_selected('article', content_kind)}>Article</option>
        <option value="excerpt"{_selected('excerpt', content_kind)}>Excerpt</option>
        <option value="unclassified"{_selected('unclassified', content_kind)}>Unclassified</option>
      </select>
    """
    status_select = f"""
      <select name="library_status" form="{form_id}"
              aria-label="Library status for {_escape(title)}" class="library-inline-select">
        <option value="inbox"{_selected('inbox', library_status)}>Inbox</option>
        <option value="reading"{_selected('reading', library_status)}>Reading</option>
        <option value="finished"{_selected('finished', library_status)}>Finished</option>
        <option value="archived"{_selected('archived', library_status)}>Archived</option>
      </select>
    """
    tags_picker = _library_tag_picker(
        form_id=form_id,
        title=title,
        tags=tags,
        available_tags=available_tags,
    )
    return (
        f'<tr id="library-item-{book_id}" class="library-item-row">'
        f'<td><a href="/books/{book_id}/open">{_escape(title)}</a></td>'
        f"<td>{type_select}</td>"
        f"<td>{status_select}</td>"
        f'<td class="library-tag-cell">{tags_picker}</td>'
        f"<td>{_escape(author)}</td>"
        f"<td>{_escape(str(row['source_format']).upper())}</td>"
        f"<td>{row['total_chapters']}</td>"
        f"<td>{row['total_sentences']}</td>"
        '<td><div class="library-row-actions">'
        f'{classification_form}<a class="button small" href="/books/{book_id}">Details</a>'
        f"{_delete_book_form(book_id)}"
        "</div></td>"
        "</tr>"
    )


def _library_tag_picker(
    *,
    form_id: str,
    title: str,
    tags: str,
    available_tags: list[str],
) -> str:
    selected_tags = _normalized_tag_names(tags.split(","))
    choices = _normalized_tag_names([*selected_tags, *available_tags])
    selected_keys = {tag.casefold() for tag in selected_tags}
    options = "".join(
        '<label class="library-tag-option">'
        f'<input type="checkbox" value="{_escape(tag)}" data-tag-option'
        f'{" checked" if tag.casefold() in selected_keys else ""}>'
        f'<span>{_escape(tag)}</span></label>'
        for tag in choices
    )
    empty_state = (
        '<p class="muted library-tag-empty" data-tag-empty>No saved tags yet.</p>'
        if not choices
        else '<p class="muted library-tag-empty" data-tag-empty hidden>'
        "No saved tags yet.</p>"
    )
    summary = _library_tag_summary(selected_tags)
    return (
        '<details class="library-tag-picker" data-tag-picker>'
        f'<summary aria-label="Tags for {_escape(title)}">'
        f'<span class="library-tag-summary" data-tag-summary>{summary}</span>'
        "</summary>"
        f'<input type="hidden" name="tags" form="{form_id}" '
        f'value="{_escape(", ".join(selected_tags))}" data-tag-value>'
        '<div class="library-tag-panel">'
        '<fieldset><legend class="library-tag-legend">Choose tags</legend>'
        f'<div class="library-tag-options" data-tag-options>{options}</div>'
        f"{empty_state}</fieldset>"
        '<div class="library-tag-new">'
        '<input type="text" data-tag-new aria-label="New tag" '
        'placeholder="New tag">'
        '<button type="button" class="small" data-tag-add>Add</button>'
        "</div>"
        '<p class="muted library-tag-hint">Select any number, or add a new tag.</p>'
        "</div></details>"
    )


def _normalized_tag_names(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = raw_tag.strip()
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        normalized.append(tag)
    return normalized


def _library_tag_summary(tags: list[str]) -> str:
    if not tags:
        return '<span class="library-tag-placeholder">Select tags</span>'
    return "".join(
        f'<span class="library-tag-chip">{_escape(tag)}</span>' for tag in tags
    )


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


def _library_notice(
    rows: list[dict[str, Any]],
    *,
    saved: int = 0,
    saved_title: str = "",
    deleted_tag: str = "",
    tag_items: str = "",
) -> str:
    """Render one-time save/tag-delete feedback for the Library list."""
    titles = {int(row["id"]): str(row["title"]) for row in rows}
    messages: list[str] = []
    if saved:
        title = saved_title or titles.get(saved, "")
        messages.append(f"Saved {_escape(title)}." if title else "Saved.")
    if deleted_tag:
        item_ids = [
            int(raw)
            for raw in tag_items.split(",")
            if raw.strip().isdigit()
        ]
        message = f"Tag {_escape(deleted_tag)} deleted"
        if item_ids:
            links = ", ".join(
                f'<a href="/books#library-item-{item_id}">'
                f'{_escape(titles.get(item_id) or f"Item {item_id}")}</a>'
                for item_id in item_ids
            )
            noun = "item" if len(item_ids) == 1 else "items"
            message += (
                f"; removed from {len(item_ids)} {noun}: {links}. "
                "You can update them below."
            )
        else:
            message += "; no items were using it."
        messages.append(message)
    if not messages:
        return ""
    return f'<p class="flash" role="status">{" ".join(messages)}</p>'


def _library_tag_manager(tags_usage: list[dict[str, Any]]) -> str:
    """Render the collapsible tag management section for the Library list."""
    if not tags_usage:
        return ""
    entries = "".join(
        "<li>"
        f'<span class="tag-manager-name">{_escape(str(tag["name"]))}</span>'
        f'<span class="muted">{int(tag["item_count"])} '
        f'{"item" if int(tag["item_count"]) == 1 else "items"}</span>'
        f'<form method="post" action="/tags/{int(tag["id"])}/delete" '
        'class="inline-form">'
        f'<button class="danger small" type="submit" '
        f'onclick="return confirm('
        f'{_escape(json.dumps(_tag_delete_confirm(str(tag["name"]), int(tag["item_count"]))))}'
        f')">Delete</button></form></li>'
        for tag in tags_usage
    )
    return (
        '<details class="tag-manager">'
        "<summary>Manage tags</summary>"
        f'<ul class="tag-manager-list">{entries}</ul>'
        '<p class="muted tag-manager-hint">Add a tag from any item\'s tag '
        "picker and save that row. Deleting a tag here removes "
        "it from every item.</p>"
        "</details>"
    )


def _tag_delete_confirm(name: str, item_count: int) -> str:
    noun = "item" if item_count == 1 else "items"
    return f'Delete tag "{name}"? It will be removed from {item_count} {noun}.'


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
        <input type="hidden" name="library_status"
               value="{_escape(book.get('library_status') or 'inbox')}">
        <input type="hidden" name="tags" value="{_escape(book.get('tags') or '')}">
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
    <table id="item-contents" class="chapter-table">
      <thead><tr><th>{heading}</th><th>Sentences</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _has_meaningful_contents(
    rows: list[dict[str, Any]],
    *,
    content_kind: str,
) -> bool:
    if content_kind == "excerpt":
        return False
    readable_sections = sum(
        1
        for row in rows
        if int(row.get("sentence_end") or 0) - int(row.get("sentence_start") or 0) > 0
    )
    return readable_sections > 1


def _library_item_open_redirect(
    book_id: int,
    *,
    has_contents: bool,
    primary_read_idx: int | None,
) -> str:
    direct_href = (
        f"/read/{book_id}?chapter={primary_read_idx}"
        if primary_read_idx is not None
        else f"/read/{book_id}"
    )
    first_open_href = f"/books/{book_id}/contents" if has_contents else direct_href
    has_contents_js = "true" if has_contents else "false"
    return f"""
    <section class="band">
      <h1>Opening Library Item…</h1>
      <p class="muted">Restoring your reading position or preparing the item.</p>
      <p><a class="button primary" href="{first_open_href}">Open item</a></p>
    </section>
    <script>
      (() => {{
        const bookId = "{book_id}";
        const hasContents = {has_contents_js};
        const directHref = "{direct_href}";
        let hasProgress = false;
        try {{
          const progress = JSON.parse(
            window.localStorage.getItem(`reader:progress:book:${{bookId}}`) || "null",
          );
          hasProgress = Number.parseInt(progress?.chapter_idx, 10) > 0;
        }} catch (error) {{
          hasProgress = false;
        }}
        const target = hasProgress
          ? `/read/${{encodeURIComponent(bookId)}}?restore=1`
          : (hasContents ? `/books/${{encodeURIComponent(bookId)}}/contents` : directHref);
        window.location.replace(target);
      }})();
    </script>
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
