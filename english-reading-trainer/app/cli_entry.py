"""
CLI entry point for the English Reading Trainer.

DB path resolution (highest priority first):
  1. TRAINER_DB environment variable
  2. Default: <project_root>/data/reading_trainer.db

Usage examples:
  trainer books list
  trainer books import txt ./book.txt --title "My Book"
  trainer books import epub ./book.epub
  trainer books show 1
  trainer read 1 --chapter 2
  trainer mark sentence 42 --note "hard relative clause"
  trainer mark word 42 "give rise to" --type phrase
  trainer cards sentences
  trainer cards words
  trainer review due
  trainer review answer sentence 1 pass
  trainer profile status
  trainer profile prompt
  trainer profile save
  trainer ai prompt-sentence 42          # print prompt → paste into AI chat
  trainer ai prompt-word 42 "mitigate"  # print word prompt
  trainer ai save-sentence 42            # paste JSON when prompted
  trainer ai save-word 42 "mitigate"    # paste JSON when prompted
"""

import os
import re
from pathlib import Path

import typer

from app.ai.prompt_version_registry import sync_prompt_versions
from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    create_sentence_card,
    list_sentence_cards,
    save_sentence_translation,
)
from app.cards.word_card_service import (
    create_or_update_word_card,
    list_word_cards,
)
from app.db_connection import DatabaseConnection
from app.db_models import CardType, LexicalType, ReviewOutcome
from app.importers.epub_importer import import_epub
from app.importers.pdf_importer import import_pdf
from app.importers.txt_importer import DuplicateBookError, import_txt
from app.profile.learner_profile_generator import (
    ProfileInputError,
    build_profile_prompt,
    collect_profile_stats,
    get_latest_profile_snapshot,
    get_profile_trigger_status,
    profile_stats_to_payload,
    save_profile_snapshot,
)
from app.review.daily_review_queue import build_daily_review_queue
from app.review.sm2_scheduler import (
    ReviewCardNotFoundError,
    ReviewInputError,
    apply_review,
)

# ---------------------------------------------------------------------------
# DB resolution
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_DEFAULT_DB   = _PROJECT_ROOT / "data" / "reading_trainer.db"
_MIGRATIONS   = _PROJECT_ROOT / "migrations"


def _get_db() -> DatabaseConnection:
    db_path = os.environ.get("TRAINER_DB", str(_DEFAULT_DB))
    db = DatabaseConnection(db_path)
    db.apply_migrations(_MIGRATIONS)
    sync_prompt_versions(db, _PROJECT_ROOT / "prompts")
    return db


# ---------------------------------------------------------------------------
# Typer app tree
# ---------------------------------------------------------------------------

app         = typer.Typer(help="English Reading Trainer — CLI", add_completion=False)
books_app   = typer.Typer(help="Manage imported books.")
import_app  = typer.Typer(help="Import a book into the trainer.")
mark_app    = typer.Typer(help="Mark a sentence or word for review.")
cards_app   = typer.Typer(help="List and inspect cards.")
review_app  = typer.Typer(help="Review due cards.")
profile_app = typer.Typer(help="Learner profile snapshots.")
ai_app      = typer.Typer(help="AI analysis: generate prompts and save results.")

app.add_typer(books_app,  name="books")
books_app.add_typer(import_app, name="import")
app.add_typer(mark_app,   name="mark")
app.add_typer(cards_app,  name="cards")
app.add_typer(review_app, name="review")
app.add_typer(profile_app, name="profile")
app.add_typer(ai_app,     name="ai")


# ---------------------------------------------------------------------------
# books list
# ---------------------------------------------------------------------------

@books_app.command("list")
def books_list() -> None:
    """List all imported books."""
    db = _get_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, author, source_format, total_chapters, "
            "total_sentences, imported_at FROM books ORDER BY id"
        ).fetchall()

    if not rows:
        typer.echo("No books imported yet.  Use: trainer books import txt/epub <path>")
        return

    _print_row(["ID", "Title", "Author", "Format", "Chapters", "Sentences", "Imported"])
    _print_row(["-" * 4, "-" * 30, "-" * 20, "-" * 6, "-" * 8, "-" * 9, "-" * 20])
    for r in rows:
        imported = (r["imported_at"] or "")[:19].replace("T", " ")
        _print_row([
            r["id"], r["title"][:30], (r["author"] or "")[:20],
            r["source_format"], r["total_chapters"],
            r["total_sentences"], imported,
        ])


# ---------------------------------------------------------------------------
# books import txt / epub / pdf
# ---------------------------------------------------------------------------

@import_app.command("txt")
def import_txt_cmd(
    path: Path = typer.Argument(..., help="Path to .txt file"),
    title: str = typer.Option("", "--title", "-t", help="Book title (auto-detected if omitted)"),
    author: str = typer.Option("", "--author", "-a", help="Author name"),
    language: str = typer.Option("en", "--language", "-l", help="Language code"),
) -> None:
    """Import a plain-text (.txt) book."""
    db = _get_db()
    effective_title = title or path.stem
    try:
        result = import_txt(db, path, title=effective_title, author=author, language=language)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except DuplicateBookError as e:
        typer.echo(f"Skipped (already imported): {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(
        f"Imported '{effective_title}' (book id={result.book_id}): "
        f"{result.chapter_count} chapters, {result.sentence_count} sentences."
    )


@import_app.command("epub")
def import_epub_cmd(
    path: Path = typer.Argument(..., help="Path to .epub file"),
    title: str = typer.Option("", "--title", "-t", help="Override title from EPUB metadata"),
    author: str = typer.Option("", "--author", "-a", help="Override author from EPUB metadata"),
    language: str = typer.Option("en", "--language", "-l", help="Language code"),
) -> None:
    """Import an EPUB book."""
    db = _get_db()
    try:
        result = import_epub(
            db, path,
            title=title or None,
            author=author or None,
            language=language,
        )
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except DuplicateBookError as e:
        typer.echo(f"Skipped (already imported): {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT title, author FROM books WHERE id = ?", (result.book_id,)
        ).fetchone()
    typer.echo(
        f"Imported '{row['title']}' by {row['author'] or '(unknown)'} "
        f"(book id={result.book_id}): "
        f"{result.chapter_count} chapters, {result.sentence_count} sentences."
    )


@import_app.command("pdf")
def import_pdf_cmd(
    path: Path = typer.Argument(..., help="Path to .pdf file"),
    title: str = typer.Option("", "--title", "-t", help="Override title from PDF metadata"),
    author: str = typer.Option("", "--author", "-a", help="Override author from PDF metadata"),
    language: str = typer.Option("en", "--language", "-l", help="Language code"),
) -> None:
    """Import a selectable-text PDF book."""
    db = _get_db()
    try:
        result = import_pdf(
            db,
            path,
            title=title or None,
            author=author or None,
            language=language,
        )
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except DuplicateBookError as e:
        typer.echo(f"Skipped (already imported): {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT title, author FROM books WHERE id = ?", (result.book_id,)
        ).fetchone()
    typer.echo(
        f"Imported '{row['title']}' by {row['author'] or '(unknown)'} "
        f"(book id={result.book_id}): "
        f"{result.chapter_count} chapters, {result.sentence_count} sentences."
    )


# ---------------------------------------------------------------------------
# books show
# ---------------------------------------------------------------------------

@books_app.command("show")
def books_show(
    book_id: int = typer.Argument(..., help="Book ID"),
) -> None:
    """Show chapters of a book."""
    db = _get_db()
    with db.get_connection() as conn:
        book = conn.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if not book:
            typer.echo(f"Book id={book_id} not found.", err=True)
            raise typer.Exit(1)

        chapters = conn.execute(
            "SELECT idx, title, sentence_start, sentence_end, "
            "section_kind, chapter_number "
            "FROM chapters WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()

    typer.echo(f"\n{book['title']} — {book['author'] or '(unknown author)'}")
    typer.echo(f"Format: {book['source_format']}  |  "
               f"{book['total_chapters']} chapters  |  "
               f"{book['total_sentences']} sentences\n")

    _print_row(["Section", "Kind", "Sentences"])
    _print_row(["-" * 40, "-" * 11, "-" * 9])
    for ch in chapters:
        sent_count = ch["sentence_end"] - ch["sentence_start"]
        _print_row([_section_label(ch)[:40], ch["section_kind"], sent_count])


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

@app.command("read")
def read_cmd(
    book_id: int = typer.Argument(..., help="Book ID"),
    chapter: int = typer.Option(1, "--chapter", "-c", help="Chapter index (1-based)"),
    width: int = typer.Option(80, "--width", "-w", help="Display width for wrapping"),
) -> None:
    """Display sentences in a chapter with their IDs for marking."""
    db = _get_db()
    with db.get_connection() as conn:
        book = conn.execute(
            "SELECT title FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if not book:
            typer.echo(f"Book id={book_id} not found.", err=True)
            raise typer.Exit(1)

        ch = conn.execute(
            "SELECT id, idx, title, section_kind, chapter_number "
            "FROM chapters WHERE book_id = ? AND idx = ?",
            (book_id, chapter),
        ).fetchone()
        if not ch:
            typer.echo(
                f"Chapter {chapter} not found in book id={book_id}.", err=True
            )
            raise typer.Exit(1)

        sentences = conn.execute(
            """SELECT s.id, s.idx, s.text,
                      CASE WHEN sc.id IS NOT NULL THEN 1 ELSE 0 END AS has_card
               FROM sentences s
               LEFT JOIN sentence_cards sc
                 ON sc.sentence_id = s.id AND sc.archived_at IS NULL
               WHERE s.chapter_id = ?
               ORDER BY s.idx""",
            (ch["id"],),
        ).fetchall()

    typer.echo(f"\n{'=' * width}")
    typer.echo(f"  {book['title']}  |  {_section_label(ch)}")
    typer.echo(f"{'=' * width}\n")

    current_para_id = None
    with db.get_connection() as conn:
        para_map = {
            row["id"]: row["paragraph_id"]
            for row in conn.execute(
                "SELECT id, paragraph_id FROM sentences WHERE chapter_id = ?",
                (ch["id"],),
            ).fetchall()
        }

    for sent in sentences:
        para_id = para_map.get(sent["id"])
        if para_id != current_para_id:
            if current_para_id is not None:
                typer.echo("")
            current_para_id = para_id

        card_marker = " [*]" if sent["has_card"] else ""
        label = f"[{sent['id']}]{card_marker}"
        # Simple word-wrap
        line = f"{label:<12}{sent['text']}"
        typer.echo(line[:width + 12])

    typer.echo(f"\n{'=' * width}")
    typer.echo("  [*] = card exists   |  Use: trainer mark sentence <ID>")
    typer.echo(f"{'=' * width}\n")


# ---------------------------------------------------------------------------
# mark sentence
# ---------------------------------------------------------------------------

@mark_app.command("sentence")
def mark_sentence(
    sentence_id: int = typer.Argument(..., help="Sentence ID (from 'trainer read')"),
    note: str = typer.Option("", "--note", "-n", help="Personal note for this card"),
    translation: str = typer.Option(
        "",
        "--translation",
        "-t",
        help="Your Chinese translation or understanding of this sentence",
    ),
) -> None:
    """Create a sentence card for a difficult sentence."""
    db = _get_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT s.text, b.title AS book_title, c.title AS chapter_title "
            "FROM sentences s "
            "JOIN books b ON s.book_id = b.id "
            "JOIN chapters c ON s.chapter_id = c.id "
            "WHERE s.id = ?",
            (sentence_id,),
        ).fetchone()

    if not row:
        typer.echo(f"Sentence id={sentence_id} not found.", err=True)
        raise typer.Exit(1)

    if translation.strip():
        try:
            card_id = save_sentence_translation(
                db,
                sentence_id,
                translation,
                user_note=note,
            )
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
    else:
        try:
            card_id = create_sentence_card(db, sentence_id, user_note=note)
        except SentenceCardAlreadyExistsError as e:
            typer.echo(f"Already marked: {e}")
            raise typer.Exit(0)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    typer.echo(f"Sentence card created (id={card_id})")
    typer.echo(f"  Book:    {row['book_title']}")
    typer.echo(f"  Chapter: {row['chapter_title']}")
    typer.echo(f"  Text:    \"{row['text']}\"")


# ---------------------------------------------------------------------------
# mark word
# ---------------------------------------------------------------------------

@mark_app.command("word")
def mark_word(
    sentence_id: int  = typer.Argument(..., help="Sentence ID containing the word"),
    surface_form: str = typer.Argument(..., help="Word or phrase as it appears in text"),
    lexical_type: str = typer.Option(
        "word", "--type", "-t",
        help="Type: word | phrase | collocation",
    ),
    note: str = typer.Option("", "--note", "-n", help="Personal note"),
) -> None:
    """Create or update a word/phrase card."""
    try:
        lt = LexicalType(lexical_type)
    except ValueError:
        typer.echo(
            f"Invalid type '{lexical_type}'. Choose: word, phrase, collocation",
            err=True,
        )
        raise typer.Exit(1)

    db = _get_db()
    with db.get_connection() as conn:
        sent_row = conn.execute(
            "SELECT text FROM sentences WHERE id = ?", (sentence_id,)
        ).fetchone()

    if not sent_row:
        typer.echo(f"Sentence id={sentence_id} not found.", err=True)
        raise typer.Exit(1)

    try:
        card_id, created = create_or_update_word_card(
            db, sentence_id, surface_form, lt, user_note=note
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if created:
        typer.echo(f"Word card created (id={card_id}): '{surface_form}'")
    else:
        typer.echo(
            f"Word already tracked (id={card_id}): "
            f"'{surface_form}' — source recorded if this location is new."
        )
    typer.echo(f"  From: \"{sent_row['text'][:80]}\"")


# ---------------------------------------------------------------------------
# cards sentences
# ---------------------------------------------------------------------------

@cards_app.command("sentences")
def cards_sentences(
    limit: int  = typer.Option(20, "--limit",   "-l", help="Max rows to show"),
    offset: int = typer.Option(0,  "--offset",  "-o", help="Row offset"),
    book_id: int | None = typer.Option(None, "--book", "-b", help="Filter by book ID"),
) -> None:
    """List sentence cards."""
    db = _get_db()
    cards = list_sentence_cards(db, book_id=book_id, limit=limit, offset=offset)
    if not cards:
        typer.echo("No sentence cards yet.  Use: trainer mark sentence <ID>")
        return

    _print_row(["ID", "Sent ID", "State", "Box/EF", "Due", "Text (first 50)"])
    _print_row(["-" * 4, "-" * 7, "-" * 8, "-" * 8, "-" * 12, "-" * 50])
    for c in cards:
        due = (c["due_at"] or "")[:10]
        ef  = f"{c['ef']:.1f}"
        _print_row([
            c["id"], c["sentence_id"],
            c["mastery_state"], ef,
            due, c["sentence_text"][:50],
        ])


# ---------------------------------------------------------------------------
# cards words
# ---------------------------------------------------------------------------

@cards_app.command("words")
def cards_words(
    limit: int  = typer.Option(20, "--limit",  "-l", help="Max rows to show"),
    offset: int = typer.Option(0,  "--offset", "-o", help="Row offset"),
) -> None:
    """List word/phrase cards."""
    db = _get_db()
    cards = list_word_cards(db, limit=limit, offset=offset)
    if not cards:
        typer.echo("No word cards yet.  Use: trainer mark word <SENT_ID> <WORD>")
        return

    _print_row(["ID", "Lemma", "Type", "State", "EF", "Occ.", "Due"])
    _print_row(["-" * 4, "-" * 25, "-" * 11, "-" * 8, "-" * 5, "-" * 4, "-" * 12])
    for c in cards:
        due = (c["due_at"] or "")[:10]
        _print_row([
            c["id"], c["lemma"][:25], c["lexical_type"],
            c["mastery_state"], f"{c['ef']:.1f}",
            c["occurrence_count"], due,
        ])


# ---------------------------------------------------------------------------
# review due
# ---------------------------------------------------------------------------

@review_app.command("due")
def review_due(
    limit: int = typer.Option(40, "--limit", "-l", help="Max due cards to show"),
) -> None:
    """List today's mixed review queue."""
    db = _get_db()
    try:
        items = build_daily_review_queue(db, daily_limit=limit)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if not items:
        typer.echo("No cards due for review.")
        return

    _print_row(["Type", "ID", "State", "EF", "Due", "Prompt"])
    _print_row(["-" * 8, "-" * 4, "-" * 8, "-" * 4, "-" * 12, "-" * 50])
    for item in items:
        _print_row([
            item.card_type.value,
            item.card_id,
            item.mastery_state.value,
            f"{item.ef:.1f}",
            item.due_at.date().isoformat(),
            item.prompt[:50],
        ])


# ---------------------------------------------------------------------------
# review answer
# ---------------------------------------------------------------------------

@review_app.command("answer")
def review_answer(
    card_type: str = typer.Argument(..., help="Card type: sentence | word"),
    card_id: int = typer.Argument(..., help="Card ID"),
    outcome: str = typer.Argument(..., help="Outcome: pass | partial | fail"),
    latency_ms: int = typer.Option(0, "--latency-ms", help="Answer latency in ms"),
) -> None:
    """Record a review answer and schedule the card's next due date."""
    try:
        parsed_card_type = CardType(card_type)
        parsed_outcome = ReviewOutcome(outcome)
    except ValueError:
        typer.echo(
            "Invalid review input. Use card_type=sentence|word and "
            "outcome=pass|partial|fail.",
            err=True,
        )
        raise typer.Exit(1)

    db = _get_db()
    try:
        result = apply_review(
            db,
            parsed_card_type,
            card_id,
            parsed_outcome,
            latency_ms=latency_ms,
        )
    except (ReviewCardNotFoundError, ReviewInputError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(
        f"Reviewed {result.card_type.value} card id={result.card_id}: "
        f"{result.outcome.value} (quality={result.quality})."
    )
    typer.echo(
        f"Next due: {result.state_after.due_at.date().isoformat()}  "
        f"state={result.state_after.mastery_state.value}  "
        f"ef={result.state_after.ef:.2f}  "
        f"interval={result.state_after.interval_days}d"
    )


# ---------------------------------------------------------------------------
# profile status
# ---------------------------------------------------------------------------

@profile_app.command("status")
def profile_status() -> None:
    """Show whether a new learner profile snapshot is due."""
    db = _get_db()
    try:
        status = get_profile_trigger_status(db)
    except ProfileInputError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    state = "due" if status.should_generate else "not due"
    typer.echo(f"Profile status: {state} ({status.reason})")
    typer.echo(f"Reviews since snapshot: {status.reviews_since_snapshot}")
    if status.last_snapshot_at is None:
        typer.echo("Last snapshot: none")
    else:
        typer.echo(f"Last snapshot: {status.last_snapshot_at.date().isoformat()}")
        typer.echo(f"Days since snapshot: {status.days_since_snapshot}")


# ---------------------------------------------------------------------------
# profile prompt
# ---------------------------------------------------------------------------

@profile_app.command("prompt")
def profile_prompt(
    lookback_days: int = typer.Option(90, "--lookback-days", help="Review lookback window"),
) -> None:
    """Print the filled learner-profile prompt for manual AI generation."""
    db = _get_db()
    try:
        prompt = build_profile_prompt(db, lookback_days=lookback_days)
    except (FileNotFoundError, ProfileInputError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo("\n" + "=" * 72)
    typer.echo("  COPY EVERYTHING BELOW THIS LINE AND PASTE INTO YOUR AI CHAT")
    typer.echo("=" * 72 + "\n")
    typer.echo(prompt)
    typer.echo("\n" + "=" * 72)
    typer.echo("  When done, run:  trainer profile save")
    typer.echo("=" * 72 + "\n")


# ---------------------------------------------------------------------------
# profile save
# ---------------------------------------------------------------------------

@profile_app.command("save")
def profile_save(
    lookback_days: int = typer.Option(90, "--lookback-days", help="Stats window for payload"),
) -> None:
    """Save a Markdown learner profile summary from stdin."""
    typer.echo("Paste the Markdown profile from your AI chat. Finish with Ctrl-D:\n")
    import sys
    try:
        summary_md = sys.stdin.read().strip()
    except (KeyboardInterrupt, EOFError):
        summary_md = ""

    if not summary_md:
        typer.echo("No input received.", err=True)
        raise typer.Exit(1)

    db = _get_db()
    try:
        stats = collect_profile_stats(db, lookback_days=lookback_days)
        snapshot_id = save_profile_snapshot(
            db,
            summary_md,
            payload=profile_stats_to_payload(stats),
        )
    except ProfileInputError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Saved learner profile snapshot id={snapshot_id}")


# ---------------------------------------------------------------------------
# profile latest
# ---------------------------------------------------------------------------

@profile_app.command("latest")
def profile_latest() -> None:
    """Print the latest saved learner profile snapshot."""
    db = _get_db()
    snapshot = get_latest_profile_snapshot(db)
    if snapshot is None:
        typer.echo("No learner profile snapshots yet.")
        return

    typer.echo(f"Snapshot id={snapshot.id}  created={snapshot.created_at.date().isoformat()}")
    typer.echo("")
    typer.echo(snapshot.summary_md)


# ---------------------------------------------------------------------------
# ai prompt-sentence / prompt-word
# ---------------------------------------------------------------------------

@ai_app.command("prompt-sentence")
def ai_prompt_sentence(
    sentence_id: int = typer.Argument(..., help="Sentence ID from 'trainer read'"),
    translation: str = typer.Option(
        "",
        "--translation",
        "-t",
        help="Temporary user translation for diagnosis prompt",
    ),
) -> None:
    """Print the filled analysis prompt — paste it into Claude / Gemini / Codex chat."""
    from app.ai.context_builder import build_sentence_prompt
    db = _get_db()
    try:
        prompt = build_sentence_prompt(
            db,
            sentence_id,
            user_translation=translation if translation.strip() else None,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo("\n" + "=" * 72)
    typer.echo("  COPY EVERYTHING BELOW THIS LINE AND PASTE INTO YOUR AI CHAT")
    typer.echo("=" * 72 + "\n")
    typer.echo(prompt)
    typer.echo("\n" + "=" * 72)
    typer.echo(f"  When done, run:  trainer ai save-sentence {sentence_id}")
    typer.echo("=" * 72 + "\n")


@ai_app.command("prompt-word")
def ai_prompt_word(
    sentence_id:  int = typer.Argument(..., help="Sentence ID containing the word"),
    surface_form: str = typer.Argument(..., help="Word or phrase as it appears in text"),
) -> None:
    """Print the filled word-analysis prompt — paste into AI chat."""
    from app.ai.context_builder import build_word_prompt
    db = _get_db()
    try:
        prompt = build_word_prompt(db, sentence_id, surface_form)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo("\n" + "=" * 72)
    typer.echo("  COPY EVERYTHING BELOW THIS LINE AND PASTE INTO YOUR AI CHAT")
    typer.echo("=" * 72 + "\n")
    typer.echo(prompt)
    typer.echo("\n" + "=" * 72)
    typer.echo(
        f"  When done, run:  trainer ai save-word {sentence_id} \"{surface_form}\""
    )
    typer.echo("=" * 72 + "\n")


# ---------------------------------------------------------------------------
# ai save-sentence / save-word
# ---------------------------------------------------------------------------

@ai_app.command("save-sentence")
def ai_save_sentence(
    sentence_id:    int = typer.Argument(..., help="Sentence ID"),
    model:          str = typer.Option("manual", "--model", "-m",
                        help="Model label (e.g. claude-opus-4-7, gemini-2.0)"),
    prompt_version: str = typer.Option("v1", "--prompt-version", "-p"),
) -> None:
    """
    Save a sentence analysis JSON returned by your AI chat.

    Paste the JSON when prompted (finish with Ctrl-D on a new line).
    """
    from app.ai.analysis_saver import save_sentence_analysis
    typer.echo("Paste the JSON from your AI chat. Finish with Ctrl-D (Mac/Linux):\n")
    import sys
    try:
        raw_json = sys.stdin.read().strip()
    except (KeyboardInterrupt, EOFError):
        raw_json = ""

    if not raw_json:
        typer.echo("No input received.", err=True)
        raise typer.Exit(1)

    db = _get_db()
    try:
        result = save_sentence_analysis(
            db, sentence_id, raw_json, model=model, prompt_version=prompt_version
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if not result.is_valid:
        typer.echo(f"Validation failed — saved as invalid (cache id={result.cache_id}).")
        typer.echo(f"Error: {result.error[:200]}", err=True)
        raise typer.Exit(1)

    action = "created" if result.card_created else "updated"
    typer.echo(f"Saved  cache_id={result.cache_id}")
    typer.echo(f"Card {action}  card_id={result.card_id}")


@ai_app.command("save-word")
def ai_save_word(
    sentence_id:    int = typer.Argument(..., help="Sentence ID containing the word"),
    surface_form:   str = typer.Argument(..., help="Word or phrase"),
    model:          str = typer.Option("manual", "--model", "-m"),
    prompt_version: str = typer.Option("v1", "--prompt-version", "-p"),
) -> None:
    """
    Save a word/phrase analysis JSON returned by your AI chat.

    Paste the JSON when prompted (finish with Ctrl-D on a new line).
    """
    from app.ai.analysis_saver import save_word_analysis
    typer.echo("Paste the JSON from your AI chat. Finish with Ctrl-D (Mac/Linux):\n")
    import sys
    try:
        raw_json = sys.stdin.read().strip()
    except (KeyboardInterrupt, EOFError):
        raw_json = ""

    if not raw_json:
        typer.echo("No input received.", err=True)
        raise typer.Exit(1)

    db = _get_db()
    try:
        result = save_word_analysis(
            db, sentence_id, surface_form, raw_json,
            model=model, prompt_version=prompt_version,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if not result.is_valid:
        typer.echo(f"Validation failed — saved as invalid (cache id={result.cache_id}).")
        typer.echo(f"Error: {result.error[:200]}", err=True)
        raise typer.Exit(1)

    action = "created" if result.card_created else "updated"
    typer.echo(f"Saved  cache_id={result.cache_id}")
    typer.echo(f"Card {action}  card_id={result.card_id}")


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def _print_row(cols: list) -> None:
    typer.echo("  ".join(str(c) for c in cols))


def _section_label(row) -> str:
    title = str(row["title"] or "").strip()
    kind = row["section_kind"] or "chapter"
    if kind == "chapter":
        chapter_number = row["chapter_number"] or row["idx"]
        clean_title = _strip_section_ordinal(title)
        return (
            f"Chapter {chapter_number}: {clean_title}"
            if clean_title
            else f"Chapter {chapter_number}"
        )
    if kind == "appendix":
        clean_title = _strip_appendix_ordinal(title)
        appendix_letter = _appendix_letter(title)
        if appendix_letter:
            return (
                f"Appendix {appendix_letter}: {clean_title}"
                if clean_title
                else f"Appendix {appendix_letter}"
            )
        return f"Appendix: {title}" if title else "Appendix"
    return title or kind.title()


def _strip_section_ordinal(title: str) -> str:
    return re.sub(r"^\s*(?:chapter\s+)?\d+(?:[\s.:)-]+)", "", title, flags=re.I).strip()


def _appendix_letter(title: str) -> str:
    match = re.match(r"^\s*(?:appendix\s+)?([A-Z])(?:[\s.:)-]+|$)", title)
    return match.group(1) if match else ""


def _strip_appendix_ordinal(title: str) -> str:
    return re.sub(r"^\s*(?:appendix\s+)?[A-Z](?:[\s.:)-]+)", "", title).strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
