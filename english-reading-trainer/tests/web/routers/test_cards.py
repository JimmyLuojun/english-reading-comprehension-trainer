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


def test_sentence_translation_route_allows_empty_value(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_save_sentence_translation(db, sentence_id, user_translation):
        captured["db"] = db
        captured["sentence_id"] = sentence_id
        captured["user_translation"] = user_translation

    monkeypatch.setattr(cards, "save_sentence_translation", fake_save_sentence_translation)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/sentence/42/translation",
        data={"user_translation": "", "return_to": "/read/1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/read/1"
    assert captured == {
        "db": "db",
        "sentence_id": 42,
        "user_translation": "",
    }


def test_mark_word_json_route_passes_and_returns_source_offsets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_or_update_word_card(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 7, True

    def fake_get_word_card(_db, card_id):
        assert card_id == 7
        return {
            "id": 7,
            "lemma": "bright",
            "surface_form": "bright",
            "lexical_type": "word",
            "current_meaning": "",
            "user_note": "",
        }

    def fake_matching_word_source(*args):
        captured["source_args"] = args
        return {
            "id": 11,
            "sentence_id": 42,
            "start_offset": 9,
            "end_offset": 15,
            "selected_text": "bright",
        }

    monkeypatch.setattr(cards, "create_or_update_word_card", fake_create_or_update_word_card)
    monkeypatch.setattr(cards, "get_word_card", fake_get_word_card)
    monkeypatch.setattr(cards, "_matching_word_source", fake_matching_word_source)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/word",
        data={
            "sentence_id": "42",
            "surface_form": "bright",
            "lexical_type": "word",
            "source_start_offset": "9",
            "source_end_offset": "15",
            "selected_text": "bright",
        },
        headers={"X-Requested-With": "fetch", "Accept": "application/json"},
    )

    assert response.status_code == 200
    assert captured["kwargs"] == {
        "source_start_offset": 9,
        "source_end_offset": 15,
        "selected_text": "bright",
    }
    assert response.json()["source"] == {
        "id": 11,
        "sentence_id": 42,
        "start_offset": 9,
        "end_offset": 15,
        "selected_text": "bright",
    }
