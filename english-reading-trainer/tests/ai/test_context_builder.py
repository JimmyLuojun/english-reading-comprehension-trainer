"""
Tests for app/ai/context_builder.py.

Uses real SQLite (tmp_path) and real prompt templates from prompts/.
No LLM calls or network access.

Coverage areas:
  _strip_frontmatter: with/without frontmatter, unterminated frontmatter
  _render: single var, multiple vars, missing var (left as-is)
  _load_prompt: existing template, missing template
  _fetch_sentence_context: basic, context window, related cards, word cards,
                           learner profile, sentence not found
  build_sentence_prompt: happy path, not-found error
  build_word_prompt: happy path, not-found error
  get_sentence_info: delegates to _fetch_sentence_context
"""

import json
import runpy
import sys
from pathlib import Path

import pytest

from app.ai.context_builder import (
    _render,
    _strip_frontmatter,
    build_sentence_prompt,
    build_word_prompt,
    get_sentence_info,
)
from app.cards.sentence_card_service import save_sentence_translation
from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
CONTEXT_BUILDER_PATH = (
    Path(__file__).parent.parent.parent / "app" / "ai" / "context_builder.py"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


@pytest.fixture()
def seeded(db: DatabaseConnection, tmp_path: Path) -> tuple[DatabaseConnection, int, int]:
    """Import a book and return (db, book_id, first_sentence_id)."""
    txt = tmp_path / "book.txt"
    txt.write_text(
        "Chapter One\n\n"
        "The quick brown fox jumps over the lazy dog. "
        "It was a bright cold day in April. "
        "The clocks were striking thirteen.",
        encoding="utf-8",
    )
    result = import_txt(db, txt, title="Test Book", author="Author")
    with db.get_connection() as conn:
        sid = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY id LIMIT 1",
            (result.book_id,),
        ).fetchone()["id"]
    return db, result.book_id, sid


# ---------------------------------------------------------------------------
# _strip_frontmatter
# ---------------------------------------------------------------------------

class TestStripFrontmatter:
    def test_no_frontmatter_returned_unchanged(self):
        text = "Hello world\nSecond line"
        assert _strip_frontmatter(text) == text

    def test_standard_frontmatter_stripped(self):
        text = "---\nname: foo\nversion: v1\n---\n\nBody text here."
        result = _strip_frontmatter(text)
        assert result == "Body text here."
        assert "name: foo" not in result

    def test_frontmatter_with_no_closing_dashes_returned_unchanged(self):
        text = "---\nname: foo\nno closing marker"
        assert _strip_frontmatter(text) == text

    def test_empty_frontmatter(self):
        text = "---\n---\n\nContent starts here."
        result = _strip_frontmatter(text)
        assert "Content starts here." in result

    def test_strips_leading_newline_after_frontmatter(self):
        text = "---\nkey: val\n---\n\nFirst line."
        result = _strip_frontmatter(text)
        assert not result.startswith("\n")
        assert result.startswith("First line.")


# ---------------------------------------------------------------------------
# _render
# ---------------------------------------------------------------------------

class TestRender:
    def test_single_variable_replaced(self):
        result = _render("Hello {{ name }}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_variables_replaced(self):
        result = _render("{{ a }} and {{ b }}", {"a": "foo", "b": "bar"})
        assert result == "foo and bar"

    def test_unknown_variable_left_as_is(self):
        result = _render("{{ unknown }}", {"other": "x"})
        assert "{{ unknown }}" in result

    def test_empty_variables_dict(self):
        template = "No placeholders here."
        assert _render(template, {}) == template

    def test_value_can_contain_braces(self):
        result = _render("{{ x }}", {"x": "{some value}"})
        assert result == "{some value}"

    def test_replaces_all_occurrences(self):
        result = _render("{{ v }} {{ v }}", {"v": "hi"})
        assert result == "hi hi"


# ---------------------------------------------------------------------------
# build_sentence_prompt — happy path & error
# ---------------------------------------------------------------------------

class TestBuildSentencePrompt:
    def test_returns_string(self, seeded):
        db, book_id, sid = seeded
        prompt = build_sentence_prompt(db, sid)
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_contains_sentence_text(self, seeded):
        db, book_id, sid = seeded
        with db.get_connection() as conn:
            text = conn.execute(
                "SELECT text FROM sentences WHERE id = ?", (sid,)
            ).fetchone()["text"]
        prompt = build_sentence_prompt(db, sid)
        assert text in prompt

    def test_no_unreplaced_placeholders(self, seeded):
        db, book_id, sid = seeded
        prompt = build_sentence_prompt(db, sid)
        # The five known template keys must all be replaced
        for key in ("sentence", "context", "chapter_title", "related_cards", "learner_profile"):
            assert f"{{{{ {key} }}}}" not in prompt

    def test_raises_value_error_for_unknown_id(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="not found"):
            build_sentence_prompt(db, 999_999)

    def test_context_marks_target_sentence(self, seeded):
        db, book_id, sid = seeded
        prompt = build_sentence_prompt(db, sid)
        assert ">>>" in prompt

    def test_prompt_includes_chapter_title(self, seeded):
        db, book_id, sid = seeded
        prompt = build_sentence_prompt(db, sid)
        # chapter_title placeholder must be gone; some title text should appear
        assert "{{ chapter_title }}" not in prompt

    def test_without_translation_uses_prediction_prompt(self, seeded):
        db, book_id, sid = seeded
        prompt = build_sentence_prompt(db, sid)
        assert "Prediction Mode" in prompt
        assert '"diagnosis_basis": "predicted"' in prompt

    def test_explicit_translation_uses_diagnosis_prompt(self, seeded):
        db, book_id, sid = seeded
        prompt = build_sentence_prompt(db, sid, user_translation="狐狸跳过狗。")
        assert "Diagnosis Mode" in prompt
        assert "狐狸跳过狗。" in prompt

    def test_stored_translation_uses_diagnosis_prompt(self, seeded):
        db, book_id, sid = seeded
        save_sentence_translation(db, sid, "狐狸跳过狗。")
        prompt = build_sentence_prompt(db, sid)
        assert "Diagnosis Mode" in prompt
        assert "狐狸跳过狗。" in prompt


# ---------------------------------------------------------------------------
# build_word_prompt — happy path & error
# ---------------------------------------------------------------------------

class TestBuildWordPrompt:
    def test_returns_string(self, seeded):
        db, book_id, sid = seeded
        prompt = build_word_prompt(db, sid, "fox")
        assert isinstance(prompt, str)

    def test_contains_surface_form(self, seeded):
        db, book_id, sid = seeded
        prompt = build_word_prompt(db, sid, "fox")
        assert "fox" in prompt

    def test_no_unreplaced_placeholders(self, seeded):
        db, book_id, sid = seeded
        prompt = build_word_prompt(db, sid, "fox")
        for key in ("surface_form", "sentence", "context", "related_cards", "learner_profile"):
            assert f"{{{{ {key} }}}}" not in prompt

    def test_raises_value_error_for_unknown_sentence(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="not found"):
            build_word_prompt(db, 999_999, "word")

    def test_different_surface_forms_produce_different_prompts(self, seeded):
        db, book_id, sid = seeded
        p1 = build_word_prompt(db, sid, "fox")
        p2 = build_word_prompt(db, sid, "dog")
        assert p1 != p2


# ---------------------------------------------------------------------------
# get_sentence_info
# ---------------------------------------------------------------------------

class TestGetSentenceInfo:
    def test_returns_dict_with_expected_keys(self, seeded):
        db, book_id, sid = seeded
        info = get_sentence_info(db, sid)
        expected_keys = {
            "sentence_id", "sentence_text", "book_title",
            "chapter_title", "context", "related_cards_text",
            "learner_profile", "user_translation",
        }
        assert set(info.keys()) >= expected_keys

    def test_sentence_id_matches(self, seeded):
        db, book_id, sid = seeded
        info = get_sentence_info(db, sid)
        assert info["sentence_id"] == sid

    def test_book_title_correct(self, seeded):
        db, book_id, sid = seeded
        info = get_sentence_info(db, sid)
        assert info["book_title"] == "Test Book"

    def test_no_profile_fallback(self, seeded):
        db, book_id, sid = seeded
        info = get_sentence_info(db, sid)
        assert info["learner_profile"] == "(no profile yet)"

    def test_related_cards_none_when_empty(self, seeded):
        db, book_id, sid = seeded
        info = get_sentence_info(db, sid)
        assert info["related_cards_text"] == "(none)"

    def test_raises_for_unknown_id(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="not found"):
            get_sentence_info(db, 999_999)


# ---------------------------------------------------------------------------
# Context window — neighbouring sentences
# ---------------------------------------------------------------------------

class TestContextWindow:
    def test_context_includes_target_marker(self, seeded):
        db, book_id, sid = seeded
        info = get_sentence_info(db, sid)
        assert ">>>" in info["context"]
        assert "<<<" in info["context"]

    def test_context_includes_neighbouring_text(self, db: DatabaseConnection, tmp_path: Path):
        txt = tmp_path / "multi.txt"
        txt.write_text(
            "Sentence A here. Sentence B here. Sentence C here. Sentence D here.",
            encoding="utf-8",
        )
        result = import_txt(db, txt, title="Multi")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM sentences WHERE book_id = ? ORDER BY id",
                (result.book_id,),
            ).fetchall()
        # Pick the middle sentence so it has at least one neighbour
        mid_sid = rows[1]["id"]
        info = get_sentence_info(db, mid_sid)
        # Context should have more text than just the target sentence
        assert len(info["context"]) > len(info["sentence_text"])


# ---------------------------------------------------------------------------
# Learner profile included when present
# ---------------------------------------------------------------------------

class TestLearnerProfile:
    def test_learner_profile_returned_when_snapshot_exists(self, seeded):
        db, book_id, sid = seeded
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO learner_profile_snapshots (summary_md, created_at) VALUES (?, ?)",
                ("## My Profile\nI struggle with relative clauses.", "2026-01-01T00:00:00+00:00"),
            )
        info = get_sentence_info(db, sid)
        assert "My Profile" in info["learner_profile"]

    def test_latest_profile_used_when_multiple_exist(self, seeded):
        db, book_id, sid = seeded
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO learner_profile_snapshots (summary_md, created_at) VALUES (?, ?)",
                ("Old profile.", "2025-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO learner_profile_snapshots (summary_md, created_at) VALUES (?, ?)",
                ("New profile.", "2026-06-01T00:00:00+00:00"),
            )
        info = get_sentence_info(db, sid)
        assert "New profile." in info["learner_profile"]


# ---------------------------------------------------------------------------
# Related cards included when present
# ---------------------------------------------------------------------------

class TestRelatedCards:
    def test_related_sentence_card_appears_in_output(self, seeded):
        db, book_id, sid = seeded
        with db.get_connection() as conn:
            related_sid = conn.execute(
                """SELECT id FROM sentences
                   WHERE book_id = ? AND id != ?
                   ORDER BY id LIMIT 1""",
                (book_id, sid),
            ).fetchone()["id"]
            cache_id = conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json, is_valid, created_at)
                   VALUES ('related-sentence', 'v1', 'test', ?, 1, '2026-01-01')""",
                (json.dumps({"summary": "related"}),),
            ).lastrowid
            conn.execute(
                """INSERT INTO sentence_cards
                   (sentence_id, created_at, due_at, ai_analysis_id)
                   VALUES (?, '2026-01-01', '2026-01-01', ?)""",
                (related_sid, cache_id),
            )

        info = get_sentence_info(db, sid)

        assert "• [" in info["related_cards_text"]
        assert "It was a bright cold day" in info["related_cards_text"]

    def test_related_word_card_appears_in_output(self, seeded):
        db, book_id, sid = seeded
        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO word_cards
                   (lemma, surface_form, lexical_type, first_sentence_id,
                    current_meaning, pos, created_at, review_count,
                    mastery_state, ef, interval_days, repetitions, due_at,
                    occurrence_count, user_note)
                   VALUES ('mitigate','mitigating','word',?,
                   'to lessen severity','verb','2026-01-01',0,
                   'new',2.5,0,0,'2026-01-01',1,'')""",
                (sid,),
            )
        info = get_sentence_info(db, sid)
        assert "mitigate" in info["related_cards_text"]
        assert "to lessen severity" in info["related_cards_text"]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

class TestCliEntryPoint:
    def test_cli_without_args_exits_with_usage(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["context_builder"])

        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(CONTEXT_BUILDER_PATH), run_name="__main__")

        assert exc.value.code == 1
        assert "Usage: python -m app.ai.context_builder sentence <id>" in capsys.readouterr().out

    def test_cli_sentence_mode_prints_prompt(
        self,
        seeded,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, book_id, sid = seeded
        monkeypatch.setenv("TRAINER_DB", str(getattr(db, "_db_path")))
        monkeypatch.setattr(sys, "argv", ["context_builder", "sentence", str(sid)])

        runpy.run_path(str(CONTEXT_BUILDER_PATH), run_name="__main__")

        assert "Prediction Mode" in capsys.readouterr().out

    def test_cli_word_mode_prints_prompt(
        self,
        seeded,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, book_id, sid = seeded
        monkeypatch.setenv("TRAINER_DB", str(getattr(db, "_db_path")))
        monkeypatch.setattr(sys, "argv", ["context_builder", "word", str(sid), "fox"])

        runpy.run_path(str(CONTEXT_BUILDER_PATH), run_name="__main__")

        output = capsys.readouterr().out
        assert "fox" in output
        assert "The quick brown fox" in output

    def test_cli_info_mode_prints_json(
        self,
        seeded,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, book_id, sid = seeded
        monkeypatch.setenv("TRAINER_DB", str(getattr(db, "_db_path")))
        monkeypatch.setattr(sys, "argv", ["context_builder", "info", str(sid)])

        runpy.run_path(str(CONTEXT_BUILDER_PATH), run_name="__main__")

        payload = json.loads(capsys.readouterr().out)
        assert payload["sentence_id"] == sid
        assert payload["book_title"] == "Test Book"

    def test_cli_unknown_mode_exits_with_error(
        self,
        seeded,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, book_id, sid = seeded
        monkeypatch.setenv("TRAINER_DB", str(getattr(db, "_db_path")))
        monkeypatch.setattr(sys, "argv", ["context_builder", "unknown", str(sid)])

        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(CONTEXT_BUILDER_PATH), run_name="__main__")

        assert exc.value.code == 1
        assert "Unknown command: unknown" in capsys.readouterr().err
