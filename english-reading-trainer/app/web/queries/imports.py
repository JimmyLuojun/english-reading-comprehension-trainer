"""Import route query helpers."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.review.daily_review_queue import list_due_cards
from app.web.config import (
    _DEFAULT_SENTENCE_PROMPT_VERSION,
    _DEFAULT_WORD_PROMPT_VERSION,
    _DIAGNOSE_SENTENCE_PROMPT,
    _PREDICT_SENTENCE_PROMPT,
    _WORD_ANALYSIS_PROMPT,
    _WORD_TOKEN_RE,
)
from app.web.models import DeleteBookResult

def _lookup_book_id_by_hash(db: DatabaseConnection, file_hash: str) -> int | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    return int(row["id"]) if row else None
