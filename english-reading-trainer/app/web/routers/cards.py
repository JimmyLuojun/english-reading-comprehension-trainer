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

def register_card_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.post("/mark/sentence/{sentence_id}")
    async def mark_sentence(sentence_id: int, request: Request) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/cards"))
        db = db_factory()
        try:
            create_sentence_card(db, sentence_id)
        except SentenceCardAlreadyExistsError:
            pass
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.post("/mark/sentence/{sentence_id}/translation")
    async def mark_sentence_translation(sentence_id: int, request: Request) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/cards"))
        db = db_factory()
        try:
            save_sentence_translation(
                db,
                sentence_id,
                form.get("user_translation", ""),
            )
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)
    @web_app.delete("/mark/sentence/{sentence_id}")
    async def unmark_sentence(sentence_id: int, request: Request) -> Any:
        return_to = _safe_return_to(request.query_params.get("return_to", "/cards"))
        db = db_factory()
        try:
            archive_sentence_card(db, sentence_id)
        except (SentenceCardNotFoundError, ValueError) as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.post("/mark/word")
    async def mark_word(request: Request) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/cards"))
        wants_json = _wants_json(request)
        try:
            sentence_id = int(form.get("sentence_id", "0"))
            lexical_type = LexicalType(form.get("lexical_type", LexicalType.WORD.value))
            surface_form = form.get("surface_form", "")
        except ValueError as exc:
            if wants_json:
                return JSONResponse(
                    {"ok": False, "error": f"Invalid word card input: {exc}"},
                    status_code=400,
                )
            return _error_page(f"Invalid word card input: {exc}", status_code=400)

        db = db_factory()
        try:
            card_id, created = create_or_update_word_card(db, sentence_id, surface_form, lexical_type)
        except ValueError as exc:
            if wants_json:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            return _error_page(str(exc), status_code=400)
        if wants_json:
            card = get_word_card(db, card_id)
            if card is None:
                return JSONResponse(
                    {"ok": False, "error": "Word card was not saved."},
                    status_code=500,
                )
            return JSONResponse(
                {
                    "ok": True,
                    "card_id": card_id,
                    "created": created,
                    "word_card": _word_card_json_payload(card),
                }
            )
        return _redirect(return_to)

    @web_app.delete("/mark/word/{card_id}")
    async def unmark_word(card_id: int, request: Request) -> Any:
        return_to = _safe_return_to(request.query_params.get("return_to", "/cards"))
        db = db_factory()
        try:
            archive_word_card(db, card_id)
        except WordCardNotFoundError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.patch("/mark/word/{card_id}")
    async def update_word_note_endpoint(card_id: int, request: Request) -> JSONResponse:
        form = await _read_form(request)
        db = db_factory()
        try:
            update_word_card_note(
                db,
                card_id,
                current_meaning=form.get("current_meaning", ""),
                user_note=form.get("user_note", ""),
            )
        except WordCardNotFoundError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        return JSONResponse({"ok": True})
    @web_app.get("/cards", response_class=HTMLResponse)
    def cards() -> HTMLResponse:
        db = db_factory()
        sentence_cards = list_sentence_cards(db, limit=_DEFAULT_PAGE_LIMIT)
        word_cards = list_word_cards(db, limit=_DEFAULT_PAGE_LIMIT)
        body = f"""
        <section class="toolbar">
          <div>
            <h1>Cards</h1>
            <p class="muted">Sentence and word cards currently tracked.</p>
          </div>
        </section>
        {_cards_return_script()}
        <section class="band">
          <h2>Sentence Cards</h2>
          {_sentence_cards_table(sentence_cards)}
          <h2>Word Cards</h2>
          {_word_cards_table(word_cards)}
        </section>
        """
        return _html_page("Cards", body, active="cards")
