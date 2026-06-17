from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.ai.ai_provider_config import get_ai_provider_settings
from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    SentenceCardNotFoundError,
    archive_sentence_card,
    create_sentence_card,
    list_sentence_cards,
    save_sentence_translation,
)
from app.cards.word_card_service import (
    WordCardNotFoundError,
    archive_word_card,
    create_or_update_word_card,
    get_word_card,
    list_word_cards,
    update_word_card_note,
)
from app.db_connection import DatabaseConnection
from app.db_models import CardType, LexicalType, ReviewOutcome
from app.importers.epub_importer import DuplicateBookError as EpubDuplicateBookError
from app.importers.epub_importer import calculate_epub_file_hash, import_epub
from app.importers.txt_importer import DuplicateBookError, import_text
from app.profile.learner_profile_generator import (
    ProfileInputError,
    build_profile_prompt,
    get_latest_profile_snapshot,
    get_profile_trigger_status,
    save_profile_snapshot,
)
from app.review.daily_review_queue import build_daily_review_queue
from app.review.sm2_scheduler import (
    ReviewCardNotFoundError,
    ReviewInputError,
    apply_review,
)
from app.web.config import _DEFAULT_PAGE_LIMIT
from app.web.http_utils import (
    _error_page,
    _read_form,
    _read_upload_bytes,
    _redirect,
    _safe_return_to,
    _save_upload_to_temp,
    _unlink_silent,
    _wants_json,
    _word_card_json_payload,
)
from app.web.models import UploadTooLargeError
from app.web.queries import (
    _active_sentence_prompt_version,
    _asset_storage_path,
    _dashboard_stats,
    _default_read_idx,
    _delete_book,
    _fetch_active_word_cards,
    _fetch_book,
    _fetch_book_asset,
    _fetch_books,
    _fetch_cache_metadata,
    _fetch_chapter_blocks,
    _fetch_chapter_by_idx,
    _fetch_chapter_sentences,
    _fetch_chapters,
    _fetch_adjacent_chapters,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
    _lookup_book_id_by_hash,
    _purge_book_assets_dir,
)
from app.web.utils import _format_mb, _resolve_title
from app.web.views import (
    _books_table,
    _cards_return_script,
    _chapters_table,
    _due_table,
    _duplicate_page,
    _escape,
    _html_page,
    _import_forms,
    _latest_profile_block,
    _metric,
    _primary_read_idx,
    _profile_save_form,
    _reader_view,
    _sentence_cards_table,
    _word_cards_table,
)

def register_dashboard_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        db = db_factory()
        stats = _dashboard_stats(db)
        due_items = build_daily_review_queue(db, daily_limit=8)
        latest_profile = get_latest_profile_snapshot(db)
        profile_status = get_profile_trigger_status(db)

        body = f"""
        <section class="toolbar">
          <div>
            <h1>Reading Trainer</h1>
            <p class="muted">Books, cards, review queue, and learner profile.</p>
          </div>
          <a class="button primary" href="/review">Start review</a>
        </section>
        <section class="metrics">
          {_metric("Books", stats["books"])}
          {_metric("Sentences", stats["sentences"])}
          {_metric("Sentence cards", stats["sentence_cards"])}
          {_metric("Word cards", stats["word_cards"])}
          {_metric("Due now", stats["due_cards"])}
        </section>
        <section class="band">
          <div class="split">
            <div>
              <h2>Due Queue</h2>
              {_due_table(due_items, return_to="/")}
            </div>
            <div>
              <h2>Profile</h2>
              <p>Status: <strong>{_escape(profile_status.reason)}</strong></p>
              <p>Reviews since snapshot: {profile_status.reviews_since_snapshot}</p>
              {_latest_profile_block(latest_profile)}
            </div>
          </div>
        </section>
        """
        return _html_page("Dashboard", body, active="dashboard")

    @web_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}
