"""Tests for card route registration."""

from __future__ import annotations

from app.web.routers.cards import register_card_routes
from tests.web.routers._helpers import registered_paths


def test_register_card_routes_adds_card_endpoints() -> None:
    paths = registered_paths(register_card_routes)

    assert ("POST", "/mark/sentence/{sentence_id}") in paths
    assert ("POST", "/mark/sentence/{sentence_id}/translation") in paths
    assert ("DELETE", "/mark/sentence/{sentence_id}") in paths
    assert ("POST", "/mark/word") in paths
    assert ("DELETE", "/mark/word/{card_id}") in paths
    assert ("PATCH", "/mark/word/{card_id}") in paths
    assert ("GET", "/cards") in paths
