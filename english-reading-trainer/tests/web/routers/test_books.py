"""Tests for book route registration."""

from __future__ import annotations

from app.web.routers.books import register_book_routes
from tests.web.routers._helpers import registered_paths


def test_register_book_routes_adds_book_endpoints() -> None:
    paths = registered_paths(register_book_routes)

    assert ("GET", "/books") in paths
    assert ("POST", "/books/{book_id}/delete") in paths
    assert ("GET", "/books/{book_id}") in paths
