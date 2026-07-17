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


def test_resolve_title_stops_at_first_sentence_within_wrapped_source_line() -> None:
    raw = (
        "2. No foreign-trade layer — this is the biggest fit gap. The system\n"
        "continues on the next source line."
    ).encode()

    assert _resolve_title("", raw) == (
        "2. No foreign-trade layer — this is the biggest fit gap."
    )


def test_resolve_title_prefers_meaningful_filename_fallback_before_first_line() -> None:
    assert _resolve_title(
        "",
        b"Movie Scripts\n\nBody.",
        fallback_title="The_escappe_plan_lines",
    ) == "The_escappe_plan_lines"


def test_resolve_title_ignores_throwaway_filename_fallback() -> None:
    assert _resolve_title("", b"First line\nBody.", fallback_title="a") == "First line"
    assert _resolve_title("", b"First line\nBody.", fallback_title="tmp110d0ebd") == "First line"
