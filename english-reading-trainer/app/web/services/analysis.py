"""AI analysis workflow services for the FastAPI web interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.ai.ai_provider_config import get_ai_provider_settings, get_pro_analysis_model
from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import (
    save_sentence_structure,
    save_sentence_translation,
)
from app.cards.word_card_service import get_word_card, record_word_card_diagnosis
from app.db_connection import DatabaseConnection
from app.web.queries import (
    _active_sentence_prompt_version,
    _fetch_cache_metadata,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
)

_WORD_ANALYSIS_FALLBACK_WARNING = (
    "New AI response failed validation. Showing previous saved analysis."
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
    user_structure: str | None = None,
    prefer_pro: bool = False,
    force_refresh: bool = False,
) -> AnalysisOutcome:
    """Analyze a sentence, save the result, and return its reader payload."""
    import app.web.fastapi_app as fastapi_app

    try:
        if user_translation is not None and user_translation.strip():
            save_sentence_translation(db, sentence_id, user_translation)
        if user_structure is not None and user_structure.strip():
            save_sentence_structure(db, sentence_id, user_structure)

        sentence = _fetch_sentence_for_analysis(db, sentence_id)
        result = fastapi_app.analyze_sentence(
            db,
            sentence["text"],
            user_translation=sentence.get("user_translation") or None,
            user_structure=sentence.get("user_structure") or None,
            model=get_pro_analysis_model() if prefer_pro else None,
            force_refresh=force_refresh,
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


def _fallback_word_analysis_payload(
    db: DatabaseConnection,
    card_id: int,
    *,
    warning: str = _WORD_ANALYSIS_FALLBACK_WARNING,
) -> dict[str, Any] | None:
    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return None
    payload["is_stale"] = True
    payload["from_cache"] = True
    payload["retry"] = True
    payload["warning"] = warning
    return payload


def analyze_word_card_for_reader(
    db: DatabaseConnection,
    card_id: int,
    *,
    context_text: str = "",
    prefer_pro: bool = False,
    force_refresh: bool = False,
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
            context=context_text.strip(),
            learner_note=(card.get("user_note") or "").strip(),
            model=get_pro_analysis_model() if prefer_pro else None,
            allow_stale=False,
            force_refresh=force_refresh,
        )
        if not result.is_valid:
            payload = _fallback_word_analysis_payload(db, card_id)
            if payload is not None:
                return AnalysisOutcome(payload=payload)
            return AnalysisOutcome(
                error="AI response failed validation.",
                status_code=502,
                retry=True,
            )
        fastapi_app._update_word_card_analysis_id(db, card_id, result.cache_id)
        record_word_card_diagnosis(db, card_id, result.data)
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    except RuntimeError as exc:
        payload = _fallback_word_analysis_payload(db, card_id, warning=str(exc))
        if payload is not None:
            return AnalysisOutcome(payload=payload)
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)
    except FileNotFoundError as exc:
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)

    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return AnalysisOutcome(error="Analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = result.from_cache
    payload["is_stale"] = bool(payload["is_stale"] or result.is_stale)
    return AnalysisOutcome(payload=payload)
