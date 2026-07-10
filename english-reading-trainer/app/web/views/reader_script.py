"""Reader interaction script asset lookup used by contract tests."""

from __future__ import annotations

from pathlib import Path

_READER_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "static" / "reader.js"


def _selection_script() -> str:
    """Return the browser asset for source-level interaction contract tests."""
    return _READER_SCRIPT_PATH.read_text(encoding="utf-8")
