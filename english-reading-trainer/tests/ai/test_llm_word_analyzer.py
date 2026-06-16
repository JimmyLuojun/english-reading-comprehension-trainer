"""
Tests for app/ai/llm_word_analyzer.py.

Mirrors test_llm_sentence_analyzer.py structure but uses the word schema.
LLM calls mocked; cache uses real SQLite.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.llm_word_analyzer import WordAnalysisResult, analyze_word
from app.db_connection import DatabaseConnection

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

_VALID_WORD_RESPONSE_V1 = json.dumps({
    "lemma": "mitigate",
    "lexical_type": "word",
    "pos": "verb",
    "meaning_in_context": "to make less severe",
    "common_collocations": ["mitigate risks"],
    "near_synonyms": ["alleviate"],
    "confusable_with": [],
    "morphology": {"root": "mitis", "family": ["mitigation"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
})

_VALID_WORD_RESPONSE = json.dumps({
    "lemma": "mitigate",
    "lexical_type": "word",
    "pos": "verb",
    "meaning_in_context": "to make the harmful effects of something less severe",
    "chinese_meaning": "减轻不良影响",
    "register": "formal",
    "why_this_word": "Mitigate is formal register and targets a specific harm; reduce is vaguer. Writing 'reduce the effects' loses the connotation of purposeful countermeasure.",
    "vs_simpler": [
        {"simpler": "reduce", "difference": "Reduce is neutral; mitigate implies deliberate remediation."},
    ],
    "morphology": {"root": "mitis", "family": ["mitigation"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
})

_VALID_WORD_RESPONSE_V2 = json.dumps({
    "lemma": "mitigate",
    "lexical_type": "word",
    "pos": "verb",
    "meaning_in_context": "to make the harmful effects of something less severe",
    "register": "formal",
    "why_this_word": "Mitigate is formal register and targets a specific harm; reduce is vaguer. Writing 'reduce the effects' loses the connotation of purposeful countermeasure.",
    "vs_simpler": [
        {"simpler": "reduce", "difference": "Reduce is neutral; mitigate implies deliberate remediation."},
    ],
    "morphology": {"root": "mitis", "family": ["mitigation"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
})

_SURFACE = "mitigate"
_SENTENCE = "Governments tried to mitigate the effects of inflation."
_MODEL = "gpt-4o-mini"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


def _mock_llm(return_values: list[str]):
    mock = MagicMock(side_effect=return_values)
    return patch("app.ai.llm_word_analyzer._call_llm", mock)


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------

class TestAnalyzeWordCacheHit:
    def test_served_from_cache_on_second_call(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE]):
            analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        with _mock_llm([]) as mock:
            result = analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        mock.assert_not_called()
        assert result.from_cache is True

    def test_stale_returned_for_different_version(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE_V1]):
            analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL, prompt_version="v1")
        with _mock_llm([]) as mock:
            result = analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL, prompt_version="v2")
        mock.assert_not_called()
        assert result.is_stale is True

    def test_allow_stale_false_ignores_stale_and_calls_llm(
        self, db: DatabaseConnection
    ) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE_V1]):
            analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL, prompt_version="v1")
        with _mock_llm([_VALID_WORD_RESPONSE_V2]) as mock:
            result = analyze_word(
                db, _SURFACE, _SENTENCE, model=_MODEL,
                prompt_version="v2", allow_stale=False,
            )
        mock.assert_called_once()
        assert result.is_stale is False
        assert result.from_cache is False


# ---------------------------------------------------------------------------
# LLM success
# ---------------------------------------------------------------------------

class TestAnalyzeWordLLMSuccess:
    def test_returns_valid_result(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE]):
            result = analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        assert result.is_valid is True
        assert result.from_cache is False
        assert result.data["lemma"] == "mitigate"
        assert result.data["chinese_meaning"] == "减轻不良影响"

    def test_result_saved_to_cache(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE]):
            result = analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        assert result.cache_id > 0

    def test_llm_called_once(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE]) as mock:
            analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        assert mock.call_count == 1


# ---------------------------------------------------------------------------
# Retry on invalid
# ---------------------------------------------------------------------------

class TestAnalyzeWordRetry:
    def test_retries_on_invalid_first_response(self, db: DatabaseConnection) -> None:
        with _mock_llm(["NOT JSON", _VALID_WORD_RESPONSE]) as mock:
            result = analyze_word(db, "claim", "She claimed victory.", model=_MODEL)
        assert mock.call_count == 2
        assert result.is_valid is True

    def test_both_invalid_is_valid_false(self, db: DatabaseConnection) -> None:
        with _mock_llm(["bad", "also bad"]):
            result = analyze_word(db, "argue", "He argued the point.", model=_MODEL)
        assert result.is_valid is False
        assert result.data == {}

    def test_both_invalid_saved_with_is_valid_false(self, db: DatabaseConnection) -> None:
        with _mock_llm(["x", "y"]):
            result = analyze_word(db, "assert", "She asserted.", model=_MODEL)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (result.cache_id,)
            ).fetchone()
        assert row["is_valid"] == 0


# ---------------------------------------------------------------------------
# Content hash includes surface_form
# ---------------------------------------------------------------------------

class TestWordContentHash:
    def test_different_surface_forms_different_cache_entries(
        self, db: DatabaseConnection
    ) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE]):
            r1 = analyze_word(db, "mitigate", _SENTENCE, model=_MODEL)
        with _mock_llm([_VALID_WORD_RESPONSE]):
            r2 = analyze_word(db, "alleviate", _SENTENCE, model=_MODEL)
        assert r1.cache_id != r2.cache_id

    def test_same_surface_form_same_cache(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_WORD_RESPONSE]):
            analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        with _mock_llm([]) as mock:
            analyze_word(db, _SURFACE, _SENTENCE, model=_MODEL)
        mock.assert_not_called()
