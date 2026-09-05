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
    _fetch_library_tag_usage,
)
from app.web.services.books import (
    delete_book_and_assets,
    delete_library_tag,
    rename_library_tag,
    update_library_item,
)
from app.web.views import (
    _books_table,
    _chapters_table,
    _has_meaningful_contents,
    _html_page,
    _library_filters,
    _library_item_form,
    _library_item_open_redirect,
    _library_notice,
    _library_tag_manager,
    _page_header,
    _primary_read_idx,
)

def register_book_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/books", response_class=HTMLResponse)
    def books(
        content_kind: str = "",
        library_status: str = "",
        tag: str = "",
        saved: int = 0,
        deleted_tag: str = "",
        renamed_tag: str = "",
        renamed_to: str = "",
        tag_items: str = "",
        tag_sentence_cards: int = 0,
        tag_word_cards: int = 0,
    ) -> HTMLResponse:
        db = db_factory()
        rows = _fetch_books(
            db,
            content_kind=content_kind,
            library_status=library_status,
            tag=tag,
        )
        tags = _fetch_library_tags(db)
        tag_usage = _fetch_library_tag_usage(db)
        saved_title = ""
        if saved:
            saved_title = next(
                (str(row["title"]) for row in rows if int(row["id"]) == saved), ""
            )
            if not saved_title:
                book = _fetch_book(db, saved)
                saved_title = str(book["title"]) if book else ""
        body = _page_header("Library", "Books, articles, and excerpts in one place.")
        body += _library_notice(
            rows,
            saved=saved,
            saved_title=saved_title,
            deleted_tag=deleted_tag,
            renamed_tag=renamed_tag,
            renamed_to=renamed_to,
            tag_items=tag_items,
            tag_sentence_cards=tag_sentence_cards,
            tag_word_cards=tag_word_cards,
        )
        body += _library_filters(
            tags,
            selected_kind=content_kind,
            selected_status=library_status,
            selected_tag=tag,
        )
        body += _library_tag_manager(tag_usage)
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
        body += _books_table(
            rows,
            available_tags=[str(tag["name"]) for tag in tag_usage],
            return_to=return_to,
        )
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
        if return_to == "/books" or return_to.startswith("/books?"):
            separator = "&" if "?" in return_to else "?"
            return_to = f"{return_to}{separator}saved={book_id}"
        return _redirect(return_to)

    @web_app.post("/tags/{tag_id}/delete")
    def delete_tag(tag_id: int) -> Any:
        db = db_factory()
        result = delete_library_tag(db, tag_id)
        if result is None:
            return _error_page("Tag not found", status_code=404)
        query = urlencode(
            {
                "deleted_tag": result["name"],
                "tag_items": ",".join(str(book_id) for book_id in result["book_ids"]),
                "tag_sentence_cards": result["sentence_card_count"],
                "tag_word_cards": result["word_card_count"],
            }
        )
        return _redirect(f"/books?{query}")

    @web_app.post("/tags/{tag_id}/rename")
    async def rename_tag(request: Request, tag_id: int) -> Any:
        form = await _read_form(request)
        db = db_factory()
        try:
            result = rename_library_tag(db, tag_id, form.get("name", ""))
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        if result is None:
            return _error_page("Tag not found", status_code=404)
        query = urlencode(
            {
                "renamed_tag": result["old_name"],
                "renamed_to": result["new_name"],
                "tag_items": ",".join(str(book_id) for book_id in result["book_ids"]),
                "tag_sentence_cards": result["sentence_card_count"],
                "tag_word_cards": result["word_card_count"],
            }
        )
        return _redirect(f"/books?{query}")

    @web_app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(book_id: int) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Library Item not found", status_code=404)
        chapters = _fetch_chapters(db, book_id)
        tag_usage = _fetch_library_tag_usage(db)
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
            f'<a class="button" href="{read_href}">Start from beginning</a>',
        )}
        {_library_item_form(
            book,
            available_tags=[str(tag["name"]) for tag in tag_usage],
        )}
        {_chapters_table(
            book_id,
            chapters,
            content_kind=book.get("content_kind") or "unclassified",
        )}
        """
        return _html_page(book["title"], body, active="library")

    @web_app.get("/books/{book_id}/open", response_class=HTMLResponse)
    def open_library_item(book_id: int) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Library Item not found", status_code=404)
        chapters = _fetch_chapters(db, book_id)
        content_kind = book.get("content_kind") or "unclassified"
        body = _library_item_open_redirect(
            book_id,
            has_contents=_has_meaningful_contents(
                chapters,
                content_kind=content_kind,
            ),
            primary_read_idx=_primary_read_idx(chapters),
        )
        return _html_page(f'Open {book["title"]}', body, active="library")

    @web_app.get("/books/{book_id}/contents", response_class=HTMLResponse)
    def library_item_contents(book_id: int) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Library Item not found", status_code=404)
        chapters = _fetch_chapters(db, book_id)
        read_idx = _primary_read_idx(chapters)
        start_href = (
            f"/read/{book_id}?chapter={read_idx}"
            if read_idx is not None
            else f"/read/{book_id}"
        )
        content_kind = book.get("content_kind") or "unclassified"
        item_type = str(content_kind).replace("_", " ").title()
        body = f"""
        {_page_header(
            book["title"],
            f'{item_type} · Choose where to begin',
            f'<a class="button" href="{start_href}">Start from beginning</a>',
        )}
        <section class="band">
          <h2>Contents</h2>
          {_chapters_table(book_id, chapters, content_kind=content_kind)}
        </section>
        """
        return _html_page(f'Contents · {book["title"]}', body, active="library")
