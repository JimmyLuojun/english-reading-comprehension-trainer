from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _read_form,
)
from app.web.queries import (
    _fetch_sentence_analysis_payload,
    _fetch_word_analysis_payload,
)
from app.web.services.analysis import analyze_sentence_for_reader, analyze_word_card_for_reader


def _truthy_form_value(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def register_analysis_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/analysis/sentence/{sentence_id}")
    def get_sentence_analysis(sentence_id: int) -> JSONResponse:
        payload = _fetch_sentence_analysis_payload(db_factory(), sentence_id)
        if payload is None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "No saved analysis for this sentence.",
                    "retry": True,
                },
                status_code=404,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/sentence/{sentence_id}")
    async def analyze_sentence_endpoint(
        sentence_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        outcome = analyze_sentence_for_reader(
            db_factory(),
            sentence_id,
            user_translation=form.get("user_translation"),
            prefer_pro=_truthy_form_value(form.get("prefer_pro")),
            force_refresh=_truthy_form_value(form.get("force_refresh")),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.get("/analysis/word/{card_id}")
    def get_word_analysis(card_id: int) -> JSONResponse:
        payload = _fetch_word_analysis_payload(db_factory(), card_id)
        if payload is None:
            return JSONResponse(
                {"ok": False, "error": "No saved analysis for this word.", "retry": True},
                status_code=404,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/word/{card_id}")
    async def analyze_word_endpoint(card_id: int, request: Request) -> JSONResponse:
        form = await _read_form(request)
        outcome = analyze_word_card_for_reader(
            db_factory(),
            card_id,
            context_text=form.get("context_text", ""),
            prefer_pro=_truthy_form_value(form.get("prefer_pro")),
            force_refresh=_truthy_form_value(form.get("force_refresh")),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)
