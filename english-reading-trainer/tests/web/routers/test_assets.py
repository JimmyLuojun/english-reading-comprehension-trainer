"""Tests for asset route registration."""

from __future__ import annotations

from app.web.routers.assets import register_asset_routes
from tests.web.routers._helpers import registered_paths


def test_register_asset_routes_adds_asset_endpoint() -> None:
    assert ("GET", "/assets/books/{book_id}/{asset_id}") in registered_paths(
        register_asset_routes,
    )
