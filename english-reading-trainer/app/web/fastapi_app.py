"""
FastAPI web UI for the English Reading Trainer.

Provides a compact server-rendered interface for browsing books, marking cards,
reviewing due items, and viewing learner profile snapshots.
"""

from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    create_sentence_card,
    list_sentence_cards,
)
from app.cards.word_card_service import create_or_update_word_card, list_word_cards
from app.db_connection import DatabaseConnection
from app.db_models import CardType, LexicalType, ReviewOutcome
from app.profile.learner_profile_generator import (
    ProfileInputError,
    build_profile_prompt,
    get_latest_profile_snapshot,
    get_profile_trigger_status,
    save_profile_snapshot,
)
from app.review.daily_review_queue import build_daily_review_queue, list_due_cards
from app.review.sm2_scheduler import (
    ReviewCardNotFoundError,
    ReviewInputError,
    apply_review,
)


_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "reading_trainer.db"
_MIGRATIONS = _PROJECT_ROOT / "migrations"
_DEFAULT_PAGE_LIMIT = 50


def create_app(
    db_factory: Callable[[], DatabaseConnection] | None = None,
) -> FastAPI:
    """Create a FastAPI app. Tests can pass a db_factory for isolation."""
    db_factory = db_factory or _get_db
    web_app = FastAPI(title="English Reading Trainer")

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

    @web_app.get("/books", response_class=HTMLResponse)
    def books() -> HTMLResponse:
        db = db_factory()
        rows = _fetch_books(db)
        body = """
        <section class="toolbar">
          <div>
            <h1>Books</h1>
            <p class="muted">Imported reading material.</p>
          </div>
        </section>
        """
        body += _books_table(rows)
        return _html_page("Books", body, active="books")

    @web_app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(book_id: int) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Book not found", status_code=404)
        chapters = _fetch_chapters(db, book_id)
        body = f"""
        <section class="toolbar">
          <div>
            <h1>{_escape(book["title"])}</h1>
            <p class="muted">{_escape(book["author"] or "Unknown author")}</p>
          </div>
          <a class="button" href="/read/{book_id}">Read chapter 1</a>
        </section>
        {_chapters_table(book_id, chapters)}
        """
        return _html_page(book["title"], body, active="books")

    @web_app.get("/read/{book_id}", response_class=HTMLResponse)
    def read_book(book_id: int, chapter: int = 1) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Book not found", status_code=404)
        chapter_row = _fetch_chapter_by_idx(db, book_id, chapter)
        if chapter_row is None:
            return _error_page("Chapter not found", status_code=404)
        sentences = _fetch_chapter_sentences(db, chapter_row["id"])
        return_to = f"/read/{book_id}?chapter={chapter}"
        body = f"""
        <section class="toolbar">
          <div>
            <h1>{_escape(book["title"])}</h1>
            <p class="muted">Chapter {chapter}: {_escape(chapter_row["title"])}</p>
          </div>
          <a class="button" href="/books/{book_id}">Chapters</a>
        </section>
        {_sentences_list(sentences, return_to)}
        """
        return _html_page("Read", body, active="books")

    @web_app.post("/mark/sentence/{sentence_id}")
    async def mark_sentence(sentence_id: int, request: Request) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/cards"))
        db = db_factory()
        try:
            create_sentence_card(db, sentence_id)
        except SentenceCardAlreadyExistsError:
            pass
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.post("/mark/word")
    async def mark_word(request: Request) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/cards"))
        try:
            sentence_id = int(form.get("sentence_id", "0"))
            lexical_type = LexicalType(form.get("lexical_type", LexicalType.WORD.value))
            surface_form = form.get("surface_form", "")
        except ValueError as exc:
            return _error_page(f"Invalid word card input: {exc}", status_code=400)

        db = db_factory()
        try:
            create_or_update_word_card(db, sentence_id, surface_form, lexical_type)
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.get("/cards", response_class=HTMLResponse)
    def cards() -> HTMLResponse:
        db = db_factory()
        sentence_cards = list_sentence_cards(db, limit=_DEFAULT_PAGE_LIMIT)
        word_cards = list_word_cards(db, limit=_DEFAULT_PAGE_LIMIT)
        body = f"""
        <section class="toolbar">
          <div>
            <h1>Cards</h1>
            <p class="muted">Sentence and word cards currently tracked.</p>
          </div>
        </section>
        <section class="band">
          <h2>Sentence Cards</h2>
          {_sentence_cards_table(sentence_cards)}
          <h2>Word Cards</h2>
          {_word_cards_table(word_cards)}
        </section>
        """
        return _html_page("Cards", body, active="cards")

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

    return web_app


def _get_db() -> DatabaseConnection:
    db_path = os.environ.get("TRAINER_DB", str(_DEFAULT_DB))
    db = DatabaseConnection(db_path)
    db.apply_migrations(_MIGRATIONS)
    return db


def _dashboard_stats(db: DatabaseConnection) -> dict[str, int]:
    with db.get_connection() as conn:
        books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        sentences = conn.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]
        sentence_cards = conn.execute("SELECT COUNT(*) FROM sentence_cards").fetchone()[0]
        word_cards = conn.execute("SELECT COUNT(*) FROM word_cards").fetchone()[0]
    return {
        "books": books,
        "sentences": sentences,
        "sentence_cards": sentence_cards,
        "word_cards": word_cards,
        "due_cards": len(list_due_cards(db)),
    }


def _fetch_books(db: DatabaseConnection) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, title, author, source_format, total_chapters,
                      total_sentences, imported_at
                 FROM books
                ORDER BY id"""
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_book(db: DatabaseConnection, book_id: int) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def _fetch_chapters(db: DatabaseConnection, book_id: int) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, idx, title, sentence_start, sentence_end
                 FROM chapters
                WHERE book_id = ?
                ORDER BY idx""",
            (book_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_chapter_by_idx(
    db: DatabaseConnection,
    book_id: int,
    chapter_idx: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chapters WHERE book_id = ? AND idx = ?",
            (book_id, chapter_idx),
        ).fetchone()
    return dict(row) if row else None


def _fetch_chapter_sentences(
    db: DatabaseConnection,
    chapter_id: int,
) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT s.id, s.idx, s.text,
                      CASE WHEN sc.id IS NULL THEN 0 ELSE 1 END AS has_card
                 FROM sentences s
                 LEFT JOIN sentence_cards sc ON sc.sentence_id = s.id
                WHERE s.chapter_id = ?
                ORDER BY s.idx""",
            (chapter_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _books_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No books imported yet.</p>'
    body = "\n".join(
        "<tr>"
        f"<td>{row['id']}</td>"
        f"<td><a href=\"/books/{row['id']}\">{_escape(row['title'])}</a></td>"
        f"<td>{_escape(row['author'] or '')}</td>"
        f"<td>{_escape(row['source_format'])}</td>"
        f"<td>{row['total_chapters']}</td>"
        f"<td>{row['total_sentences']}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>ID</th><th>Title</th><th>Author</th><th>Format</th><th>Chapters</th><th>Sentences</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _chapters_table(book_id: int, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No chapters found.</p>'
    body = "\n".join(
        "<tr>"
        f"<td>{row['idx']}</td>"
        f"<td>{_escape(row['title'])}</td>"
        f"<td>{row['sentence_end'] - row['sentence_start']}</td>"
        f"<td><a class=\"button small\" href=\"/read/{book_id}?chapter={row['idx']}\">Read</a></td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>#</th><th>Title</th><th>Sentences</th><th></th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _sentences_list(rows: list[dict[str, Any]], return_to: str) -> str:
    if not rows:
        return '<p class="empty">No sentences in this chapter.</p>'
    return "\n".join(_sentence_item(row, return_to) for row in rows)


def _sentence_item(row: dict[str, Any], return_to: str) -> str:
    marker = '<span class="badge">marked</span>' if row["has_card"] else ""
    return f"""
    <article class="sentence">
      <div class="sentence-meta">#{row['id']} {marker}</div>
      <p>{_escape(row['text'])}</p>
      <div class="actions">
        <form method="post" action="/mark/sentence/{row['id']}">
          <input type="hidden" name="return_to" value="{_escape(return_to)}">
          <button type="submit">Mark sentence</button>
        </form>
        <form method="post" action="/mark/word" class="inline-form">
          <input type="hidden" name="sentence_id" value="{row['id']}">
          <input type="hidden" name="return_to" value="{_escape(return_to)}">
          <input name="surface_form" placeholder="word or phrase" aria-label="word or phrase">
          <select name="lexical_type" aria-label="lexical type">
            <option value="word">word</option>
            <option value="phrase">phrase</option>
            <option value="collocation">collocation</option>
          </select>
          <button type="submit">Mark word</button>
        </form>
      </div>
    </article>
    """


def _sentence_cards_table(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return '<p class="empty">No sentence cards.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{card['id']}</td>"
        f"<td>{_escape(card['mastery_state'])}</td>"
        f"<td>{_escape(_date(card['due_at']))}</td>"
        f"<td>{_escape(card['sentence_text'][:100])}</td>"
        "</tr>"
        for card in cards
    )
    return f"<table><thead><tr><th>ID</th><th>State</th><th>Due</th><th>Text</th></tr></thead><tbody>{rows}</tbody></table>"


def _word_cards_table(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return '<p class="empty">No word cards.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{card['id']}</td>"
        f"<td>{_escape(card['surface_form'])}</td>"
        f"<td>{_escape(card['lexical_type'])}</td>"
        f"<td>{_escape(card['mastery_state'])}</td>"
        f"<td>{card['occurrence_count']}</td>"
        "</tr>"
        for card in cards
    )
    return f"<table><thead><tr><th>ID</th><th>Word/Phrase</th><th>Type</th><th>State</th><th>Occ.</th></tr></thead><tbody>{rows}</tbody></table>"


def _due_table(items: list[Any], return_to: str) -> str:
    if not items:
        return '<p class="empty">No cards due for review.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{_escape(item.card_type.value)}</td>"
        f"<td>{item.card_id}</td>"
        f"<td>{_escape(item.mastery_state.value)}</td>"
        f"<td>{_escape(_date(item.due_at.isoformat()))}</td>"
        f"<td>{_escape(item.prompt[:120])}</td>"
        f"<td>{_review_form(item, return_to)}</td>"
        "</tr>"
        for item in items
    )
    return f"""
    <table>
      <thead><tr><th>Type</th><th>ID</th><th>State</th><th>Due</th><th>Prompt</th><th>Answer</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _review_form(item: Any, return_to: str) -> str:
    options = "".join(
        f'<button type="submit" name="outcome" value="{outcome.value}">{outcome.value}</button>'
        for outcome in (ReviewOutcome.PASS, ReviewOutcome.PARTIAL, ReviewOutcome.FAIL)
    )
    return f"""
    <form method="post" action="/review/{item.card_type.value}/{item.card_id}" class="answer-form">
      <input type="hidden" name="return_to" value="{_escape(return_to)}">
      {options}
    </form>
    """


def _latest_profile_block(snapshot: Any | None) -> str:
    if snapshot is None:
        return '<p class="empty">No learner profile snapshots yet.</p>'
    return f"""
    <div class="profile-summary">
      <p class="muted">Snapshot #{snapshot.id} from {snapshot.created_at.date().isoformat()}</p>
      <pre>{_escape(snapshot.summary_md)}</pre>
    </div>
    """


def _profile_save_form() -> str:
    return """
    <form method="post" action="/profile/save" class="stack-form">
      <label for="summary_md">Markdown summary</label>
      <textarea id="summary_md" name="summary_md" rows="10" placeholder="Paste the AI-generated profile Markdown here"></textarea>
      <button type="submit">Save snapshot</button>
    </form>
    """


def _metric(label: str, value: int) -> str:
    return f'<div class="metric"><span>{_escape(label)}</span><strong>{value}</strong></div>'


async def _read_form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _safe_return_to(value: str) -> str:
    if value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _error_page(message: str, *, status_code: int) -> HTMLResponse:
    body = f"""
    <section class="toolbar">
      <div>
        <h1>Request Error</h1>
        <p class="muted">{_escape(message)}</p>
      </div>
      <a class="button" href="/">Dashboard</a>
    </section>
    """
    return _html_page("Error", body, active="", status_code=status_code)


def _html_page(
    title: str,
    body: str,
    *,
    active: str,
    status_code: int = 200,
) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} - English Reading Trainer</title>
  <style>{_css()}</style>
</head>
<body>
  <nav>
    <a class="{_active(active, "dashboard")}" href="/">Dashboard</a>
    <a class="{_active(active, "books")}" href="/books">Books</a>
    <a class="{_active(active, "cards")}" href="/cards">Cards</a>
    <a class="{_active(active, "review")}" href="/review">Review</a>
    <a class="{_active(active, "profile")}" href="/profile">Profile</a>
  </nav>
  <main>{body}</main>
</body>
</html>""",
        status_code=status_code,
    )


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --surface: #ffffff;
      --line: #d9dee7;
      --text: #1f2937;
      --muted: #667085;
      --accent: #2563eb;
      --accent-strong: #1d4ed8;
      --ok: #047857;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    nav {
      display: flex;
      gap: 6px;
      align-items: center;
      padding: 12px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
      position: sticky;
      top: 0;
      z-index: 1;
    }
    nav a, .button, button {
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      text-decoration: none;
      padding: 7px 10px;
      border-radius: 6px;
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }
    nav a.active, .button.primary, button:hover, .button:hover {
      border-color: var(--accent);
      color: var(--accent-strong);
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 48px;
    }
    h1 { margin: 0; font-size: 26px; }
    h2 { margin: 24px 0 10px; font-size: 18px; }
    p { margin: 6px 0; }
    .muted { color: var(--muted); }
    .toolbar {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 18px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 20px;
    }
    .metric {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
    }
    .metric span { display: block; color: var(--muted); font-size: 13px; }
    .metric strong { font-size: 24px; }
    .band, .sentence {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
      margin-bottom: 14px;
    }
    .split {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
      gap: 24px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 600; background: #f2f4f7; }
    tr:last-child td { border-bottom: 0; }
    .sentence-meta { color: var(--muted); font-size: 13px; }
    .badge {
      color: var(--ok);
      border: 1px solid #9bd4bd;
      border-radius: 999px;
      padding: 1px 7px;
      margin-left: 6px;
    }
    .actions, .answer-form, .inline-form {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .inline-form input, .inline-form select, textarea {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 9px;
      font: inherit;
      min-width: 160px;
    }
    textarea { width: 100%; min-height: 180px; }
    .stack-form { display: grid; gap: 8px; }
    .small { padding: 4px 8px; }
    .prompt, .profile-summary pre {
      white-space: pre-wrap;
      background: #111827;
      color: #f9fafb;
      padding: 14px;
      border-radius: 6px;
      overflow-x: auto;
    }
    .empty {
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 6px;
      padding: 12px;
      background: var(--surface);
    }
    @media (max-width: 780px) {
      nav { overflow-x: auto; padding: 10px; }
      main { width: min(100vw - 20px, 1180px); margin-top: 16px; }
      .toolbar, .split { display: block; }
      table { font-size: 14px; }
      th, td { padding: 8px; }
    }
    """


def _date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return value[:10]


def _active(current: str, expected: str) -> str:
    return "active" if current == expected else ""


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


app = create_app()
