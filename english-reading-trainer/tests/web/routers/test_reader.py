"""Tests for reader route registration."""

from __future__ import annotations

from app.web.routers.reader import register_reader_routes
from tests.web.routers._helpers import registered_paths


def test_register_reader_routes_adds_reader_endpoint() -> None:
    assert ("GET", "/read/{book_id}") in registered_paths(register_reader_routes)
