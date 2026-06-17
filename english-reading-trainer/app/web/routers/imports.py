from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.ai.ai_provider_config import get_ai_provider_settings
from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    SentenceCardNotFoundError,
    archive_sentence_card,
    create_sentence_card,
    list_sentence_cards,
    save_sentence_translation,
)
from app.cards.word_card_service import (
    WordCardNotFoundError,
    archive_word_card,
    create_or_update_word_card,
    get_word_card,
    list_word_cards,
    update_word_card_note,
)
from app.db_connection import DatabaseConnection
from app.db_models import CardType, LexicalType, ReviewOutcome
from app.importers.epub_importer import DuplicateBookError as EpubDuplicateBookError
from app.importers.epub_importer import calculate_epub_file_hash, import_epub
from app.importers.txt_importer import DuplicateBookError, import_text
from app.profile.learner_profile_generator import (
    ProfileInputError,
    build_profile_prompt,
    get_latest_profile_snapshot,
    get_profile_trigger_status,
    save_profile_snapshot,
)
from app.review.daily_review_queue import build_daily_review_queue
from app.review.sm2_scheduler import (
    ReviewCardNotFoundError,
    ReviewInputError,
    apply_review,
)
from app.web.config import _DEFAULT_PAGE_LIMIT
from app.web.http_utils import (
    _error_page,
    _read_form,
    _read_upload_bytes,
    _redirect,
    _safe_return_to,
    _save_upload_to_temp,
    _unlink_silent,
    _wants_json,
    _word_card_json_payload,
)
from app.web.models import UploadTooLargeError
from app.web.queries import (
    _active_sentence_prompt_version,
    _asset_storage_path,
    _dashboard_stats,
    _default_read_idx,
    _delete_book,
    _fetch_active_word_cards,
    _fetch_book,
    _fetch_book_asset,
    _fetch_books,
    _fetch_cache_metadata,
    _fetch_chapter_blocks,
    _fetch_chapter_by_idx,
    _fetch_chapter_sentences,
    _fetch_chapters,
    _fetch_adjacent_chapters,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
    _lookup_book_id_by_hash,
    _purge_book_assets_dir,
)
from app.web.services.imports import ImportOutcome, import_epub_file, import_text_bytes
from app.web.utils import _format_mb, _resolve_title
from app.web.views import (
    _books_table,
    _cards_return_script,
    _chapters_table,
    _due_table,
    _duplicate_page,
    _escape,
    _html_page,
    _import_forms,
    _latest_profile_block,
    _metric,
    _primary_read_idx,
    _profile_save_form,
    _reader_view,
    _sentence_cards_table,
    _word_cards_table,
)

def register_import_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    import app.web.fastapi_app as fastapi_app
    @web_app.get("/import", response_class=HTMLResponse)
    def import_page() -> HTMLResponse:
        return _html_page("Import", _import_forms(), active="import")

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
