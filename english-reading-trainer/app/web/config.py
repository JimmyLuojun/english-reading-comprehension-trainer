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
_MAX_URL_IMPORT_BYTES = _MAX_TEXT_IMPORT_BYTES
_URL_IMPORT_TIMEOUT_SECONDS = 10.0
_URL_IMPORT_MAX_REDIRECTS = 5
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_AUTO_TITLE_MAX_LEN = 80
_DEFAULT_SENTENCE_PROMPT_VERSION = "v7"
_DEFAULT_WORD_PROMPT_VERSION = "v5"
_DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION = "paragraph_logic_lens.v3"
_PREDICT_SENTENCE_PROMPT = "sentence_analysis_predict"
_DIAGNOSE_SENTENCE_PROMPT = "sentence_analysis_diagnose"
_WORD_ANALYSIS_PROMPT = "word_analysis"
_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[’'-][A-Za-z0-9]+)*")
