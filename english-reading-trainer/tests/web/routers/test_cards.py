"""Tests for card route registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.routers import cards
from app.web.routers.cards import register_card_routes
from tests.web.routers._helpers import registered_paths


def test_register_card_routes_adds_card_endpoints() -> None:
    paths = registered_paths(register_card_routes)

    assert ("POST", "/mark/sentence/{sentence_id}") in paths
    assert ("POST", "/mark/sentence/{sentence_id}/translation") in paths
    assert ("POST", "/mark/sentence/{sentence_id}/structure") in paths
    assert ("DELETE", "/mark/sentence/{sentence_id}") in paths
    assert ("PATCH", "/mark/sentence/{sentence_id}") in paths
    assert ("POST", "/mark/word") in paths
    assert ("DELETE", "/mark/word/{card_id}") in paths
    assert ("PATCH", "/mark/word/{card_id}") in paths
    assert ("GET", "/cards") in paths
    assert ("GET", "/cards/word/{card_id}/sources") in paths
    assert ("POST", "/cards/word/{card_id}/sources") in paths
    assert ("POST", "/cards/word/{card_id}/sources/{source_id}/primary") in paths


def test_sentence_structure_route_saves_form_value(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_save_sentence_structure(db, sentence_id, user_structure):
        captured["db"] = db
        captured["sentence_id"] = sentence_id
        captured["user_structure"] = user_structure

    monkeypatch.setattr(cards, "save_sentence_structure", fake_save_sentence_structure)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/sentence/42/structure",
        data={"user_structure": "主干：The cat sat", "return_to": "/read/1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/read/1"
    assert captured == {
        "db": "db",
        "sentence_id": 42,
        "user_structure": "主干：The cat sat",
    }
