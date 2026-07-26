from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _read_form,
)
from app.web.queries import (
    _fetch_paragraph_logic_payload,
    _fetch_sentence_analysis_payload,
    _fetch_word_analysis_payload,
)
from app.web.services.analysis import (
    analyze_paragraph_logic_for_reader,
    analyze_sentence_for_reader,
    analyze_word_card_for_reader,
    build_external_paragraph_logic_prompt,
    build_external_sentence_prompt,
    build_external_word_prompt_for_card,
    build_external_word_prompt_for_selection,
    confirm_word_source_sense,
    save_external_paragraph_logic_for_reader,
    save_external_sentence_analysis_for_reader,
    save_external_word_analysis_for_card,
    save_external_word_analysis_for_selection,
)


def _truthy_form_value(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_int_form_value(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if text else None


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
        outcome = await run_in_threadpool(
            analyze_sentence_for_reader,
            db_factory(),
            sentence_id,
            user_translation=form.get("user_translation"),
            user_structure=form.get("user_structure"),
            prefer_pro=_truthy_form_value(form.get("prefer_pro")),
            force_refresh=_truthy_form_value(form.get("force_refresh")),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.get("/analysis/paragraph/{paragraph_id}/logic")
    def get_paragraph_logic_endpoint(paragraph_id: int) -> JSONResponse:
        try:
            payload = _fetch_paragraph_logic_payload(db_factory(), paragraph_id)
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        if payload is None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "No saved analysis for this paragraph.",
                    "retry": True,
                },
                status_code=404,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/paragraph/{paragraph_id}/logic")
    async def analyze_paragraph_logic_endpoint(
        paragraph_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        outcome = await run_in_threadpool(
            analyze_paragraph_logic_for_reader,
            db_factory(),
            paragraph_id,
            prefer_pro=_truthy_form_value(form.get("prefer_pro")),
            force_refresh=_truthy_form_value(form.get("force_refresh")),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.get("/analysis/paragraph/{paragraph_id}/logic-prompt")
    async def paragraph_logic_prompt_endpoint(paragraph_id: int) -> JSONResponse:
        try:
            prompt = await run_in_threadpool(
                build_external_paragraph_logic_prompt,
                db_factory(),
                paragraph_id,
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        return JSONResponse({"ok": True, "paragraph_id": paragraph_id, "prompt": prompt})

    @web_app.post("/analysis/paragraph/{paragraph_id}/logic-external")
    async def external_paragraph_logic_endpoint(
        paragraph_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        outcome = await run_in_threadpool(
            save_external_paragraph_logic_for_reader,
            db_factory(),
            paragraph_id,
            external_result=form.get("external_result", ""),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.get("/analysis/sentence/{sentence_id}/external-prompt")
    async def external_sentence_prompt_endpoint(sentence_id: int) -> JSONResponse:
        try:
            prompt = await run_in_threadpool(
                build_external_sentence_prompt,
                db_factory(),
                sentence_id,
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        return JSONResponse({"ok": True, "sentence_id": sentence_id, "prompt": prompt})

    @web_app.post("/analysis/sentence/{sentence_id}/external")
    async def external_sentence_analysis_endpoint(
        sentence_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        outcome = await run_in_threadpool(
            save_external_sentence_analysis_for_reader,
            db_factory(),
            sentence_id,
            external_result=form.get("external_result", ""),
            user_translation=form.get("user_translation"),
            user_structure=form.get("user_structure"),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.get("/analysis/word/{card_id}")
    def get_word_analysis(card_id: int, source_id: int | None = None) -> JSONResponse:
        payload = (
            _fetch_word_analysis_payload(db_factory(), card_id, source_id)
            if source_id is not None
            else _fetch_word_analysis_payload(db_factory(), card_id)
        )
        if payload is None:
            return JSONResponse(
                {"ok": False, "error": "No saved analysis for this word.", "retry": True},
                status_code=404,
            )
        return JSONResponse(payload)

    @web_app.get("/analysis/word/{card_id}/external-prompt")
    async def external_word_card_prompt_endpoint(
        card_id: int,
        source_id: int | None = None,
    ) -> JSONResponse:
        try:
            if source_id is None:
                payload = await run_in_threadpool(
                    build_external_word_prompt_for_card,
                    db_factory(),
                    card_id,
                )
            else:
                payload = await run_in_threadpool(
                    build_external_word_prompt_for_card,
                    db_factory(),
                    card_id,
                    source_id=source_id,
                )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/word/{card_id}/external")
    async def external_word_card_analysis_endpoint(
        card_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        source_id = _optional_int_form_value(form.get("source_id"))
        if source_id is None:
            outcome = await run_in_threadpool(
                save_external_word_analysis_for_card,
                db_factory(),
                card_id,
                external_result=form.get("external_result", ""),
            )
        else:
            outcome = await run_in_threadpool(
                save_external_word_analysis_for_card,
                db_factory(),
                card_id,
                external_result=form.get("external_result", ""),
                source_id=source_id,
            )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.post("/analysis/word/{card_id}")
    async def analyze_word_endpoint(card_id: int, request: Request) -> JSONResponse:
        form = await _read_form(request)
        outcome = await run_in_threadpool(
            analyze_word_card_for_reader,
            db_factory(),
            card_id,
            source_id=_optional_int_form_value(form.get("source_id")),
            context_text=form.get("context_text", ""),
            prefer_pro=_truthy_form_value(form.get("prefer_pro")),
            force_refresh=_truthy_form_value(form.get("force_refresh")),
        )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)

    @web_app.post("/analysis/word-source/{source_id}/sense")
    async def confirm_word_source_sense_endpoint(
        source_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        try:
            payload = await run_in_threadpool(
                confirm_word_source_sense,
                db_factory(),
                source_id,
                sense_id=_optional_int_form_value(form.get("sense_id")),
                create_new=_truthy_form_value(form.get("create_new")),
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/selection/word-external-prompt")
    async def external_word_selection_prompt_endpoint(request: Request) -> JSONResponse:
        form = await _read_form(request)
        try:
            payload = await run_in_threadpool(
                build_external_word_prompt_for_selection,
                db_factory(),
                sentence_id=int(form.get("sentence_id", "0")),
                surface_form=form.get("surface_form", ""),
                lexical_type=form.get("lexical_type", "word"),
                start_offset=_optional_int_form_value(
                    form.get("start_offset") or form.get("source_start_offset")
                ),
                end_offset=_optional_int_form_value(
                    form.get("end_offset") or form.get("source_end_offset")
                ),
                learner_note=form.get("learner_note", ""),
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/selection/word-external")
    async def external_word_selection_analysis_endpoint(request: Request) -> JSONResponse:
        form = await _read_form(request)
        try:
            outcome = await run_in_threadpool(
                save_external_word_analysis_for_selection,
                db_factory(),
                sentence_id=int(form.get("sentence_id", "0")),
                surface_form=form.get("surface_form", ""),
                lexical_type=form.get("lexical_type", "word"),
                start_offset=_optional_int_form_value(
                    form.get("start_offset") or form.get("source_start_offset")
                ),
                end_offset=_optional_int_form_value(
                    form.get("end_offset") or form.get("source_end_offset")
                ),
                learner_note=form.get("learner_note", ""),
                external_result=form.get("external_result", ""),
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        if outcome.is_error:
            return JSONResponse(outcome.error_payload(), status_code=outcome.status_code)
        return JSONResponse(outcome.payload)
