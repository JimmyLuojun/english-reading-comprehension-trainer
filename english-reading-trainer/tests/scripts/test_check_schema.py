"""Tests for schema parity generation."""

from __future__ import annotations

from scripts.check_schema import generated_schema


def test_generated_schema_contains_current_migration_checksum_column() -> None:
    schema = generated_schema()

    assert "CREATE TABLE schema_migrations" in schema
    assert "checksum TEXT" in schema
