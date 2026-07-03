"""Tests for asset route registration."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.routers import assets
from app.web.routers.assets import register_asset_routes
from tests.web.routers._helpers import registered_paths


def test_register_asset_routes_adds_asset_endpoint() -> None:
    assert ("GET", "/assets/books/{book_id}/{asset_id}") in registered_paths(
        register_asset_routes,
    )


def test_asset_route_returns_404_for_missing_asset(monkeypatch) -> None:
    monkeypatch.setattr(assets, "_fetch_book_asset", lambda db, book_id, asset_id: None)
    app = FastAPI()
    register_asset_routes(app, lambda: object())

    response = TestClient(app).get("/assets/books/1/2")

    assert response.status_code == 404
    assert "Asset not found" in response.text


def test_asset_route_returns_404_for_invalid_storage_path(monkeypatch) -> None:
    monkeypatch.setattr(
        assets,
        "_fetch_book_asset",
        lambda db, book_id, asset_id: {
            "is_missing": False,
            "storage_path": "../escape.png",
            "media_type": "image/png",
        },
    )

    def reject_path(db, storage_path):
        raise ValueError("invalid")

    monkeypatch.setattr(assets, "_asset_storage_path", reject_path)
    app = FastAPI()
    register_asset_routes(app, lambda: object())

    response = TestClient(app).get("/assets/books/1/2")

    assert response.status_code == 404
    assert "Asset path is invalid" in response.text


def test_asset_route_returns_404_when_file_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.png"
    monkeypatch.setattr(
        assets,
        "_fetch_book_asset",
        lambda db, book_id, asset_id: {
            "is_missing": False,
            "storage_path": "missing.png",
            "media_type": "image/png",
        },
    )
    monkeypatch.setattr(assets, "_asset_storage_path", lambda db, storage_path: missing_path)
    app = FastAPI()
    register_asset_routes(app, lambda: object())

    response = TestClient(app).get("/assets/books/1/2")

    assert response.status_code == 404
    assert "Asset file is missing" in response.text
