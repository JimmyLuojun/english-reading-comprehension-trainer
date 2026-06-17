from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _error_page,
)
from app.web.queries import (
    _default_read_idx,
    _fetch_active_word_cards,
    _fetch_book,
    _fetch_chapter_blocks,
    _fetch_chapter_by_idx,
    _fetch_chapter_sentences,
    _fetch_adjacent_chapters,
)
from app.web.views import (
    _html_page,
    _reader_view,
)

def register_reader_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/read/{book_id}", response_class=HTMLResponse)
    def read_book(request: Request, book_id: int, chapter: int = 1) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Book not found", status_code=404)
        chapter_idx = chapter
        if "chapter" not in request.query_params:
            default_idx = _default_read_idx(db, book_id)
            if default_idx is not None:
                chapter_idx = default_idx
        chapter_row = _fetch_chapter_by_idx(db, book_id, chapter_idx)
        if chapter_row is None:
            return _error_page("Chapter not found", status_code=404)
        adjacent_chapters = _fetch_adjacent_chapters(db, book_id, chapter_idx)
        sentences = _fetch_chapter_sentences(db, chapter_row["id"])
        blocks = _fetch_chapter_blocks(db, chapter_row["id"])
        word_cards = _fetch_active_word_cards(db)
        return_to = f"/read/{book_id}?chapter={chapter_idx}&restore=1"
        restore_progress = "chapter" not in request.query_params or (
            request.query_params.get("restore") == "1"
        )
        body = f"""
        {_reader_view(
            rows=sentences,
            blocks=blocks,
            return_to=return_to,
            chapter_id=chapter_row["id"],
            word_cards=word_cards,
            book_id=book_id,
            book_title=book["title"],
            chapter_idx=chapter_idx,
            chapter_title=chapter_row["title"],
            section_kind=chapter_row.get("section_kind") or "chapter",
            chapter_number=chapter_row.get("chapter_number"),
            restore_progress=restore_progress,
            previous_chapter=adjacent_chapters["previous"],
            next_chapter=adjacent_chapters["next"],
        )}
        """
        return _html_page("Read", body, active="books", page_class="reader-page")
