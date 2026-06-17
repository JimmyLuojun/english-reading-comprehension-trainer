"""Data containers and exceptions for the FastAPI web interface."""

from __future__ import annotations

from dataclasses import dataclass

from app.web.utils import _format_mb


class UploadTooLargeError(ValueError):
    """Raised when a streamed upload exceeds the configured byte cap."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"Upload exceeds {_format_mb(max_bytes)} MB limit.")


@dataclass(frozen=True)
class DeleteBookResult:
    """Statistics returned after deleting an imported book/article."""

    sentence_cards_deleted: int
    word_cards_reanchored: int
    word_cards_deleted: int
    review_logs_deleted: int
