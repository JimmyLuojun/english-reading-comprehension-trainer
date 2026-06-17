from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _error_page,
    _redirect,
)
from app.web.queries import (
    _fetch_book,
    _fetch_books,
    _fetch_chapters,
)
from app.web.services.books import delete_book_and_assets
from app.web.views import (
    _books_continue_script,
    _books_table,
    _chapters_table,
    _escape,
    _html_page,
    _primary_read_idx,
)

def register_book_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/books", response_class=HTMLResponse)
    def books() -> HTMLResponse:
        db = db_factory()
        rows = _fetch_books(db)
        body = """
        <section class="toolbar">
          <div>
            <h1>Books</h1>
            <p class="muted">Imported reading material.</p>
          </div>
        </section>
        """
        body += _books_continue_script()
        body += _books_table(rows)
        return _html_page("Books", body, active="books")

    @web_app.post("/books/{book_id}/delete")
    def delete_book(book_id: int) -> Any:
        db = db_factory()
        result = delete_book_and_assets(db, book_id)
        if result is None:
            return _error_page("Book not found", status_code=404)
        return _redirect("/books")

    @web_app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(book_id: int) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Book not found", status_code=404)
        chapters = _fetch_chapters(db, book_id)
        read_idx = _primary_read_idx(chapters)
        read_href = (
            f"/read/{book_id}?chapter={read_idx}"
            if read_idx is not None
            else f"/read/{book_id}"
        )
        body = f"""
        <section class="toolbar">
          <div>
            <h1>{_escape(book["title"])}</h1>
            <p class="muted">{_escape(book["author"] or "Unknown author")}</p>
          </div>
          <a class="button" href="{read_href}">Start reading</a>
        </section>
        {_chapters_table(book_id, chapters)}
        """
        return _html_page(book["title"], body, active="books")
