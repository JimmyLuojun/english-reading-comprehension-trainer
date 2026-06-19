"""
Fetch all context needed for AI analysis from the DB and render it into a
prompt string ready to paste into any AI chat.

Can be used:
  - As a library: build_sentence_prompt() / build_word_prompt()
  - As a CLI:
      python -m app.ai.context_builder sentence <sentence_id>
      python -m app.ai.context_builder word <sentence_id> <surface_form>
    Prints the filled prompt to stdout.
"""

import json
import os
import sys
from pathlib import Path

from app.db_connection import DatabaseConnection

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PROMPTS_DIR  = _PROJECT_ROOT / "prompts"
_MIGRATIONS   = _PROJECT_ROOT / "migrations"

_CONTEXT_WINDOW = 2   # sentences before/after to include as context
_MAX_RELATED    = 5   # max related cards to include in prompt
_SENTENCE_PROMPT_VERSION = "v4"
_WORD_PROMPT_VERSION = "v5"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sentence_prompt(
    db: DatabaseConnection,
    sentence_id: int,
    user_translation: str | None = None,
) -> str:
    """
    Return a fully rendered sentence-analysis prompt for *sentence_id*.

    If a user translation is supplied or already stored on the active
    sentence card, the diagnosis prompt is used. Otherwise the prediction
    prompt is used.
    Raises ValueError if sentence not found.
    """
    ctx = _fetch_sentence_context(db, sentence_id)
    cleaned_translation = _resolve_user_translation(user_translation, ctx)
    prompt_name = (
        "sentence_analysis_diagnose"
        if cleaned_translation
        else "sentence_analysis_predict"
    )
    template = _load_prompt(prompt_name, _SENTENCE_PROMPT_VERSION)
    return _render(template, {
        "sentence":        ctx["sentence_text"],
        "context":         ctx["context"],
        "chapter_title":   ctx["chapter_title"],
        "related_cards":   ctx["related_cards_text"],
        "learner_profile": ctx["learner_profile"],
        "user_translation": cleaned_translation or "(none)",
    })


def build_word_prompt(
    db: DatabaseConnection,
    sentence_id: int,
    surface_form: str,
) -> str:
    """
    Return a fully rendered word_analysis prompt for *surface_form*
    as it appears in *sentence_id*.
    """
    ctx = _fetch_sentence_context(db, sentence_id)
    template = _load_prompt("word_analysis", _WORD_PROMPT_VERSION)
    return _render(template, {
        "surface_form":    surface_form,
        "sentence":        ctx["sentence_text"],
        "context":         ctx["context"],
        "learner_note":    "(none)",
        "related_cards":   ctx["related_cards_text"],
        "learner_profile": ctx["learner_profile"],
    })


def get_sentence_info(db: DatabaseConnection, sentence_id: int) -> dict:
    """Return raw context dict (used by tests and CLI)."""
    return _fetch_sentence_context(db, sentence_id)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _fetch_sentence_context(db: DatabaseConnection, sentence_id: int) -> dict:
    with db.get_connection() as conn:
        sent = conn.execute(
            """SELECT s.id, s.text, s.idx, s.book_id, s.chapter_id,
                      b.title AS book_title,
                      c.title AS chapter_title,
                      sc.user_translation
               FROM sentences s
               JOIN books    b ON s.book_id    = b.id
               JOIN chapters c ON s.chapter_id = c.id
               LEFT JOIN sentence_cards sc
                 ON sc.sentence_id = s.id
               WHERE s.id = ?""",
            (sentence_id,),
        ).fetchone()

        if not sent:
            raise ValueError(f"Sentence id={sentence_id} not found.")

        # Surrounding sentences for context window
        prev_rows = conn.execute(
            """SELECT text FROM sentences
               WHERE chapter_id = ? AND idx < ?
               ORDER BY idx DESC LIMIT ?""",
            (sent["chapter_id"], sent["idx"], _CONTEXT_WINDOW),
        ).fetchall()
        next_rows = conn.execute(
            """SELECT text FROM sentences
               WHERE chapter_id = ? AND idx > ?
               ORDER BY idx ASC LIMIT ?""",
            (sent["chapter_id"], sent["idx"], _CONTEXT_WINDOW),
        ).fetchall()

        context_parts = (
            [r["text"] for r in reversed(prev_rows)]
            + [f">>> {sent['text']} <<<"]   # mark target sentence
            + [r["text"] for r in next_rows]
        )
        context = " ".join(context_parts)

        # Related cards (sentence cards with AI analysis in same book)
        related_sc = conn.execute(
            """SELECT sc.id, s.text AS sentence_text,
                      ac.response_json
               FROM sentence_cards sc
               JOIN sentences s  ON sc.sentence_id    = s.id
               LEFT JOIN ai_cache ac ON sc.ai_analysis_id = ac.id
               WHERE s.book_id = ? AND s.id != ?
                 AND sc.archived_at IS NULL
                 AND ac.id IS NOT NULL AND ac.is_valid = 1
               ORDER BY sc.created_at DESC LIMIT ?""",
            (sent["book_id"], sentence_id, _MAX_RELATED),
        ).fetchall()

        # Related word cards
        related_wc = conn.execute(
            """SELECT lemma, surface_form, current_meaning
               FROM word_cards
               WHERE archived_at IS NULL
               ORDER BY occurrence_count DESC, created_at DESC
               LIMIT ?""",
            (_MAX_RELATED,),
        ).fetchall()

        # Latest learner profile
        profile_row = conn.execute(
            "SELECT summary_md FROM learner_profile_snapshots "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    # Format related cards as readable text
    rc_lines = []
    for sc in related_sc:
        rc_lines.append(f'• [{sc["id"]}] "{sc["sentence_text"][:80]}"')
    for wc in related_wc:
        meaning = f" — {wc['current_meaning']}" if wc["current_meaning"] else ""
        rc_lines.append(f'• {wc["surface_form"]} ({wc["lemma"]}){meaning}')
    related_cards_text = "\n".join(rc_lines) if rc_lines else "(none)"

    learner_profile = (
        profile_row["summary_md"] if profile_row else "(no profile yet)"
    )

    return {
        "sentence_id":       sent["id"],
        "sentence_text":     sent["text"],
        "book_title":        sent["book_title"],
        "chapter_title":     sent["chapter_title"],
        "context":           context,
        "related_cards_text": related_cards_text,
        "learner_profile":   learner_profile,
        "user_translation":   sent["user_translation"] or "",
    }


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _load_prompt(name: str, version: str) -> str:
    path = _PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    text = path.read_text(encoding="utf-8")
    return _strip_frontmatter(text)


def _resolve_user_translation(
    explicit_translation: str | None,
    ctx: dict,
) -> str:
    if explicit_translation is not None:
        return explicit_translation.strip()
    return str(ctx.get("user_translation") or "").strip()


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    return text[end + 3:].lstrip("\n") if end != -1 else text


def _render(template: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        template = template.replace(f"{{{{ {key} }}}}", value)
    return template


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _get_db() -> DatabaseConnection:
    db_path = os.environ.get(
        "TRAINER_DB",
        str(_PROJECT_ROOT / "data" / "reading_trainer.db"),
    )
    db = DatabaseConnection(db_path)
    db.apply_migrations(_MIGRATIONS)
    return db


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python -m app.ai.context_builder sentence <id>")
        print("       python -m app.ai.context_builder word <id> <surface_form>")
        sys.exit(1)

    db = _get_db()
    mode = args[0]

    if mode == "sentence" and len(args) == 2:
        sid = int(args[1])
        prompt = build_sentence_prompt(db, sid)
        print(prompt)

    elif mode == "word" and len(args) == 3:
        sid = int(args[1])
        surface = args[2]
        prompt = build_word_prompt(db, sid, surface)
        print(prompt)

    elif mode == "info" and len(args) == 2:
        sid = int(args[1])
        info = get_sentence_info(db, sid)
        print(json.dumps(info, ensure_ascii=False, indent=2))

    else:
        print(f"Unknown command: {' '.join(args)}", file=sys.stderr)
        sys.exit(1)
