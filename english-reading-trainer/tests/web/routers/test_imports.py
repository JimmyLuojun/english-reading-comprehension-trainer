"""Tests for import route registration."""

from __future__ import annotations

from app.web.routers.imports import register_import_routes
from tests.web.routers._helpers import registered_paths


def test_register_import_routes_adds_import_endpoints() -> None:
    paths = registered_paths(register_import_routes)

    assert ("GET", "/import") in paths
    assert ("POST", "/import/file") in paths
    assert ("POST", "/import/paste") in paths
