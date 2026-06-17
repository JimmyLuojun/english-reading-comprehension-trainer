"""Tests for dashboard statistics query helpers."""

from __future__ import annotations

from pathlib import Path

from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from app.web.queries import stats

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def test_dashboard_stats_counts_library_and_due_cards(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    source = tmp_path / "book.txt"
    source.write_text("One sentence. Two sentence.", encoding="utf-8")
    import_txt(db, source, title="Book", author="")
    monkeypatch.setattr(stats, "list_due_cards", lambda db: [object(), object()])

    result = stats._dashboard_stats(db)

    assert result["books"] == 1
    assert result["sentences"] == 2
    assert result["sentence_cards"] == 0
    assert result["word_cards"] == 0
    assert result["due_cards"] == 2
