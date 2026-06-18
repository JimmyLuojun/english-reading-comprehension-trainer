"""HTTP request, response, and upload helpers for web routes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.web.config import _UPLOAD_CHUNK_BYTES
from app.web.models import UploadTooLargeError
from app.web.views import _html_page, _page_header

async def _read_upload_bytes(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)

async def _save_upload_to_temp(
    file: UploadFile,
    *,
    suffix: str,
    max_bytes: int,
) -> tuple[Path, int]:
    total = 0
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLargeError(max_bytes)
                tmp.write(chunk)
        except Exception:
            _unlink_silent(tmp_path)
            raise
    return tmp_path, total

def _unlink_silent(file_path: str | Path) -> None:
    try:
        Path(file_path).unlink()
    except OSError:
        pass

async def _read_form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}

def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    requested_with = request.headers.get("x-requested-with", "")
    return "application/json" in accept or requested_with.lower() == "fetch"

def _word_card_json_payload(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card["id"],
        "lemma": card["lemma"],
        "surface_form": card["surface_form"],
        "lexical_type": card["lexical_type"],
        "current_meaning": card.get("current_meaning") or "",
        "user_note": card.get("user_note") or "",
    }

def _safe_return_to(value: str) -> str:
    if value.startswith("/") and not value.startswith("//"):
        return value
    return "/"

def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)

def _error_page(message: str, *, status_code: int) -> HTMLResponse:
    body = _page_header(
        "Request Error",
        message,
        '<a class="button" href="/">Dashboard</a>',
    )
    return _html_page("Error", body, active="", status_code=status_code)
