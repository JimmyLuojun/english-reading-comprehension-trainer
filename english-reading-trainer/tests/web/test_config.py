"""Tests for web configuration constants."""

from __future__ import annotations

from app.web import config


def test_upload_limits_and_paths_are_defined() -> None:
    assert config._MAX_TEXT_IMPORT_BYTES > 0
    assert config._MAX_EPUB_IMPORT_BYTES > config._MAX_TEXT_IMPORT_BYTES
    assert config._UPLOAD_CHUNK_BYTES > 0
    assert config._DEFAULT_DB.name == "reading_trainer.db"
    assert config._MIGRATIONS.name == "migrations"


def test_word_token_pattern_matches_english_terms() -> None:
    assert [m.group(0) for m in config._WORD_TOKEN_RE.finditer("Cat's cradle, 42")] == [
        "Cat's",
        "cradle",
        "42",
    ]
