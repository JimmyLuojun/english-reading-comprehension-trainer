"""Tests for review route registration."""

from __future__ import annotations

from app.web.routers.review import register_review_routes
from tests.web.routers._helpers import registered_paths


def test_register_review_routes_adds_review_endpoints() -> None:
    paths = registered_paths(register_review_routes)

    assert ("GET", "/review") in paths
    assert ("POST", "/review/{card_type}/{card_id}") in paths
