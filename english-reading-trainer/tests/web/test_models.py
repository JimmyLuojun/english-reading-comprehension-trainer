"""Tests for web data containers and exceptions."""

from __future__ import annotations

from app.web.models import DeleteBookResult, UploadTooLargeError


def test_upload_too_large_error_exposes_limit() -> None:
    exc = UploadTooLargeError(3 * 1024 * 1024)

    assert exc.max_bytes == 3 * 1024 * 1024
    assert str(exc) == "Upload exceeds 3 MB limit."


def test_delete_book_result_is_value_container() -> None:
    result = DeleteBookResult(
        sentence_cards_deleted=1,
        word_cards_reanchored=2,
        word_cards_deleted=3,
        review_logs_deleted=4,
    )

    assert result.word_cards_reanchored == 2
