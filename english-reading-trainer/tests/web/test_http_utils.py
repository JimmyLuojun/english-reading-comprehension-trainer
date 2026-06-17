"""Tests for web HTTP and upload helpers."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import UploadFile

from app.web.http_utils import (
    _error_page,
    _read_form,
    _read_upload_bytes,
    _redirect,
    _safe_return_to,
    _save_upload_to_temp,
    _unlink_silent,
    _wants_json,
    _word_card_json_payload,
)
from app.web.models import UploadTooLargeError


class _FakeRequest:
    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self._body = body

    async def body(self) -> bytes:
        return self._body


def test_read_upload_bytes_enforces_limit() -> None:
    upload = UploadFile(file=BytesIO(b"abc"), filename="sample.txt")

    assert asyncio.run(_read_upload_bytes(upload, max_bytes=3)) == b"abc"

    too_large = UploadFile(file=BytesIO(b"abcd"), filename="sample.txt")
    with pytest.raises(UploadTooLargeError):
        asyncio.run(_read_upload_bytes(too_large, max_bytes=3))


def test_save_upload_to_temp_writes_and_cleans(tmp_path) -> None:
    upload = UploadFile(file=BytesIO(b"abc"), filename="sample.txt")

    path, size = asyncio.run(
        _save_upload_to_temp(upload, suffix=".txt", max_bytes=10),
    )

    assert size == 3
    assert path.read_bytes() == b"abc"
    _unlink_silent(path)
    assert not path.exists()
    _unlink_silent(tmp_path / "missing.txt")


def test_read_form_and_json_detection() -> None:
    request = _FakeRequest(b"title=A+Book&title=Final&empty=")

    assert asyncio.run(_read_form(request)) == {"title": "Final", "empty": ""}
    assert _wants_json(_FakeRequest(headers={"accept": "application/json"}))
    assert _wants_json(_FakeRequest(headers={"x-requested-with": "fetch"}))
    assert not _wants_json(_FakeRequest(headers={"accept": "text/html"}))


def test_response_helpers_escape_and_redirect() -> None:
    assert _safe_return_to("/read/1") == "/read/1"
    assert _safe_return_to("//evil.test") == "/"
    assert _redirect("/books").status_code == 303

    response = _error_page("<bad>", status_code=400)

    assert response.status_code == 400
    assert b"&lt;bad&gt;" in response.body


def test_word_card_json_payload_normalizes_optional_text() -> None:
    payload = _word_card_json_payload(
        {
            "id": 1,
            "lemma": "cat",
            "surface_form": "Cat",
            "lexical_type": "word",
            "current_meaning": None,
            "user_note": None,
        }
    )

    assert payload["current_meaning"] == ""
    assert payload["user_note"] == ""
