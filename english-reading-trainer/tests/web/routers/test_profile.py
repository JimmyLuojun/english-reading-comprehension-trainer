"""Tests for profile route registration."""

from __future__ import annotations

from app.web.routers.profile import register_profile_routes
from tests.web.routers._helpers import registered_paths


def test_register_profile_routes_adds_profile_endpoints() -> None:
    paths = registered_paths(register_profile_routes)

    assert ("GET", "/profile") in paths
    assert ("GET", "/profile/prompt") in paths
    assert ("POST", "/profile/save") in paths
