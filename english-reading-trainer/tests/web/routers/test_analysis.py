"""Tests for analysis route registration."""

from __future__ import annotations

from app.web.routers.analysis import register_analysis_routes
from tests.web.routers._helpers import registered_paths


def test_register_analysis_routes_adds_analysis_endpoints() -> None:
    paths = registered_paths(register_analysis_routes)

    assert ("GET", "/analysis/sentence/{sentence_id}") in paths
    assert ("POST", "/analysis/sentence/{sentence_id}") in paths
    assert ("GET", "/analysis/word/{card_id}") in paths
    assert ("POST", "/analysis/word/{card_id}") in paths
