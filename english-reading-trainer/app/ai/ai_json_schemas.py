"""
JSON Schema definitions for AI output validation (§9 of design.md).

Both schemas use `additionalProperties: false` to prevent prompt-injection
via unexpected extra fields. Error codes are validated against the closed
enumeration from db_models.VALID_ERROR_CODES.
"""

from app.db_models import VALID_ERROR_CODES

# Sorted for determinism in error messages and test assertions
_ERROR_CODES = sorted(VALID_ERROR_CODES)
_DIAGNOSIS_EVIDENCE_CODES = _ERROR_CODES + ["OK"]

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
