"""
FastAPI web UI for the English Reading Trainer.

Provides the app factory and registers feature-specific route modules.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable

from fastapi import FastAPI

from app.ai.llm_sentence_analyzer import analyze_sentence
from app.ai.llm_word_analyzer import analyze_word
from app.ai.prompt_version_registry import sync_prompt_versions
from app.db_connection import DatabaseConnection
from app.web.config import (
    _DEFAULT_DB,
    _MAX_EPUB_IMPORT_BYTES,
    _MAX_PDF_IMPORT_BYTES,
    _MAX_TEXT_IMPORT_BYTES,
    _MIGRATIONS,
    _PROJECT_ROOT,
)
from app.web.queries import _update_word_card_analysis_id
from app.web.routers.analysis import register_analysis_routes
from app.web.routers.assets import register_asset_routes
from app.web.routers.books import register_book_routes
from app.web.routers.cards import register_card_routes
from app.web.routers.dashboard import register_dashboard_routes
from app.web.routers.imports import register_import_routes
from app.web.routers.profile import register_profile_routes
from app.web.routers.reader import register_reader_routes
from app.web.routers.review import register_review_routes


__all__ = [
    "_MAX_EPUB_IMPORT_BYTES",
    "_MAX_PDF_IMPORT_BYTES",
    "_MAX_TEXT_IMPORT_BYTES",
    "_update_word_card_analysis_id",
    "analyze_sentence",
    "analyze_word",
    "app",
    "create_app",
    "shutil",
    "tempfile",
]


def create_app(
    db_factory: Callable[[], DatabaseConnection] | None = None,
) -> FastAPI:
    """Create a FastAPI app. Tests can pass a db_factory for isolation."""
    db_factory = db_factory or _get_db
    web_app = FastAPI(title="English Reading Trainer")

    register_dashboard_routes(web_app, db_factory)
    register_asset_routes(web_app, db_factory)
    register_import_routes(web_app, db_factory)
    register_book_routes(web_app, db_factory)
    register_reader_routes(web_app, db_factory)
    register_card_routes(web_app, db_factory)
    register_analysis_routes(web_app, db_factory)
    register_review_routes(web_app, db_factory)
    register_profile_routes(web_app, db_factory)
    return web_app


def _get_db() -> DatabaseConnection:
    db_path = os.environ.get("TRAINER_DB", str(_DEFAULT_DB))
    db = DatabaseConnection(db_path)
    db.apply_migrations(_MIGRATIONS)
    sync_prompt_versions(db, _PROJECT_ROOT / "prompts")
    return db


app = create_app()
