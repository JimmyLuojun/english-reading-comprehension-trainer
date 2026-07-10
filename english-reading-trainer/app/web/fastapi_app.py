"""
FastAPI web UI for the English Reading Trainer.

Provides the app factory and registers feature-specific route modules.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
from app.web.observability import RequestLoggingMiddleware, configure_project_logging
from app.web.security import (
    LocalAccessMiddleware,
    SecurityHeadersMiddleware,
    build_local_security_settings,
)


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
    *,
    request_token: str | None = None,
    enforce_local_security: bool | None = None,
) -> FastAPI:
    """Create a FastAPI app. Tests can pass a db_factory for isolation."""
    is_default_database = db_factory is None
    startup_lock = threading.Lock()
    initialized_db: DatabaseConnection | None = None

    def initialized_default_db() -> DatabaseConnection:
        nonlocal initialized_db
        if initialized_db is not None:
            return initialized_db
        with startup_lock:
            if initialized_db is None:
                initialized_db = _get_db()
                configure_project_logging(initialized_db)
        return initialized_db

    resolved_db_factory = db_factory or initialized_default_db
    security_enabled = (
        is_default_database if enforce_local_security is None else enforce_local_security
    )
    security_settings = build_local_security_settings(
        enabled=security_enabled,
        request_token=request_token,
    )
    @asynccontextmanager
    async def lifespan(web_app: FastAPI) -> AsyncIterator[None]:
        if is_default_database:
            web_app.state.database = await run_in_threadpool(initialized_default_db)
        yield

    web_app = FastAPI(title="English Reading Trainer", lifespan=lifespan)
    web_app.state.local_security = security_settings
    web_app.add_middleware(SecurityHeadersMiddleware)
    web_app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(security_settings.allowed_hosts),
    )
    web_app.add_middleware(LocalAccessMiddleware, settings=security_settings)
    web_app.add_middleware(RequestLoggingMiddleware)
    web_app.mount(
        "/static",
        StaticFiles(directory=_PROJECT_ROOT / "app" / "web" / "static"),
        name="static",
    )

    register_dashboard_routes(web_app, resolved_db_factory)
    register_asset_routes(web_app, resolved_db_factory)
    register_import_routes(web_app, resolved_db_factory)
    register_book_routes(web_app, resolved_db_factory)
    register_reader_routes(web_app, resolved_db_factory)
    register_card_routes(web_app, resolved_db_factory)
    register_analysis_routes(web_app, resolved_db_factory)
    register_review_routes(web_app, resolved_db_factory)
    register_profile_routes(web_app, resolved_db_factory)
    return web_app


def _get_db() -> DatabaseConnection:
    db_path = os.environ.get("TRAINER_DB", str(_DEFAULT_DB))
    db = DatabaseConnection(db_path)
    db.apply_migrations(_MIGRATIONS)
    sync_prompt_versions(db, _PROJECT_ROOT / "prompts")
    return db


app = create_app()
