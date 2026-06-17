from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.db_connection import DatabaseConnection
from app.profile.learner_profile_generator import (
    ProfileInputError,
    build_profile_prompt,
    get_latest_profile_snapshot,
    get_profile_trigger_status,
    save_profile_snapshot,
)
from app.web.http_utils import (
    _error_page,
    _read_form,
    _redirect,
)
from app.web.views import (
    _escape,
    _html_page,
    _latest_profile_block,
    _profile_save_form,
)

def register_profile_routes(web_app: FastAPI, db_factory: Callable[[], DatabaseConnection]) -> None:
    @web_app.get("/profile", response_class=HTMLResponse)
    def profile() -> HTMLResponse:
        db = db_factory()
        latest = get_latest_profile_snapshot(db)
        status = get_profile_trigger_status(db)
        body = f"""
        <section class="toolbar">
          <div>
            <h1>Learner Profile</h1>
            <p class="muted">Manual AI profile summary and snapshot history.</p>
          </div>
          <a class="button" href="/profile/prompt">Generate prompt</a>
        </section>
        <section class="band">
          <h2>Status</h2>
          <p>Profile is <strong>{"due" if status.should_generate else "not due"}</strong>
          ({_escape(status.reason)}).</p>
          <p>Reviews since snapshot: {status.reviews_since_snapshot}</p>
          <h2>Latest Snapshot</h2>
          {_latest_profile_block(latest)}
          <h2>Save New Snapshot</h2>
          {_profile_save_form()}
        </section>
        """
        return _html_page("Profile", body, active="profile")

    @web_app.get("/profile/prompt", response_class=HTMLResponse)
    def profile_prompt() -> HTMLResponse:
        try:
            prompt = build_profile_prompt(db_factory())
        except ProfileInputError as exc:
            return _error_page(str(exc), status_code=400)
        body = f"""
        <section class="toolbar">
          <div>
            <h1>Profile Prompt</h1>
            <p class="muted">Copy this into your AI chat, then save the Markdown output.</p>
          </div>
          <a class="button" href="/profile">Back to profile</a>
        </section>
        <pre class="prompt">{_escape(prompt)}</pre>
        """
        return _html_page("Profile Prompt", body, active="profile")

    @web_app.post("/profile/save")
    async def save_profile(request: Request) -> Any:
        form = await _read_form(request)
        try:
            save_profile_snapshot(db_factory(), form.get("summary_md", ""))
        except ProfileInputError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect("/profile")
