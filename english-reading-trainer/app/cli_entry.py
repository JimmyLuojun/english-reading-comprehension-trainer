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
  trainer ai prompt-sentence 42          # print prompt → paste into AI chat
  trainer ai prompt-word 42 "mitigate"  # print word prompt
  trainer ai save-sentence 42            # paste JSON when prompted
  trainer ai save-word 42 "mitigate"    # paste JSON when prompted
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import typer

from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    create_sentence_card,
    list_sentence_cards,
)
from app.cards.word_card_service import (
    create_or_update_word_card,
    list_word_cards,
)
from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.importers.epub_importer import import_epub
from app.importers.txt_importer import DuplicateBookError, import_txt

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
    return db


# ---------------------------------------------------------------------------
# Typer app tree
# ---------------------------------------------------------------------------

app         = typer.Typer(help="English Reading Trainer — CLI", add_completion=False)
books_app   = typer.Typer(help="Manage imported books.")
import_app  = typer.Typer(help="Import a book into the trainer.")
mark_app    = typer.Typer(help="Mark a sentence or word for review.")
cards_app   = typer.Typer(help="List and inspect cards.")
ai_app      = typer.Typer(help="AI analysis: generate prompts and save results.")

app.add_typer(books_app,  name="books")
books_app.add_typer(import_app, name="import")
app.add_typer(mark_app,   name="mark")
app.add_typer(cards_app,  name="cards")
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
# books import txt / epub
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
            "SELECT idx, title, sentence_start, sentence_end "
            "FROM chapters WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()

    typer.echo(f"\n{book['title']} — {book['author'] or '(unknown author)'}")
    typer.echo(f"Format: {book['source_format']}  |  "
               f"{book['total_chapters']} chapters  |  "
               f"{book['total_sentences']} sentences\n")

    _print_row(["#", "Title", "Sentences"])
    _print_row(["-" * 3, "-" * 40, "-" * 9])
    for ch in chapters:
        sent_count = ch["sentence_end"] - ch["sentence_start"]
        _print_row([ch["idx"], ch["title"][:40], sent_count])


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
            "SELECT id, title FROM chapters WHERE book_id = ? AND idx = ?",
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
               LEFT JOIN sentence_cards sc ON sc.sentence_id = s.id
               WHERE s.chapter_id = ?
               ORDER BY s.idx""",
            (ch["id"],),
        ).fetchall()

    typer.echo(f"\n{'=' * width}")
    typer.echo(f"  {book['title']}  |  Chapter {chapter}: {ch['title']}")
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
            f"'{surface_form}' — occurrence count incremented."
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
# ai prompt-sentence / prompt-word
# ---------------------------------------------------------------------------

@ai_app.command("prompt-sentence")
def ai_prompt_sentence(
    sentence_id: int = typer.Argument(..., help="Sentence ID from 'trainer read'"),
) -> None:
    """Print the filled analysis prompt — paste it into Claude / Gemini / Codex chat."""
    from app.ai.context_builder import build_sentence_prompt
    db = _get_db()
    try:
        prompt = build_sentence_prompt(db, sentence_id)
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
