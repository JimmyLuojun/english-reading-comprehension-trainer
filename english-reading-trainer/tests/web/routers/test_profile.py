"""Tests for profile route registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.profile.learner_profile_generator import ProfileInputError
from app.web.routers import profile
from app.web.routers.profile import register_profile_routes
from tests.web.routers._helpers import registered_paths


def test_register_profile_routes_adds_profile_endpoints() -> None:
    paths = registered_paths(register_profile_routes)

    assert ("GET", "/profile") in paths
    assert ("GET", "/profile/prompt") in paths
    assert ("POST", "/profile/save") in paths


def test_profile_prompt_route_maps_input_error(monkeypatch) -> None:
    def fail_prompt(db):
        raise ProfileInputError("Not enough review data.")

    monkeypatch.setattr(profile, "build_profile_prompt", fail_prompt)
    app = FastAPI()
    register_profile_routes(app, lambda: object())

    response = TestClient(app).get("/profile/prompt")

    assert response.status_code == 400
    assert "Not enough review data." in response.text
