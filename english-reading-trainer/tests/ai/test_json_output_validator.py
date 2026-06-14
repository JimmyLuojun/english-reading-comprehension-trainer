"""
Tests for app/ai/json_output_validator.py  — 100% line + branch coverage required.

Covers every public function and every branch:
  _strip_fences: no fence, ```json fence, plain fence, unterminated fence
  parse_and_validate: valid, fenced-valid, bad JSON, schema failure, semantic failure
  _semantic_validate: sentence with main clause, without main clause, non-dict, word schema
"""

import json

import pytest
from jsonschema import ValidationError

from app.ai.ai_json_schemas import SENTENCE_ANALYSIS_SCHEMA, WORD_ANALYSIS_SCHEMA
from app.ai.json_output_validator import (
    _semantic_validate,
    _strip_fences,
    parse_and_validate,
)

# ---------------------------------------------------------------------------
# Minimal valid fixtures
# ---------------------------------------------------------------------------

VALID_SENTENCE_DATA = {
    "subject_skeleton": "The cat sat",
    "clauses": [{"type": "main", "text": "The cat sat", "role": "main"}],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat.",
    "chinese_gloss": "猫坐着。",
    "predicted_error_types": ["G01"],
    "confidence": 0.9,
}

VALID_WORD_DATA = {
    "lemma": "mitigate",
    "lexical_type": "word",
    "pos": "verb",
    "meaning_in_context": "to reduce severity",
    "common_collocations": ["mitigate risks"],
    "near_synonyms": ["alleviate"],
    "confusable_with": [],
    "morphology": {"root": "mitis", "family": ["mitigation"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
}


# ---------------------------------------------------------------------------
# _strip_fences — 100% branch coverage
# ---------------------------------------------------------------------------

class TestStripFences:
    def test_no_fence_returns_text_unchanged(self) -> None:
        text = '{"key": "value"}'
        assert _strip_fences(text) == text

    def test_json_fence_stripped(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = _strip_fences(text)
        assert result == '{"key": "value"}'

    def test_plain_fence_stripped(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = _strip_fences(text)
        assert result == '{"key": "value"}'

    def test_fence_with_leading_whitespace(self) -> None:
        text = '  ```json\n{"a": 1}\n```  '
        result = _strip_fences(text)
        assert result == '{"a": 1}'

    def test_fence_without_closing_backticks(self) -> None:
        # No closing ```: strip opening line only, keep rest
        text = "```json\n{\"key\": \"value\"}"
        result = _strip_fences(text)
        # Should not crash; content after opening line returned
        assert "key" in result

    def test_fence_with_only_backticks_no_content(self) -> None:
        # ``` with no newline after → _strip_fences returns ""
        text = "```"
        result = _strip_fences(text)
        assert result == ""

    def test_plain_json_not_modified(self) -> None:
        text = '{"a": 1, "b": [1, 2]}'
        assert _strip_fences(text) == text

    def test_multiline_json_fence(self) -> None:
        inner = '{\n  "subject_skeleton": "x"\n}'
        text = f"```json\n{inner}\n```"
        assert _strip_fences(text) == inner


# ---------------------------------------------------------------------------
# parse_and_validate — 100% branch coverage
# ---------------------------------------------------------------------------

class TestParseAndValidate:
    def test_valid_sentence_json_string(self) -> None:
        raw = json.dumps(VALID_SENTENCE_DATA)
        result = parse_and_validate(raw, SENTENCE_ANALYSIS_SCHEMA)
        assert result["subject_skeleton"] == "The cat sat"

    def test_valid_sentence_with_json_fence(self) -> None:
        raw = f"```json\n{json.dumps(VALID_SENTENCE_DATA)}\n```"
        result = parse_and_validate(raw, SENTENCE_ANALYSIS_SCHEMA)
        assert "clauses" in result

    def test_valid_word_json(self) -> None:
        raw = json.dumps(VALID_WORD_DATA)
        result = parse_and_validate(raw, WORD_ANALYSIS_SCHEMA)
        assert result["lemma"] == "mitigate"

    def test_invalid_json_raises_json_decode_error(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            parse_and_validate("not valid json at all", SENTENCE_ANALYSIS_SCHEMA)

    def test_schema_violation_raises_validation_error(self) -> None:
        bad = {**VALID_SENTENCE_DATA, "confidence": 2.0}  # > 1.0
        with pytest.raises(ValidationError):
            parse_and_validate(json.dumps(bad), SENTENCE_ANALYSIS_SCHEMA)

    def test_missing_required_field_raises_validation_error(self) -> None:
        bad = {k: v for k, v in VALID_SENTENCE_DATA.items() if k != "chinese_gloss"}
        with pytest.raises(ValidationError):
            parse_and_validate(json.dumps(bad), SENTENCE_ANALYSIS_SCHEMA)

    def test_wrong_error_code_raises_validation_error(self) -> None:
        bad = {**VALID_SENTENCE_DATA, "predicted_error_types": ["Z99"]}
        with pytest.raises(ValidationError):
            parse_and_validate(json.dumps(bad), SENTENCE_ANALYSIS_SCHEMA)

    def test_extra_field_raises_validation_error(self) -> None:
        bad = {**VALID_SENTENCE_DATA, "unexpected": "field"}
        with pytest.raises(ValidationError):
            parse_and_validate(json.dumps(bad), SENTENCE_ANALYSIS_SCHEMA)

    def test_empty_string_raises_json_decode_error(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            parse_and_validate("", SENTENCE_ANALYSIS_SCHEMA)

    def test_null_json_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_and_validate("null", SENTENCE_ANALYSIS_SCHEMA)

    def test_array_json_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_and_validate("[1, 2, 3]", SENTENCE_ANALYSIS_SCHEMA)

    def test_returns_dict(self) -> None:
        result = parse_and_validate(json.dumps(VALID_SENTENCE_DATA), SENTENCE_ANALYSIS_SCHEMA)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _semantic_validate — 100% branch coverage
# ---------------------------------------------------------------------------

class TestSemanticValidate:
    def test_sentence_with_main_clause_passes(self) -> None:
        # Should not raise
        _semantic_validate(VALID_SENTENCE_DATA, SENTENCE_ANALYSIS_SCHEMA)

    def test_sentence_without_main_clause_raises(self) -> None:
        bad = {
            **VALID_SENTENCE_DATA,
            "clauses": [{"type": "relative", "text": "which he bought", "role": "modifier"}],
        }
        with pytest.raises(ValidationError, match="main"):
            _semantic_validate(bad, SENTENCE_ANALYSIS_SCHEMA)

    def test_non_dict_data_skipped_silently(self) -> None:
        # Should not raise — non-dict is allowed to pass through semantic check
        _semantic_validate([1, 2, 3], SENTENCE_ANALYSIS_SCHEMA)
        _semantic_validate("a string", SENTENCE_ANALYSIS_SCHEMA)
        _semantic_validate(None, SENTENCE_ANALYSIS_SCHEMA)

    def test_word_data_no_clauses_key_passes(self) -> None:
        # Word schema has no 'clauses' field — semantic check should be a no-op
        _semantic_validate(VALID_WORD_DATA, WORD_ANALYSIS_SCHEMA)

    def test_dict_without_clauses_key_passes(self) -> None:
        # Dict that has subject_skeleton but no clauses (edge case)
        _semantic_validate({"subject_skeleton": "x"}, SENTENCE_ANALYSIS_SCHEMA)

    def test_clauses_with_non_dict_items_raises(self) -> None:
        # If clauses contains non-dict items, no main clause found → raises
        bad = {**VALID_SENTENCE_DATA, "clauses": ["not a dict"]}
        with pytest.raises(ValidationError, match="main"):
            _semantic_validate(bad, SENTENCE_ANALYSIS_SCHEMA)

    def test_multiple_clause_types_with_one_main_passes(self) -> None:
        data = {
            **VALID_SENTENCE_DATA,
            "clauses": [
                {"type": "relative", "text": "which...", "role": "mod"},
                {"type": "main", "text": "He left", "role": "main"},
            ],
        }
        _semantic_validate(data, SENTENCE_ANALYSIS_SCHEMA)
