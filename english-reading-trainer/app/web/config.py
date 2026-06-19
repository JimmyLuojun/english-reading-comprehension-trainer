"""Configuration constants for the FastAPI web interface."""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "reading_trainer.db"
_MIGRATIONS = _PROJECT_ROOT / "migrations"
_DEFAULT_PAGE_LIMIT = 50
_MAX_TEXT_IMPORT_BYTES = 10 * 1024 * 1024
_MAX_EPUB_IMPORT_BYTES = 100 * 1024 * 1024
_MAX_PDF_IMPORT_BYTES = 100 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_AUTO_TITLE_MAX_LEN = 80
_DEFAULT_SENTENCE_PROMPT_VERSION = "v4"
_DEFAULT_WORD_PROMPT_VERSION = "v5"
_PREDICT_SENTENCE_PROMPT = "sentence_analysis_predict"
_DIAGNOSE_SENTENCE_PROMPT = "sentence_analysis_diagnose"
_WORD_ANALYSIS_PROMPT = "word_analysis"
_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[’'-][A-Za-z0-9]+)*")
