from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

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
from app.db_models import LexicalType
from app.web.config import _DEFAULT_PAGE_LIMIT
from app.web.http_utils import (
    _error_page,
    _read_form,
    _redirect,
    _safe_return_to,
    _wants_json,
    _word_card_json_payload,
)
from app.web.views import (
    _cards_return_script,
    _html_page,
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
