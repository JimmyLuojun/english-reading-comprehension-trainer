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

    monkeypatch.setattr(books, "_fetch_book", lambda db, book_id: {"id": book_id})
    monkeypatch.setattr(books, "_delete_book", lambda db, book_id: result)
    monkeypatch.setattr(
        books,
        "_purge_book_assets_dir",
        lambda db, book_id: calls.append((db, book_id)),
    )

    class FakeDb:
        def create_backup(self, *, reason: str) -> None:
            calls.append((reason, 0))

    db = FakeDb()

    assert books.delete_book_and_assets(db, 42) == result
    assert calls == [("pre-book-delete-42", 0), (db, 42)]


def test_delete_book_and_assets_skips_purge_when_book_missing(monkeypatch) -> None:
    calls: list[tuple[object, int]] = []

    monkeypatch.setattr(books, "_fetch_book", lambda db, book_id: None)
    monkeypatch.setattr(
        books,
        "_purge_book_assets_dir",
        lambda db, book_id: calls.append((db, book_id)),
    )

    assert books.delete_book_and_assets(object(), 42) is None
    assert calls == []


def test_update_library_item_splits_tag_text(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_update(db, book_id, **values):
        captured.update({"db": db, "book_id": book_id, **values})
        return True

    monkeypatch.setattr(books, "_update_library_item", fake_update)
    db = object()

    assert books.update_library_item(
        db,
        7,
        title="Article",
        author="Writer",
        content_kind="article",
        library_status="reading",
        tags_text="Trade, Siemens",
    )
    assert captured == {
        "db": db,
        "book_id": 7,
        "title": "Article",
        "author": "Writer",
        "content_kind": "article",
        "library_status": "reading",
        "tags": ["Trade", " Siemens"],
    }


def test_delete_library_tag_delegates_to_query(monkeypatch) -> None:
    monkeypatch.setattr(
        books, "_delete_library_tag", lambda db, tag_id: ("Trade", [1, 2])
    )

    assert books.delete_library_tag(object(), 5) == ("Trade", [1, 2])
