"""
Unit tests for db_models.py constants and enumerations.

No database or I/O — pure logic.
"""

import pytest

from app.db_models import (
    ERROR_TYPES,
    OUTCOME_TO_QUALITY,
    VALID_ERROR_CODES,
    CardType,
    ErrorLayer,
    LexicalType,
    MasteryState,
    ReviewOutcome,
    SM2_DEFAULT_EF,
    SM2_MIN_EF,
    SourceFormat,
)


class TestErrorTypeConstants:
    def test_error_types_has_18_entries(self) -> None:
        assert len(ERROR_TYPES) == 18

    def test_all_codes_unique(self) -> None:
        codes = [e["code"] for e in ERROR_TYPES]
        assert len(codes) == len(set(codes))

    def test_all_layers_valid(self) -> None:
        valid = {layer.value for layer in ErrorLayer}
        for entry in ERROR_TYPES:
            assert entry["layer"].value in valid

    def test_grammar_layer_has_7_codes(self) -> None:
        grammar = [e for e in ERROR_TYPES if e["layer"] == ErrorLayer.GRAMMAR]
        assert len(grammar) == 7

    def test_lexical_layer_has_6_codes(self) -> None:
        lexical = [e for e in ERROR_TYPES if e["layer"] == ErrorLayer.LEXICAL]
        assert len(lexical) == 6

    def test_discourse_layer_has_5_codes(self) -> None:
        discourse = [e for e in ERROR_TYPES if e["layer"] == ErrorLayer.DISCOURSE]
        assert len(discourse) == 5

    def test_valid_error_codes_matches_error_types(self) -> None:
        expected = frozenset(e["code"] for e in ERROR_TYPES)
        assert VALID_ERROR_CODES == expected

    @pytest.mark.parametrize("prefix,layer", [
        ("G", ErrorLayer.GRAMMAR),
        ("L", ErrorLayer.LEXICAL),
        ("D", ErrorLayer.DISCOURSE),
    ])
    def test_code_prefix_matches_layer(self, prefix: str, layer: ErrorLayer) -> None:
        for entry in ERROR_TYPES:
            if entry["layer"] == layer:
                assert entry["code"].startswith(prefix), (
                    f"Code {entry['code']} should start with '{prefix}' for layer {layer}"
                )

    def test_each_entry_has_required_keys(self) -> None:
        for entry in ERROR_TYPES:
            assert "code" in entry
            assert "name" in entry
            assert "layer" in entry


class TestSM2Constants:
    def test_default_ef_is_2_5(self) -> None:
        assert SM2_DEFAULT_EF == 2.5

    def test_min_ef_is_1_3(self) -> None:
        assert SM2_MIN_EF == 1.3

    def test_min_ef_less_than_default(self) -> None:
        assert SM2_MIN_EF < SM2_DEFAULT_EF


class TestOutcomeToQualityMapping:
    def test_pass_maps_to_5(self) -> None:
        assert OUTCOME_TO_QUALITY[ReviewOutcome.PASS] == 5

    def test_partial_maps_to_3(self) -> None:
        assert OUTCOME_TO_QUALITY[ReviewOutcome.PARTIAL] == 3

    def test_fail_maps_to_1(self) -> None:
        assert OUTCOME_TO_QUALITY[ReviewOutcome.FAIL] == 1

    def test_all_outcomes_mapped(self) -> None:
        for outcome in ReviewOutcome:
            assert outcome in OUTCOME_TO_QUALITY

    def test_qualities_are_in_valid_range(self) -> None:
        for q in OUTCOME_TO_QUALITY.values():
            assert 0 <= q <= 5


class TestEnumerations:
    def test_source_format_values(self) -> None:
        assert SourceFormat.TXT.value == "txt"
        assert SourceFormat.EPUB.value == "epub"

    def test_lexical_type_values(self) -> None:
        assert LexicalType.WORD.value == "word"
        assert LexicalType.PHRASE.value == "phrase"
        assert LexicalType.COLLOCATION.value == "collocation"

    def test_card_type_values(self) -> None:
        assert CardType.SENTENCE.value == "sentence"
        assert CardType.WORD.value == "word"

    def test_review_outcome_values(self) -> None:
        assert ReviewOutcome.PASS.value == "pass"
        assert ReviewOutcome.PARTIAL.value == "partial"
        assert ReviewOutcome.FAIL.value == "fail"

    def test_mastery_state_values(self) -> None:
        expected = {"new", "learning", "mature", "lapsed"}
        actual = {s.value for s in MasteryState}
        assert actual == expected

    def test_error_layer_values(self) -> None:
        expected = {"grammar", "lexical", "discourse"}
        actual = {l.value for l in ErrorLayer}
        assert actual == expected
