from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.db_connection import DatabaseConnection
from app.web.http_utils import (
    _error_page,
)
from app.web.queries import (
    _asset_storage_path,
    _fetch_book_asset,
)

def register_asset_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/assets/books/{book_id}/{asset_id}")
    def book_asset(book_id: int, asset_id: int) -> Any:
        db = db_factory()
        asset = _fetch_book_asset(db, book_id, asset_id)
        if asset is None or asset["is_missing"]:
            return _error_page("Asset not found", status_code=404)
        try:
            asset_path = _asset_storage_path(db, asset["storage_path"])
        except ValueError:
            return _error_page("Asset path is invalid", status_code=404)
        if not asset_path.is_file():
            return _error_page("Asset file is missing", status_code=404)
        return FileResponse(
            asset_path,
            media_type=asset["media_type"] or None,
        )
