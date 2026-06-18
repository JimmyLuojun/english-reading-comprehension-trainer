from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _error_page,
    _read_form,
    _read_upload_bytes,
    _redirect,
    _save_upload_to_temp,
    _unlink_silent,
)
from app.web.models import UploadTooLargeError
from app.web.services.imports import (
    ImportOutcome,
    import_epub_file,
    import_pdf_file,
    import_text_bytes,
)
from app.web.utils import _format_mb
from app.web.views import (
    _duplicate_page,
    _html_page,
    _import_forms,
)

def register_import_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    import app.web.fastapi_app as fastapi_app
    @web_app.get("/import", response_class=HTMLResponse)
    def import_page() -> HTMLResponse:
        return _html_page("Import", _import_forms(), active="import", page_class="narrow")

    @web_app.post("/import/file")
    async def import_file(
        file: UploadFile = File(...),
        title: str = Form(""),
        author: str = Form(""),
    ) -> Any:
        filename = (file.filename or "").lower()
        if filename.endswith(".epub"):
            try:
                tmp_path, size = await _save_upload_to_temp(
                    file,
                    suffix=".epub",
                    max_bytes=fastapi_app._MAX_EPUB_IMPORT_BYTES,
                )
            except UploadTooLargeError as exc:
                return _error_page(
                    f"Uploaded EPUB exceeds {_format_mb(exc.max_bytes)} MB limit.",
                    status_code=413,
                )
            if size == 0:
                _unlink_silent(tmp_path)
                return _error_page("Uploaded file is empty.", status_code=400)
            try:
                return _do_import_epub(db_factory(), tmp_path, title, author)
            finally:
                _unlink_silent(tmp_path)

        if filename.endswith(".pdf"):
            try:
                tmp_path, size = await _save_upload_to_temp(
                    file,
                    suffix=".pdf",
                    max_bytes=fastapi_app._MAX_PDF_IMPORT_BYTES,
                )
            except UploadTooLargeError as exc:
                return _error_page(
                    f"Uploaded PDF exceeds {_format_mb(exc.max_bytes)} MB limit.",
                    status_code=413,
                )
            if size == 0:
                _unlink_silent(tmp_path)
                return _error_page("Uploaded file is empty.", status_code=400)
            try:
                return _do_import_pdf(db_factory(), tmp_path, title, author)
            finally:
                _unlink_silent(tmp_path)

        try:
            raw = await _read_upload_bytes(file, max_bytes=fastapi_app._MAX_TEXT_IMPORT_BYTES)
        except UploadTooLargeError as exc:
            return _error_page(
                f"Uploaded file exceeds {_format_mb(exc.max_bytes)} MB limit.",
                status_code=413,
            )
        if not raw.strip():
            return _error_page("Uploaded file is empty.", status_code=400)
        return _import_outcome_response(
            import_text_bytes(
                db_factory(),
                raw,
                form_title=title,
                author=author,
            )
        )

    @web_app.post("/import/paste")
    async def import_paste(request: Request) -> Any:
        form = await _read_form(request)
        text = form.get("text", "")
        title = form.get("title", "")
        author = form.get("author", "")
        raw = text.encode("utf-8")
        if len(raw) > fastapi_app._MAX_TEXT_IMPORT_BYTES:
            return _error_page(
                f"Pasted text exceeds {_format_mb(fastapi_app._MAX_TEXT_IMPORT_BYTES)} MB limit.",
                status_code=413,
            )
        if not text.strip():
            return _error_page("Pasted text is empty.", status_code=400)
        return _import_outcome_response(
            import_text_bytes(
                db_factory(),
                raw,
                form_title=title,
                author=author,
            )
        )

    def _import_outcome_response(outcome: ImportOutcome) -> Any:
        if outcome.is_duplicate:
            return _duplicate_page(outcome.duplicate_book_id)
        if outcome.is_error:
            return _error_page(outcome.error or "Import failed.", status_code=outcome.status_code)
        return _redirect(f"/read/{outcome.book_id}")

    def _do_import_epub(
        db: DatabaseConnection,
        file_path: str | Path,
        form_title: str,
        author: str,
    ) -> Any:
        return _import_outcome_response(
            import_epub_file(
                db,
                file_path,
                form_title=form_title,
                author=author,
            )
        )

    def _do_import_pdf(
        db: DatabaseConnection,
        file_path: str | Path,
        form_title: str,
        author: str,
    ) -> Any:
        return _import_outcome_response(
            import_pdf_file(
                db,
                file_path,
                form_title=form_title,
                author=author,
            )
        )
