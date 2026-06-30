"""Tests for import route registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.routers import imports
from app.web.services.imports import ImportOutcome
from tests.web.routers._helpers import registered_paths


def test_register_import_routes_adds_import_endpoints() -> None:
    paths = registered_paths(imports.register_import_routes)

    assert ("GET", "/import") in paths
    assert ("POST", "/import/file") in paths
    assert ("POST", "/import/paste") in paths
    assert ("POST", "/import/url") in paths


def test_import_url_route_redirects_to_reader(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_import_url_content(db, url, *, form_title, author):
        seen["url"] = url
        seen["title"] = form_title
        seen["author"] = author
        return ImportOutcome(book_id=23)

    monkeypatch.setattr(imports, "import_url_content", fake_import_url_content)
    app = FastAPI()
    imports.register_import_routes(app, lambda: object())

    response = TestClient(app).post(
        "/import/url",
        data={
            "url": "https://example.com/article",
            "title": "Remote Article",
            "author": "Writer",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/read/23"
    assert seen == {
        "url": "https://example.com/article",
        "title": "Remote Article",
        "author": "Writer",
    }


def test_import_url_route_requires_url(monkeypatch) -> None:
    monkeypatch.setattr(
        imports,
        "import_url_content",
        lambda *args, **kwargs: ImportOutcome(book_id=99),
    )
    app = FastAPI()
    imports.register_import_routes(app, lambda: object())

    response = TestClient(app).post("/import/url", data={"url": "   "})

    assert response.status_code == 400
    assert "URL is empty" in response.text


def test_import_url_route_returns_service_error(monkeypatch) -> None:
    monkeypatch.setattr(
        imports,
        "import_url_content",
        lambda *args, **kwargs: ImportOutcome(error="URL failed", status_code=502),
    )
    app = FastAPI()
    imports.register_import_routes(app, lambda: object())

    response = TestClient(app).post(
        "/import/url",
        data={"url": "https://example.com/article"},
    )

    assert response.status_code == 502
    assert "URL failed" in response.text


def test_import_empty_epub_and_pdf_return_400() -> None:
    app = FastAPI()
    imports.register_import_routes(app, lambda: object())
    client = TestClient(app)

    epub_response = client.post(
        "/import/file",
        files={"file": ("empty.epub", b"", "application/epub+zip")},
    )
    pdf_response = client.post(
        "/import/file",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert epub_response.status_code == 400
    assert pdf_response.status_code == 400
    assert "empty" in epub_response.text.lower()
    assert "empty" in pdf_response.text.lower()
