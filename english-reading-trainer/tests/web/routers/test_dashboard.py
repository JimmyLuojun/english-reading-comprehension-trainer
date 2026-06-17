"""Tests for dashboard route registration."""

from __future__ import annotations

from app.web.routers.dashboard import register_dashboard_routes
from tests.web.routers._helpers import registered_paths


def test_register_dashboard_routes_adds_dashboard_and_health() -> None:
    paths = registered_paths(register_dashboard_routes)

    assert ("GET", "/") in paths
    assert ("GET", "/health") in paths
