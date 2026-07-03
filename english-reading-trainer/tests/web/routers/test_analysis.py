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
