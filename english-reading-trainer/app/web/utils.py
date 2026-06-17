"""Small shared web helpers."""

from __future__ import annotations

from app.web.config import _AUTO_TITLE_MAX_LEN


def _format_mb(byte_count: int) -> int:
    return byte_count // (1024 * 1024)


def _resolve_title(form_title: str, raw: bytes) -> str:
    title = form_title.strip()
    if title:
        return title
    first_line = raw.decode("utf-8", errors="ignore").strip().splitlines()[0:1]
    candidate = first_line[0].strip() if first_line else "Imported Text"
    return candidate[:_AUTO_TITLE_MAX_LEN] or "Imported Text"
