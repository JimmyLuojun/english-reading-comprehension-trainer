"""Tests for card route registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.web.routers import cards
from app.web.routers.cards import _matching_word_source, register_card_routes
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


def test_mark_sentence_route_ignores_already_exists_and_redirects(monkeypatch) -> None:
    def already_exists(*_args, **_kwargs):
        raise cards.SentenceCardAlreadyExistsError("exists")

    monkeypatch.setattr(cards, "create_sentence_card", already_exists)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/sentence/42",
        data={"return_to": "/read/1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/read/1"


def test_sentence_mutation_success_routes_redirect(monkeypatch) -> None:
    monkeypatch.setattr(cards, "delete_sentence_translation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards, "archive_sentence_card", lambda *_args, **_kwargs: None)
    app = FastAPI()
    register_card_routes(app, lambda: "db")
    client = TestClient(app)

    translation_response = client.delete(
        "/mark/sentence/42/translation?return_to=/read/1",
        follow_redirects=False,
    )
    unmark_response = client.delete(
        "/mark/sentence/42?return_to=/read/1",
        follow_redirects=False,
    )

    assert translation_response.status_code == 303
    assert translation_response.headers["location"] == "/read/1"
    assert unmark_response.status_code == 303
    assert unmark_response.headers["location"] == "/read/1"


def test_sentence_note_patch_success_returns_card_id(monkeypatch) -> None:
    monkeypatch.setattr(cards, "update_sentence_card_note", lambda *_args, **_kwargs: 9)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).patch("/mark/sentence/42", data={"user_note": "note"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "card_id": 9}


def test_mark_word_html_success_redirects(monkeypatch) -> None:
    monkeypatch.setattr(cards, "create_or_update_word_card", lambda *_args, **_kwargs: (7, True))
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/word",
        data={
            "sentence_id": "42",
            "surface_form": "bright",
            "lexical_type": "word",
            "return_to": "/read/1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/read/1"


def test_word_mutation_success_routes_redirect_and_patch(monkeypatch) -> None:
    monkeypatch.setattr(cards, "archive_word_card", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards, "update_word_card_note", lambda *_args, **_kwargs: None)
    app = FastAPI()
    register_card_routes(app, lambda: "db")
    client = TestClient(app)

    delete_response = client.delete(
        "/mark/word/7?return_to=/cards",
        follow_redirects=False,
    )
    patch_response = client.patch(
        "/mark/word/7",
        data={"current_meaning": "meaning", "user_note": "note"},
    )

    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/cards"
    assert patch_response.status_code == 200
    assert patch_response.json() == {"ok": True}


def test_cards_page_renders_sentence_and_word_tables(monkeypatch) -> None:
    monkeypatch.setattr(cards, "list_sentence_cards", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cards, "list_word_cards", lambda *_args, **_kwargs: [])
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).get("/cards")

    assert response.status_code == 200
    assert "Sentence Cards" in response.text
    assert "Word Cards" in response.text


def test_word_card_sources_page_renders_existing_card(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "get_word_card",
        lambda *_args, **_kwargs: {
            "id": 7,
            "surface_form": "bright",
            "lemma": "bright",
            "lexical_type": "word",
            "occurrence_count": 1,
            "created_at": "2026-06-30",
            "next_review_at": "2026-07-01",
        },
    )
    monkeypatch.setattr(cards, "list_word_card_sources", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        cards,
        "find_word_card_occurrence_candidates",
        lambda *_args, **_kwargs: [],
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).get("/cards/word/7/sources")

    assert response.status_code == 200
    assert "Word Card Sources" in response.text


def test_word_source_mutation_success_routes_redirect(monkeypatch) -> None:
    monkeypatch.setattr(cards, "add_word_card_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards, "set_primary_word_card_source", lambda *_args, **_kwargs: None)
    app = FastAPI()
    register_card_routes(app, lambda: "db")
    client = TestClient(app)

    add_response = client.post(
        "/cards/word/7/sources",
        data={"sentence_id": "42"},
        follow_redirects=False,
    )
    primary_response = client.post(
        "/cards/word/7/sources/11/primary",
        follow_redirects=False,
    )

    assert add_response.status_code == 303
    assert add_response.headers["location"] == "/cards/word/7/sources"
    assert primary_response.status_code == 303
    assert primary_response.headers["location"] == "/cards/word/7/sources"


def test_matching_word_source_filters_until_exact_offset_match(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "list_word_card_sources",
        lambda _db, _card_id: [
            {
                "id": 1,
                "sentence_id": 99,
                "source_key": "bright",
                "start_offset": 9,
                "end_offset": 15,
                "selected_text": "wrong sentence",
            },
            {
                "id": 2,
                "sentence_id": 42,
                "source_key": "other",
                "start_offset": 9,
                "end_offset": 15,
                "selected_text": "wrong key",
            },
            {
                "id": 3,
                "sentence_id": 42,
                "source_key": "bright",
                "start_offset": 1,
                "end_offset": 7,
                "selected_text": "wrong offset",
            },
            {
                "id": 4,
                "sentence_id": 42,
                "source_key": "bright",
                "start_offset": 9,
                "end_offset": 15,
                "selected_text": "Bright",
            },
        ],
    )

    assert _matching_word_source("db", 7, 42, " Bright ", 9, 15) == {
        "id": 4,
        "sentence_id": 42,
        "start_offset": 9,
        "end_offset": 15,
        "selected_text": "Bright",
    }


def test_matching_word_source_requires_legacy_source_when_offsets_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "list_word_card_sources",
        lambda _db, _card_id: [
            {
                "id": 1,
                "sentence_id": 42,
                "source_key": "bright",
                "start_offset": 9,
                "end_offset": 15,
                "selected_text": "new",
            },
            {
                "id": 2,
                "sentence_id": 42,
                "source_key": "bright",
                "start_offset": None,
                "end_offset": None,
                "selected_text": None,
            },
        ],
    )

    assert _matching_word_source("db", 7, 42, "bright", None, None) == {
        "id": 2,
        "sentence_id": 42,
        "start_offset": None,
        "end_offset": None,
        "selected_text": "",
    }


def test_matching_word_source_returns_none_without_match(monkeypatch) -> None:
    monkeypatch.setattr(cards, "list_word_card_sources", lambda _db, _card_id: [])

    assert _matching_word_source("db", 7, 42, "bright", 9, 15) is None


@pytest.mark.parametrize(
    ("route", "service_name"),
    [
        ("/mark/sentence/42/translation", "save_sentence_translation"),
        ("/mark/sentence/42/structure", "save_sentence_structure"),
    ],
)
def test_sentence_save_routes_return_400_on_value_error(
    monkeypatch,
    route: str,
    service_name: str,
) -> None:
    def fail(*_args, **_kwargs):
        raise ValueError("bad sentence")

    monkeypatch.setattr(cards, service_name, fail)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(route, data={"return_to": "/read/1"})

    assert response.status_code == 400
    assert "bad sentence" in response.text


def test_mark_sentence_route_returns_400_on_value_error(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "create_sentence_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("missing sentence")),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post("/mark/sentence/42", data={"return_to": "/read/1"})

    assert response.status_code == 400
    assert "missing sentence" in response.text


def test_sentence_delete_translation_route_returns_400_on_value_error(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "delete_sentence_translation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("no sentence")),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).delete("/mark/sentence/42/translation")

    assert response.status_code == 400
    assert "no sentence" in response.text


def test_unmark_sentence_route_returns_400_on_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "archive_sentence_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cards.SentenceCardNotFoundError("not marked")
        ),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).delete("/mark/sentence/42")

    assert response.status_code == 400
    assert "not marked" in response.text


def test_sentence_note_patch_returns_json_404_on_value_error(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "update_sentence_card_note",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("missing card")),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).patch("/mark/sentence/42", data={"user_note": "note"})

    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": "missing card"}


@pytest.mark.parametrize("headers", [{}, {"Accept": "application/json"}])
def test_mark_word_route_returns_400_on_invalid_form_input(headers) -> None:
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/word",
        data={"sentence_id": "not-int", "lexical_type": "word"},
        headers=headers,
    )

    assert response.status_code == 400
    assert "Invalid word card input" in response.text


@pytest.mark.parametrize("headers", [{}, {"Accept": "application/json"}])
def test_mark_word_route_returns_400_on_service_value_error(monkeypatch, headers) -> None:
    monkeypatch.setattr(
        cards,
        "create_or_update_word_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad word")),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/word",
        data={"sentence_id": "42", "surface_form": "x", "lexical_type": "word"},
        headers=headers,
    )

    assert response.status_code == 400
    assert "bad word" in response.text


def test_mark_word_json_route_returns_500_when_saved_card_missing(monkeypatch) -> None:
    monkeypatch.setattr(cards, "create_or_update_word_card", lambda *_args, **_kwargs: (7, True))
    monkeypatch.setattr(cards, "get_word_card", lambda *_args, **_kwargs: None)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/mark/word",
        data={"sentence_id": "42", "surface_form": "x", "lexical_type": "word"},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 500
    assert response.json() == {"ok": False, "error": "Word card was not saved."}


def test_unmark_word_route_returns_400_on_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "archive_word_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cards.WordCardNotFoundError("missing word")
        ),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).delete("/mark/word/7")

    assert response.status_code == 400
    assert "missing word" in response.text


def test_word_note_patch_returns_json_404_on_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "update_word_card_note",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cards.WordCardNotFoundError("missing word")
        ),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).patch("/mark/word/7", data={"user_note": "note"})

    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": "missing word"}


def test_word_card_sources_page_returns_404_when_card_missing(monkeypatch) -> None:
    monkeypatch.setattr(cards, "get_word_card", lambda *_args, **_kwargs: None)
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).get("/cards/word/7/sources")

    assert response.status_code == 404
    assert "Active word card id=7 not found." in response.text


def test_add_word_source_route_returns_400_on_invalid_input(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "add_word_card_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad source")),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/cards/word/7/sources",
        data={"sentence_id": "42"},
    )

    assert response.status_code == 400
    assert "bad source" in response.text


def test_set_primary_word_source_route_returns_400_on_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        cards,
        "set_primary_word_card_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cards.WordCardSourceNotFoundError("missing source")
        ),
    )
    app = FastAPI()
    register_card_routes(app, lambda: "db")

    response = TestClient(app).post("/cards/word/7/sources/11/primary")

    assert response.status_code == 400
    assert "missing source" in response.text
