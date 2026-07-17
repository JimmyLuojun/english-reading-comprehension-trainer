from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _error_page,
    _read_form,
    _redirect,
    _safe_return_to,
)
from app.web.queries import (
    _fetch_book,
    _fetch_books,
    _fetch_chapters,
    _fetch_library_tags,
)
from app.web.services.books import delete_book_and_assets, update_library_item
from app.web.views import (
    _books_table,
    _chapters_table,
    _html_page,
    _library_filters,
    _library_item_form,
    _page_header,
    _primary_read_idx,
)

def register_book_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/books", response_class=HTMLResponse)
    def books(
        content_kind: str = "",
        library_status: str = "",
        tag: str = "",
    ) -> HTMLResponse:
        db = db_factory()
        rows = _fetch_books(
            db,
            content_kind=content_kind,
            library_status=library_status,
            tag=tag,
        )
        tags = _fetch_library_tags(db)
        body = _page_header("Library", "Books, articles, and excerpts in one place.")
        body += _library_filters(
            tags,
            selected_kind=content_kind,
            selected_status=library_status,
            selected_tag=tag,
        )
        filters = {
            key: value
            for key, value in (
                ("content_kind", content_kind),
                ("library_status", library_status),
                ("tag", tag),
            )
            if value
        }
        query = urlencode(filters)
        return_to = f"/books?{query}" if query else "/books"
        body += _books_table(rows, return_to=return_to)
        return _html_page("Library", body, active="library")

    @web_app.post("/books/{book_id}/delete")
    def delete_book(book_id: int) -> Any:
        db = db_factory()
        result = delete_book_and_assets(db, book_id)
        if result is None:
            return _error_page("Library Item not found", status_code=404)
        return _redirect("/books")

    @web_app.post("/books/{book_id}/metadata")
    async def edit_library_item(request: Request, book_id: int) -> Any:
        form = await _read_form(request)
        db = db_factory()
        try:
            updated = update_library_item(
                db,
                book_id,
                title=form.get("title", ""),
                author=form.get("author", ""),
                content_kind=form.get("content_kind", ""),
                library_status=form.get("library_status", ""),
                tags_text=form.get("tags", ""),
            )
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        if not updated:
            return _error_page("Library Item not found", status_code=404)
        return_to = _safe_return_to(form.get("return_to", f"/books/{book_id}"))
        return _redirect(return_to)

    @web_app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(book_id: int) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Library Item not found", status_code=404)
        chapters = _fetch_chapters(db, book_id)
        read_idx = _primary_read_idx(chapters)
        read_href = (
            f"/read/{book_id}?chapter={read_idx}"
            if read_idx is not None
            else f"/read/{book_id}"
        )
        item_type = str(book.get("content_kind") or "unclassified").replace("_", " ").title()
        body = f"""
        {_page_header(
            book["title"],
            f'{item_type} · {book["author"] or "Unknown author"}',
            f'<a class="button" href="{read_href}">Start reading</a>',
        )}
        {_library_item_form(book)}
        {_chapters_table(
            book_id,
            chapters,
            content_kind=book.get("content_kind") or "unclassified",
        )}
        """
        return _html_page(book["title"], body, active="library")
