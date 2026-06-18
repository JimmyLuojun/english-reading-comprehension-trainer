"""
Tests for prompt files in prompts/.

Validates:
- All current prompt files exist
- Frontmatter is present and contains required fields (name, version, reason)
- Version string matches filename
- JSON schema embedded in sentence/word prompts references only valid error codes
- Required template variables ({{ ... }}) are present
- Output section headings match design.md §9 and §10
- Profile prompt has the four required section headings
- No file exceeds a reasonable size (prompt bloat guard)
- Prompt files are valid UTF-8
"""

import re
from pathlib import Path

import pytest

from app.db_models import VALID_ERROR_CODES

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

PROMPT_FILES = {
    "sentence_analysis_predict":  PROMPTS_DIR / "sentence_analysis_predict.v3.md",
    "sentence_analysis_diagnose": PROMPTS_DIR / "sentence_analysis_diagnose.v3.md",
    "word_analysis":              PROMPTS_DIR / "word_analysis.v5.md",
    "profile_summary":            PROMPTS_DIR / "profile_summary.v1.md",
}
SENTENCE_ANALYSIS_PREDICT_V1 = PROMPTS_DIR / "sentence_analysis_predict.v1.md"
SENTENCE_ANALYSIS_DIAGNOSE_V1 = PROMPTS_DIR / "sentence_analysis_diagnose.v1.md"
SENTENCE_ANALYSIS_PREDICT_V2 = PROMPTS_DIR / "sentence_analysis_predict.v2.md"
SENTENCE_ANALYSIS_DIAGNOSE_V2 = PROMPTS_DIR / "sentence_analysis_diagnose.v2.md"
WORD_ANALYSIS_V3 = PROMPTS_DIR / "word_analysis.v3.md"
WORD_ANALYSIS_V4 = PROMPTS_DIR / "word_analysis.v4.md"
WORD_ANALYSIS_V5 = PROMPTS_DIR / "word_analysis.v5.md"

# Required template variables per prompt
REQUIRED_VARS = {
    "sentence_analysis_predict": ["sentence", "context", "chapter_title",
                                  "related_cards", "learner_profile"],
    "sentence_analysis_diagnose": ["sentence", "user_translation", "context",
                                   "chapter_title", "related_cards",
                                   "learner_profile"],
    "word_analysis": ["surface_form", "sentence", "context",
                      "related_cards", "learner_note", "learner_profile"],
    "profile_summary": ["lookback_days", "total_reviews",
                        "sentence_card_count", "word_card_count",
                        "error_type_stats"],
}

# Profile prompt must contain these four headings
PROFILE_HEADINGS = [
    "## Current Weaknesses",
    "## Emerging Strengths",
    "## Vocabulary Watch",
    "## Suggested Focus",
]

MAX_PROMPT_BYTES = 12_000  # guard against accidental prompt bloat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(name: str) -> str:
    return PROMPT_FILES[name].read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract key: value pairs from the YAML-style frontmatter block."""
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _extract_template_vars(text: str) -> set[str]:
    """Return all {{ var_name }} references in the prompt."""
    return set(re.findall(r"\{\{\s*(\w+)\s*\}\}", text))


def _extract_error_codes_in_prompt(text: str) -> set[str]:
    """Find all closed error-code references mentioned in the prompt text."""
    return set(re.findall(r"\b([GLDI]\d{2})\b", text))


# ---------------------------------------------------------------------------
# File existence and encoding
# ---------------------------------------------------------------------------

class TestPromptFilesExist:
    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_file_exists(self, name: str) -> None:
        assert PROMPT_FILES[name].exists(), f"Prompt file missing: {PROMPT_FILES[name]}"

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_file_is_valid_utf8(self, name: str) -> None:
        PROMPT_FILES[name].read_text(encoding="utf-8")  # raises on bad encoding

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_file_not_empty(self, name: str) -> None:
        assert len(_read(name).strip()) > 0

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_file_size_within_limit(self, name: str) -> None:
        size = PROMPT_FILES[name].stat().st_size
        assert size <= MAX_PROMPT_BYTES, (
            f"{name} is {size} bytes — exceeds {MAX_PROMPT_BYTES} byte limit"
        )

    def test_historical_word_prompt_v4_exists(self) -> None:
        assert WORD_ANALYSIS_V4.exists()
        assert WORD_ANALYSIS_V4.stat().st_size <= MAX_PROMPT_BYTES

    def test_current_word_prompt_v5_exists(self) -> None:
        assert WORD_ANALYSIS_V5.exists()
        assert WORD_ANALYSIS_V5.stat().st_size <= MAX_PROMPT_BYTES

    def test_historical_word_prompt_v3_exists(self) -> None:
        assert WORD_ANALYSIS_V3.exists()
        assert WORD_ANALYSIS_V3.stat().st_size <= MAX_PROMPT_BYTES


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

class TestFrontmatter:
    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_has_frontmatter_block(self, name: str) -> None:
        text = _read(name)
        assert text.startswith("---\n"), f"{name}: must start with frontmatter '---'"
        assert "---" in text[4:], f"{name}: frontmatter closing '---' not found"

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_frontmatter_has_name(self, name: str) -> None:
        fm = _parse_frontmatter(_read(name))
        assert "name" in fm and fm["name"], f"{name}: frontmatter missing 'name'"

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_frontmatter_has_version(self, name: str) -> None:
        fm = _parse_frontmatter(_read(name))
        assert "version" in fm and fm["version"], f"{name}: frontmatter missing 'version'"

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_frontmatter_has_reason(self, name: str) -> None:
        fm = _parse_frontmatter(_read(name))
        assert "reason" in fm and len(fm["reason"]) > 10, (
            f"{name}: frontmatter 'reason' missing or too short"
        )

    @pytest.mark.parametrize("name,expected_version", [
        ("sentence_analysis_predict", "v3"),
        ("sentence_analysis_diagnose", "v3"),
        ("word_analysis", "v5"),
        ("profile_summary", "v1"),
    ])
    def test_version_matches_filename(self, name: str, expected_version: str) -> None:
        fm = _parse_frontmatter(_read(name))
        assert fm.get("version") == expected_version, (
            f"{name}: frontmatter version '{fm.get('version')}' "
            f"does not match filename '{expected_version}'"
        )

    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_frontmatter_name_matches_key(self, name: str) -> None:
        fm = _parse_frontmatter(_read(name))
        assert fm.get("name") == name, (
            f"Frontmatter name '{fm.get('name')}' does not match expected '{name}'"
        )


# ---------------------------------------------------------------------------
# Template variables
# ---------------------------------------------------------------------------

class TestTemplateVariables:
    @pytest.mark.parametrize("name", list(PROMPT_FILES))
    def test_required_vars_present(self, name: str) -> None:
        found = _extract_template_vars(_read(name))
        for var in REQUIRED_VARS[name]:
            assert var in found, f"{name}: required template variable '{{{{ {var} }}}}' not found"


# ---------------------------------------------------------------------------
# Error codes referenced in prompts
# ---------------------------------------------------------------------------

class TestErrorCodesInPrompts:
    @pytest.mark.parametrize("name", ["sentence_analysis_predict", "sentence_analysis_diagnose"])
    def test_sentence_prompt_references_only_valid_codes(self, name: str) -> None:
        codes = _extract_error_codes_in_prompt(_read(name))
        invalid = codes - VALID_ERROR_CODES
        assert not invalid, f"{name} references unknown error codes: {invalid}"

    def test_word_prompt_references_only_valid_codes(self) -> None:
        codes = _extract_error_codes_in_prompt(_read("word_analysis"))
        invalid = codes - VALID_ERROR_CODES
        assert not invalid, f"word_analysis references unknown error codes: {invalid}"

    @pytest.mark.parametrize("name", ["sentence_analysis_predict", "sentence_analysis_diagnose"])
    def test_sentence_prompt_covers_all_layers(self, name: str) -> None:
        codes = _extract_error_codes_in_prompt(_read(name))
        assert any(c.startswith("G") for c in codes), f"{name} missing grammar codes"
        assert any(c.startswith("L") for c in codes), f"{name} missing lexical codes"
        assert any(c.startswith("D") for c in codes), f"{name} missing discourse codes"
        assert any(c.startswith("I") for c in codes), f"{name} missing inference codes"

    def test_word_prompt_covers_lexical_layer(self) -> None:
        codes = _extract_error_codes_in_prompt(_read("word_analysis"))
        assert any(c.startswith("L") for c in codes), "word_analysis must reference lexical codes"

    def test_few_shot_example_codes_are_valid(self) -> None:
        for name in ("sentence_analysis_predict", "sentence_analysis_diagnose", "word_analysis"):
            codes = _extract_error_codes_in_prompt(_read(name))
            invalid = codes - VALID_ERROR_CODES
            assert not invalid, f"{name} few-shot uses invalid codes: {invalid}"


# ---------------------------------------------------------------------------
# JSON schema field names in sentence / word prompts
# ---------------------------------------------------------------------------

class TestJSONSchemaFieldsInPrompts:
    SENTENCE_FIELDS = [
        "subject_skeleton", "clauses", "modifiers", "logic_markers",
        "anaphora", "simplified_en", "chinese_gloss", "blocking_point",
        "predicted_error_types", "diagnosis_basis",
        "diagnosed_error_types", "diagnosis_evidence",
        "takeaway_suggestion", "confidence",
    ]
    WORD_FIELDS = [
        "lemma", "lexical_type", "pos", "meaning_in_context",
        "chinese_meaning", "role_in_sentence", "register", "why_this_word",
        "vs_simpler", "learner_note_check",
        "morphology", "predicted_error_types", "confidence",
    ]

    @pytest.mark.parametrize("name", ["sentence_analysis_predict", "sentence_analysis_diagnose"])
    @pytest.mark.parametrize("field", SENTENCE_FIELDS)
    def test_sentence_prompt_contains_field(self, name: str, field: str) -> None:
        assert field in _read(name), (
            f"{name} missing JSON field '{field}'"
        )

    @pytest.mark.parametrize("field", WORD_FIELDS)
    def test_word_prompt_contains_field(self, field: str) -> None:
        assert field in _read("word_analysis"), (
            f"word_analysis missing JSON field '{field}'"
        )

    def test_word_prompt_v3_contains_chinese_meaning(self) -> None:
        text = WORD_ANALYSIS_V3.read_text(encoding="utf-8")
        assert "version: v3" in text
        assert "chinese_meaning" in text

    def test_word_prompt_v4_contains_learner_note_check(self) -> None:
        text = WORD_ANALYSIS_V4.read_text(encoding="utf-8")
        assert "{{ learner_note }}" in text
        assert "learner_note_check" in text
        assert "not_provided" in text
        assert "Do not let the learner note override" in text

    def test_current_word_prompt_v5_contains_role_in_sentence(self) -> None:
        text = WORD_ANALYSIS_V5.read_text(encoding="utf-8")
        assert "version: v5" in text
        assert "role_in_sentence" in text

    def test_historical_sentence_prompt_v1_files_remain(self) -> None:
        assert SENTENCE_ANALYSIS_PREDICT_V1.exists()
        assert SENTENCE_ANALYSIS_DIAGNOSE_V1.exists()

    def test_historical_sentence_prompt_v2_files_remain(self) -> None:
        assert SENTENCE_ANALYSIS_PREDICT_V2.exists()
        assert SENTENCE_ANALYSIS_DIAGNOSE_V2.exists()


# ---------------------------------------------------------------------------
# Profile prompt structure
# ---------------------------------------------------------------------------

class TestProfilePromptStructure:
    @pytest.mark.parametrize("heading", PROFILE_HEADINGS)
    def test_profile_has_required_heading(self, heading: str) -> None:
        assert heading in _read("profile_summary"), (
            f"profile_summary missing required heading: '{heading}'"
        )

    def test_profile_headings_in_correct_order(self) -> None:
        text = _read("profile_summary")
        positions = [text.index(h) for h in PROFILE_HEADINGS]
        assert positions == sorted(positions), "Profile headings are not in the required order"

    def test_profile_mentions_300_word_limit(self) -> None:
        assert "300" in _read("profile_summary"), (
            "profile_summary should mention the 300-word output limit"
        )

    def test_profile_mentions_second_person_or_impersonal(self) -> None:
        text = _read("profile_summary")
        assert "second person" in text.lower() or '"you"' in text, (
            "profile_summary should instruct to write in second person or impersonally"
        )


# ---------------------------------------------------------------------------
# Instruction sanity checks
# ---------------------------------------------------------------------------

class TestPromptInstructionSanity:
    @pytest.mark.parametrize("name", ["sentence_analysis_predict", "sentence_analysis_diagnose"])
    def test_sentence_prompt_forbids_output_outside_json(self, name: str) -> None:
        text = _read(name)
        assert "no markdown fences" in text.lower() or "nothing outside" in text.lower() or \
               "do not output anything outside" in text.lower(), \
            f"{name} should instruct model not to wrap output in markdown fences"

    def test_word_prompt_forbids_output_outside_json(self) -> None:
        text = _read("word_analysis")
        assert "do not output anything outside" in text.lower() or \
               "no markdown fences" in text.lower(), \
            "word_analysis should instruct model not to output outside JSON"

    @pytest.mark.parametrize("name", ["sentence_analysis_predict", "sentence_analysis_diagnose"])
    def test_sentence_prompt_requires_one_main_clause(self, name: str) -> None:
        assert "main" in _read(name), \
            f"{name} should require exactly one main clause"

    def test_word_prompt_specifies_lexical_type_choices(self) -> None:
        text = _read("word_analysis")
        for lt in ("word", "phrase", "collocation"):
            assert lt in text, f"word_analysis missing lexical_type value '{lt}'"

    @pytest.mark.parametrize("name", ["sentence_analysis_predict", "sentence_analysis_diagnose"])
    def test_sentence_prompt_has_few_shot_example(self, name: str) -> None:
        assert "Few-shot Example" in _read(name) or \
               "few-shot" in _read(name).lower(), \
            f"{name} should contain a few-shot example"

    def test_word_prompt_has_few_shot_example(self) -> None:
        assert "Few-shot Example" in _read("word_analysis") or \
               "few-shot" in _read("word_analysis").lower(), \
            "word_analysis should contain a few-shot example"

    def test_confidence_field_range_specified(self) -> None:
        for name in ("sentence_analysis_predict", "sentence_analysis_diagnose", "word_analysis"):
            text = _read(name)
            assert "[0.0, 1.0]" in text or "0.0, 1.0" in text, \
                f"{name} should specify confidence range [0.0, 1.0]"
