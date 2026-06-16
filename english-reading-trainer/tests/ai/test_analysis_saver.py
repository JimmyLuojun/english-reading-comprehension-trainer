"""
Tests for app/ai/analysis_saver.py.

Uses real SQLite (tmp_path). No mocking, no LLM calls.

Coverage areas:
  SaveResult dataclass
  save_sentence_analysis:
    - happy path (creates cache + new card)
    - second call (updates existing card)
    - invalid JSON (saves as invalid, no card)
    - JSON schema validation failure (saves as invalid)
    - sentence not found (raises ValueError)
  save_word_analysis:
    - happy path (creates cache + new word card)
    - second call same lemma (updates occurrence_count)
    - empty surface_form (raises ValueError)
    - sentence not found (raises ValueError)
    - invalid JSON (saves as invalid, no card)
  _upsert_sentence_card: covered indirectly via save_sentence_analysis
  _upsert_word_card: covered indirectly via save_word_analysis
"""

import json
from pathlib import Path

import pytest

from app.ai.analysis_saver import SaveResult, save_sentence_analysis, save_word_analysis
from app.cards.sentence_card_service import save_sentence_translation
from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

# ---------------------------------------------------------------------------
# Valid JSON fixtures
# ---------------------------------------------------------------------------

_VALID_SENTENCE_JSON = json.dumps({
    "subject_skeleton": "fox jumps",
    "clauses": [
        {"type": "main", "text": "The quick brown fox jumps over the lazy dog", "role": "statement"}
    ],
    "modifiers": [{"target": "fox", "modifier": "quick brown", "type": "adjective"}],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The fox jumped over the dog",
    "chinese_gloss": "那只狐狸跳过了狗",
    "predicted_error_types": ["G01"],
    "diagnosis_basis": "predicted",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [],
    "confidence": 0.95,
})

_VALID_DIAGNOSED_SENTENCE_JSON = json.dumps({
    "subject_skeleton": "fox jumps",
    "clauses": [
        {"type": "main", "text": "The quick brown fox jumps over the lazy dog", "role": "statement"}
    ],
    "modifiers": [{"target": "fox", "modifier": "quick brown", "type": "adjective"}],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The fox jumped over the dog",
    "chinese_gloss": "那只狐狸跳过了狗",
    "predicted_error_types": [],
    "diagnosis_basis": "user_translation",
    "diagnosed_error_types": ["G02"],
    "diagnosis_evidence": [
        {
            "error_type": "G02",
            "evidence": "The user translation attaches the modifier to the wrong noun.",
        }
    ],
    "confidence": 0.9,
})

_VALID_OK_DIAGNOSED_SENTENCE_JSON = json.dumps({
    "subject_skeleton": "fox jumps",
    "clauses": [
        {"type": "main", "text": "The quick brown fox jumps over the lazy dog", "role": "statement"}
    ],
    "modifiers": [{"target": "fox", "modifier": "quick brown", "type": "adjective"}],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The fox jumped over the dog",
    "chinese_gloss": "那只狐狸跳过了狗",
    "predicted_error_types": [],
    "diagnosis_basis": "user_translation",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [
        {"error_type": "OK", "evidence": "The translation preserves the main meaning."}
    ],
    "confidence": 0.9,
})

_VALID_WORD_JSON = json.dumps({
    "lemma": "fox",
    "lexical_type": "word",
    "pos": "noun",
    "meaning_in_context": "a wild animal known for cunning",
    "common_collocations": ["foxy lady", "fox hunt", "outfox someone"],
    "near_synonyms": ["vixen"],
    "confusable_with": [],
    "morphology": {"root": "", "family": ["foxy", "foxlike"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
})

_VALID_WORD_JSON_V3 = json.dumps({
    "lemma": "fox",
    "lexical_type": "word",
    "pos": "noun",
    "meaning_in_context": "a wild animal known for cunning",
    "chinese_meaning": "以狡猾著称的狐狸",
    "register": "neutral",
    "why_this_word": "Fox is the precise animal name; animal would be too general. If you wrote animal, you would lose the cultural association with cleverness.",
    "vs_simpler": [
        {"simpler": "animal", "difference": "Animal is broader; fox names the species and its familiar connotations."}
    ],
    "morphology": {"root": "", "family": ["foxy", "foxlike"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
})

_INVALID_JSON_STR = "{ this is not valid JSON }"

_INVALID_SCHEMA_JSON = json.dumps({
    "subject_skeleton": "fox jumps",
    "clauses": [],            # MISSING required "main" clause → semantic validation fails
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "Fox jumped",
    "chinese_gloss": "狐狸跳",
    "predicted_error_types": ["G01"],
    "diagnosis_basis": "predicted",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [],
    "confidence": 0.9,
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


@pytest.fixture()
def sid(db: DatabaseConnection, tmp_path: Path) -> int:
    """Seed one book and return the first sentence_id."""
    txt = tmp_path / "book.txt"
    txt.write_text(
        "The quick brown fox jumps over the lazy dog. It was a bright cold day.",
        encoding="utf-8",
    )
    result = import_txt(db, txt, title="Test Book")
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY id LIMIT 1",
            (result.book_id,),
        ).fetchone()["id"]


def _sentence_error_codes(db: DatabaseConnection, card_id: int) -> set[str]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT et.code
                 FROM sentence_card_errors sce
                 JOIN error_types et ON et.id = sce.error_type_id
                WHERE sce.card_id = ?""",
            (card_id,),
        ).fetchall()
    return {row["code"] for row in rows}


# ---------------------------------------------------------------------------
# SaveResult dataclass
# ---------------------------------------------------------------------------

class TestSaveResultDataclass:
    def test_fields_accessible(self):
        r = SaveResult(cache_id=1, card_id=2, card_created=True, is_valid=True, error="")
        assert r.cache_id == 1
        assert r.card_id == 2
        assert r.card_created is True
        assert r.is_valid is True
        assert r.error == ""

    def test_invalid_result_has_no_card(self):
        r = SaveResult(cache_id=5, card_id=None, card_created=False, is_valid=False, error="bad")
        assert r.card_id is None
        assert not r.is_valid


# ---------------------------------------------------------------------------
# save_sentence_analysis — happy path
# ---------------------------------------------------------------------------

class TestSaveSentenceAnalysisHappyPath:
    def test_returns_save_result(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert isinstance(r, SaveResult)

    def test_is_valid_true(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert r.is_valid is True

    def test_cache_id_positive(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert r.cache_id > 0

    def test_card_created_first_time(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert r.card_created is True
        assert r.card_id is not None

    def test_card_in_db(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sentence_cards WHERE id = ?", (r.card_id,)
            ).fetchone()
        assert row is not None
        assert row["sentence_id"] == sid

    def test_error_empty_on_success(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert r.error == ""

    def test_cache_marked_valid(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (r.cache_id,)
            ).fetchone()
        assert row["is_valid"] == 1

    def test_predicted_error_codes_synced_to_card_errors(
        self, db: DatabaseConnection, sid: int
    ):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert _sentence_error_codes(db, r.card_id) == {"G01"}

    def test_accepts_json_with_markdown_fences(self, db: DatabaseConnection, sid: int):
        fenced = "```json\n" + _VALID_SENTENCE_JSON + "\n```"
        r = save_sentence_analysis(db, sid, fenced)
        assert r.is_valid is True

    def test_custom_model_stored_in_cache(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON, model="claude-opus-4-7")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT model FROM ai_cache WHERE id = ?", (r.cache_id,)
            ).fetchone()
        assert row["model"] == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# save_sentence_analysis — second call (update existing card)
# ---------------------------------------------------------------------------

class TestSaveSentenceAnalysisUpdate:
    def test_second_call_not_created(self, db: DatabaseConnection, sid: int):
        save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        r2 = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert r2.card_created is False

    def test_second_call_same_card_id(self, db: DatabaseConnection, sid: int):
        r1 = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        r2 = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        assert r1.card_id == r2.card_id

    def test_ai_analysis_id_updated(self, db: DatabaseConnection, sid: int):
        save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON, model="v1")
        r2 = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON, model="v2")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT ai_analysis_id FROM sentence_cards WHERE id = ?",
                (r2.card_id,),
            ).fetchone()
        assert row["ai_analysis_id"] == r2.cache_id

    def test_diagnosed_error_codes_replace_predicted_codes(
        self, db: DatabaseConnection, sid: int
    ):
        first = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        save_sentence_translation(db, sid, "我把修饰语理解错了。")

        second = save_sentence_analysis(db, sid, _VALID_DIAGNOSED_SENTENCE_JSON)

        assert second.card_id == first.card_id
        assert _sentence_error_codes(db, second.card_id) == {"G02"}

    def test_ok_diagnosis_clears_sentence_error_codes(
        self, db: DatabaseConnection, sid: int
    ):
        first = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        save_sentence_translation(db, sid, "那只敏捷的棕色狐狸跳过了懒狗。")

        second = save_sentence_analysis(db, sid, _VALID_OK_DIAGNOSED_SENTENCE_JSON)

        assert second.card_id == first.card_id
        assert _sentence_error_codes(db, second.card_id) == set()

    def test_translation_changes_sentence_cache_hash(
        self, db: DatabaseConnection, sid: int
    ):
        first = save_sentence_analysis(db, sid, _VALID_SENTENCE_JSON)
        save_sentence_translation(db, sid, "那只狐狸跳过了狗。")

        second = save_sentence_analysis(db, sid, _VALID_DIAGNOSED_SENTENCE_JSON)

        assert second.cache_id != first.cache_id


# ---------------------------------------------------------------------------
# save_sentence_analysis — error paths
# ---------------------------------------------------------------------------

class TestSaveSentenceAnalysisErrors:
    def test_invalid_json_returns_is_valid_false(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _INVALID_JSON_STR)
        assert r.is_valid is False

    def test_invalid_json_no_card_created(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _INVALID_JSON_STR)
        assert r.card_id is None
        assert r.card_created is False

    def test_invalid_json_error_message_populated(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _INVALID_JSON_STR)
        assert len(r.error) > 0

    def test_invalid_json_still_saves_cache(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _INVALID_JSON_STR)
        assert r.cache_id > 0
        with db.get_connection() as conn:
            row = conn.execute("SELECT is_valid FROM ai_cache WHERE id = ?", (r.cache_id,)).fetchone()
        assert row["is_valid"] == 0

    def test_schema_violation_is_valid_false(self, db: DatabaseConnection, sid: int):
        r = save_sentence_analysis(db, sid, _INVALID_SCHEMA_JSON)
        assert r.is_valid is False

    def test_sentence_not_found_raises(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="not found"):
            save_sentence_analysis(db, 999_999, _VALID_SENTENCE_JSON)


# ---------------------------------------------------------------------------
# save_word_analysis — happy path
# ---------------------------------------------------------------------------

class TestSaveWordAnalysisHappyPath:
    def test_returns_save_result(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert isinstance(r, SaveResult)

    def test_is_valid_true(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert r.is_valid is True

    def test_card_created_first_time(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert r.card_created is True
        assert r.card_id is not None

    def test_card_in_db(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM word_cards WHERE id = ?", (r.card_id,)
            ).fetchone()
        assert row is not None
        assert row["surface_form"] == "fox"

    def test_lemma_stored_from_analysis(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT lemma FROM word_cards WHERE id = ?", (r.card_id,)
            ).fetchone()
        assert row["lemma"] == "fox"

    def test_meaning_stored(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT current_meaning FROM word_cards WHERE id = ?", (r.card_id,)
            ).fetchone()
        assert "cunning" in row["current_meaning"]

    def test_pos_stored(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT pos FROM word_cards WHERE id = ?", (r.card_id,)
            ).fetchone()
        assert row["pos"] == "noun"

    def test_v3_json_with_chinese_meaning_is_valid(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(
            db,
            sid,
            "fox",
            _VALID_WORD_JSON_V3,
            prompt_version="v3",
        )

        assert r.is_valid is True

    def test_cache_id_positive(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert r.cache_id > 0

    def test_error_empty_on_success(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert r.error == ""


# ---------------------------------------------------------------------------
# save_word_analysis — second call (update)
# ---------------------------------------------------------------------------

class TestSaveWordAnalysisUpdate:
    def test_second_call_not_created(self, db: DatabaseConnection, sid: int):
        save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        r2 = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert r2.card_created is False

    def test_second_call_same_card_id(self, db: DatabaseConnection, sid: int):
        r1 = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        r2 = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        assert r1.card_id == r2.card_id

    def test_occurrence_count_increments(self, db: DatabaseConnection, sid: int):
        r1 = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT occurrence_count FROM word_cards WHERE id = ?", (r1.card_id,)
            ).fetchone()
        assert row["occurrence_count"] == 2


# ---------------------------------------------------------------------------
# save_word_analysis — error paths
# ---------------------------------------------------------------------------

class TestSaveWordAnalysisErrors:
    def test_empty_surface_form_raises(self, db: DatabaseConnection, sid: int):
        with pytest.raises(ValueError, match="surface_form"):
            save_word_analysis(db, sid, "", _VALID_WORD_JSON)

    def test_whitespace_only_surface_form_raises(self, db: DatabaseConnection, sid: int):
        with pytest.raises(ValueError, match="surface_form"):
            save_word_analysis(db, sid, "   ", _VALID_WORD_JSON)

    def test_sentence_not_found_raises(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="not found"):
            save_word_analysis(db, 999_999, "fox", _VALID_WORD_JSON)

    def test_invalid_json_is_valid_false(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _INVALID_JSON_STR)
        assert r.is_valid is False

    def test_invalid_json_no_card_created(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _INVALID_JSON_STR)
        assert r.card_id is None
        assert r.card_created is False

    def test_invalid_json_saves_cache(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _INVALID_JSON_STR)
        assert r.cache_id > 0

    def test_invalid_json_error_populated(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _INVALID_JSON_STR)
        assert len(r.error) > 0

    def test_cache_marked_invalid_on_bad_json(self, db: DatabaseConnection, sid: int):
        r = save_word_analysis(db, sid, "fox", _INVALID_JSON_STR)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (r.cache_id,)
            ).fetchone()
        assert row["is_valid"] == 0


# ---------------------------------------------------------------------------
# Different surface forms for same sentence → separate cache entries
# ---------------------------------------------------------------------------

class TestMultipleWordsOneSentence:
    def test_two_words_create_two_cache_entries(self, db: DatabaseConnection, sid: int):
        r1 = save_word_analysis(db, sid, "fox", _VALID_WORD_JSON)
        dog_json = json.dumps({
            "lemma": "dog",
            "lexical_type": "word",
            "pos": "noun",
            "meaning_in_context": "a domestic animal",
            "common_collocations": ["hot dog", "dog walk"],
            "near_synonyms": ["hound"],
            "confusable_with": [],
            "morphology": {"root": "", "family": ["doggy"]},
            "predicted_error_types": ["L01"],
            "confidence": 0.8,
        })
        r2 = save_word_analysis(db, sid, "dog", dog_json)
        assert r1.cache_id != r2.cache_id
        assert r1.card_id != r2.card_id
