"""Tests for review route registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_models import CardType, ReviewOutcome
from app.web.routers import review as review_router
from app.web.routers.review import register_review_routes
from tests.web.routers._helpers import registered_paths


def test_register_review_routes_adds_review_endpoints() -> None:
    paths = registered_paths(register_review_routes)

    assert ("GET", "/review") in paths
    assert ("POST", "/review/{card_type}/{card_id}") in paths


def test_review_card_accepts_urlencoded_outcome(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_apply_review(db, card_type, card_id, outcome):
        captured["card_type"] = card_type
        captured["card_id"] = card_id
        captured["outcome"] = outcome

    monkeypatch.setattr(review_router, "apply_review", fake_apply_review)
    app = FastAPI()
    register_review_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/review/word/36",
        data={"outcome": "pass", "return_to": "/review"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/review"
    assert captured == {
        "card_type": CardType.WORD,
        "card_id": 36,
        "outcome": ReviewOutcome.PASS,
    }


def test_review_card_rejects_missing_outcome() -> None:
    app = FastAPI()
    register_review_routes(app, lambda: "db")

    response = TestClient(app).post(
        "/review/word/36",
        data={"return_to": "/review"},
        follow_redirects=False,
    )

    assert response.status_code == 400
