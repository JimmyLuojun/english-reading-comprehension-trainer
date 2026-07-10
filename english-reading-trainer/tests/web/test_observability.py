"""Tests for local request logging and trace identifiers."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_connection import DatabaseConnection
from app.web.fastapi_app import create_app
from app.web.observability import _LOGGER_NAME, configure_project_logging


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def test_configure_project_logging_writes_bounded_local_log(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "trainer.db")
    db.apply_migrations(MIGRATIONS_DIR)
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, "name", "") == "english_reading_trainer_file":
            logger.removeHandler(handler)
            handler.close()

    log_path = configure_project_logging(db)
    logger.info("storage-ready")
    for handler in logger.handlers:
        handler.flush()

    assert log_path == tmp_path / "logs" / "trainer.log"
    assert "storage-ready" in log_path.read_text(encoding="utf-8")

    assert configure_project_logging(db) == log_path


def test_request_logging_adds_response_request_id(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "request.db")
    db.apply_migrations(MIGRATIONS_DIR)
    client = TestClient(create_app(lambda: db))

    response = client.get("/health", headers={"X-Request-ID": "request-test"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-test"


def test_request_logging_logs_application_exceptions(tmp_path: Path) -> None:
    db = DatabaseConnection(tmp_path / "failure.db")
    db.apply_migrations(MIGRATIONS_DIR)
    web_app: FastAPI = create_app(lambda: db)

    @web_app.get("/failure")
    def failure() -> None:
        raise RuntimeError("expected failure")

    client = TestClient(web_app, raise_server_exceptions=False)

    assert client.get("/failure").status_code == 500
