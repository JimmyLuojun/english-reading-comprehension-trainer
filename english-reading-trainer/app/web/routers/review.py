from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.db_models import CardType, ReviewOutcome
from app.review.daily_review_queue import build_daily_review_queue
from app.review.sm2_scheduler import (
    ReviewCardNotFoundError,
    ReviewInputError,
    apply_review,
)
from app.web.http_utils import (
    _error_page,
    _read_form,
    _redirect,
    _safe_return_to,
)
from app.web.views import (
    _due_table,
    _html_page,
)

def register_review_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/review", response_class=HTMLResponse)
    def review() -> HTMLResponse:
        db = db_factory()
        items = build_daily_review_queue(db)
        body = f"""
        <section class="toolbar">
          <div>
            <h1>Review Queue</h1>
            <p class="muted">Due cards ordered by priority and budget rules.</p>
          </div>
        </section>
        {_due_table(items, return_to="/review")}
        """
        return _html_page("Review", body, active="review")

    @web_app.post("/review/{card_type}/{card_id}")
    async def review_card(
        card_type: str,
        card_id: int,
        request: Request,
    ) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/review"))
        try:
            apply_review(
                db_factory(),
                CardType(card_type),
                card_id,
                ReviewOutcome(form.get("outcome", "")),
            )
        except (ReviewCardNotFoundError, ReviewInputError, ValueError) as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)
