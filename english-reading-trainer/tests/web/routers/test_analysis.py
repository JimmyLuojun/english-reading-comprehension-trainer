"""Tests for analysis route registration."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.routers import analysis
from app.web.routers.analysis import register_analysis_routes
from tests.web.routers._helpers import registered_paths


def test_register_analysis_routes_adds_analysis_endpoints() -> None:
    paths = registered_paths(register_analysis_routes)

    assert ("GET", "/analysis/sentence/{sentence_id}") in paths
    assert ("POST", "/analysis/sentence/{sentence_id}") in paths
    assert ("GET", "/analysis/sentence/{sentence_id}/external-prompt") in paths
    assert ("POST", "/analysis/sentence/{sentence_id}/external") in paths
    assert ("POST", "/analysis/paragraph/{paragraph_id}/logic") in paths
    assert ("GET", "/analysis/paragraph/{paragraph_id}/logic-prompt") in paths
    assert ("POST", "/analysis/paragraph/{paragraph_id}/logic-external") in paths
    assert ("GET", "/analysis/word/{card_id}") in paths
    assert ("POST", "/analysis/word/{card_id}") in paths
    assert ("GET", "/analysis/word/{card_id}/external-prompt") in paths
    assert ("POST", "/analysis/word/{card_id}/external") in paths
    assert ("POST", "/analysis/selection/word-external-prompt") in paths
    assert ("POST", "/analysis/selection/word-external") in paths


def test_sentence_analysis_route_parses_force_refresh(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_analyze_sentence_for_reader(*args, **kwargs):
        captured.update(kwargs)
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "analyze_sentence_for_reader",
        fake_analyze_sentence_for_reader,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/sentence/1",
        data={
            "force_refresh": "1",
            "prefer_pro": "1",
            "user_structure": "主干：The cat sat",
        },
    )

    assert response.status_code == 200
    assert captured["force_refresh"] is True
    assert captured["prefer_pro"] is True
    assert captured["user_structure"] == "主干：The cat sat"


def test_get_sentence_analysis_route_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "_fetch_sentence_analysis_payload", lambda db, sid: None)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/sentence/1")

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "No saved analysis for this sentence.",
        "retry": True,
    }


def test_sentence_analysis_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 502

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "AI response failed validation.", "retry": True}

    monkeypatch.setattr(
        analysis,
        "analyze_sentence_for_reader",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post("/analysis/sentence/1")

    assert response.status_code == 502
    assert response.json() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }


def test_word_analysis_route_parses_force_refresh(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_analyze_word_card_for_reader(*args, **kwargs):
        captured.update(kwargs)
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "analyze_word_card_for_reader",
        fake_analyze_word_card_for_reader,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/word/1",
        data={"force_refresh": "true", "prefer_pro": "true"},
    )

    assert response.status_code == 200
    assert captured["force_refresh"] is True
    assert captured["prefer_pro"] is True


def test_word_analysis_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 404

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "Word card not found."}

    monkeypatch.setattr(
        analysis,
        "analyze_word_card_for_reader",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post("/analysis/word/1")

    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": "Word card not found."}


def test_get_word_analysis_route_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "_fetch_word_analysis_payload", lambda db, cid: None)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/word/7")

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "No saved analysis for this word.",
        "retry": True,
    }


def test_get_word_analysis_route_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, cid: {"ok": True, "card_id": cid},
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/word/7")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "card_id": 7}


def test_get_word_analysis_route_passes_source_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fetch(db, card_id, source_id):
        captured.update(card_id=card_id, source_id=source_id)
        return {"ok": True, "card_id": card_id, "source_id": source_id}

    monkeypatch.setattr(analysis, "_fetch_word_analysis_payload", fetch)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/word/7?source_id=13")

    assert response.status_code == 200
    assert captured == {"card_id": 7, "source_id": 13}


def test_confirm_word_source_sense_route(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def confirm(db, source_id, **kwargs):
        captured.update(source_id=source_id, **kwargs)
        return {"ok": True, "source_id": source_id, "current_sense_id": kwargs["sense_id"]}

    monkeypatch.setattr(analysis, "confirm_word_source_sense", confirm)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/word-source/5/sense",
        data={"sense_id": "12"},
    )

    assert response.status_code == 200
    assert captured == {"source_id": 5, "sense_id": 12, "create_new": False}
    assert response.json()["current_sense_id"] == 12


def test_confirm_word_source_sense_route_maps_invalid_choice(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise ValueError("Choose an existing meaning or create a new one.")

    monkeypatch.setattr(analysis, "confirm_word_source_sense", fail)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post("/analysis/word-source/5/sense")

    assert response.status_code == 400
    assert response.json()["retry"] is False


def test_paragraph_logic_route_parses_force_refresh(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_analyze_paragraph_logic_for_reader(*args, **kwargs):
        captured.update(kwargs)
        captured["paragraph_id"] = args[1]
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "analyze_paragraph_logic_for_reader",
        fake_analyze_paragraph_logic_for_reader,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/paragraph/7/logic",
        data={"force_refresh": "true", "prefer_pro": "true"},
    )

    assert response.status_code == 200
    assert captured == {
        "paragraph_id": 7,
        "force_refresh": True,
        "prefer_pro": True,
    }


def test_paragraph_logic_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 502

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "AI response failed validation.", "retry": True}

    monkeypatch.setattr(
        analysis,
        "analyze_paragraph_logic_for_reader",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post("/analysis/paragraph/7/logic")

    assert response.status_code == 502
    assert response.json() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }


def test_get_paragraph_logic_route_maps_value_error(monkeypatch) -> None:
    def fail_fetch(db, paragraph_id):
        raise ValueError("Paragraph id=7 not found.")

    monkeypatch.setattr(analysis, "_fetch_paragraph_logic_payload", fail_fetch)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/paragraph/7/logic")

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "Paragraph id=7 not found.",
        "retry": False,
    }


def test_get_paragraph_logic_route_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "_fetch_paragraph_logic_payload", lambda db, pid: None)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/paragraph/7/logic")

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "No saved analysis for this paragraph.",
        "retry": True,
    }


def test_get_paragraph_logic_route_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_logic_payload",
        lambda db, pid: {"ok": True, "paragraph_id": pid},
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/paragraph/7/logic")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "paragraph_id": 7}


def test_paragraph_logic_prompt_route_returns_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "build_external_paragraph_logic_prompt",
        lambda db, paragraph_id: f"paragraph prompt for {paragraph_id}",
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/paragraph/5/logic-prompt")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "paragraph_id": 5,
        "prompt": "paragraph prompt for 5",
    }


def test_paragraph_logic_prompt_route_maps_value_error(monkeypatch) -> None:
    def fail_prompt(db, paragraph_id):
        raise ValueError("Paragraph id=5 not found.")

    monkeypatch.setattr(analysis, "build_external_paragraph_logic_prompt", fail_prompt)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/paragraph/5/logic-prompt")

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "Paragraph id=5 not found.",
        "retry": False,
    }


def test_external_sentence_prompt_route_returns_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "build_external_sentence_prompt",
        lambda db, sentence_id: f"prompt for {sentence_id}",
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/sentence/5/external-prompt")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "sentence_id": 5,
        "prompt": "prompt for 5",
    }


def test_external_word_card_prompt_route_returns_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "build_external_word_prompt_for_card",
        lambda db, card_id: {
            "ok": True,
            "card_id": card_id,
            "sentence_id": 9,
            "prompt": f"word prompt for {card_id}",
        },
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/word/7/external-prompt")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "card_id": 7,
        "sentence_id": 9,
        "prompt": "word prompt for 7",
    }


def test_external_word_card_prompt_route_passes_source_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_prompt(*args, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "prompt": "context prompt"}

    monkeypatch.setattr(
        analysis,
        "build_external_word_prompt_for_card",
        fake_prompt,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get(
        "/analysis/word/7/external-prompt?source_id=19"
    )

    assert response.status_code == 200
    assert captured == {"source_id": 19}


def test_external_word_card_prompt_route_maps_value_error(monkeypatch) -> None:
    def fail_prompt(*args, **kwargs):
        raise ValueError("Word card not found.")

    monkeypatch.setattr(
        analysis,
        "build_external_word_prompt_for_card",
        fail_prompt,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/word/7/external-prompt")

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "Word card not found.",
        "retry": False,
    }


def test_external_word_selection_prompt_route_passes_offsets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_build_external_word_prompt_for_selection(*args, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "prompt": "selection prompt"}

    monkeypatch.setattr(
        analysis,
        "build_external_word_prompt_for_selection",
        fake_build_external_word_prompt_for_selection,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/selection/word-external-prompt",
        data={
            "sentence_id": "9",
            "surface_form": "evidenced",
            "lexical_type": "word",
            "start_offset": "16",
            "end_offset": "25",
            "learner_note": "证明；此处是被动语态",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "prompt": "selection prompt"}
    assert captured == {
        "sentence_id": 9,
        "surface_form": "evidenced",
        "lexical_type": "word",
        "start_offset": 16,
        "end_offset": 25,
        "learner_note": "证明；此处是被动语态",
    }


def test_external_word_selection_prompt_route_maps_value_error(monkeypatch) -> None:
    def fail_prompt(*args, **kwargs):
        raise ValueError("surface_form must not be empty.")

    monkeypatch.setattr(
        analysis,
        "build_external_word_prompt_for_selection",
        fail_prompt,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/selection/word-external-prompt",
        data={"sentence_id": "9", "surface_form": "", "lexical_type": "word"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "surface_form must not be empty.",
        "retry": False,
    }


def test_external_word_card_analysis_route_passes_pasted_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_save_external_word_analysis_for_card(*args, **kwargs):
        captured.update(kwargs)
        captured["card_id"] = args[1]
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "save_external_word_analysis_for_card",
        fake_save_external_word_analysis_for_card,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/word/7/external",
        data={"external_result": "full word reply"},
    )

    assert response.status_code == 200
    assert captured == {
        "card_id": 7,
        "external_result": "full word reply",
    }


def test_external_word_card_analysis_route_passes_source_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_save(*args, **kwargs):
        captured.update(kwargs)
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "save_external_word_analysis_for_card",
        fake_save,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/word/7/external",
        data={"external_result": "full word reply", "source_id": "19"},
    )

    assert response.status_code == 200
    assert captured == {
        "external_result": "full word reply",
        "source_id": 19,
    }


def test_external_word_card_analysis_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 400

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "bad external word JSON", "retry": False}

    monkeypatch.setattr(
        analysis,
        "save_external_word_analysis_for_card",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/word/7/external",
        data={"external_result": "not json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "bad external word JSON",
        "retry": False,
    }


def test_external_word_selection_analysis_route_passes_selection(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_save_external_word_analysis_for_selection(*args, **kwargs):
        captured.update(kwargs)
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "save_external_word_analysis_for_selection",
        fake_save_external_word_analysis_for_selection,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/selection/word-external",
        data={
            "sentence_id": "9",
            "surface_form": "evidenced",
            "lexical_type": "word",
            "start_offset": "16",
            "end_offset": "25",
            "learner_note": "证明；此处是被动语态",
            "external_result": "full word reply",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "sentence_id": 9,
        "surface_form": "evidenced",
        "lexical_type": "word",
        "start_offset": 16,
        "end_offset": 25,
        "learner_note": "证明；此处是被动语态",
        "external_result": "full word reply",
    }


def test_external_word_selection_analysis_route_maps_value_error(monkeypatch) -> None:
    def fail_save(*args, **kwargs):
        raise ValueError("selection offsets must include both start and end.")

    monkeypatch.setattr(
        analysis,
        "save_external_word_analysis_for_selection",
        fail_save,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/selection/word-external",
        data={
            "sentence_id": "9",
            "surface_form": "evidenced",
            "lexical_type": "word",
            "start_offset": "16",
            "external_result": "full word reply",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "selection offsets must include both start and end.",
        "retry": False,
    }


def test_external_word_selection_analysis_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 400

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "bad selection JSON", "retry": False}

    monkeypatch.setattr(
        analysis,
        "save_external_word_analysis_for_selection",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/selection/word-external",
        data={
            "sentence_id": "9",
            "surface_form": "evidenced",
            "lexical_type": "word",
            "external_result": "not json",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "bad selection JSON",
        "retry": False,
    }


def test_external_paragraph_logic_route_passes_pasted_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_save_external_paragraph_logic_for_reader(*args, **kwargs):
        captured.update(kwargs)
        captured["paragraph_id"] = args[1]
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "save_external_paragraph_logic_for_reader",
        fake_save_external_paragraph_logic_for_reader,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/paragraph/7/logic-external",
        data={"external_result": "full paragraph reply"},
    )

    assert response.status_code == 200
    assert captured == {
        "paragraph_id": 7,
        "external_result": "full paragraph reply",
    }


def test_external_paragraph_logic_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 400

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "bad paragraph JSON", "retry": False}

    monkeypatch.setattr(
        analysis,
        "save_external_paragraph_logic_for_reader",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/paragraph/7/logic-external",
        data={"external_result": "not json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "bad paragraph JSON",
        "retry": False,
    }


def test_external_sentence_prompt_route_maps_value_error(monkeypatch) -> None:
    def fail_prompt(db, sentence_id):
        raise ValueError("Sentence id=5 not found.")

    monkeypatch.setattr(analysis, "build_external_sentence_prompt", fail_prompt)
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).get("/analysis/sentence/5/external-prompt")

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "Sentence id=5 not found.",
        "retry": False,
    }


def test_external_sentence_analysis_route_passes_pasted_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def fake_save_external_sentence_analysis_for_reader(*args, **kwargs):
        captured.update(kwargs)
        captured["sentence_id"] = args[1]
        return Outcome()

    monkeypatch.setattr(
        analysis,
        "save_external_sentence_analysis_for_reader",
        fake_save_external_sentence_analysis_for_reader,
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/sentence/7/external",
        data={
            "external_result": "full reply",
            "user_translation": "译文",
            "user_structure": "主干：x",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "sentence_id": 7,
        "external_result": "full reply",
        "user_translation": "译文",
        "user_structure": "主干：x",
    }


def test_external_sentence_analysis_route_maps_service_error(monkeypatch) -> None:
    class Outcome:
        is_error = True
        status_code = 400

        @staticmethod
        def error_payload():
            return {"ok": False, "error": "bad external JSON", "retry": False}

    monkeypatch.setattr(
        analysis,
        "save_external_sentence_analysis_for_reader",
        lambda *args, **kwargs: Outcome(),
    )
    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    response = TestClient(app).post(
        "/analysis/sentence/7/external",
        data={"external_result": "not json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "bad external JSON",
        "retry": False,
    }


def test_blocking_analysis_post_does_not_block_event_loop(monkeypatch) -> None:
    """A slow analysis POST must not stall a concurrent saved-analysis GET.

    Regression: the POST handler used to run the blocking LLM call directly on
    the event loop (``async def`` calling a sync function), so a GET for another
    sentence's saved analysis hung on "Loading analysis..." until the in-flight
    analysis finished. Offloading to a threadpool keeps the loop responsive.
    """

    post_thread: dict[str, object] = {}
    release = threading.Event()

    class Outcome:
        is_error = False
        payload = {"ok": True}

    def slow_analyze_sentence_for_reader(*args, **kwargs):
        post_thread["thread"] = threading.current_thread()
        # Block the worker thread; the event loop must stay free meanwhile.
        release.wait(timeout=5)
        return Outcome()

    def fake_fetch_payload(_db, sentence_id):
        return {"ok": True, "sentence_id": sentence_id}

    monkeypatch.setattr(
        analysis,
        "analyze_sentence_for_reader",
        slow_analyze_sentence_for_reader,
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        fake_fetch_payload,
    )

    app = FastAPI()
    register_analysis_routes(app, lambda: object())

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            post_task = asyncio.create_task(client.post("/analysis/sentence/1"))
            # Give the POST a moment to enter the blocking worker call.
            await asyncio.sleep(0.1)

            # The GET must complete even though the POST is still blocked.
            get_response = await asyncio.wait_for(
                client.get("/analysis/sentence/2"), timeout=2
            )
            assert get_response.status_code == 200
            assert get_response.json()["sentence_id"] == 2

            # Now let the blocking POST finish.
            release.set()
            post_response = await asyncio.wait_for(post_task, timeout=2)
            assert post_response.status_code == 200

    start = time.monotonic()
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    # Sanity: the whole scenario finished well under the 5s block timeout,
    # proving the GET did not wait for the POST.
    assert time.monotonic() - start < 4

    # The blocking work ran off the event-loop thread (in a worker thread).
    assert post_thread["thread"] is not threading.main_thread()
