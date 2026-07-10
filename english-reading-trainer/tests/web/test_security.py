"""Tests for local access protection and browser response boundaries."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.db_connection import DatabaseConnection
from app.web.fastapi_app import create_app
from app.web.security import _configured_allowed_hosts


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_TOKEN = "test-local-access-token"


def _client(tmp_path: Path) -> TestClient:
    db = DatabaseConnection(tmp_path / "security.db")
    db.apply_migrations(MIGRATIONS_DIR)
    return TestClient(
        create_app(
            lambda: db,
            request_token=_TOKEN,
            enforce_local_security=True,
        ),
        raise_server_exceptions=True,
    )


def test_local_access_token_is_required(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 401


def test_tokenized_entry_url_sets_session_cookie_and_removes_token(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get(
            f"/?access_token={_TOKEN}&chapter=1",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].endswith("/?chapter=1")
        assert "trainer_access" in response.headers["set-cookie"]

        resumed = client.get("/")

    assert resumed.status_code == 200


def test_header_token_allows_non_browser_clients(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/health", headers={"X-Trainer-Token": _TOKEN})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_cross_origin_write_is_rejected_even_with_valid_token(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/profile/save",
            data={"summary_md": "profile"},
            headers={
                "X-Trainer-Token": _TOKEN,
                "Origin": "https://attacker.example",
            },
        )

    assert response.status_code == 403


def test_same_origin_write_is_accepted(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/profile/save",
            data={"summary_md": "profile"},
            headers={
                "X-Trainer-Token": _TOKEN,
                "Origin": "http://testserver",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303


def test_query_token_on_same_origin_write_sets_access_cookie(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            f"/profile/save?access_token={_TOKEN}",
            data={"summary_md": "profile"},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "trainer_access" in response.headers["set-cookie"]


def test_cross_origin_referer_is_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/profile/save",
            data={"summary_md": "profile"},
            headers={
                "X-Trainer-Token": _TOKEN,
                "Referer": "https://attacker.example/form",
            },
        )

    assert response.status_code == 403


def test_allowed_hosts_are_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("TRAINER_ALLOWED_HOSTS", "127.0.0.1, Reader.Local ")

    assert _configured_allowed_hosts() == ("127.0.0.1", "reader.local")


def test_security_headers_are_present_for_html_responses(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/", headers={"X-Trainer-Token": _TOKEN})

    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
