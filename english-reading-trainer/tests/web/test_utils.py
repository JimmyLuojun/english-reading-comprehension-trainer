"""Tests for small shared web helpers."""

from __future__ import annotations

from app.web.utils import _format_mb, _resolve_title


def test_format_mb_uses_integer_megabytes() -> None:
    assert _format_mb(2 * 1024 * 1024 + 999) == 2


def test_resolve_title_prefers_form_title() -> None:
    assert _resolve_title("  Custom  ", b"First line") == "Custom"


def test_resolve_title_uses_first_line_or_fallback() -> None:
    assert _resolve_title("", b"  First line\nSecond") == "First line"
    assert _resolve_title("", b"   \n") == "Imported Text"
