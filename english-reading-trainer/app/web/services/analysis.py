"""AI analysis workflow services for the FastAPI web interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.ai.ai_provider_config import get_ai_provider_settings
from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import save_sentence_translation
from app.cards.word_card_service import get_word_card
from app.db_connection import DatabaseConnection
from app.web.queries import (
    _active_sentence_prompt_version,
    _fetch_cache_metadata,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
)


@dataclass(frozen=True)
class AnalysisOutcome:
    """Result of an AI analysis workflow, independent of HTTP rendering."""

    payload: dict[str, Any] | None = None
    error: str | None = None
    status_code: int = 200
    retry: bool | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def error_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "error": self.error or ""}
        if self.retry is not None:
            payload["retry"] = self.retry
        return payload


def analyze_sentence_for_reader(
    db: DatabaseConnection,
    sentence_id: int,
    *,
    user_translation: str | None,
) -> AnalysisOutcome:
    """Analyze a sentence, save the result, and return its reader payload."""
    import app.web.fastapi_app as fastapi_app

    try:
        if user_translation is not None and user_translation.strip():
            save_sentence_translation(db, sentence_id, user_translation)

        sentence = _fetch_sentence_for_analysis(db, sentence_id)
        result = fastapi_app.analyze_sentence(
            db,
            sentence["text"],
            user_translation=sentence.get("user_translation") or None,
        )
        if not result.is_valid:
            return AnalysisOutcome(
                error="AI response failed validation.",
                status_code=502,
                retry=True,
            )

        cache_meta = _fetch_cache_metadata(db, result.cache_id)
        save_sentence_analysis(
            db,
            sentence_id,
            json.dumps(result.data, ensure_ascii=False),
            model=cache_meta.get("model") or get_ai_provider_settings().model,
            prompt_version=cache_meta.get("prompt_version")
            or _active_sentence_prompt_version(
                db,
                sentence.get("user_translation") or None,
            ),
        )
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    except (FileNotFoundError, RuntimeError) as exc:
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)

    payload = _fetch_sentence_analysis_payload(db, sentence_id)
    if payload is None:
        return AnalysisOutcome(error="Analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = result.from_cache
    payload["is_stale"] = bool(payload["is_stale"] or result.is_stale)
    return AnalysisOutcome(payload=payload)


def analyze_word_card_for_reader(
    db: DatabaseConnection,
    card_id: int,
) -> AnalysisOutcome:
    """Analyze a word card, attach the cache id, and return its reader payload."""
    import app.web.fastapi_app as fastapi_app

    card = get_word_card(db, card_id)
    if card is None:
        return AnalysisOutcome(error="Word card not found.", status_code=404)
    try:
        sentence = _fetch_sentence_for_analysis(db, card["first_sentence_id"])
        result = fastapi_app.analyze_word(
            db,
            surface_form=card["surface_form"],
            sentence_text=sentence["text"],
            allow_stale=False,
        )
        if not result.is_valid:
            return AnalysisOutcome(
                error="AI response failed validation.",
                status_code=502,
                retry=True,
            )
        fastapi_app._update_word_card_analysis_id(db, card_id, result.cache_id)
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    except (FileNotFoundError, RuntimeError) as exc:
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)

    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return AnalysisOutcome(error="Analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = result.from_cache
    payload["is_stale"] = bool(payload["is_stale"] or result.is_stale)
    return AnalysisOutcome(payload=payload)
