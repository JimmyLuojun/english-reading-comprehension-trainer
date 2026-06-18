from __future__ import annotations

from typing import Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.profile.learner_profile_generator import (
    get_latest_profile_snapshot,
    get_profile_trigger_status,
)
from app.review.daily_review_queue import build_daily_review_queue
from app.web.queries import (
    _dashboard_stats,
)
from app.web.views import (
    _due_table,
    _escape,
    _html_page,
    _latest_profile_block,
    _metric,
    _page_header,
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
        {_page_header(
            "Reading Trainer",
            "Books, cards, review queue, and learner profile.",
            '<a class="button primary" href="/review">Start review</a>',
        )}
        <section class="metrics">
          {_metric("Books", stats["books"], href="/books")}
          {_metric("Sentences", stats["sentences"])}
          {_metric("Sentence cards", stats["sentence_cards"], href="/cards#sentence-cards")}
          {_metric("Word cards", stats["word_cards"], href="/cards#word-cards")}
          {_metric("Due now", stats["due_cards"], href="/review")}
        </section>
        <section class="band" id="due-queue">
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
