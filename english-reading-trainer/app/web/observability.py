"""Minimal local logging and request tracing for the FastAPI application."""

from __future__ import annotations

import logging
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.db_connection import DatabaseConnection


_LOGGER_NAME = "english_reading_trainer"
_LOG_HANDLER_NAME = "english_reading_trainer_file"
_MAX_LOG_BYTES = 2 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


def configure_project_logging(db: DatabaseConnection) -> Path:
    """Configure a bounded local file log beside the active SQLite database."""
    log_dir = db.db_path.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "trainer.log"
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    existing_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, "name", "") == _LOG_HANDLER_NAME
    ]
    if any(getattr(handler, "baseFilename", "") == str(log_path) for handler in existing_handlers):
        return log_path
    for handler in existing_handlers:
        logger.removeHandler(handler)
        handler.close()
    if not existing_handlers or not any(
        getattr(handler, "baseFilename", "") == str(log_path) for handler in logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.name = _LOG_HANDLER_NAME
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    return log_path


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request outcomes without recording query strings, bodies, or tokens."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started_at = time.perf_counter()
        logger = logging.getLogger(_LOGGER_NAME)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
