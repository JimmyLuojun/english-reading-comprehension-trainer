"""
FastAPI web UI for the English Reading Trainer.

Provides a compact server-rendered interface for browsing books, marking cards,
reviewing due items, and viewing learner profile snapshots.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.ai.ai_provider_config import get_ai_provider_settings
from app.ai.analysis_saver import save_sentence_analysis
from app.ai.llm_sentence_analyzer import analyze_sentence
from app.ai.prompt_version_registry import sync_prompt_versions
from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    SentenceCardNotFoundError,
    archive_sentence_card,
    create_sentence_card,
    list_sentence_cards,
    save_sentence_translation,
)
from app.ai.llm_word_analyzer import analyze_word
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
from app.importers.txt_importer import DuplicateBookError, import_text
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
_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB cap for both file upload and pasted text
_AUTO_TITLE_MAX_LEN = 80
_DEFAULT_SENTENCE_PROMPT_VERSION = "v1"
_PREDICT_SENTENCE_PROMPT = "sentence_analysis_predict"
_DIAGNOSE_SENTENCE_PROMPT = "sentence_analysis_diagnose"


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

    @web_app.get("/import", response_class=HTMLResponse)
    def import_page() -> HTMLResponse:
        return _html_page("Import", _import_forms(), active="import")

    @web_app.post("/import/file")
    async def import_file(
        file: UploadFile = File(...),
        title: str = Form(""),
        author: str = Form(""),
    ) -> Any:
        raw = await file.read()
        if len(raw) > _MAX_IMPORT_BYTES:
            return _error_page(
                f"Uploaded file exceeds {_MAX_IMPORT_BYTES // (1024 * 1024)} MB limit.",
                status_code=413,
            )
        if not raw.strip():
            return _error_page("Uploaded file is empty.", status_code=400)
        return _do_import(db_factory(), raw, title, author)

    @web_app.post("/import/paste")
    async def import_paste(request: Request) -> Any:
        form = await _read_form(request)
        text = form.get("text", "")
        title = form.get("title", "")
        author = form.get("author", "")
        raw = text.encode("utf-8")
        if len(raw) > _MAX_IMPORT_BYTES:
            return _error_page(
                f"Pasted text exceeds {_MAX_IMPORT_BYTES // (1024 * 1024)} MB limit.",
                status_code=413,
            )
        if not text.strip():
            return _error_page("Pasted text is empty.", status_code=400)
        return _do_import(db_factory(), raw, title, author)

    def _do_import(
        db: DatabaseConnection,
        raw: bytes,
        form_title: str,
        author: str,
    ) -> Any:
        title = _resolve_title(form_title, raw)
        try:
            result = import_text(db, raw, title=title, author=author.strip())
        except DuplicateBookError:
            existing_id = _lookup_book_id_by_hash(db, hashlib.sha256(raw).hexdigest())
            return _duplicate_page(existing_id)
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(f"/read/{result.book_id}")

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
    def read_book(request: Request, book_id: int, chapter: int = 1) -> HTMLResponse:
        db = db_factory()
        book = _fetch_book(db, book_id)
        if book is None:
            return _error_page("Book not found", status_code=404)
        chapter_row = _fetch_chapter_by_idx(db, book_id, chapter)
        if chapter_row is None:
            return _error_page("Chapter not found", status_code=404)
        sentences = _fetch_chapter_sentences(db, chapter_row["id"])
        word_cards = _fetch_active_word_cards(db)
        return_to = f"/read/{book_id}?chapter={chapter}"
        restore_progress = "chapter" not in request.query_params or (
            request.query_params.get("restore") == "1"
        )
        body = f"""
        {_reader_view(
            rows=sentences,
            return_to=return_to,
            chapter_id=chapter_row["id"],
            word_cards=word_cards,
            book_id=book_id,
            book_title=book["title"],
            chapter_idx=chapter,
            chapter_title=chapter_row["title"],
            restore_progress=restore_progress,
        )}
        """
        return _html_page("Read", body, active="books", page_class="reader-page")

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

    @web_app.post("/mark/sentence/{sentence_id}/translation")
    async def mark_sentence_translation(sentence_id: int, request: Request) -> Any:
        form = await _read_form(request)
        return_to = _safe_return_to(form.get("return_to", "/cards"))
        db = db_factory()
        try:
            save_sentence_translation(
                db,
                sentence_id,
                form.get("user_translation", ""),
            )
        except ValueError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.get("/analysis/sentence/{sentence_id}")
    def get_sentence_analysis(sentence_id: int) -> JSONResponse:
        payload = _fetch_sentence_analysis_payload(db_factory(), sentence_id)
        if payload is None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "No saved analysis for this sentence.",
                    "retry": True,
                },
                status_code=404,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/sentence/{sentence_id}")
    async def analyze_sentence_endpoint(
        sentence_id: int,
        request: Request,
    ) -> JSONResponse:
        form = await _read_form(request)
        db = db_factory()
        try:
            translation = form.get("user_translation")
            if translation is not None and translation.strip():
                save_sentence_translation(db, sentence_id, translation)

            sentence = _fetch_sentence_for_analysis(db, sentence_id)
            result = analyze_sentence(
                db,
                sentence["text"],
                user_translation=sentence.get("user_translation") or None,
            )
            if not result.is_valid:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "AI response failed validation.",
                        "retry": True,
                    },
                    status_code=502,
                )

            cache_meta = _fetch_cache_metadata(db, result.cache_id)
            save_sentence_analysis(
                db,
                sentence_id,
                json.dumps(result.data, ensure_ascii=False),
                model=cache_meta.get("model") or get_ai_provider_settings().model,
                prompt_version=cache_meta.get("prompt_version")
                or _active_sentence_prompt_version(
                    db,
                    sentence.get("user_translation") or None,
                ),
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": False},
                status_code=400,
            )
        except (FileNotFoundError, RuntimeError) as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "retry": True},
                status_code=502,
            )

        payload = _fetch_sentence_analysis_payload(db, sentence_id)
        if payload is None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Analysis was not saved.",
                    "retry": True,
                },
                status_code=500,
            )
        payload["from_cache"] = result.from_cache
        payload["is_stale"] = bool(payload["is_stale"] or result.is_stale)
        return JSONResponse(payload)

    @web_app.delete("/mark/sentence/{sentence_id}")
    async def unmark_sentence(sentence_id: int, request: Request) -> Any:
        return_to = _safe_return_to(request.query_params.get("return_to", "/cards"))
        db = db_factory()
        try:
            archive_sentence_card(db, sentence_id)
        except (SentenceCardNotFoundError, ValueError) as exc:
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

    @web_app.delete("/mark/word/{card_id}")
    async def unmark_word(card_id: int, request: Request) -> Any:
        return_to = _safe_return_to(request.query_params.get("return_to", "/cards"))
        db = db_factory()
        try:
            archive_word_card(db, card_id)
        except WordCardNotFoundError as exc:
            return _error_page(str(exc), status_code=400)
        return _redirect(return_to)

    @web_app.patch("/mark/word/{card_id}")
    async def update_word_note_endpoint(card_id: int, request: Request) -> JSONResponse:
        form = await _read_form(request)
        db = db_factory()
        try:
            update_word_card_note(
                db,
                card_id,
                current_meaning=form.get("current_meaning", ""),
                user_note=form.get("user_note", ""),
            )
        except WordCardNotFoundError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        return JSONResponse({"ok": True})

    @web_app.get("/analysis/word/{card_id}")
    def get_word_analysis(card_id: int) -> JSONResponse:
        payload = _fetch_word_analysis_payload(db_factory(), card_id)
        if payload is None:
            return JSONResponse(
                {"ok": False, "error": "No saved analysis for this word.", "retry": True},
                status_code=404,
            )
        return JSONResponse(payload)

    @web_app.post("/analysis/word/{card_id}")
    async def analyze_word_endpoint(card_id: int) -> JSONResponse:
        db = db_factory()
        card = get_word_card(db, card_id)
        if card is None:
            return JSONResponse({"ok": False, "error": "Word card not found."}, status_code=404)
        try:
            sentence = _fetch_sentence_for_analysis(db, card["first_sentence_id"])
            result = analyze_word(
                db,
                surface_form=card["surface_form"],
                sentence_text=sentence["text"],
                allow_stale=False,
            )
            if not result.is_valid:
                return JSONResponse(
                    {"ok": False, "error": "AI response failed validation.", "retry": True},
                    status_code=502,
                )
            _update_word_card_analysis_id(db, card_id, result.cache_id)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc), "retry": False}, status_code=400)
        except (FileNotFoundError, RuntimeError) as exc:
            return JSONResponse({"ok": False, "error": str(exc), "retry": True}, status_code=502)
        payload = _fetch_word_analysis_payload(db, card_id)
        if payload is None:
            return JSONResponse(
                {"ok": False, "error": "Analysis was not saved.", "retry": True},
                status_code=500,
            )
        payload["from_cache"] = result.from_cache
        return JSONResponse(payload)

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
    sync_prompt_versions(db, _PROJECT_ROOT / "prompts")
    return db


def _dashboard_stats(db: DatabaseConnection) -> dict[str, int]:
    with db.get_connection() as conn:
        books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        sentences = conn.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]
        sentence_cards = conn.execute(
            "SELECT COUNT(*) FROM sentence_cards WHERE archived_at IS NULL"
        ).fetchone()[0]
        word_cards = conn.execute(
            "SELECT COUNT(*) FROM word_cards WHERE archived_at IS NULL"
        ).fetchone()[0]
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
            """SELECT s.id, s.idx, s.text, s.paragraph_id, p.idx AS paragraph_idx,
                      CASE WHEN sc.id IS NULL THEN 0 ELSE 1 END AS has_card,
                      COALESCE(sc.user_translation, '') AS user_translation,
                      sc.ai_analysis_id,
                      ac.prompt_version AS analysis_prompt_version,
                      ac.model AS analysis_model,
                      COALESCE(ac.is_valid, 0) AS analysis_is_valid
                 FROM sentences s
                 JOIN paragraphs p ON p.id = s.paragraph_id
                 LEFT JOIN sentence_cards sc
                   ON sc.sentence_id = s.id AND sc.archived_at IS NULL
                 LEFT JOIN ai_cache ac
                   ON ac.id = sc.ai_analysis_id
                WHERE s.chapter_id = ?
                ORDER BY p.idx, s.idx""",
            (chapter_id,),
        ).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        has_analysis = bool(row.get("ai_analysis_id") and row.get("analysis_is_valid"))
        active_version = _active_sentence_prompt_version(
            db,
            row.get("user_translation") or None,
        )
        row["has_analysis"] = 1 if has_analysis else 0
        row["analysis_is_stale"] = (
            1
            if has_analysis and row.get("analysis_prompt_version") != active_version
            else 0
        )
    return result


def _fetch_active_word_cards(db: DatabaseConnection) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, lemma, surface_form, lexical_type, first_sentence_id,
                      current_meaning, user_note
                 FROM word_cards
                WHERE archived_at IS NULL
                ORDER BY created_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_sentence_for_analysis(
    db: DatabaseConnection,
    sentence_id: int,
) -> dict[str, Any]:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT s.id, s.text, COALESCE(sc.user_translation, '') AS user_translation
                 FROM sentences s
                 LEFT JOIN sentence_cards sc
                   ON sc.sentence_id = s.id AND sc.archived_at IS NULL
                WHERE s.id = ?""",
            (sentence_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Sentence id={sentence_id} not found.")
    return dict(row)


def _fetch_sentence_analysis_payload(
    db: DatabaseConnection,
    sentence_id: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT sc.id AS card_id, sc.user_translation,
                      ac.id AS cache_id, ac.prompt_version, ac.model,
                      ac.response_json, ac.is_valid, ac.created_at
                 FROM sentences s
                 JOIN sentence_cards sc
                   ON sc.sentence_id = s.id AND sc.archived_at IS NULL
                 JOIN ai_cache ac
                   ON ac.id = sc.ai_analysis_id
                WHERE s.id = ? AND ac.is_valid = 1""",
            (sentence_id,),
        ).fetchone()
    if row is None:
        return None

    analysis = json.loads(row["response_json"])
    active_version = _active_sentence_prompt_version(
        db,
        row["user_translation"] or None,
    )
    return {
        "ok": True,
        "sentence_id": sentence_id,
        "card_id": row["card_id"],
        "cache_id": row["cache_id"],
        "user_translation": row["user_translation"] or "",
        "prompt_version": row["prompt_version"],
        "active_prompt_version": active_version,
        "model": row["model"],
        "created_at": row["created_at"],
        "is_stale": row["prompt_version"] != active_version,
        "from_cache": True,
        "analysis": analysis,
    }


def _fetch_word_analysis_payload(
    db: DatabaseConnection,
    card_id: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT wc.id AS card_id, wc.surface_form, wc.lemma,
                      ac.id AS cache_id, ac.prompt_version, ac.model,
                      ac.response_json, ac.created_at
                 FROM word_cards wc
                 JOIN ai_cache ac ON ac.id = wc.ai_analysis_id
                WHERE wc.id = ? AND wc.archived_at IS NULL AND ac.is_valid = 1""",
            (card_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "ok": True,
        "card_id": row["card_id"],
        "surface_form": row["surface_form"],
        "lemma": row["lemma"],
        "cache_id": row["cache_id"],
        "prompt_version": row["prompt_version"],
        "model": row["model"],
        "created_at": row["created_at"],
        "is_stale": False,
        "from_cache": True,
        "analysis": json.loads(row["response_json"]),
    }


def _update_word_card_analysis_id(
    db: DatabaseConnection,
    card_id: int,
    cache_id: int,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )


def _fetch_cache_metadata(
    db: DatabaseConnection,
    cache_id: int,
) -> dict[str, str]:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT prompt_version, model FROM ai_cache WHERE id = ?",
            (cache_id,),
        ).fetchone()
    return dict(row) if row else {}


def _active_sentence_prompt_version(
    db: DatabaseConnection,
    user_translation: str | None,
) -> str:
    prompt_name = (
        _DIAGNOSE_SENTENCE_PROMPT
        if user_translation and user_translation.strip()
        else _PREDICT_SENTENCE_PROMPT
    )
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT version
                 FROM prompt_versions
                WHERE name = ? AND is_active = 1
                ORDER BY id DESC LIMIT 1""",
            (prompt_name,),
        ).fetchone()
    return row["version"] if row else _DEFAULT_SENTENCE_PROMPT_VERSION


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


def _reader_view(
    rows: list[dict[str, Any]],
    return_to: str,
    chapter_id: int,
    word_cards: list[dict[str, Any]],
    book_id: int,
    book_title: str,
    chapter_idx: int,
    chapter_title: str,
    restore_progress: bool,
) -> str:
    if not rows:
        return '<p class="empty">No sentences in this chapter.</p>'
    cards_by_sentence = _word_cards_by_sentence(word_cards)
    paragraphs = "\n".join(
        _reader_paragraph(paragraph_rows, chapter_id, cards_by_sentence)
        for paragraph_rows in _group_sentence_paragraphs(rows)
    )
    restore_flag = "1" if restore_progress else "0"
    return f"""
    <article class="reader" data-reader data-book-id="{book_id}"
      data-chapter-idx="{chapter_idx}" data-return-to="{_escape(return_to)}"
      data-restore-progress="{restore_flag}">
      <header class="reader-header">
        <a class="reader-back" href="/books/{book_id}">Chapters</a>
        <h1 class="reader-title">{_escape(book_title)}</h1>
        <h2 class="reader-chapter">Chapter {chapter_idx}: {_escape(chapter_title)}</h2>
      </header>
      {paragraphs}
    </article>
    {_analysis_panel()}
    {_selection_toolbar(return_to, word_cards)}
    """


def _group_sentence_paragraphs(
    rows: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    paragraphs: list[list[dict[str, Any]]] = []
    current_id: int | None = None
    for row in rows:
        paragraph_id = int(row["paragraph_id"])
        if paragraph_id != current_id:
            paragraphs.append([])
            current_id = paragraph_id
        paragraphs[-1].append(row)
    return paragraphs


def _reader_paragraph(
    rows: list[dict[str, Any]],
    chapter_id: int,
    cards_by_sentence: dict[int, list[dict[str, Any]]],
) -> str:
    sentence_spans = " ".join(
        _reader_sentence_span(row, chapter_id, cards_by_sentence.get(row["id"], []))
        for row in rows
    )
    return f'<p class="reader-para">{sentence_spans}</p>'


def _word_cards_by_sentence(
    word_cards: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for card in word_cards:
        grouped.setdefault(int(card["first_sentence_id"]), []).append(card)
    return grouped


def _reader_sentence_span(
    row: dict[str, Any],
    chapter_id: int,
    word_cards: list[dict[str, Any]],
) -> str:
    marked = "1" if row["has_card"] else "0"
    classes = ["reader-sentence"]
    if row["has_card"]:
        classes.append("marked")
    if row.get("has_analysis"):
        classes.append("analyzed-stale" if row.get("analysis_is_stale") else "analyzed")
    text = _highlight_word_cards(row["text"], word_cards)
    return (
        f'<span id="sentence-{row["id"]}" class="{" ".join(classes)}" '
        f'data-sentence-id="{row["id"]}" '
        f'data-chapter-id="{chapter_id}" data-marked="{marked}" '
        f'data-translation="{_escape(row.get("user_translation", ""))}" '
        f'data-analysis-id="{_escape(row.get("ai_analysis_id") or "")}" '
        f'data-analysis-stale="{int(row.get("analysis_is_stale") or 0)}">'
        f'{text}</span>'
    )


def _highlight_word_cards(text: str, word_cards: list[dict[str, Any]]) -> str:
    if not word_cards:
        return _escape(text)

    lower_text = text.lower()
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for card in word_cards:
        surface = str(card.get("surface_form") or card.get("lemma") or "").strip()
        if not surface:
            continue
        start = lower_text.find(surface.lower())
        if start >= 0:
            matches.append((start, start + len(surface), card))

    selected: list[tuple[int, int, dict[str, Any]]] = []
    occupied_until = -1
    for start, end, card in sorted(
        matches,
        key=lambda item: (item[0], -(item[1] - item[0])),
    ):
        if start < occupied_until:
            continue
        selected.append((start, end, card))
        occupied_until = end

    if not selected:
        return _escape(text)

    pieces: list[str] = []
    cursor = 0
    for start, end, card in selected:
        pieces.append(_escape(text[cursor:start]))
        meaning = _escape(str(card.get("current_meaning") or ""))
        note = _escape(str(card.get("user_note") or ""))
        pieces.append(
            f'<span data-word-card="{card["id"]}"'
            f' data-meaning="{meaning}" data-note="{note}"'
            f'>{_escape(text[start:end])}</span>'
        )
        cursor = end
    pieces.append(_escape(text[cursor:]))
    return "".join(pieces)


def _selection_toolbar(return_to: str, word_cards: list[dict[str, Any]]) -> str:
    word_index = {
        card["lemma"]: {
            "id": card["id"],
            "surface_form": card["surface_form"],
            "current_meaning": card.get("current_meaning") or "",
            "user_note": card.get("user_note") or "",
        }
        for card in word_cards
    }
    return f"""
    <div id="selection-toolbar" class="selection-toolbar" hidden>
      <form id="toolbar-sentence-form" method="post" class="toolbar-group" hidden>
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
        <button id="toolbar-sentence-submit" type="submit">Mark sentence</button>
        <button id="toolbar-sentence-delete" type="button" class="danger" hidden>Unmark sentence</button>
        <button id="toolbar-translation-open" type="button">Write translation</button>
        <button id="toolbar-analysis-open" type="button">AI analysis</button>
      </form>
      <form id="toolbar-translation-form" method="post" class="toolbar-group" hidden>
        <input id="toolbar-translation-value" type="hidden" name="user_translation">
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
      </form>
      <div id="toolbar-translation-editor" class="translation-editor" hidden>
        <label for="toolbar-translation-text">Your understanding</label>
        <textarea id="toolbar-translation-text" rows="4" placeholder="Write your Chinese understanding"></textarea>
        <div class="translation-actions">
          <button id="toolbar-translation-cancel" type="button">Cancel</button>
          <button id="toolbar-translation-save" type="button">Save only</button>
          <button id="toolbar-translation-analyze" type="button">Save and AI analyze</button>
        </div>
        <p id="toolbar-translation-status" class="toolbar-status" aria-live="polite"></p>
      </div>
      <form id="toolbar-word-form" method="post" action="/mark/word" class="toolbar-group" hidden>
        <input id="toolbar-word-sentence-id" type="hidden" name="sentence_id">
        <input id="toolbar-word-surface-form" type="hidden" name="surface_form">
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
        <button type="submit" name="lexical_type" value="word">Mark word</button>
        <button type="submit" name="lexical_type" value="phrase">Mark phrase</button>
        <button type="submit" name="lexical_type" value="collocation">Mark collocation</button>
      </form>
      <div id="toolbar-word-detail" class="toolbar-group word-detail-panel" hidden>
        <strong id="toolbar-word-detail-surface" class="word-detail-surface"></strong>
        <div class="word-detail-fields">
          <label class="word-detail-label">Meaning
            <input id="toolbar-word-detail-meaning" type="text" placeholder="Definition…">
          </label>
          <label class="word-detail-label">Note
            <input id="toolbar-word-detail-note" type="text" placeholder="Your note…">
          </label>
        </div>
        <div class="word-detail-actions">
          <button id="toolbar-word-detail-save" type="button">Save</button>
          <button id="toolbar-word-detail-explain" type="button">Explain word</button>
          <button id="toolbar-word-detail-remove" type="button" class="danger">Remove from cards</button>
        </div>
      </div>
      <div id="toolbar-cross-sentence" class="toolbar-group" hidden>
        <span class="toolbar-status">Selection spans sentences</span>
        <button id="toolbar-cross-sentence-delete" type="button" class="danger" hidden>Unmark sentences</button>
        <button id="toolbar-dismiss" type="button">Dismiss</button>
      </div>
    </div>
    <script id="word-card-index" type="application/json">{_json_script(word_index)}</script>
    <script>{_selection_script()}</script>
    """


def _analysis_panel() -> str:
    return """
    <aside id="analysis-panel" class="analysis-panel" hidden aria-live="polite">
      <header class="analysis-panel-header">
        <div>
          <p id="analysis-panel-kicker" class="panel-kicker">Sentence analysis</p>
          <h2 id="analysis-panel-title">AI Analysis</h2>
          <p id="analysis-panel-meta" class="muted"></p>
        </div>
        <button id="analysis-panel-close" type="button">Close panel</button>
      </header>
      <div id="analysis-panel-status" class="analysis-status"></div>
      <div id="analysis-sentence-sections">
        <section class="analysis-section">
          <h3>Simplified English</h3>
          <p id="analysis-simplified" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Chinese gloss</h3>
          <p id="analysis-gloss" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Diagnosis</h3>
          <div id="analysis-diagnosis"></div>
        </section>
        <section class="analysis-section">
          <h3>Subject skeleton</h3>
          <p id="analysis-skeleton" class="analysis-text"></p>
        </section>
      </div>
      <div id="analysis-word-sections" hidden>
        <section class="analysis-section">
          <h3>Meaning in context</h3>
          <p id="analysis-word-meaning" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Register</h3>
          <p id="analysis-word-register" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Why this word</h3>
          <p id="analysis-word-why" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>vs. simpler alternatives</h3>
          <div id="analysis-word-vs-simpler"></div>
        </section>
        <section class="analysis-section">
          <h3>Morphology</h3>
          <p id="analysis-word-morphology" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Predicted error types</h3>
          <p id="analysis-word-errors" class="analysis-text analysis-codes"></p>
        </section>
        <section id="word-panel-notes" class="analysis-section">
          <h3>My notes</h3>
          <div class="word-notes-fields">
            <label class="word-notes-label">Definition
              <input id="word-panel-meaning" type="text" placeholder="My definition…">
            </label>
            <label class="word-notes-label">Notes
              <input id="word-panel-note" type="text" placeholder="My understanding…">
            </label>
          </div>
          <div class="word-notes-actions">
            <button id="word-panel-save" type="button">Save</button>
            <span id="word-panel-save-status" class="toolbar-status" aria-live="polite"></span>
          </div>
        </section>
      </div>
      <footer class="analysis-panel-actions">
        <button id="analysis-panel-retry" type="button">Reanalyze</button>
        <button id="analysis-panel-return" type="button">Back to reading</button>
      </footer>
    </aside>
    """


def _json_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c")


def _selection_script() -> str:
    return r"""
    (() => {
      const reader = document.querySelector("[data-reader]");
      const toolbar = document.getElementById("selection-toolbar");
      if (!reader || !toolbar) return;

      const returnTo = reader.dataset.returnTo || window.location.pathname;
      const wordIndexElement = document.getElementById("word-card-index");
      const wordCards = JSON.parse(wordIndexElement?.textContent || "{}");
      const sentenceForm = document.getElementById("toolbar-sentence-form");
      const sentenceSubmit = document.getElementById("toolbar-sentence-submit");
      const sentenceDelete = document.getElementById("toolbar-sentence-delete");
      const translationOpen = document.getElementById("toolbar-translation-open");
      const analysisOpen = document.getElementById("toolbar-analysis-open");
      const translationForm = document.getElementById("toolbar-translation-form");
      const translationValue = document.getElementById("toolbar-translation-value");
      const translationEditor = document.getElementById("toolbar-translation-editor");
      const translationText = document.getElementById("toolbar-translation-text");
      const translationCancel = document.getElementById("toolbar-translation-cancel");
      const translationSave = document.getElementById("toolbar-translation-save");
      const translationAnalyze = document.getElementById("toolbar-translation-analyze");
      const translationStatus = document.getElementById("toolbar-translation-status");
      const wordForm = document.getElementById("toolbar-word-form");
      const wordSentenceId = document.getElementById("toolbar-word-sentence-id");
      const wordSurfaceForm = document.getElementById("toolbar-word-surface-form");
      const wordDetail = document.getElementById("toolbar-word-detail");
      const wordDetailSurface = document.getElementById("toolbar-word-detail-surface");
      const wordDetailMeaning = document.getElementById("toolbar-word-detail-meaning");
      const wordDetailNote = document.getElementById("toolbar-word-detail-note");
      const wordDetailSave = document.getElementById("toolbar-word-detail-save");
      const wordDetailExplain = document.getElementById("toolbar-word-detail-explain");
      const wordDetailRemove = document.getElementById("toolbar-word-detail-remove");
      const crossSentence = document.getElementById("toolbar-cross-sentence");
      const crossSentenceDelete = document.getElementById("toolbar-cross-sentence-delete");
      const dismissButton = document.getElementById("toolbar-dismiss");
      const panel = document.getElementById("analysis-panel");
      const panelClose = document.getElementById("analysis-panel-close");
      const panelReturn = document.getElementById("analysis-panel-return");
      const panelRetry = document.getElementById("analysis-panel-retry");
      const panelKicker = document.getElementById("analysis-panel-kicker");
      const panelTitle = document.getElementById("analysis-panel-title");
      const panelMeta = document.getElementById("analysis-panel-meta");
      const panelStatus = document.getElementById("analysis-panel-status");
      const sentenceSections = document.getElementById("analysis-sentence-sections");
      const wordSections = document.getElementById("analysis-word-sections");
      const simplified = document.getElementById("analysis-simplified");
      const gloss = document.getElementById("analysis-gloss");
      const skeleton = document.getElementById("analysis-skeleton");
      const diagnosis = document.getElementById("analysis-diagnosis");
      const wordAnalysisMeaning = document.getElementById("analysis-word-meaning");
      const wordRegister = document.getElementById("analysis-word-register");
      const wordWhy = document.getElementById("analysis-word-why");
      const wordVsSimpler = document.getElementById("analysis-word-vs-simpler");
      const wordAnalysisMorphology = document.getElementById("analysis-word-morphology");
      const wordAnalysisErrors = document.getElementById("analysis-word-errors");
      const wordPanelMeaning = document.getElementById("word-panel-meaning");
      const wordPanelNote = document.getElementById("word-panel-note");
      const wordPanelSave = document.getElementById("word-panel-save");
      const wordPanelSaveStatus = document.getElementById("word-panel-save-status");
      const bookId = reader.dataset.bookId || "";
      const chapterIdx = Number.parseInt(reader.dataset.chapterIdx || "1", 10);
      const progressKey = bookId ? `reader:progress:book:${bookId}` : "";

      const ERROR_CODE_LABELS = {
        G01: "G01 长主语识别失败",
        G02: "G02 后置定语修饰对象判断错",
        G03: "G03 嵌套从句边界混乱",
        G04: "G04 倒装 / 强调结构",
        G05: "G05 非谓语动词作用判断错",
        G06: "G06 省略 / 替代识别失败",
        G07: "G07 平行结构对应失败",
        L01: "L01 多义词义项判断错",
        L02: "L02 假朋友 / 形近词混淆",
        L03: "L03 搭配不熟（动名 / 形名 / 介词）",
        L04: "L04 词根 / 词族联想不足",
        L05: "L05 习语 / 固定短语未识别",
        L06: "L06 学术词汇陌生",
        D01: "D01 代词指代对象判断错",
        D02: "D02 让步 / 对比逻辑误读",
        D03: "D03 因果 / 推论连词误读",
        D04: "D04 信息焦点判断错",
        D05: "D05 篇章衔接回指失败",
        X00: "X00 其他",
      };

      let activeSentenceId = null;
      let activeSentenceTranslation = "";
      let activeWordCardId = null;
      let activeWordCardIds = [];
      let activeCrossSentenceIds = [];
      let activeWordDetailCardId = null;
      let activeAnalysisSentenceId = null;
      let activeAnalysisWordCardId = null;
      let panelMode = "sentence";
      let translationEditorOpen = false;
      let progressTimer = null;
      let suppressNextUpdate = false;

      const normalizeText = (value) => value.replace(/\s+/g, " ").trim();
      const lemmaKey = (value) => value.toLowerCase().trim();

      function hideTranslationEditor() {
        translationEditor.hidden = true;
        translationEditorOpen = false;
        translationStatus.textContent = "";
      }

      function hideAllPanels() {
        hideTranslationEditor();
        setVisible(sentenceForm, false);
        setVisible(wordForm, false);
        setVisible(wordDetail, false);
        setVisible(crossSentence, false);
      }

      function hideToolbar() {
        hideAllPanels();
        toolbar.hidden = true;
        activeSentenceId = null;
        activeSentenceTranslation = "";
        activeWordCardId = null;
        activeWordCardIds = [];
        activeCrossSentenceIds = [];
        activeWordDetailCardId = null;
        wordDetailRemove.dataset.cardId = "";
        crossSentenceDelete.dataset.sentenceIds = "";
      }

      function setVisible(element, visible) {
        element.hidden = !visible;
      }

      function selectedSentenceSpans(range) {
        return Array.from(reader.querySelectorAll("[data-sentence-id]")).filter((span) => {
          try {
            return range.intersectsNode(span);
          } catch {
            return false;
          }
        });
      }

      function selectedWordCardIds(range) {
        const ids = Array.from(reader.querySelectorAll("[data-word-card]"))
          .filter((span) => {
            try {
              return range.intersectsNode(span);
            } catch {
              return false;
            }
          })
          .map((span) => span.dataset.wordCard)
          .filter(Boolean);
        return Array.from(new Set(ids));
      }

      function configureCrossSentenceActions(spans) {
        activeCrossSentenceIds = spans
          .filter((span) => span.dataset.marked === "1")
          .map((span) => span.dataset.sentenceId)
          .filter(Boolean);
        crossSentenceDelete.dataset.sentenceIds = activeCrossSentenceIds.join(",");
        crossSentenceDelete.textContent =
          `Unmark ${activeCrossSentenceIds.length} sentence${activeCrossSentenceIds.length === 1 ? "" : "s"}`;
        setVisible(crossSentenceDelete, activeCrossSentenceIds.length > 0);
      }

      function positionToolbar(anchor) {
        toolbar.hidden = false;
        requestAnimationFrame(() => {
          const toolbarRect = toolbar.getBoundingClientRect();
          const viewportPadding = 8;
          let top = window.scrollY + anchor.top - toolbarRect.height - 10;
          if (top < window.scrollY + viewportPadding) {
            top = window.scrollY + anchor.bottom + 10;
          }
          const centeredLeft = window.scrollX + anchor.left + (anchor.width / 2) - (toolbarRect.width / 2);
          const maxLeft = window.scrollX + window.innerWidth - toolbarRect.width - viewportPadding;
          const left = Math.max(window.scrollX + viewportPadding, Math.min(centeredLeft, maxLeft));
          toolbar.style.top = `${top}px`;
          toolbar.style.left = `${left}px`;
        });
      }

      function showToolbar(range) {
        const rect = range.getBoundingClientRect();
        const fallbackRect = range.getClientRects()[0];
        const anchor = rect.width || rect.height ? rect : fallbackRect;
        if (!anchor) { hideToolbar(); return; }
        positionToolbar(anchor);
      }

      function fillWordDetail(cardId, surface, meaning, note) {
        activeWordDetailCardId = String(cardId || "");
        wordDetailSurface.textContent = surface || "";
        wordDetailMeaning.value = meaning || "";
        wordDetailNote.value = note || "";
        wordDetailRemove.dataset.cardId = activeWordDetailCardId;
      }

      function showWordDetail(span) {
        hideAllPanels();
        fillWordDetail(
          span.dataset.wordCard,
          span.textContent,
          span.dataset.meaning,
          span.dataset.note,
        );
        setVisible(wordDetail, true);
        positionToolbar(span.getBoundingClientRect());
        suppressNextUpdate = true;
      }

      function updateToolbar() {
        if (suppressNextUpdate) {
          suppressNextUpdate = false;
          return;
        }
        if (translationEditorOpen || toolbar.contains(document.activeElement)) return;
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
          hideToolbar();
          return;
        }

        const range = selection.getRangeAt(0);
        const selectedText = selection.toString().trim();
        const normalizedSelection = normalizeText(selectedText);
        if (!normalizedSelection) {
          hideToolbar();
          return;
        }

        const spans = selectedSentenceSpans(range);
        if (!spans.length) {
          hideToolbar();
          return;
        }

        hideAllPanels();
        if (spans.length > 1) {
          configureCrossSentenceActions(spans);
          setVisible(crossSentence, true);
          showToolbar(range);
          return;
        }

        const sentence = spans[0];
        activeSentenceId = sentence.dataset.sentenceId;
        activeSentenceTranslation = sentence.dataset.translation || "";
        const wholeSentence = normalizedSelection === normalizeText(sentence.textContent || "");
        const markedSentence = sentence.dataset.marked === "1";
        const selectedCardIds = selectedWordCardIds(range);
        const existingWord = selectedCardIds.length ? null : wordCards[lemmaKey(selectedText)];
        activeWordCardIds = selectedCardIds.length
          ? selectedCardIds
          : (existingWord ? [String(existingWord.id)] : []);
        activeWordCardId = activeWordCardIds.length ? activeWordCardIds[0] : null;

        sentenceForm.action = `/mark/sentence/${activeSentenceId}`;
        translationForm.action = `/mark/sentence/${activeSentenceId}/translation`;
        sentenceSubmit.hidden = !wholeSentence || markedSentence;
        sentenceDelete.hidden = !wholeSentence || !markedSentence;
        translationOpen.hidden = !wholeSentence;
        analysisOpen.hidden = !wholeSentence;
        translationOpen.textContent = activeSentenceTranslation ? "Update translation" : "Write translation";
        analysisOpen.textContent = sentence.dataset.analysisId ? "Open analysis panel" : "AI analysis";

        wordSentenceId.value = activeSentenceId;
        wordSurfaceForm.value = selectedText;
        configureCrossSentenceActions([]);
        if (wholeSentence) {
          setVisible(sentenceForm, true);
        } else if (activeWordCardId) {
          const detailSpan = reader.querySelector(`[data-word-card="${activeWordCardId}"]`);
          if (detailSpan) {
            fillWordDetail(
              activeWordCardId,
              detailSpan.textContent,
              detailSpan.dataset.meaning,
              detailSpan.dataset.note,
            );
          } else {
            fillWordDetail(
              activeWordCardId,
              existingWord?.surface_form || selectedText,
              existingWord?.current_meaning,
              existingWord?.user_note,
            );
          }
          setVisible(wordDetail, true);
        } else {
          setVisible(wordForm, true);
        }
        showToolbar(range);
      }

      function readProgress() {
        if (!progressKey) return null;
        try {
          return JSON.parse(window.localStorage.getItem(progressKey) || "null");
        } catch {
          return null;
        }
      }

      function restoreReaderProgress() {
        if (reader.dataset.restoreProgress !== "1") return;
        const saved = readProgress();
        if (!saved) return;
        const savedChapter = Number.parseInt(saved.chapter_idx, 10);
        if (savedChapter && savedChapter !== chapterIdx) {
          window.location.replace(`/read/${bookId}?chapter=${savedChapter}&restore=1`);
          return;
        }
        const sentenceId = Number.parseInt(saved.top_sentence_id, 10);
        if (!sentenceId) return;
        window.setTimeout(() => {
          document.getElementById(`sentence-${sentenceId}`)?.scrollIntoView({ block: "start" });
        }, 0);
      }

      function topSentenceId() {
        const spans = Array.from(reader.querySelectorAll("[data-sentence-id]"));
        for (const span of spans) {
          const rect = span.getBoundingClientRect();
          if (rect.bottom >= 0) {
            return Number.parseInt(span.dataset.sentenceId, 10);
          }
        }
        return spans.length ? Number.parseInt(spans[spans.length - 1].dataset.sentenceId, 10) : null;
      }

      function saveReaderProgress() {
        if (!progressKey) return;
        const sentenceId = topSentenceId();
        if (!sentenceId) return;
        window.localStorage.setItem(progressKey, JSON.stringify({
          chapter_idx: chapterIdx,
          top_sentence_id: sentenceId,
          ts: new Date().toISOString(),
        }));
      }

      function scheduleProgressSave() {
        window.clearTimeout(progressTimer);
        progressTimer = window.setTimeout(saveReaderProgress, 300);
      }

      async function deleteAndReload(url) {
        const separator = url.includes("?") ? "&" : "?";
        const response = await fetch(`${url}${separator}return_to=${encodeURIComponent(returnTo)}`, {
          method: "DELETE",
        });
        if (response.ok) {
          window.location.assign(returnTo);
        } else {
          window.location.assign(response.url || returnTo);
        }
      }

      async function deleteWordCardsAndReload(cardIds) {
        const ids = cardIds.filter(Boolean);
        if (!ids.length) return;
        for (const cardId of ids) {
          const separator = `/mark/word/${cardId}`.includes("?") ? "&" : "?";
          const response = await fetch(
            `/mark/word/${cardId}${separator}return_to=${encodeURIComponent(returnTo)}`,
            { method: "DELETE" },
          );
          if (!response.ok) {
            window.location.assign(response.url || returnTo);
            return;
          }
        }
        window.location.assign(returnTo);
      }

      function markSentenceSpanUnmarked(sentenceId) {
        const sentence = document.getElementById(`sentence-${sentenceId}`);
        if (!sentence) return;
        sentence.classList.remove("marked", "analyzed", "analyzed-stale");
        sentence.dataset.marked = "0";
        sentence.dataset.analysisId = "";
        sentence.dataset.analysisStale = "0";
        sentence.dataset.translation = "";
      }

      async function deleteSentenceCardsInPlace(sentenceIds) {
        const ids = Array.from(new Set(sentenceIds.filter(Boolean)));
        if (!ids.length) return;
        ids.forEach(markSentenceSpanUnmarked);
        const requests = ids.map((sentenceId) => {
          const url = `/mark/sentence/${sentenceId}?return_to=${encodeURIComponent(returnTo)}`;
          return fetch(url, { method: "DELETE" }).then((response) => ({
            sentenceId,
            response,
          }));
        });
        const results = await Promise.all(requests);
        const failed = results.find((result) => !result.response.ok);
        if (failed) {
          window.location.assign(failed.response.url || returnTo);
          return;
        }
        window.getSelection()?.removeAllRanges();
        hideToolbar();
      }

      function openTranslationEditor() {
        if (!activeSentenceId) return;
        translationText.value = activeSentenceTranslation;
        translationEditor.hidden = false;
        translationEditorOpen = true;
        translationStatus.textContent = "";
        setVisible(wordForm, false);
        setVisible(wordDetail, false);
        setVisible(crossSentence, false);
        requestAnimationFrame(() => translationText.focus());
      }

      function saveTranslationOnly() {
        const value = translationText.value.trim();
        if (!value) {
          translationStatus.textContent = "Enter a translation first, or use AI analysis without saving.";
          return;
        }
        translationValue.value = value;
        translationForm.submit();
      }

      function setSentenceMode() {
        panelMode = "sentence";
        if (panelKicker) panelKicker.textContent = "Sentence analysis";
        if (panelTitle) panelTitle.textContent = "AI Analysis";
        if (sentenceSections) sentenceSections.hidden = false;
        if (wordSections) wordSections.hidden = true;
      }

      function setWordMode() {
        panelMode = "word";
        if (panelKicker) panelKicker.textContent = "Word analysis";
        if (panelTitle) panelTitle.textContent = "Word Analysis";
        if (sentenceSections) sentenceSections.hidden = true;
        if (wordSections) wordSections.hidden = false;
      }

      function openPanel() {
        panel.hidden = false;
        document.body.classList.add("analysis-open");
      }

      function closePanel() {
        panel.hidden = true;
        document.body.classList.remove("analysis-open");
        clearEvidenceHighlight();
        reader.querySelectorAll("[data-word-card].word-analysis-active").forEach((el) => {
          el.classList.remove("word-analysis-active");
        });
      }

      function setPanelLoading(message) {
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = message;
        panelMeta.textContent = "";
        simplified.textContent = "";
        gloss.textContent = "";
        skeleton.textContent = "";
        diagnosis.replaceChildren();
      }

      function setPanelLoadingWord(message) {
        setWordMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = message;
        panelMeta.textContent = "";
        panelRetry.hidden = true;
        if (wordAnalysisMeaning) wordAnalysisMeaning.textContent = "";
        if (wordRegister) wordRegister.textContent = "";
        if (wordWhy) wordWhy.textContent = "";
        if (wordVsSimpler) wordVsSimpler.replaceChildren();
        if (wordAnalysisMorphology) wordAnalysisMorphology.textContent = "";
        if (wordAnalysisErrors) wordAnalysisErrors.textContent = "";
        if (wordPanelMeaning) wordPanelMeaning.value = "";
        if (wordPanelNote) wordPanelNote.value = "";
        if (wordPanelSaveStatus) wordPanelSaveStatus.textContent = "";
      }

      function renderAnalysisError(message, retryable) {
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status error";
        panelStatus.textContent = message;
        panelRetry.hidden = !retryable || !activeAnalysisSentenceId;
      }

      function renderWordAnalysisError(message, retryable) {
        setWordMode();
        openPanel();
        panelStatus.className = "analysis-status error";
        panelStatus.textContent = message;
        panelRetry.hidden = !retryable;
      }

      function renderAnalysisPayload(payload) {
        const analysis = payload.analysis || {};
        activeAnalysisSentenceId = String(payload.sentence_id || activeAnalysisSentenceId || "");
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = payload.is_stale ? "Analysis is stale. Reanalyze when ready." : "";
        panelRetry.hidden = false;
        panelMeta.textContent = [
          `prompt ${payload.prompt_version || "unknown"}`,
          payload.is_stale ? "stale" : "current",
          payload.from_cache ? "cache" : "fresh",
        ].join(" · ");
        simplified.textContent = analysis.simplified_en || "";
        gloss.textContent = analysis.chinese_gloss || "";
        skeleton.textContent = analysis.subject_skeleton || "";
        renderDiagnosis(analysis);
      }

      function renderDiagnosis(analysis) {
        diagnosis.replaceChildren();
        const basis = document.createElement("p");
        basis.className = "analysis-text muted";
        basis.textContent = analysis.diagnosis_basis === "user_translation"
          ? "Based on your translation"
          : "Predicted without a translation";
        diagnosis.append(basis);

        const codes = analysis.diagnosis_basis === "user_translation"
          ? (analysis.diagnosed_error_types || [])
          : (analysis.predicted_error_types || []);
        if (codes.length) {
          const codeLine = document.createElement("p");
          codeLine.className = "analysis-codes";
          codeLine.textContent = codes.map((c) => ERROR_CODE_LABELS[c] || c).join("  ·  ");
          diagnosis.append(codeLine);
        }

        const evidence = analysis.diagnosis_evidence || [];
        if (!evidence.length) {
          const empty = document.createElement("p");
          empty.className = "analysis-text";
          empty.textContent = codes.length ? "No detailed evidence saved." : "No specific issue found.";
          diagnosis.append(empty);
          return;
        }

        for (const item of evidence) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "evidence-item";
          const code = item.error_type || "OK";
          const text = item.evidence || "";
          const codeLabel = ERROR_CODE_LABELS[code] || code;
          button.textContent = `${codeLabel}: ${text}`;
          button.addEventListener("mouseenter", () => highlightEvidence(text));
          button.addEventListener("mouseleave", clearEvidenceHighlight);
          button.addEventListener("click", () => highlightEvidence(text));
          diagnosis.append(button);
        }
      }

      function updateSentenceAnalysisState(sentenceId, payload) {
        const sentence = document.getElementById(`sentence-${sentenceId}`);
        if (!sentence) return;
        sentence.dataset.marked = "1";
        sentence.dataset.analysisId = payload.cache_id || "";
        sentence.dataset.analysisStale = payload.is_stale ? "1" : "0";
        sentence.dataset.translation = payload.user_translation || sentence.dataset.translation || "";
        sentence.classList.add("marked");
        sentence.classList.remove("analyzed", "analyzed-stale");
        sentence.classList.add(payload.is_stale ? "analyzed-stale" : "analyzed");
      }

      async function loadSavedAnalysis(sentenceId) {
        activeAnalysisSentenceId = sentenceId;
        setPanelLoading("Loading analysis...");
        try {
          const response = await fetch(`/analysis/sentence/${sentenceId}`);
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderAnalysisError(payload.error || "No saved analysis found.", Boolean(payload.retry));
            return;
          }
          renderAnalysisPayload(payload);
        } catch (error) {
          renderAnalysisError(`Could not load analysis: ${error}`, true);
        }
      }

      async function requestAnalysis(sentenceId, translation) {
        activeAnalysisSentenceId = sentenceId;
        setPanelLoading("Analyzing sentence...");
        const params = new URLSearchParams();
        params.set("return_to", returnTo);
        if (translation && translation.trim()) params.set("user_translation", translation.trim());
        try {
          const response = await fetch(`/analysis/sentence/${sentenceId}`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: params.toString(),
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderAnalysisError(payload.error || "Analysis failed.", Boolean(payload.retry));
            return;
          }
          updateSentenceAnalysisState(sentenceId, payload);
          renderAnalysisPayload(payload);
        } catch (error) {
          renderAnalysisError(`Analysis failed: ${error}`, true);
        }
      }

      function renderVsSimpler(container, items) {
        container.replaceChildren();
        if (!items.length) { container.textContent = "—"; return; }
        for (const item of items) {
          const p = document.createElement("p");
          p.className = "vs-simpler-item analysis-text";
          const strong = document.createElement("strong");
          strong.textContent = item.simpler || "";
          p.append(strong);
          p.append(document.createTextNode(": " + (item.difference || "")));
          container.append(p);
        }
      }

      function renderWordAnalysis(payload) {
        const a = payload.analysis || {};
        activeAnalysisWordCardId = String(payload.card_id || "");
        setWordMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = payload.is_stale ? "Analysis is stale. Reanalyze when ready." : "";
        panelRetry.hidden = false;
        panelMeta.textContent = [
          `prompt ${payload.prompt_version || "unknown"}`,
          payload.from_cache ? "cache" : "fresh",
        ].join(" · ");
        reader.querySelectorAll("[data-word-card].word-analysis-active").forEach((el) => {
          el.classList.remove("word-analysis-active");
        });
        if (payload.card_id) {
          const wordSpan = reader.querySelector(`[data-word-card="${payload.card_id}"]`);
          if (wordSpan) wordSpan.classList.add("word-analysis-active");
        }
        if (wordAnalysisMeaning) wordAnalysisMeaning.textContent = a.meaning_in_context || "—";
        if (wordRegister) wordRegister.textContent = a.register || "—";
        if (wordWhy) wordWhy.textContent = a.why_this_word || "—";
        if (wordVsSimpler) renderVsSimpler(wordVsSimpler, a.vs_simpler || []);
        const root = a.morphology?.root || "";
        const family = (a.morphology?.family || []).join(", ");
        if (wordAnalysisMorphology) {
          wordAnalysisMorphology.textContent = root
            ? (family ? `${root} → ${family}` : root)
            : (family || "—");
        }
        if (wordAnalysisErrors) {
          const codes = a.predicted_error_types || [];
          wordAnalysisErrors.textContent = codes.length
            ? codes.map((c) => ERROR_CODE_LABELS[c] || c).join("  ·  ")
            : "—";
        }
        const cardId = String(payload.card_id || "");
        const noteSpan = cardId ? reader.querySelector(`[data-word-card="${cardId}"]`) : null;
        if (wordPanelMeaning) wordPanelMeaning.value = noteSpan?.dataset.meaning || "";
        if (wordPanelNote) wordPanelNote.value = noteSpan?.dataset.note || "";
        if (wordPanelSaveStatus) wordPanelSaveStatus.textContent = "";
      }

      async function requestWordAnalysis(cardId) {
        activeAnalysisWordCardId = cardId;
        setPanelLoadingWord("Analyzing word...");
        hideToolbar();
        try {
          const response = await fetch(`/analysis/word/${cardId}`, { method: "POST" });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderWordAnalysisError(payload.error || "Word analysis failed.", Boolean(payload.retry));
            return;
          }
          renderWordAnalysis(payload);
        } catch (error) {
          renderWordAnalysisError(`Word analysis failed: ${error}`, true);
        }
      }

      function clearEvidenceHighlight() {
        reader.querySelectorAll(".analysis-highlight").forEach((node) => {
          node.replaceWith(document.createTextNode(node.textContent || ""));
        });
        reader.querySelectorAll(".analysis-highlight-fallback").forEach((node) => {
          node.classList.remove("analysis-highlight-fallback");
        });
      }

      function evidencePhrase(text) {
        const matches = Array.from(text.matchAll(/[\"'“‘`]([^\"'“”‘’`]{3,120})[\"'”’`]/g));
        if (matches.length) {
          return matches.sort((a, b) => b[1].length - a[1].length)[0][1];
        }
        return normalizeText(text).slice(0, 80);
      }

      function highlightEvidence(text) {
        clearEvidenceHighlight();
        const sentence = activeAnalysisSentenceId
          ? document.getElementById(`sentence-${activeAnalysisSentenceId}`)
          : null;
        if (!sentence) return;
        const phrase = evidencePhrase(text).toLowerCase();
        if (!phrase) {
          sentence.classList.add("analysis-highlight-fallback");
          return;
        }
        const walker = document.createTreeWalker(sentence, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node) {
          const index = (node.nodeValue || "").toLowerCase().indexOf(phrase);
          if (index >= 0) {
            const range = document.createRange();
            range.setStart(node, index);
            range.setEnd(node, index + phrase.length);
            const mark = document.createElement("span");
            mark.className = "analysis-highlight";
            range.surroundContents(mark);
            return;
          }
          node = walker.nextNode();
        }
        sentence.classList.add("analysis-highlight-fallback");
      }

      toolbar.addEventListener("mousedown", (event) => {
        if (event.target.closest("textarea, input")) return;
        event.preventDefault();
      });
      sentenceDelete.addEventListener("click", () => {
        if (activeSentenceId) deleteAndReload(`/mark/sentence/${activeSentenceId}`);
      });
      translationOpen.addEventListener("click", openTranslationEditor);
      translationCancel.addEventListener("click", hideTranslationEditor);
      translationSave.addEventListener("click", saveTranslationOnly);
      translationAnalyze.addEventListener("click", () => {
        const sentenceId = activeSentenceId;
        const value = translationText.value.trim();
        hideToolbar();
        if (sentenceId) requestAnalysis(sentenceId, value || null);
      });
      analysisOpen.addEventListener("click", () => {
        if (!activeSentenceId) return;
        const sentenceId = activeSentenceId;
        const sentence = document.getElementById(`sentence-${activeSentenceId}`);
        hideToolbar();
        if (sentence?.dataset.analysisId) loadSavedAnalysis(sentenceId);
        else requestAnalysis(sentenceId, null);
      });
      crossSentenceDelete.addEventListener("click", () => {
        const ids = (crossSentenceDelete.dataset.sentenceIds || "")
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean);
        if (ids.length) deleteSentenceCardsInPlace(ids);
      });
      dismissButton.addEventListener("click", () => {
        window.getSelection()?.removeAllRanges();
        hideToolbar();
      });
      panelClose.addEventListener("click", closePanel);
      panelReturn.addEventListener("click", closePanel);
      panelRetry.addEventListener("click", () => {
        if (panelMode === "word" && activeAnalysisWordCardId) {
          requestWordAnalysis(activeAnalysisWordCardId);
        } else if (activeAnalysisSentenceId) {
          requestAnalysis(activeAnalysisSentenceId, null);
        }
      });
      wordDetailSave.addEventListener("click", async () => {
        if (!activeWordDetailCardId) return;
        const cardId = activeWordDetailCardId;
        const meaning = wordDetailMeaning.value;
        const note = wordDetailNote.value;
        const body = new URLSearchParams({ current_meaning: meaning, user_note: note });
        const resp = await fetch(`/mark/word/${cardId}`, { method: "PATCH", body });
        if (resp.ok) {
          reader.querySelectorAll(`[data-word-card="${cardId}"]`).forEach((span) => {
            span.dataset.meaning = meaning;
            span.dataset.note = note;
          });
          hideToolbar();
        }
      });
      wordDetailRemove.addEventListener("click", () => {
        const cardId = wordDetailRemove.dataset.cardId;
        if (cardId) deleteWordCardsAndReload([cardId]);
      });
      if (wordDetailExplain) {
        wordDetailExplain.addEventListener("click", () => {
          if (activeWordDetailCardId) requestWordAnalysis(activeWordDetailCardId);
        });
      }
      if (wordPanelSave) {
        wordPanelSave.addEventListener("click", async () => {
          if (!activeAnalysisWordCardId) return;
          const cardId = activeAnalysisWordCardId;
          const meaning = wordPanelMeaning?.value || "";
          const note = wordPanelNote?.value || "";
          const body = new URLSearchParams({ current_meaning: meaning, user_note: note });
          const resp = await fetch(`/mark/word/${cardId}`, { method: "PATCH", body });
          if (resp.ok) {
            reader.querySelectorAll(`[data-word-card="${cardId}"]`).forEach((span) => {
              span.dataset.meaning = meaning;
              span.dataset.note = note;
            });
            if (wordPanelSaveStatus) {
              wordPanelSaveStatus.textContent = "Saved ✓";
              window.setTimeout(() => {
                if (wordPanelSaveStatus) wordPanelSaveStatus.textContent = "";
              }, 1500);
            }
          }
        });
      }
      reader.addEventListener("click", (event) => {
        const selection = window.getSelection();
        const hasSelection = selection && !selection.isCollapsed;
        const wordSpan = event.target.closest("[data-word-card]");
        if (wordSpan && !hasSelection) {
          showWordDetail(wordSpan);
          return;
        }
        const sentence = event.target.closest("[data-sentence-id]");
        if (!sentence || !sentence.dataset.analysisId) return;
        if (hasSelection) return;
        loadSavedAnalysis(sentence.dataset.sentenceId);
      });
      document.addEventListener("selectionchange", () => window.setTimeout(updateToolbar, 0));
      window.addEventListener("scroll", () => {
        hideToolbar();
        scheduleProgressSave();
      }, { passive: true });
      if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", () => {
          if (!translationEditorOpen) return;
          const keyboardInset = Math.max(
            10,
            window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop + 10,
          );
          toolbar.style.bottom = `${keyboardInset}px`;
        });
      }
      restoreReaderProgress();
    })();
    """


def _sentence_cards_table(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return '<p class="empty">No sentence cards.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{card['id']}</td>"
        f"<td>{_escape(card['mastery_state'])}</td>"
        f"<td>{_escape(_date(card['due_at']))}</td>"
        f"<td>{_escape((card.get('user_translation') or '')[:80])}</td>"
        f"<td>{_escape(card['sentence_text'][:100])}</td>"
        "</tr>"
        for card in cards
    )
    return f"<table><thead><tr><th>ID</th><th>State</th><th>Due</th><th>Translation</th><th>Text</th></tr></thead><tbody>{rows}</tbody></table>"


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


def _import_forms() -> str:
    return """
    <section class="toolbar">
      <div>
        <h1>Import</h1>
        <p class="muted">Add a TXT file or paste text directly. You jump straight to the reader after import.</p>
      </div>
    </section>
    <section class="band">
      <h2>Upload TXT file</h2>
      <form method="post" action="/import/file" enctype="multipart/form-data" class="stack-form">
        <label for="file-title">Title (optional)</label>
        <input id="file-title" name="title" placeholder="Leave blank to auto-detect">
        <label for="file-author">Author (optional)</label>
        <input id="file-author" name="author">
        <label for="file-input">TXT file</label>
        <input id="file-input" type="file" name="file" accept=".txt,text/plain" required>
        <button type="submit">Import file</button>
      </form>
    </section>
    <section class="band">
      <h2>Paste text</h2>
      <form method="post" action="/import/paste" class="stack-form">
        <label for="paste-title">Title (optional)</label>
        <input id="paste-title" name="title" placeholder="Leave blank to auto-detect">
        <label for="paste-author">Author (optional)</label>
        <input id="paste-author" name="author">
        <label for="paste-text">Article text</label>
        <textarea id="paste-text" name="text" rows="14" placeholder="Paste an article here..." required></textarea>
        <button type="submit">Import pasted text</button>
      </form>
    </section>
    """


def _duplicate_page(existing_book_id: int | None) -> HTMLResponse:
    if existing_book_id is not None:
        link = (
            f'<a class="button primary" href="/read/{existing_book_id}">Open existing book</a> '
            f'<a class="button" href="/books/{existing_book_id}">View chapters</a>'
        )
    else:
        link = '<a class="button" href="/books">Browse books</a>'
    body = f"""
    <section class="toolbar">
      <div>
        <h1>Already imported</h1>
        <p class="muted">This content has the same hash as a book already in your library.</p>
      </div>
    </section>
    <section class="band">
      <p>No new book was created. Open the existing one to keep reading.</p>
      <p>{link}</p>
    </section>
    """
    return _html_page("Already imported", body, active="import", status_code=409)


def _resolve_title(form_title: str, raw: bytes) -> str:
    cleaned = form_title.strip()
    if cleaned:
        return cleaned[:_AUTO_TITLE_MAX_LEN]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_AUTO_TITLE_MAX_LEN]
    return f"Untitled Import {datetime.now().date().isoformat()}"


def _lookup_book_id_by_hash(db: DatabaseConnection, file_hash: str) -> int | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    return int(row["id"]) if row else None


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
    page_class: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    body_class = f' class="{_escape(page_class)}"' if page_class else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} - English Reading Trainer</title>
  <style>{_css()}</style>
</head>
<body{body_class}>
  <nav>
    <a class="{_active(active, "dashboard")}" href="/">Dashboard</a>
    <a class="{_active(active, "books")}" href="/books">Books</a>
    <a class="{_active(active, "import")}" href="/import">Import</a>
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
    .reader-page {
      background: #ffffff;
    }
    .reader-page nav {
      padding: 8px 16px;
      background: rgba(255, 255, 255, 0.88);
      backdrop-filter: blur(10px);
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 48px;
    }
    .reader-page main {
      width: 100%;
      margin: 0;
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
    .band {
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
    .reader {
      max-width: 680px;
      margin: 32px auto 96px;
      padding: 0 16px;
    }
    .reader-header {
      margin: 0 0 32px;
    }
    .reader-back {
      display: inline-block;
      margin-bottom: 18px;
      color: var(--muted);
      text-decoration: none;
    }
    .reader-back:hover { color: var(--accent-strong); }
    .reader-title {
      margin: 0 0 4px;
      font-size: 28px;
      line-height: 1.2;
    }
    .reader-chapter {
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      font-weight: 400;
    }
    .reader-para {
      margin: 0 0 1.2em;
      color: #1a1a1a;
      font-family: Georgia, "Source Han Serif SC", "Songti SC", serif;
      font-size: 18px;
      line-height: 1.75;
    }
    .reader-sentence {
      cursor: text;
      text-underline-offset: 0.22em;
    }
    [data-sentence-id].marked {
      background: linear-gradient(transparent 60%, #ffe58a 60%);
    }
    [data-sentence-id].analyzed,
    [data-sentence-id].analyzed-stale {
      border-left: 1px solid #2563eb;
      padding-left: 4px;
    }
    [data-sentence-id].analyzed-stale {
      border-left-style: dashed;
    }
    [data-sentence-id].analysis-highlight-fallback {
      outline: 2px solid rgba(37, 99, 235, 0.35);
      outline-offset: 2px;
    }
    .analysis-highlight {
      background: #bfdbfe;
      box-shadow: 0 0 0 2px #bfdbfe;
    }
    [data-word-card] {
      text-decoration: underline dotted #f59e0b;
      text-underline-offset: 3px;
    }
    .reader-page.analysis-open .reader {
      max-width: 520px;
      margin-left: max(16px, calc((100vw - 940px) / 2));
      margin-right: 400px;
      transition: margin 140ms ease, max-width 140ms ease;
    }
    .selection-toolbar {
      position: absolute;
      z-index: 20;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      max-width: min(92vw, 760px);
      padding: 8px;
      border-radius: 8px;
      background: #111827;
      color: #f9fafb;
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.28);
    }
    .selection-toolbar[hidden] { display: none; }
    .toolbar-group {
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }
    .toolbar-group[hidden] { display: none; }
    .selection-toolbar button {
      border-color: #374151;
      background: #f9fafb;
      color: #111827;
    }
    .selection-toolbar button.danger {
      border-color: #fecaca;
      color: #991b1b;
    }
    .toolbar-status {
      padding: 5px 4px;
      color: #e5e7eb;
      font-size: 14px;
      white-space: nowrap;
    }
    .word-detail-panel {
      display: grid;
      gap: 8px;
      width: min(340px, calc(92vw - 16px));
    }
    .word-detail-panel[hidden] { display: none; }
    .word-detail-surface {
      color: #f1f5f9;
      font-size: 15px;
    }
    .word-detail-fields {
      display: grid;
      gap: 6px;
    }
    .word-detail-label {
      display: grid;
      gap: 3px;
      color: #94a3b8;
      font-size: 12px;
    }
    .word-detail-label input {
      background: #f9fafb;
      color: #111827;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      padding: 5px 8px;
      font-size: 14px;
    }
    .word-detail-actions {
      display: flex;
      gap: 6px;
    }
    .translation-editor {
      display: grid;
      gap: 6px;
      width: min(520px, calc(92vw - 16px));
    }
    .translation-editor[hidden] { display: none; }
    .translation-editor label {
      color: #e5e7eb;
      font-size: 13px;
    }
    .translation-editor textarea {
      min-height: 92px;
      min-width: 100%;
      resize: vertical;
      background: #f9fafb;
      color: #111827;
    }
    .translation-actions {
      display: flex;
      gap: 6px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .analysis-panel {
      position: fixed;
      z-index: 15;
      top: 49px;
      right: 0;
      bottom: 0;
      width: 360px;
      overflow-y: auto;
      border-left: 1px solid var(--line);
      background: #ffffff;
      box-shadow: -14px 0 32px rgba(15, 23, 42, 0.14);
      padding: 18px;
    }
    .analysis-panel[hidden] { display: none; }
    .analysis-panel-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .analysis-panel-header h2 {
      margin: 0;
      font-size: 18px;
    }
    .panel-kicker {
      margin: 0 0 2px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .analysis-status {
      min-height: 20px;
      margin: 8px 0 12px;
      color: var(--muted);
      font-size: 14px;
    }
    .analysis-status.error {
      color: #b91c1c;
    }
    .analysis-section {
      border-top: 1px solid var(--line);
      padding-top: 12px;
      margin-top: 12px;
    }
    .analysis-section h3 {
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }
    .analysis-text {
      margin: 0;
      line-height: 1.55;
    }
    .analysis-codes {
      display: inline-block;
      margin: 2px 0 8px;
      border: 1px solid #bfdbfe;
      border-radius: 999px;
      padding: 2px 8px;
      color: #1d4ed8;
      background: #eff6ff;
      font-size: 13px;
    }
    .word-analysis-list {
      margin: 4px 0 0;
      padding-left: 18px;
    }
    .word-analysis-list li {
      margin: 2px 0;
      line-height: 1.45;
    }
    [data-word-card].word-analysis-active {
      background: #fef9c3;
      border-radius: 2px;
      outline: 2px solid #f59e0b;
      outline-offset: 1px;
    }
    .vs-simpler-item {
      margin: 4px 0;
    }
    .word-notes-fields {
      display: grid;
      gap: 6px;
      margin: 4px 0 8px;
    }
    .word-notes-label {
      display: flex;
      flex-direction: column;
      gap: 3px;
      font-size: 13px;
      color: var(--muted);
    }
    .word-notes-label input {
      font: inherit;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 5px 8px;
      color: var(--text);
      font-size: 14px;
    }
    .word-notes-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .evidence-item {
      width: 100%;
      margin: 6px 0 0;
      border-color: var(--line);
      background: #f8fafc;
      color: var(--text);
      text-align: left;
      white-space: normal;
    }
    .evidence-item:hover {
      border-color: #2563eb;
      color: #1d4ed8;
    }
    .analysis-panel-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
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
      .reader-page main {
        width: 100%;
        margin: 0;
      }
      .toolbar, .split { display: block; }
      table { font-size: 14px; }
      th, td { padding: 8px; }
      .reader {
        margin: 24px auto 80px;
        padding: 0 20px;
      }
      .reader-para {
        font-size: 17px;
        line-height: 1.7;
      }
      .reader-page.analysis-open .reader {
        max-width: 680px;
        margin: 24px auto 80px;
      }
      .selection-toolbar {
        position: fixed;
        left: 10px !important;
        right: 10px;
        bottom: 10px;
        top: auto !important;
        max-width: none;
      }
      .translation-editor {
        width: 100%;
      }
      .analysis-panel {
        inset: 0;
        width: 100%;
        border-left: 0;
        padding: 16px;
      }
      .analysis-panel-header {
        padding-bottom: 8px;
        border-bottom: 1px solid var(--line);
      }
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
