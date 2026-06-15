"""
JSON output validation for LLM responses (§9.3 of design.md).

Responsibilities:
  1. Strip markdown code fences that LLMs sometimes add despite instructions.
  2. Parse text as JSON.
  3. Validate the parsed object against a JSON Schema.
  4. Run semantic post-checks (e.g. at-least-one-main-clause rule).

All public functions raise standard exceptions so callers can implement
retry logic without knowing parsing details.
"""

import json
import re

import jsonschema
from jsonschema import ValidationError


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_and_validate(raw_text: str, schema: dict) -> dict:
    """
    Parse *raw_text* as JSON and validate against *schema*.

    Strips markdown fences before parsing.
    Runs semantic post-checks after schema validation.

    Returns the parsed dict on success.
    Raises:
        json.JSONDecodeError  — not valid JSON
        jsonschema.ValidationError — schema or semantic check failed
    """
    cleaned = _strip_fences(raw_text)
    data = json.loads(cleaned)  # may raise JSONDecodeError
    _schema_validate(data, schema)
    _semantic_validate(data, schema)
    return data


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """
    Remove leading/trailing markdown code fences.

    Handles:
      ```json\\n{...}\\n```
      ```\\n{...}\\n```
      {bare JSON}
    """
    text = text.strip()
    if not text.startswith("```"):
        return text

    # Strip opening fence line (``` or ```json etc.)
    first_newline = text.find("\n")
    if first_newline == -1:
        # Single-line fence with no content — return empty
        return ""
    text = text[first_newline + 1:]

    # Strip closing fence
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()

    return text.strip()


def _schema_validate(data: object, schema: dict) -> None:
    """Raise ValidationError if *data* does not conform to *schema*."""
    jsonschema.validate(instance=data, schema=schema)


def _semantic_validate(data: object, schema: dict) -> None:
    """
    Run semantic checks that JSON Schema cannot express.

    Currently enforces:
      - Sentence analysis: clauses must contain at least one 'main' entry.
    """
    if not isinstance(data, dict):
        return

    # Sentence-analysis-specific rule
    if "clauses" in data and "subject_skeleton" in data:
        clauses = data.get("clauses", [])
        main_clauses = [c for c in clauses if isinstance(c, dict) and c.get("type") == "main"]
        if not main_clauses:
            raise ValidationError(
                "Semantic check failed: 'clauses' must contain at least one "
                "entry with type='main'."
            )

    if data.get("diagnosis_basis") == "user_translation":
        diagnosed = data.get("diagnosed_error_types", [])
        evidence = data.get("diagnosis_evidence", [])
        evidence_codes = [
            item.get("error_type")
            for item in evidence
            if isinstance(item, dict)
        ]
        if not diagnosed and "OK" not in evidence_codes:
            raise ValidationError(
                "Semantic check failed: no-error translation diagnoses must "
                "include one diagnosis_evidence item with error_type='OK'."
            )
        missing_evidence = [
            code for code in diagnosed if code not in evidence_codes
        ]
        if missing_evidence:
            raise ValidationError(
                "Semantic check failed: every diagnosed_error_types code must "
                f"have matching diagnosis_evidence. Missing: {missing_evidence}."
            )
