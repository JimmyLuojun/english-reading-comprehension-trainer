"""Tests for web AI analysis workflow services."""

from __future__ import annotations

from types import SimpleNamespace

from app.web.services import analysis


def test_analysis_outcome_error_payload_omits_retry_when_unspecified() -> None:
    outcome = analysis.AnalysisOutcome(error="missing", status_code=404)

    assert outcome.error_payload() == {"ok": False, "error": "missing"}


def test_analyze_word_card_for_reader_returns_404_for_missing_card(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "get_word_card", lambda db, card_id: None)

    outcome = analysis.analyze_word_card_for_reader(object(), 123)

    assert outcome.status_code == 404
    assert outcome.error_payload() == {"ok": False, "error": "Word card not found."}


def test_analyze_sentence_for_reader_maps_invalid_ai_response(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        fastapi_app,
        "analyze_sentence",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
    )

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }
