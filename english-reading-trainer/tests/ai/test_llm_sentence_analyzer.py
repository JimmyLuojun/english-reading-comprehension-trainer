"""
Tests for app/ai/llm_sentence_analyzer.py.

LLM calls are mocked via unittest.mock.patch.
Cache uses real SQLite (tmp_path).

Covers: cache hit, cache miss → LLM success, invalid JSON → retry → success,
invalid JSON → retry → invalid → is_valid=False, prompt loading,
variable rendering, RuntimeError from LLM, missing prompt file.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.llm_sentence_analyzer import (
    _load_prompt,
    _render,
    _strip_frontmatter,
    analyze_sentence,
)
from app.db_connection import DatabaseConnection

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

_VALID_RESPONSE_V1 = json.dumps({
    "subject_skeleton": "The cat sat",
    "clauses": [{"type": "main", "text": "The cat sat", "role": "main pred"}],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat.",
    "chinese_gloss": "猫坐着。",
    "predicted_error_types": ["G01"],
    "diagnosis_basis": "predicted",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [],
    "confidence": 0.9,
})

_VALID_RESPONSE = json.dumps({
    "subject_skeleton": "The cat sat",
    "clauses": [{"type": "main", "text": "The cat sat", "role": "main pred"}],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat.",
    "chinese_gloss": "猫坐着。",
    "blocking_point": "The main verb is simple, but the prepositional phrase can be missed.",
    "predicted_error_types": ["G01"],
    "diagnosis_basis": "predicted",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [],
    "takeaway_suggestion": "遇到介词短语，先检查它补充哪个动作，否则易犯 G01。",
    "confidence": 0.9,
})

_VALID_DIAGNOSED_RESPONSE = json.dumps({
    "subject_skeleton": "The cat sat",
    "clauses": [{"type": "main", "text": "The cat sat", "role": "main pred"}],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat.",
    "chinese_gloss": "猫坐着。",
    "blocking_point": "The translation misses the modifier attached to the main clause.",
    "predicted_error_types": [],
    "diagnosis_basis": "user_translation",
    "diagnosed_error_types": ["G02"],
    "diagnosis_evidence": [
        {"error_type": "G02", "evidence": "The translation misses the modifier."}
    ],
    "takeaway_suggestion": "遇到修饰成分，先检查它修饰哪个词，否则易犯 G02。",
    "confidence": 0.9,
})

_VALID_STRUCTURE_FEEDBACK = {
    "is_correct": False,
    "missed_or_wrong": [
        {
            "error_code": "G02",
            "learner_claim": "The modifier attaches to the board.",
            "correction": "The modifier attaches to the report.",
            "reason": "The modifier follows report and describes it.",
        }
    ],
    "correct_highlights": [],
    "corrected_structure": "The report was dismissed; the relative clause modifies report.",
    "why_it_matters_for_translation": "Wrong attachment changes the Chinese subject-object relation.",
    "next_check": "Attach post-noun modifiers before translating the main action.",
}

_VALID_STRUCTURE_RESPONSE = json.dumps({
    **json.loads(_VALID_RESPONSE),
    "structure_feedback": _VALID_STRUCTURE_FEEDBACK,
})

_VALID_DIAGNOSED_STRUCTURE_RESPONSE = json.dumps({
    **json.loads(_VALID_DIAGNOSED_RESPONSE),
    "structure_feedback": _VALID_STRUCTURE_FEEDBACK,
})

_SENTENCE = "The cat sat on the mat."
_MODEL = "gpt-4o-mini"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


def _mock_llm(return_values: list[str]):
    """Return a mock that yields successive values on each call."""
    mock = MagicMock(side_effect=return_values)
    return patch("app.ai.llm_sentence_analyzer._call_llm", mock)


# ---------------------------------------------------------------------------
# Unit: _strip_frontmatter
# ---------------------------------------------------------------------------

class TestStripFrontmatter:
    def test_strips_frontmatter(self) -> None:
        text = "---\nname: test\n---\n\nActual content here."
        assert _strip_frontmatter(text) == "Actual content here."

    def test_no_frontmatter_unchanged(self) -> None:
        text = "Just content."
        assert _strip_frontmatter(text) == "Just content."

    def test_missing_closing_dashes_returns_original(self) -> None:
        text = "---\nno closing"
        assert _strip_frontmatter(text) == text


# ---------------------------------------------------------------------------
# Unit: _render
# ---------------------------------------------------------------------------

class TestRender:
    def test_replaces_single_variable(self) -> None:
        result = _render("Hello {{ name }}!", {"name": "World"})
        assert result == "Hello World!"

    def test_replaces_multiple_variables(self) -> None:
        result = _render("{{ a }} and {{ b }}", {"a": "X", "b": "Y"})
        assert result == "X and Y"

    def test_missing_variable_left_as_is(self) -> None:
        result = _render("{{ missing }} stays", {})
        assert "{{ missing }}" in result

    def test_empty_variables_dict(self) -> None:
        template = "No vars here."
        assert _render(template, {}) == template


def test_both_sentence_prompt_v6_files_load() -> None:
    assert "USER STRUCTURE ATTEMPT" in _load_prompt("sentence_analysis_predict", "v6")
    assert "USER STRUCTURE ATTEMPT" in _load_prompt("sentence_analysis_diagnose", "v6")
    assert "correct_highlights" in _load_prompt("sentence_analysis_predict", "v6")
    assert "correct_highlights" in _load_prompt("sentence_analysis_diagnose", "v6")


def test_both_sentence_prompt_v5_files_remain_loadable() -> None:
    assert "USER STRUCTURE ATTEMPT" in _load_prompt("sentence_analysis_predict", "v5")
    assert "USER STRUCTURE ATTEMPT" in _load_prompt("sentence_analysis_diagnose", "v5")


def test_analyze_sentence_defaults_to_sentence_model(
    db: DatabaseConnection,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("TRAINER_SENTENCE_MODEL", raising=False)
    monkeypatch.delenv("TRAINER_PRO_MODEL", raising=False)
    monkeypatch.setattr(
        "app.ai.ai_provider_config._DEFAULT_ENV_FILE",
        tmp_path / "missing.env",
    )

    with _mock_llm([_VALID_RESPONSE]) as mock:
        analyze_sentence(db, _SENTENCE)

    assert mock.call_args.args[1] == "deepseek-v4-pro"


# ---------------------------------------------------------------------------
# analyze_sentence — cache hit
# ---------------------------------------------------------------------------

class TestAnalyzeSentenceCacheHit:
    def test_returns_from_cache_without_llm_call(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE]):
            # Populate cache
            analyze_sentence(db, _SENTENCE, model=_MODEL)
        # Second call: should be served from cache
        with _mock_llm([]) as mock:
            result = analyze_sentence(db, _SENTENCE, model=_MODEL)
        mock.assert_not_called()
        assert result.from_cache is True

    def test_cache_hit_result_is_valid(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE]):
            analyze_sentence(db, _SENTENCE, model=_MODEL)
        result = analyze_sentence(db, _SENTENCE, model=_MODEL)
        assert result.is_valid is True

    def test_cache_hit_data_contains_subject_skeleton(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE]):
            analyze_sentence(db, _SENTENCE, model=_MODEL)
        result = analyze_sentence(db, _SENTENCE, model=_MODEL)
        assert "subject_skeleton" in result.data

    def test_force_refresh_ignores_exact_cache_and_replaces_it(
        self,
        db: DatabaseConnection,
    ) -> None:
        refreshed_response = _VALID_RESPONSE.replace("The cat sat", "The dog ran")
        with _mock_llm([_VALID_RESPONSE]):
            first = analyze_sentence(db, _SENTENCE, model=_MODEL)

        with _mock_llm([refreshed_response]) as mock:
            refreshed = analyze_sentence(
                db,
                _SENTENCE,
                model=_MODEL,
                force_refresh=True,
            )

        mock.assert_called_once()
        assert refreshed.cache_id == first.cache_id
        assert refreshed.from_cache is False
        assert refreshed.data["subject_skeleton"] == "The dog ran"
        cached = analyze_sentence(db, _SENTENCE, model=_MODEL)
        assert cached.from_cache is True
        assert cached.data["subject_skeleton"] == "The dog ran"

    def test_stale_cache_flagged(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE_V1]):
            analyze_sentence(db, _SENTENCE, model=_MODEL, prompt_version="v1")
        # Request v2: should get stale v1 back
        with _mock_llm([]) as mock:
            result = analyze_sentence(db, _SENTENCE, model=_MODEL, prompt_version="v2")
        mock.assert_not_called()
        assert result.is_stale is True


# ---------------------------------------------------------------------------
# analyze_sentence — cache miss, LLM success
# ---------------------------------------------------------------------------

class TestAnalyzeSentenceLLMSuccess:
    def test_returns_result_with_data(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE]):
            result = analyze_sentence(db, _SENTENCE, model=_MODEL)
        assert result.is_valid is True
        assert result.from_cache is False
        assert "subject_skeleton" in result.data

    def test_result_saved_to_cache(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE]):
            result = analyze_sentence(db, _SENTENCE, model=_MODEL)
        assert result.cache_id > 0
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (result.cache_id,)
            ).fetchone()
        assert row["is_valid"] == 1

    def test_llm_called_once_on_first_attempt_success(self, db: DatabaseConnection) -> None:
        with _mock_llm([_VALID_RESPONSE]) as mock:
            analyze_sentence(db, _SENTENCE, model=_MODEL)
        assert mock.call_count == 1

    def test_user_translation_uses_diagnosis_prompt(
        self, db: DatabaseConnection
    ) -> None:
        with _mock_llm([_VALID_DIAGNOSED_RESPONSE]) as mock:
            result = analyze_sentence(
                db,
                _SENTENCE,
                user_translation="猫坐在垫子上。",
                model=_MODEL,
            )

        assert result.data["diagnosis_basis"] == "user_translation"
        assert "USER TRANSLATION" in mock.call_args.args[0]

    def test_user_structure_without_translation_uses_predict_prompt(
        self, db: DatabaseConnection
    ) -> None:
        with _mock_llm([_VALID_STRUCTURE_RESPONSE]) as mock:
            result = analyze_sentence(
                db,
                _SENTENCE,
                user_structure="主干：The cat sat",
                model=_MODEL,
            )

        assert result.data["diagnosis_basis"] == "predicted"
        assert result.data["structure_feedback"]["missed_or_wrong"][0]["error_code"] == "G02"
        prompt = mock.call_args.args[0]
        assert "USER STRUCTURE ATTEMPT" in prompt
        assert "主干：The cat sat" in prompt
        assert "USER TRANSLATION" not in prompt

    def test_user_structure_with_translation_uses_diagnosis_prompt(
        self, db: DatabaseConnection
    ) -> None:
        with _mock_llm([_VALID_DIAGNOSED_STRUCTURE_RESPONSE]) as mock:
            result = analyze_sentence(
                db,
                _SENTENCE,
                user_translation="猫坐着。",
                user_structure="主干：The cat sat",
                model=_MODEL,
            )

        assert result.data["diagnosis_basis"] == "user_translation"
        assert "structure_feedback" in result.data
        prompt = mock.call_args.args[0]
        assert "USER TRANSLATION" in prompt
        assert "USER STRUCTURE ATTEMPT" in prompt

        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT input_translation, input_structure
                   FROM ai_cache
                   WHERE id = ?""",
                (result.cache_id,),
            ).fetchone()
        assert row["input_translation"] == "猫坐着。"
        assert row["input_structure"] == "主干：The cat sat"

    @pytest.mark.parametrize("translation", [None, "猫坐着。"])
    def test_no_structure_response_valid_without_structure_feedback(
        self,
        db: DatabaseConnection,
        translation: str | None,
    ) -> None:
        response = _VALID_DIAGNOSED_RESPONSE if translation else _VALID_RESPONSE
        with _mock_llm([response]):
            result = analyze_sentence(
                db,
                f"{_SENTENCE} {translation or 'predict'}",
                user_translation=translation,
                model=_MODEL,
            )

        assert result.is_valid is True
        assert "structure_feedback" not in result.data

    def test_different_translations_do_not_share_cache(
        self, db: DatabaseConnection
    ) -> None:
        with _mock_llm([_VALID_DIAGNOSED_RESPONSE]):
            first = analyze_sentence(
                db,
                _SENTENCE,
                user_translation="译文一。",
                model=_MODEL,
            )
        with _mock_llm([_VALID_DIAGNOSED_RESPONSE]):
            second = analyze_sentence(
                db,
                _SENTENCE,
                user_translation="译文二。",
                model=_MODEL,
            )

        assert second.from_cache is False
        assert second.cache_id != first.cache_id


# ---------------------------------------------------------------------------
# analyze_sentence — invalid JSON → retry → success
# ---------------------------------------------------------------------------

class TestAnalyzeSentenceRetrySuccess:
    def test_retry_on_invalid_first_response(self, db: DatabaseConnection) -> None:
        with _mock_llm(["NOT VALID JSON", _VALID_RESPONSE]) as mock:
            result = analyze_sentence(db, "Another sentence here.", model=_MODEL)
        assert mock.call_count == 2
        assert result.is_valid is True

    def test_retry_result_saved_valid(self, db: DatabaseConnection) -> None:
        with _mock_llm(["not json", _VALID_RESPONSE]):
            result = analyze_sentence(db, "Retry valid sentence.", model=_MODEL)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (result.cache_id,)
            ).fetchone()
        assert row["is_valid"] == 1


# ---------------------------------------------------------------------------
# analyze_sentence — both attempts invalid
# ---------------------------------------------------------------------------

class TestAnalyzeSentenceBothInvalid:
    def test_is_valid_false_when_both_fail(self, db: DatabaseConnection) -> None:
        with _mock_llm(["bad", "also bad"]):
            result = analyze_sentence(db, "Doubly invalid sentence.", model=_MODEL)
        assert result.is_valid is False

    def test_data_is_empty_when_both_fail(self, db: DatabaseConnection) -> None:
        with _mock_llm(["bad", "also bad"]):
            result = analyze_sentence(db, "Empty data sentence.", model=_MODEL)
        assert result.data == {}

    def test_saved_with_is_valid_false(self, db: DatabaseConnection) -> None:
        with _mock_llm(["bad1", "bad2"]):
            result = analyze_sentence(db, "Invalid saved sentence.", model=_MODEL)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (result.cache_id,)
            ).fetchone()
        assert row["is_valid"] == 0

    def test_llm_called_twice(self, db: DatabaseConnection) -> None:
        with _mock_llm(["x", "y"]) as mock:
            analyze_sentence(db, "Two calls sentence.", model=_MODEL)
        assert mock.call_count == 2
