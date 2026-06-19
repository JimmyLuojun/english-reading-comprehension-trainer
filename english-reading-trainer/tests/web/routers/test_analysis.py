"""Tests for analysis route registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.routers import analysis
from app.web.routers.analysis import register_analysis_routes
from tests.web.routers._helpers import registered_paths


def test_register_analysis_routes_adds_analysis_endpoints() -> None:
    paths = registered_paths(register_analysis_routes)

    assert ("GET", "/analysis/sentence/{sentence_id}") in paths
    assert ("POST", "/analysis/sentence/{sentence_id}") in paths
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
