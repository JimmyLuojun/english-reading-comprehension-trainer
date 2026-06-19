"""
JSON Schema definitions for AI output validation (§9 + §22 of design.md).

Both schemas use `additionalProperties: false` to prevent prompt-injection
via unexpected extra fields. Error codes are validated against the closed
enumeration from db_models.VALID_ERROR_CODES.

SENTENCE_ANALYSIS_SCHEMA    — v1 sentence prompt fields
SENTENCE_ANALYSIS_SCHEMA_V2 — v2 prompt, adds blocking point and takeaway suggestion
SENTENCE_ANALYSIS_SCHEMA_V3 — v5 prompt, adds optional structure feedback
WORD_ANALYSIS_SCHEMA        — v1 prompt, dictionary-view fields
WORD_ANALYSIS_SCHEMA_V2     — v2 prompt, writer-perspective fields (§22)
WORD_ANALYSIS_SCHEMA_V3     — v3 prompt, adds Chinese meaning for reader panel
WORD_ANALYSIS_SCHEMA_V4     — v4 prompt, adds learner-note feedback
WORD_ANALYSIS_SCHEMA_V5     — v5 prompt, adds role in sentence
"""

from app.db_models import ERROR_TYPES, ErrorLayer, VALID_ERROR_CODES

# Sorted for determinism in error messages and test assertions
_ERROR_CODES = sorted(VALID_ERROR_CODES)
_DIAGNOSIS_EVIDENCE_CODES = _ERROR_CODES + ["OK"]
STRUCTURE_SKILL_CODES = sorted(
    entry["code"]
    for entry in ERROR_TYPES
    if entry["layer"] == ErrorLayer.GRAMMAR
    or entry["code"] in {"D01", "D04", "D05"}
)

# ---------------------------------------------------------------------------
# Sentence analysis schema  (§9.1)
# ---------------------------------------------------------------------------

SENTENCE_ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "required": [
        "subject_skeleton", "clauses", "modifiers", "logic_markers",
        "anaphora", "simplified_en", "chinese_gloss",
        "predicted_error_types", "diagnosis_basis",
        "diagnosed_error_types", "diagnosis_evidence", "confidence",
    ],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {
                "properties": {"diagnosis_basis": {"const": "predicted"}},
                "required": ["diagnosis_basis"],
            },
            "then": {
                "properties": {
                    "predicted_error_types": {"minItems": 1},
                    "diagnosed_error_types": {"maxItems": 0},
                    "diagnosis_evidence": {"maxItems": 0},
                },
            },
        },
        {
            "if": {
                "properties": {"diagnosis_basis": {"const": "user_translation"}},
                "required": ["diagnosis_basis"],
            },
            "then": {
                "properties": {
                    "diagnosis_evidence": {"minItems": 1},
                },
            },
        },
    ],
    "properties": {
        "subject_skeleton": {"type": "string", "minLength": 1},
        "clauses": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["type", "text", "role"],
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["main", "relative", "noun", "adverbial"],
                    },
                    "text": {"type": "string", "minLength": 1},
                    "role": {"type": "string"},
                },
            },
        },
        "modifiers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target", "modifier", "type"],
                "additionalProperties": False,
                "properties": {
                    "target":   {"type": "string"},
                    "modifier": {"type": "string"},
                    "type":     {"type": "string"},
                },
            },
        },
        "logic_markers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["marker", "function"],
                "additionalProperties": False,
                "properties": {
                    "marker":   {"type": "string"},
                    "function": {"type": "string"},
                },
            },
        },
        "anaphora": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["pronoun", "refers_to"],
                "additionalProperties": False,
                "properties": {
                    "pronoun":    {"type": "string"},
                    "refers_to":  {"type": "string"},
                },
            },
        },
        "simplified_en":  {"type": "string", "minLength": 1},
        "chinese_gloss":  {"type": "string", "minLength": 1},
        "predicted_error_types": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "enum": _ERROR_CODES},
        },
        "diagnosis_basis": {
            "type": "string",
            "enum": ["predicted", "user_translation"],
        },
        "diagnosed_error_types": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "enum": _ERROR_CODES},
        },
        "diagnosis_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["error_type", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "error_type": {
                        "type": "string",
                        "enum": _DIAGNOSIS_EVIDENCE_CODES,
                    },
                    "evidence": {"type": "string", "minLength": 1},
                },
            },
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}

SENTENCE_ANALYSIS_SCHEMA_V2: dict = {
    **SENTENCE_ANALYSIS_SCHEMA,
    "required": [
        "subject_skeleton", "clauses", "modifiers", "logic_markers",
        "anaphora", "simplified_en", "chinese_gloss", "blocking_point",
        "predicted_error_types", "diagnosis_basis",
        "diagnosed_error_types", "diagnosis_evidence",
        "takeaway_suggestion", "confidence",
    ],
    "properties": {
        **SENTENCE_ANALYSIS_SCHEMA["properties"],
        "blocking_point": {"type": "string", "minLength": 1},
        "takeaway_suggestion": {"type": "string", "minLength": 1},
    },
}

SENTENCE_ANALYSIS_SCHEMA_V3: dict = {
    **SENTENCE_ANALYSIS_SCHEMA_V2,
    "properties": {
        **SENTENCE_ANALYSIS_SCHEMA_V2["properties"],
        "structure_feedback": {
            "type": "object",
            "required": [
                "is_correct",
                "missed_or_wrong",
                "corrected_structure",
                "why_it_matters_for_translation",
                "next_check",
            ],
            "additionalProperties": False,
            "properties": {
                "is_correct": {"type": "boolean"},
                "missed_or_wrong": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "error_code",
                            "learner_claim",
                            "correction",
                            "reason",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "error_code": {
                                "type": "string",
                                "enum": STRUCTURE_SKILL_CODES,
                            },
                            "learner_claim": {"type": "string", "minLength": 1},
                            "correction": {"type": "string", "minLength": 1},
                            "reason": {"type": "string", "minLength": 1},
                        },
                    },
                },
                "corrected_structure": {"type": "string", "minLength": 1},
                "why_it_matters_for_translation": {"type": "string", "minLength": 1},
                "next_check": {"type": "string", "minLength": 1},
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Word / phrase / collocation analysis schema  (§9.2)
# ---------------------------------------------------------------------------

WORD_ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "required": [
        "lemma", "lexical_type", "pos", "meaning_in_context",
        "common_collocations", "near_synonyms", "confusable_with",
        "morphology", "predicted_error_types", "confidence",
    ],
    "additionalProperties": False,
    "properties": {
        "lemma":              {"type": "string", "minLength": 1},
        "lexical_type": {
            "type": "string",
            "enum": ["word", "phrase", "collocation"],
        },
        "pos":                {"type": "string"},
        "meaning_in_context": {"type": "string", "minLength": 1},
        "common_collocations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "near_synonyms": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confusable_with": {
            "type": "array",
            "items": {"type": "string"},
        },
        "morphology": {
            "type": "object",
            "required": ["root", "family"],
            "additionalProperties": False,
            "properties": {
                "root":   {"type": "string"},
                "family": {"type": "array", "items": {"type": "string"}},
            },
        },
        "predicted_error_types": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string", "enum": _ERROR_CODES},
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}

# ---------------------------------------------------------------------------
# Word / phrase / collocation analysis schema v2  (§22)
# Writer-perspective redesign: register + why_this_word + vs_simpler
# replace common_collocations + near_synonyms + confusable_with
# ---------------------------------------------------------------------------

WORD_ANALYSIS_SCHEMA_V2: dict = {
    "type": "object",
    "required": [
        "lemma", "lexical_type", "pos", "meaning_in_context",
        "register", "why_this_word", "vs_simpler",
        "morphology", "predicted_error_types", "confidence",
    ],
    "additionalProperties": False,
    "properties": {
        "lemma":              {"type": "string", "minLength": 1},
        "lexical_type": {
            "type": "string",
            "enum": ["word", "phrase", "collocation"],
        },
        "pos":                {"type": "string"},
        "meaning_in_context": {"type": "string", "minLength": 1},
        "register": {
            "type": "string",
            "enum": ["academic", "formal", "literary", "neutral", "colloquial", "technical"],
        },
        "why_this_word": {"type": "string", "minLength": 1},
        "vs_simpler": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["simpler", "difference"],
                "additionalProperties": False,
                "properties": {
                    "simpler":    {"type": "string"},
                    "difference": {"type": "string"},
                },
            },
        },
        "morphology": {
            "type": "object",
            "required": ["root", "family"],
            "additionalProperties": False,
            "properties": {
                "root":   {"type": "string"},
                "family": {"type": "array", "items": {"type": "string"}},
            },
        },
        "predicted_error_types": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string", "enum": _ERROR_CODES},
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}

# ---------------------------------------------------------------------------
# Word / phrase / collocation analysis schema v3
# Adds a learner-facing Chinese meaning while preserving v2 writer-perspective
# fields for backwards-compatible rendering of older cache payloads.
# ---------------------------------------------------------------------------

WORD_ANALYSIS_SCHEMA_V3: dict = {
    **WORD_ANALYSIS_SCHEMA_V2,
    "required": [
        "lemma", "lexical_type", "pos", "meaning_in_context", "chinese_meaning",
        "register", "why_this_word", "vs_simpler",
        "morphology", "predicted_error_types", "confidence",
    ],
    "properties": {
        **WORD_ANALYSIS_SCHEMA_V2["properties"],
        "chinese_meaning": {"type": "string", "minLength": 1},
    },
}

# ---------------------------------------------------------------------------
# Word / phrase / collocation analysis schema v4
# Adds learner-note feedback to the v3 learner-facing Chinese meaning.
# ---------------------------------------------------------------------------

WORD_ANALYSIS_SCHEMA_V4: dict = {
    **WORD_ANALYSIS_SCHEMA_V3,
    "required": [
        "lemma", "lexical_type", "pos", "meaning_in_context", "chinese_meaning",
        "register", "why_this_word", "vs_simpler", "learner_note_check",
        "morphology", "predicted_error_types", "confidence",
    ],
    "properties": {
        **WORD_ANALYSIS_SCHEMA_V3["properties"],
        "learner_note_check": {
            "type": "object",
            "required": ["status", "feedback", "corrected_understanding"],
            "additionalProperties": False,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "not_provided",
                        "correct",
                        "partly_correct",
                        "incorrect",
                        "not_enough_information",
                    ],
                },
                "feedback": {"type": "string"},
                "corrected_understanding": {"type": "string"},
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Word / phrase / collocation analysis schema v5
# Adds the minimal recursive "back to the sentence" link.
# ---------------------------------------------------------------------------

WORD_ANALYSIS_SCHEMA_V5: dict = {
    **WORD_ANALYSIS_SCHEMA_V4,
    "required": [
        "lemma", "lexical_type", "pos", "meaning_in_context", "chinese_meaning",
        "role_in_sentence", "register", "why_this_word", "vs_simpler",
        "learner_note_check", "morphology", "predicted_error_types", "confidence",
    ],
    "properties": {
        **WORD_ANALYSIS_SCHEMA_V4["properties"],
        "role_in_sentence": {"type": "string", "minLength": 1},
    },
}
