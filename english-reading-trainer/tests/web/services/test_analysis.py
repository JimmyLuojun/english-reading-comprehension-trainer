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


def test_analyze_sentence_for_reader_uses_pro_model_when_requested(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v1")
    monkeypatch.setattr(analysis, "save_sentence_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"is_stale": False},
    )
    monkeypatch.setattr(analysis, "get_pro_analysis_model", lambda: "deepseek-test-pro")

    def fake_analyze_sentence(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_sentence", fake_analyze_sentence)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
        prefer_pro=True,
    )

    assert outcome.is_error is False
    assert captured["model"] == "deepseek-test-pro"


def test_analyze_sentence_for_reader_passes_force_refresh(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v1")
    monkeypatch.setattr(analysis, "save_sentence_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"is_stale": False},
    )

    def fake_analyze_sentence(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_sentence", fake_analyze_sentence)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
        force_refresh=True,
    )

    assert outcome.is_error is False
    assert captured["force_refresh"] is True


def test_analyze_sentence_for_reader_saves_and_passes_user_structure(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {
            "text": "The cat sat.",
            "user_translation": "",
            "user_structure": "主干：The cat sat",
        },
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v5")
    monkeypatch.setattr(analysis, "save_sentence_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"is_stale": False},
    )

    def fake_save_structure(db, sentence_id, user_structure):
        saved["sentence_id"] = sentence_id
        saved["user_structure"] = user_structure

    def fake_analyze_sentence(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(analysis, "save_sentence_structure", fake_save_structure)
    monkeypatch.setattr(fastapi_app, "analyze_sentence", fake_analyze_sentence)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
        user_structure="主干：The cat sat",
    )

    assert outcome.is_error is False
    assert saved == {"sentence_id": 1, "user_structure": "主干：The cat sat"}
    assert captured["user_structure"] == "主干：The cat sat"


def test_analyze_word_card_for_reader_uses_pro_model_when_requested(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(analysis, "get_pro_analysis_model", lambda: "deepseek-test-pro")
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)

    def fake_analyze_word(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_word", fake_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1, prefer_pro=True)

    assert outcome.is_error is False
    assert captured["model"] == "deepseek-test-pro"


def test_analyze_word_card_for_reader_passes_force_refresh(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)

    def fake_analyze_word(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_word", fake_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1, force_refresh=True)

    assert outcome.is_error is False
    assert captured["force_refresh"] is True


def test_analyze_word_card_for_reader_falls_back_to_saved_payload_on_invalid_response(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"ok": True, "card_id": card_id, "is_stale": False},
    )

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.is_error is False
    assert outcome.payload["is_stale"] is True
    assert outcome.payload["from_cache"] is True
    assert outcome.payload["retry"] is True
    assert "failed validation" in outcome.payload["warning"]


def test_analyze_word_card_for_reader_keeps_502_without_saved_payload_on_invalid_response(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )
    monkeypatch.setattr(analysis, "_fetch_word_analysis_payload", lambda db, card_id: None)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }


def test_analyze_word_card_for_reader_falls_back_to_saved_payload_on_runtime_error(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"ok": True, "card_id": card_id, "is_stale": False},
    )

    def fail_analyze_word(*args, **kwargs):
        raise RuntimeError("LLM call failed: timeout")

    monkeypatch.setattr(fastapi_app, "analyze_word", fail_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.is_error is False
    assert outcome.payload["is_stale"] is True
    assert outcome.payload["warning"] == "LLM call failed: timeout"


def test_analyze_word_card_for_reader_passes_analysis_context(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "pristine",
            "user_note": "未被触碰过的",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The original sentence lacks the target."},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)

    def fake_analyze_word(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_word", fake_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(
        object(),
        1,
        context_text=" A pristine ledger is untouched. ",
    )

    assert outcome.is_error is False
    assert captured["sentence_text"] == "The original sentence lacks the target."
    assert captured["context"] == "A pristine ledger is untouched."
    assert captured["learner_note"] == "未被触碰过的"
