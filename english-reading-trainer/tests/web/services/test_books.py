"""Tests for web book workflow services."""

from __future__ import annotations

from app.web.models import DeleteBookResult
from app.web.services import books


def test_delete_book_and_assets_purges_after_success(monkeypatch) -> None:
    calls: list[tuple[object, int]] = []
    result = DeleteBookResult(
        sentence_cards_deleted=1,
        word_cards_reanchored=2,
        word_cards_deleted=3,
        review_logs_deleted=4,
    )

    monkeypatch.setattr(books, "_delete_book", lambda db, book_id: result)
    monkeypatch.setattr(
        books,
        "_purge_book_assets_dir",
        lambda db, book_id: calls.append((db, book_id)),
    )

    db = object()

    assert books.delete_book_and_assets(db, 42) == result
    assert calls == [(db, 42)]


def test_delete_book_and_assets_skips_purge_when_book_missing(monkeypatch) -> None:
    calls: list[tuple[object, int]] = []

    monkeypatch.setattr(books, "_delete_book", lambda db, book_id: None)
    monkeypatch.setattr(
        books,
        "_purge_book_assets_dir",
        lambda db, book_id: calls.append((db, book_id)),
    )

    assert books.delete_book_and_assets(object(), 42) is None
    assert calls == []
