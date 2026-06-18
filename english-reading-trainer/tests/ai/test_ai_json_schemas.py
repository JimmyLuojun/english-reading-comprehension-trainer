"""
Tests for app/ai/ai_json_schemas.py.

Validates that the schemas themselves are structurally correct and contain
the expected fields, constraints, and closed enumerations.
"""

import pytest
import jsonschema

from app.ai.ai_json_schemas import (
    SENTENCE_ANALYSIS_SCHEMA,
    SENTENCE_ANALYSIS_SCHEMA_V2,
    WORD_ANALYSIS_SCHEMA,
    WORD_ANALYSIS_SCHEMA_V2,
    WORD_ANALYSIS_SCHEMA_V3,
    WORD_ANALYSIS_SCHEMA_V4,
    WORD_ANALYSIS_SCHEMA_V5,
)
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
    "diagnosis_basis": "predicted",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [],
    "confidence": 0.9,
}

VALID_DIAGNOSED_SENTENCE = {
    **VALID_SENTENCE,
    "predicted_error_types": [],
    "diagnosis_basis": "user_translation",
    "diagnosed_error_types": ["G02"],
    "diagnosis_evidence": [
        {
            "error_type": "G02",
            "evidence": "The translation attaches the modifier to the wrong noun.",
        }
    ],
}

VALID_SENTENCE_V2 = {
    **VALID_SENTENCE,
    "blocking_point": "The relative clause can be mistaken for a main action.",
    "takeaway_suggestion": "遇到名词后的从句，先检查它修饰哪个名词，否则易犯 G02。",
}

VALID_DIAGNOSED_SENTENCE_V2 = {
    **VALID_DIAGNOSED_SENTENCE,
    "blocking_point": "The translation attaches the modifier to the wrong noun.",
    "takeaway_suggestion": "遇到名词后的从句，先检查它修饰哪个名词，否则易犯 G02。",
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

VALID_WORD_V2 = {
    "lemma": "mitigate",
    "lexical_type": "word",
    "pos": "verb",
    "meaning_in_context": "to make the harmful effects of something less severe",
    "register": "formal",
    "why_this_word": "Mitigate is formal register and implies targeted action on a specific harmful effect. Reduce would be vaguer and lacks the connotation of deliberate countermeasure. Writing 'reduce the effects' would lose the sense of purposeful intervention.",
    "vs_simpler": [
        {"simpler": "reduce", "difference": "Reduce is neutral and general; mitigate implies intentional action to counteract a specific harm."},
        {"simpler": "lessen", "difference": "Lessen describes magnitude only; mitigate carries connotations of professional or policy-driven remediation."},
    ],
    "morphology": {"root": "mitis (Latin: soft, mild)", "family": ["mitigation", "mitigating", "unmitigated"]},
    "predicted_error_types": ["L02", "L04"],
    "confidence": 0.95,
}

VALID_WORD_V3 = {
    **VALID_WORD_V2,
    "chinese_meaning": "减轻不良影响",
}

VALID_WORD_V4 = {
    **VALID_WORD_V3,
    "learner_note_check": {
        "status": "correct",
        "feedback": "你的理解正确。",
        "corrected_understanding": "",
    },
}

VALID_WORD_V5 = {
    **VALID_WORD_V4,
    "role_in_sentence": (
        "It functions as the main verb and explains how the policy changes the risk. "
        "If read as a noun, the whole causal relation becomes unclear."
    ),
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
                      "predicted_error_types", "diagnosis_basis",
                      "diagnosed_error_types", "diagnosis_evidence", "confidence"]:
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

    def test_diagnosed_error_codes_in_sentence_schema_match_db(self) -> None:
        enum = set(
            SENTENCE_ANALYSIS_SCHEMA["properties"]["diagnosed_error_types"]["items"]["enum"]
        )
        assert enum == VALID_ERROR_CODES

    def test_diagnosis_evidence_allows_ok_signal(self) -> None:
        enum = set(
            SENTENCE_ANALYSIS_SCHEMA["properties"]["diagnosis_evidence"]
            ["items"]["properties"]["error_type"]["enum"]
        )
        assert enum == VALID_ERROR_CODES | {"OK"}

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

    def test_diagnosed_sentence_with_evidence(self) -> None:
        _validate(VALID_DIAGNOSED_SENTENCE, SENTENCE_ANALYSIS_SCHEMA)

    def test_correct_translation_uses_ok_evidence(self) -> None:
        data = {
            **VALID_DIAGNOSED_SENTENCE,
            "diagnosed_error_types": [],
            "diagnosis_evidence": [
                {"error_type": "OK", "evidence": "The translation preserves the meaning."}
            ],
        }
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

    def test_predicted_mode_rejects_diagnosed_error_types(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(
                {**VALID_SENTENCE, "diagnosed_error_types": ["G02"]},
                SENTENCE_ANALYSIS_SCHEMA,
            )

    def test_diagnosis_evidence_requires_known_code_or_ok(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(
                {
                    **VALID_DIAGNOSED_SENTENCE,
                    "diagnosis_evidence": [
                        {"error_type": "Z99", "evidence": "bad"}
                    ],
                },
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


# ---------------------------------------------------------------------------
# SENTENCE_ANALYSIS_SCHEMA_V2
# ---------------------------------------------------------------------------

class TestSentenceSchemaV2Structure:
    def test_v2_schema_is_dict(self) -> None:
        assert isinstance(SENTENCE_ANALYSIS_SCHEMA_V2, dict)

    def test_v2_required_fields(self) -> None:
        required = SENTENCE_ANALYSIS_SCHEMA_V2["required"]
        for field in ["blocking_point", "takeaway_suggestion"]:
            assert field in required
            assert field in SENTENCE_ANALYSIS_SCHEMA_V2["properties"]

    def test_v2_preserves_v1_fields(self) -> None:
        required = SENTENCE_ANALYSIS_SCHEMA_V2["required"]
        for field in ["subject_skeleton", "clauses", "diagnosis_basis"]:
            assert field in required


class TestSentenceSchemaV2ValidInstances:
    def test_valid_v2_predicted_sentence_passes(self) -> None:
        _validate(VALID_SENTENCE_V2, SENTENCE_ANALYSIS_SCHEMA_V2)

    def test_valid_v2_diagnosed_sentence_passes(self) -> None:
        _validate(VALID_DIAGNOSED_SENTENCE_V2, SENTENCE_ANALYSIS_SCHEMA_V2)


class TestSentenceSchemaV2InvalidInstances:
    def test_v1_sentence_rejected_by_v2_schema(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(VALID_SENTENCE, SENTENCE_ANALYSIS_SCHEMA_V2)

    def test_missing_takeaway_suggestion_rejected(self) -> None:
        bad = {k: v for k, v in VALID_SENTENCE_V2.items() if k != "takeaway_suggestion"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, SENTENCE_ANALYSIS_SCHEMA_V2)

    def test_extra_field_rejected_by_v2_schema(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_SENTENCE_V2, "extra_field": "oops"}, SENTENCE_ANALYSIS_SCHEMA_V2)


# ---------------------------------------------------------------------------
# WORD_ANALYSIS_SCHEMA_V2
# ---------------------------------------------------------------------------

class TestWordSchemaV2Structure:
    def test_v2_schema_is_dict(self) -> None:
        assert isinstance(WORD_ANALYSIS_SCHEMA_V2, dict)

    def test_v2_required_fields(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V2["required"]
        for field in ["lemma", "lexical_type", "pos", "meaning_in_context",
                      "register", "why_this_word", "vs_simpler",
                      "morphology", "predicted_error_types", "confidence"]:
            assert field in required

    def test_v2_no_v1_fields(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V2["required"]
        for old_field in ["common_collocations", "near_synonyms", "confusable_with"]:
            assert old_field not in required
        assert "common_collocations" not in WORD_ANALYSIS_SCHEMA_V2["properties"]

    def test_v2_register_enum(self) -> None:
        enum = set(WORD_ANALYSIS_SCHEMA_V2["properties"]["register"]["enum"])
        assert enum == {"academic", "formal", "literary", "neutral", "colloquial", "technical"}

    def test_v2_error_codes_match_db(self) -> None:
        enum = set(
            WORD_ANALYSIS_SCHEMA_V2["properties"]["predicted_error_types"]["items"]["enum"]
        )
        assert enum == VALID_ERROR_CODES

    def test_v2_vs_simpler_item_schema(self) -> None:
        item_props = (WORD_ANALYSIS_SCHEMA_V2["properties"]["vs_simpler"]
                      ["items"]["properties"])
        assert "simpler" in item_props
        assert "difference" in item_props


class TestWordSchemaV2ValidInstances:
    def test_valid_v2_word_passes(self) -> None:
        _validate(VALID_WORD_V2, WORD_ANALYSIS_SCHEMA_V2)

    def test_empty_vs_simpler_passes(self) -> None:
        _validate({**VALID_WORD_V2, "vs_simpler": []}, WORD_ANALYSIS_SCHEMA_V2)

    def test_multiple_vs_simpler_entries(self) -> None:
        data = {**VALID_WORD_V2, "vs_simpler": [
            {"simpler": "reduce", "difference": "more general"},
            {"simpler": "lessen", "difference": "magnitude only"},
            {"simpler": "lower", "difference": "informal"},
        ]}
        _validate(data, WORD_ANALYSIS_SCHEMA_V2)

    def test_all_register_values_accepted(self) -> None:
        for reg in ["academic", "formal", "literary", "neutral", "colloquial", "technical"]:
            _validate({**VALID_WORD_V2, "register": reg}, WORD_ANALYSIS_SCHEMA_V2)


class TestWordSchemaV2InvalidInstances:
    def test_v1_fields_rejected(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_WORD_V2, "common_collocations": ["x"]}, WORD_ANALYSIS_SCHEMA_V2)

    def test_missing_register_rejected(self) -> None:
        bad = {k: v for k, v in VALID_WORD_V2.items() if k != "register"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA_V2)

    def test_invalid_register_value_rejected(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate({**VALID_WORD_V2, "register": "slang"}, WORD_ANALYSIS_SCHEMA_V2)

    def test_missing_why_this_word_rejected(self) -> None:
        bad = {k: v for k, v in VALID_WORD_V2.items() if k != "why_this_word"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA_V2)

    def test_vs_simpler_extra_field_rejected(self) -> None:
        bad = {**VALID_WORD_V2, "vs_simpler": [
            {"simpler": "reduce", "difference": "more general", "surprise": True}
        ]}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA_V2)

    def test_v1_word_rejected_by_v2_schema(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(VALID_WORD, WORD_ANALYSIS_SCHEMA_V2)


# ---------------------------------------------------------------------------
# WORD_ANALYSIS_SCHEMA_V3
# ---------------------------------------------------------------------------

class TestWordSchemaV3Structure:
    def test_v3_schema_is_dict(self) -> None:
        assert isinstance(WORD_ANALYSIS_SCHEMA_V3, dict)

    def test_v3_requires_chinese_meaning(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V3["required"]
        assert "chinese_meaning" in required
        assert "chinese_meaning" in WORD_ANALYSIS_SCHEMA_V3["properties"]

    def test_v3_preserves_v2_writer_fields(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V3["required"]
        for field in ["register", "why_this_word", "vs_simpler"]:
            assert field in required


class TestWordSchemaV3ValidInstances:
    def test_valid_v3_word_passes(self) -> None:
        _validate(VALID_WORD_V3, WORD_ANALYSIS_SCHEMA_V3)


class TestWordSchemaV3InvalidInstances:
    def test_missing_chinese_meaning_rejected(self) -> None:
        bad = {k: v for k, v in VALID_WORD_V3.items() if k != "chinese_meaning"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA_V3)

    def test_v2_word_rejected_by_v3_schema(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(VALID_WORD_V2, WORD_ANALYSIS_SCHEMA_V3)


# ---------------------------------------------------------------------------
# WORD_ANALYSIS_SCHEMA_V4
# ---------------------------------------------------------------------------

class TestWordSchemaV4Structure:
    def test_v4_schema_is_dict(self) -> None:
        assert isinstance(WORD_ANALYSIS_SCHEMA_V4, dict)

    def test_v4_requires_learner_note_check(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V4["required"]
        assert "learner_note_check" in required
        assert "learner_note_check" in WORD_ANALYSIS_SCHEMA_V4["properties"]

    def test_v4_preserves_v3_chinese_meaning(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V4["required"]
        assert "chinese_meaning" in required
        assert "chinese_meaning" in WORD_ANALYSIS_SCHEMA_V4["properties"]


class TestWordSchemaV4ValidInstances:
    def test_valid_v4_word_passes(self) -> None:
        _validate(VALID_WORD_V4, WORD_ANALYSIS_SCHEMA_V4)


class TestWordSchemaV4InvalidInstances:
    def test_missing_learner_note_check_rejected(self) -> None:
        bad = {k: v for k, v in VALID_WORD_V4.items() if k != "learner_note_check"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA_V4)

    def test_v3_word_rejected_by_v4_schema(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(VALID_WORD_V3, WORD_ANALYSIS_SCHEMA_V4)


# ---------------------------------------------------------------------------
# WORD_ANALYSIS_SCHEMA_V5
# ---------------------------------------------------------------------------

class TestWordSchemaV5Structure:
    def test_v5_schema_is_dict(self) -> None:
        assert isinstance(WORD_ANALYSIS_SCHEMA_V5, dict)

    def test_v5_requires_role_in_sentence(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V5["required"]
        assert "role_in_sentence" in required
        assert "role_in_sentence" in WORD_ANALYSIS_SCHEMA_V5["properties"]

    def test_v5_preserves_v4_learner_note_check(self) -> None:
        required = WORD_ANALYSIS_SCHEMA_V5["required"]
        assert "learner_note_check" in required


class TestWordSchemaV5ValidInstances:
    def test_valid_v5_word_passes(self) -> None:
        _validate(VALID_WORD_V5, WORD_ANALYSIS_SCHEMA_V5)


class TestWordSchemaV5InvalidInstances:
    def test_missing_role_in_sentence_rejected(self) -> None:
        bad = {k: v for k, v in VALID_WORD_V5.items() if k != "role_in_sentence"}
        with pytest.raises(jsonschema.ValidationError):
            _validate(bad, WORD_ANALYSIS_SCHEMA_V5)

    def test_v4_word_rejected_by_v5_schema(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            _validate(VALID_WORD_V4, WORD_ANALYSIS_SCHEMA_V5)
