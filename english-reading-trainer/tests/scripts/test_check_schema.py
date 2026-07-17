"""Tests for schema parity generation."""

from __future__ import annotations

from scripts.check_schema import generated_schema


def test_generated_schema_contains_current_migration_checksum_column() -> None:
    schema = generated_schema()

    assert "CREATE TABLE schema_migrations" in schema
    assert "checksum TEXT" in schema
    assert "content_kind TEXT NOT NULL DEFAULT 'unclassified'" in schema
    assert "import_method TEXT" in schema
    assert "source_uri TEXT NOT NULL DEFAULT ''" in schema
    assert "library_status TEXT NOT NULL DEFAULT 'inbox'" in schema
    assert "CREATE TABLE book_tags" in schema
