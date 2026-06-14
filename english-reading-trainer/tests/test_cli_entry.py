"""
Tests for app/cli_entry.py (Typer CLI).

Uses typer.testing.CliRunner to invoke commands without spawning a subprocess.
Sets TRAINER_DB env var to a tmp_path DB so tests are fully isolated.
All tests use real SQLite — no mocking.
"""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli_entry import app
from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from tests.importers.epub_builder import make_epub

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture: isolated DB per test
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "trainer_test.db"


@pytest.fixture(autouse=True)
def _set_trainer_db(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_DB", str(db_path))


@pytest.fixture()
def db(db_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(db_path)
    c.apply_migrations(MIGRATIONS_DIR)
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_txt(tmp_path: Path, content: str, name: str = "book.txt") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _seed_book_and_sentence(db: DatabaseConnection, tmp_path: Path) -> tuple[int, int]:
    """Import a minimal TXT book; return (book_id, first_sentence_id)."""
    f = _write_txt(tmp_path, "The cat sat on the mat. It was a lovely day.")
    result = import_txt(db, f, title="Test Book")
    with db.get_connection() as conn:
        sid = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY id LIMIT 1",
            (result.book_id,),
        ).fetchone()["id"]
    return result.book_id, sid


# ---------------------------------------------------------------------------
# books list
# ---------------------------------------------------------------------------

class TestBooksList:
    def test_empty_message_when_no_books(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["books", "list"])
        assert result.exit_code == 0
        assert "No books" in result.output

    def test_shows_imported_book(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["books", "list"])
        assert result.exit_code == 0
        assert "Test Book" in result.output

    def test_shows_format_column(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["books", "list"])
        assert "txt" in result.output


# ---------------------------------------------------------------------------
# books import txt
# ---------------------------------------------------------------------------

class TestImportTxtCmd:
    def test_successful_import(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = _write_txt(tmp_path, "Hello world. This is a test.")
        result = runner.invoke(app, ["books", "import", "txt", str(f), "--title", "My Book"])
        assert result.exit_code == 0
        assert "My Book" in result.output
        assert "sentences" in result.output

    def test_uses_filename_as_default_title(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        f = _write_txt(tmp_path, "One sentence here.", name="myfile.txt")
        result = runner.invoke(app, ["books", "import", "txt", str(f)])
        assert result.exit_code == 0
        assert "myfile" in result.output

    def test_missing_file_exits_with_error(self, db: DatabaseConnection, tmp_path: Path) -> None:
        result = runner.invoke(app, ["books", "import", "txt", str(tmp_path / "nope.txt")])
        assert result.exit_code != 0

    def test_duplicate_import_exits_with_error(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        f = _write_txt(tmp_path, "Unique content here for dup test.")
        runner.invoke(app, ["books", "import", "txt", str(f), "--title", "Book"])
        result = runner.invoke(app, ["books", "import", "txt", str(f), "--title", "Book"])
        assert result.exit_code != 0
        assert "already imported" in result.output.lower() or "skip" in result.output.lower()

    def test_empty_file_exits_with_error(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = _write_txt(tmp_path, "")
        result = runner.invoke(app, ["books", "import", "txt", str(f)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# books import epub
# ---------------------------------------------------------------------------

class TestImportEpubCmd:
    def test_successful_import(self, db: DatabaseConnection, tmp_path: Path) -> None:
        ep = make_epub(tmp_path, "test.epub", title="EPUB Book", author="Author")
        result = runner.invoke(app, ["books", "import", "epub", str(ep)])
        assert result.exit_code == 0
        assert "EPUB Book" in result.output

    def test_override_title(self, db: DatabaseConnection, tmp_path: Path) -> None:
        ep = make_epub(tmp_path, "test2.epub")
        result = runner.invoke(
            app, ["books", "import", "epub", str(ep), "--title", "Custom Title"]
        )
        assert result.exit_code == 0
        assert "Custom Title" in result.output

    def test_missing_file_exits_with_error(self, db: DatabaseConnection, tmp_path: Path) -> None:
        result = runner.invoke(app, ["books", "import", "epub", str(tmp_path / "no.epub")])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# books show
# ---------------------------------------------------------------------------

class TestBooksShow:
    def test_shows_chapters(self, db: DatabaseConnection, tmp_path: Path) -> None:
        book_id, _ = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["books", "show", str(book_id)])
        assert result.exit_code == 0
        assert "Test Book" in result.output
        assert "Chapter" in result.output

    def test_missing_book_exits_with_error(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["books", "show", "9999"])
        assert result.exit_code != 0

    def test_shows_sentence_counts(self, db: DatabaseConnection, tmp_path: Path) -> None:
        book_id, _ = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["books", "show", str(book_id)])
        assert result.exit_code == 0
        # At least the chapter row is there
        assert result.output.count("1") >= 1


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

class TestReadCmd:
    def test_shows_sentences(self, db: DatabaseConnection, tmp_path: Path) -> None:
        book_id, _ = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["read", str(book_id), "--chapter", "1"])
        assert result.exit_code == 0
        assert "cat" in result.output or "lovely" in result.output

    def test_shows_sentence_ids(self, db: DatabaseConnection, tmp_path: Path) -> None:
        book_id, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["read", str(book_id)])
        assert result.exit_code == 0
        assert str(sid) in result.output

    def test_missing_book_exits_with_error(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["read", "9999"])
        assert result.exit_code != 0

    def test_missing_chapter_exits_with_error(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["read", str(book_id), "--chapter", "99"])
        assert result.exit_code != 0

    def test_card_marker_shown_after_marking(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["mark", "sentence", str(sid)])
        result = runner.invoke(app, ["read", str(book_id)])
        assert "[*]" in result.output


# ---------------------------------------------------------------------------
# mark sentence
# ---------------------------------------------------------------------------

class TestMarkSentence:
    def test_creates_card(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["mark", "sentence", str(sid)])
        assert result.exit_code == 0
        assert "created" in result.output.lower()

    def test_shows_sentence_text(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["mark", "sentence", str(sid)])
        assert result.exit_code == 0
        assert "cat" in result.output or "lovely" in result.output

    def test_duplicate_mark_graceful(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["mark", "sentence", str(sid)])
        result = runner.invoke(app, ["mark", "sentence", str(sid)])
        assert result.exit_code == 0
        assert "already" in result.output.lower()

    def test_missing_sentence_exits_with_error(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["mark", "sentence", "9999"])
        assert result.exit_code != 0

    def test_note_accepted(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["mark", "sentence", str(sid), "--note", "hard clause"]
        )
        assert result.exit_code == 0
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_note FROM sentence_cards WHERE sentence_id = ?", (sid,)
            ).fetchone()
        assert row["user_note"] == "hard clause"


# ---------------------------------------------------------------------------
# mark word
# ---------------------------------------------------------------------------

class TestMarkWord:
    def test_creates_word_card(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["mark", "word", str(sid), "cat"])
        assert result.exit_code == 0
        assert "created" in result.output.lower()

    def test_shows_word_in_output(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["mark", "word", str(sid), "lovely"])
        assert result.exit_code == 0
        assert "lovely" in result.output

    def test_phrase_type_accepted(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["mark", "word", str(sid), "give rise to", "--type", "phrase"]
        )
        assert result.exit_code == 0
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT lexical_type FROM word_cards WHERE lemma = 'give rise to'"
            ).fetchone()
        assert row["lexical_type"] == "phrase"

    def test_invalid_type_exits_with_error(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["mark", "word", str(sid), "word", "--type", "invalid"]
        )
        assert result.exit_code != 0

    def test_duplicate_increments_occurrence(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["mark", "word", str(sid), "cat"])
        result = runner.invoke(app, ["mark", "word", str(sid), "cat"])
        assert result.exit_code == 0
        assert "increment" in result.output.lower() or "occurrence" in result.output.lower()

    def test_missing_sentence_exits_with_error(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["mark", "word", "9999", "word"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# cards sentences
# ---------------------------------------------------------------------------

class TestCardsSentences:
    def test_empty_message_when_none(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["cards", "sentences"])
        assert result.exit_code == 0
        assert "No sentence" in result.output

    def test_shows_marked_sentence(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["mark", "sentence", str(sid)])
        result = runner.invoke(app, ["cards", "sentences"])
        assert result.exit_code == 0
        assert "new" in result.output

    def test_limit_option(self, db: DatabaseConnection, tmp_path: Path) -> None:
        f = _write_txt(
            tmp_path,
            "Sent one. Sent two. Sent three. Sent four. Sent five.",
        )
        r = import_txt(db, f, title="Multi")
        with db.get_connection() as conn:
            sids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM sentences WHERE book_id = ?", (r.book_id,)
                ).fetchall()
            ]
        for s in sids:
            runner.invoke(app, ["mark", "sentence", str(s)])
        result = runner.invoke(app, ["cards", "sentences", "--limit", "2"])
        assert result.exit_code == 0
        # Only 2 data rows (plus header)
        lines = [l for l in result.output.splitlines() if "new" in l]
        assert len(lines) <= 2


# ---------------------------------------------------------------------------
# cards words
# ---------------------------------------------------------------------------

class TestCardsWords:
    def test_empty_message_when_none(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["cards", "words"])
        assert result.exit_code == 0
        assert "No word" in result.output

    def test_shows_marked_word(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["mark", "word", str(sid), "cat"])
        result = runner.invoke(app, ["cards", "words"])
        assert result.exit_code == 0
        assert "cat" in result.output

    def test_collocation_type_shown(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(
            app, ["mark", "word", str(sid), "sat on", "--type", "collocation"]
        )
        result = runner.invoke(app, ["cards", "words"])
        assert "collocation" in result.output


# ---------------------------------------------------------------------------
# Helpers shared by ai command tests
# ---------------------------------------------------------------------------

_VALID_SENTENCE_JSON = json.dumps({
    "subject_skeleton": "cat sat",
    "clauses": [
        {"type": "main", "text": "The cat sat on the mat", "role": "statement"}
    ],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat on the mat",
    "chinese_gloss": "猫坐在垫子上",
    "predicted_error_types": ["G01"],
    "confidence": 0.9,
})

_VALID_WORD_JSON = json.dumps({
    "lemma": "cat",
    "lexical_type": "word",
    "pos": "noun",
    "meaning_in_context": "a small domestic animal",
    "common_collocations": ["fat cat", "cat nap", "cool cat"],
    "near_synonyms": ["feline", "kitty"],
    "confusable_with": [],
    "morphology": {"root": "", "family": ["cats", "catlike"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
})


# ---------------------------------------------------------------------------
# ai prompt-sentence
# ---------------------------------------------------------------------------

class TestAiPromptSentence:
    def test_prints_prompt_for_valid_sentence(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "prompt-sentence", str(sid)])
        assert result.exit_code == 0
        assert "COPY EVERYTHING" in result.output

    def test_output_contains_sentence_text(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "prompt-sentence", str(sid)])
        assert result.exit_code == 0
        # The seed sentence contains "cat"
        assert "cat" in result.output.lower()

    def test_shows_save_hint(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "prompt-sentence", str(sid)])
        assert "save-sentence" in result.output

    def test_unknown_sentence_id_exits_nonzero(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["ai", "prompt-sentence", "999999"])
        assert result.exit_code != 0

    def test_unknown_sentence_id_shows_error(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["ai", "prompt-sentence", "999999"])
        assert "error" in result.output.lower() or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# ai prompt-word
# ---------------------------------------------------------------------------

class TestAiPromptWord:
    def test_prints_prompt_for_valid_word(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "prompt-word", str(sid), "cat"])
        assert result.exit_code == 0
        assert "COPY EVERYTHING" in result.output

    def test_output_contains_surface_form(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "prompt-word", str(sid), "cat"])
        assert "cat" in result.output

    def test_shows_save_hint(self, db: DatabaseConnection, tmp_path: Path) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "prompt-word", str(sid), "cat"])
        assert "save-word" in result.output

    def test_unknown_sentence_id_exits_nonzero(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["ai", "prompt-word", "999999", "cat"])
        assert result.exit_code != 0

    def test_unknown_sentence_id_shows_error(self, db: DatabaseConnection) -> None:
        result = runner.invoke(app, ["ai", "prompt-word", "999999", "cat"])
        assert "error" in result.output.lower() or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# ai save-sentence
# ---------------------------------------------------------------------------

class TestAiSaveSentence:
    def test_valid_json_exits_zero(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-sentence", str(sid)], input=_VALID_SENTENCE_JSON
        )
        assert result.exit_code == 0

    def test_valid_json_shows_cache_and_card_ids(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-sentence", str(sid)], input=_VALID_SENTENCE_JSON
        )
        assert "cache_id" in result.output
        assert "card" in result.output.lower()

    def test_card_created_message(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-sentence", str(sid)], input=_VALID_SENTENCE_JSON
        )
        assert "created" in result.output.lower()

    def test_second_save_shows_updated(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["ai", "save-sentence", str(sid)], input=_VALID_SENTENCE_JSON)
        result = runner.invoke(
            app, ["ai", "save-sentence", str(sid)], input=_VALID_SENTENCE_JSON
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_empty_input_exits_nonzero(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(app, ["ai", "save-sentence", str(sid)], input="")
        assert result.exit_code != 0

    def test_invalid_json_exits_nonzero(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-sentence", str(sid)], input="{ not valid json }"
        )
        assert result.exit_code != 0

    def test_invalid_json_shows_validation_failed(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-sentence", str(sid)], input="{ not valid json }"
        )
        assert "validation" in result.output.lower() or "error" in result.output.lower()

    def test_unknown_sentence_id_exits_nonzero(self, db: DatabaseConnection) -> None:
        result = runner.invoke(
            app, ["ai", "save-sentence", "999999"], input=_VALID_SENTENCE_JSON
        )
        assert result.exit_code != 0

    def test_custom_model_option_accepted(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app,
            ["ai", "save-sentence", str(sid), "--model", "claude-opus-4-7"],
            input=_VALID_SENTENCE_JSON,
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# ai save-word
# ---------------------------------------------------------------------------

class TestAiSaveWord:
    def test_valid_json_exits_zero(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "cat"], input=_VALID_WORD_JSON
        )
        assert result.exit_code == 0

    def test_valid_json_shows_cache_and_card_ids(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "cat"], input=_VALID_WORD_JSON
        )
        assert "cache_id" in result.output
        assert "card" in result.output.lower()

    def test_card_created_message(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "cat"], input=_VALID_WORD_JSON
        )
        assert "created" in result.output.lower()

    def test_second_save_shows_updated(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        runner.invoke(app, ["ai", "save-word", str(sid), "cat"], input=_VALID_WORD_JSON)
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "cat"], input=_VALID_WORD_JSON
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_empty_input_exits_nonzero(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "cat"], input=""
        )
        assert result.exit_code != 0

    def test_invalid_json_exits_nonzero(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "cat"], input="not json"
        )
        assert result.exit_code != 0

    def test_unknown_sentence_id_exits_nonzero(self, db: DatabaseConnection) -> None:
        result = runner.invoke(
            app, ["ai", "save-word", "999999", "cat"], input=_VALID_WORD_JSON
        )
        assert result.exit_code != 0

    def test_multiword_surface_form(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        phrase_json = json.dumps({
            "lemma": "sit on",
            "lexical_type": "phrase",
            "pos": "phrase",
            "meaning_in_context": "to be positioned on top of",
            "common_collocations": ["sit on the fence", "sit on hands"],
            "near_synonyms": [],
            "confusable_with": [],
            "morphology": {"root": "", "family": []},
            "predicted_error_types": ["L03"],
            "confidence": 0.85,
        })
        result = runner.invoke(
            app, ["ai", "save-word", str(sid), "sat on"], input=phrase_json
        )
        assert result.exit_code == 0

    def test_custom_model_option_accepted(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sid = _seed_book_and_sentence(db, tmp_path)
        result = runner.invoke(
            app,
            ["ai", "save-word", str(sid), "cat", "--model", "gemini-2.0-flash"],
            input=_VALID_WORD_JSON,
        )
        assert result.exit_code == 0
