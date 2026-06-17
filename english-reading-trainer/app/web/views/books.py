"""Book and chapter table rendering helpers."""

from __future__ import annotations

import re
from typing import Any

from app.web.views.layout import _escape

def _books_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No books imported yet.</p>'
    body = "\n".join(
        "<tr>"
        f"<td>{row['id']}</td>"
        f"<td><a href=\"/books/{row['id']}\">{_escape(row['title'])}</a></td>"
        f"<td>{_escape(row['author'] or '')}</td>"
        f"<td>{_escape(row['source_format'])}</td>"
        f"<td>{row['total_chapters']}</td>"
        f"<td>{row['total_sentences']}</td>"
        f"<td>{_delete_book_form(row['id'])}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>ID</th><th>Title</th><th>Author</th><th>Format</th><th>Chapters</th><th>Sentences</th><th>Actions</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """

def _delete_book_form(book_id: int) -> str:
    confirm = (
        "Delete this book and all related sentence cards? Word cards that also "
        "appear in other books will be kept and re-anchored."
    )
    return (
        f'<form method="post" action="/books/{book_id}/delete" class="inline-form">'
        f'<button class="danger" type="submit" onclick="return confirm(\'{_escape(confirm)}\')">'
        "Delete</button></form>"
    )

def _chapters_table(book_id: int, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No chapters found.</p>'
    body = "\n".join(
        "<tr>"
        f"<td>{_escape(_section_label(row))}</td>"
        f"<td>{_escape(row['section_kind'])}</td>"
        f"<td>{row['sentence_end'] - row['sentence_start']}</td>"
        f"<td><a class=\"button small\" href=\"/read/{book_id}?chapter={row['idx']}\">Read</a></td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>Section</th><th>Kind</th><th>Sentences</th><th></th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """

def _primary_read_idx(rows: list[dict[str, Any]]) -> int | None:
    for row in rows:
        if row.get("section_kind") == "chapter":
            return row["idx"]
    return rows[0]["idx"] if rows else None

def _section_label(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    kind = row.get("section_kind") or "chapter"
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

def _strip_section_ordinal(title: str) -> str:
    return re.sub(r"^\s*(?:chapter\s+)?\d+(?:[\s.:)-]+)", "", title, flags=re.I).strip()

def _appendix_letter(title: str) -> str:
    match = re.match(r"^\s*(?:appendix\s+)?([A-Z])(?:[\s.:)-]+|$)", title)
    return match.group(1) if match else ""

def _strip_appendix_ordinal(title: str) -> str:
    return re.sub(r"^\s*(?:appendix\s+)?[A-Z](?:[\s.:)-]+)", "", title).strip()
