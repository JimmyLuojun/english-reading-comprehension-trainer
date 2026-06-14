"""
Tests for app/ai/ai_json_schemas.py.

Validates that the schemas themselves are structurally correct and contain
the expected fields, constraints, and closed enumerations.
"""

import pytest
import jsonschema

from app.ai.ai_json_schemas import SENTENCE_ANALYSIS_SCHEMA, WORD_ANALYSIS_SCHEMA
from app.db_models import VALID_ERROR_CODES


# ---------------------------------------------------------------------------
# Minimal valid fixtures
# ---------------------------------------------------------------------------

VALID_SENTENCE = {
    "subject_skeleton": "The report was dismissed",
    "clauses": [
        {"type": "main", "text": "The report was dismissed", "role": "main predication"}
    ],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The board dismissed the report.",
    "chinese_gloss": "委员会的报告被董事会否决了。",
    "predicted_error_types": ["G02"],
    "confidence": 0.9,
}

VALID_WORD = {
    "lemma": "mitigate",
    "lexical_type": "word",
    "pos": "verb",
    "meaning_in_context": "to make less severe",
    "common_collocations": ["mitigate risks"],
    "near_synonyms": ["alleviate"],
    "confusable_with": ["militate"],
    "morphology": {"root": "mitis", "family": ["mitigation"]},
    "predicted_error_types": ["L01"],
    "confidence": 0.95,
}


def _validate(instance, schema):
    jsonschema.validate(instance=instance, schema=schema)


# ---------------------------------------------------------------------------
# Schema self-consistency
# ---------------------------------------------------------------------------

class TestSchemaStructure:
    def test_sentence_schema_is_dict(self) -> None:
        assert isinstance(SENTENCE_ANALYSIS_SCHEMA, dict)

    def test_word_schema_is_dict(self) -> None:
        assert isinstance(WORD_ANALYSIS_SCHEMA, dict)

    def test_both_schemas_are_object_type(self) -> None:
        assert SENTENCE_ANALYSIS_SCHEMA["type"] == "object"
        assert WORD_ANALYSIS_SCHEMA["type"] == "object"

    def test_sentence_schema_has_all_required_fields(self) -> None:
        required = SENTENCE_ANALYSIS_SCHEMA["required"]
        for field in ["subject_skeleton", "clauses", "modifiers", "logic_markers",
                      "anaphora", "simplified_en", "chinese_gloss",
                      "predicted_error_types", "confidence"]:
            assert field in required

    def test_word_schema_has_all_required_fields(self) -> None:
        required = WORD_ANALYSIS_SCHEMA["required"]
        for field in ["lemma", "lexical_type", "pos", "meaning_in_context",
                      "common_collocations", "near_synonyms", "confusable_with",
                      "morphology", "predicted_error_types", "confidence"]:
            assert field in required

    def test_error_codes_in_sentence_schema_match_db(self) -> None:
        enum = set(
            SENTENCE_ANALYSIS_SCHEMA["properties"]["predicted_error_types"]["items"]["enum"]
        )
        assert enum == VALID_ERROR_CODES

    def test_error_codes_in_word_schema_match_db(self) -> None:
        enum = set(
            WORD_ANALYSIS_SCHEMA["properties"]["predicted_error_types"]["items"]["enum"]
        )
        assert enum == VALID_ERROR_CODES

    def test_sentence_schema_confidence_range(self) -> None:
        conf = SENTENCE_ANALYSIS_SCHEMA["properties"]["confidence"]
        assert conf["minimum"] == 0.0
        assert conf["maximum"] == 1.0

    def test_word_schema_lexical_type_enum(self) -> None:
        enum = WORD_ANALYSIS_SCHEMA["properties"]["lexical_type"]["enum"]
        assert set(enum) == {"word", "phrase", "collocation"}

    def test_sentence_clause_type_enum(self) -> None:
        enum = (SENTENCE_ANALYSIS_SCHEMA["properties"]["clauses"]
                ["items"]["properties"]["type"]["enum"])
        assert set(enum) == {"main", "relative", "noun", "adverbial"}


# ---------------------------------------------------------------------------
# Valid instance acceptance
# ---------------------------------------------------------------------------

class TestValidInstances:
    def test_valid_sentence_passes(self) -> None:
        _validate(VALID_SENTENCE, SENTENCE_ANALYSIS_SCHEMA)

    def test_valid_word_passes(self) -> None:
        _validate(VALID_WORD, WORD_ANALYSIS_SCHEMA)

    def test_sentence_with_multiple_clauses(self) -> None:
        data = {**VALID_SENTENCE, "clauses": [
            {"type": "main", "text": "He left", "role": "main"},
            {"type": "adverbial", "text": "when she arrived", "role": "time"},
        ]}
        _validate(data, SENTENCE_ANALYSIS_SCHEMA)

    def test_sentence_with_multiple_error_codes(self) -> None:
        data = {**VALID_SENTENCE, "predicted_error_types": ["G01", "D01"]}
        _validate(data, SENTENCE_ANALYSIS_SCHEMA)

    def test_sentence_max_three_error_codes(self) -> None:
        data = {**VALID_SENTENCE, "predicted_error_types": ["G01", "L01", "D01"]}
        _validate(data, SENTENCE_ANALYSIS_SCHEMA)

    def test_word_empty_optional_lists(self) -> None:
        data = {**VALID_WORD,
                "near_synonyms": [], "confusable_with": [],
                "morphology": {"root": "", "family": []}}
        _validate(data, WORD_ANALYSIS_SCHEMA)

    def test_confidence_boundary_zero(self) -> None:
        _validate({**VALID_SENTENCE, "confidence": 0.0}, SENTENCE_ANALYSIS_SCHEMA)

    def test_confidence_boundary_one(self) -> None:
        _validate({**VALID_SENTENCE, "confidence": 1.0}, SENTENCE_ANALYSIS_SCHEMA)


# ---------------------------------------------------------------------------
# Invalid instance rejection
# ---------------------------------------------------------------------------

class TestInvalidInstances:
    def test_missing_subject_skeleton(self) -> None:
        data = {k: v for k, v in VALID_SENTENCE.items() if k != "subject_skeleton"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(data, SENTENCE_ANALYSIS_SCHEMA)

    def test_empty_clauses_array(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_SENTENCE, "clauses": []}, SENTENCE_ANALYSIS_SCHEMA)

    def test_invalid_clause_type(self) -> None:
        bad = {**VALID_SENTENCE, "clauses": [
            {"type": "invalid_type", "text": "x", "role": "y"}
        ]}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, SENTENCE_ANALYSIS_SCHEMA)

    def test_invalid_error_code(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(
                {**VALID_SENTENCE, "predicted_error_types": ["Z99"]},
                SENTENCE_ANALYSIS_SCHEMA,
            )

    def test_too_many_error_codes_sentence(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(
                {**VALID_SENTENCE, "predicted_error_types": ["G01", "G02", "L01", "D01"]},
                SENTENCE_ANALYSIS_SCHEMA,
            )

    def test_empty_error_types(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(
                {**VALID_SENTENCE, "predicted_error_types": []},
                SENTENCE_ANALYSIS_SCHEMA,
            )

    def test_confidence_above_one(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_SENTENCE, "confidence": 1.1}, SENTENCE_ANALYSIS_SCHEMA)

    def test_confidence_below_zero(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_SENTENCE, "confidence": -0.1}, SENTENCE_ANALYSIS_SCHEMA)

    def test_extra_field_rejected_sentence(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_SENTENCE, "extra_field": "oops"}, SENTENCE_ANALYSIS_SCHEMA)

    def test_extra_field_rejected_word(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_WORD, "surprise": True}, WORD_ANALYSIS_SCHEMA)

    def test_invalid_lexical_type(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_WORD, "lexical_type": "idiom"}, WORD_ANALYSIS_SCHEMA)

    def test_too_many_error_codes_word(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(
                {**VALID_WORD, "predicted_error_types": ["L01", "L02", "L03"]},
                WORD_ANALYSIS_SCHEMA,
            )

    def test_missing_morphology_root(self) -> None:
        bad = {**VALID_WORD, "morphology": {"family": []}}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA)
