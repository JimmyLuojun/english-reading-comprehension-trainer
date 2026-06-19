"""
Sentence analysis pipeline (§9.1, §15 + §5 of design.md).

Pipeline per call:
  1. Compute content_hash from sentence, context, optional user translation,
     and optional user structure attempt.
  2. Check ai_response_cache → return CachedEntry if hit.
  3. Load prompt template, fill variables, call LLM.
  4. Validate JSON response (jsonschema + semantic checks).
  5. On failure, retry once with an explicit correction instruction.
  6. Save result to cache (is_valid reflects whether validation passed).
  7. Return SentenceAnalysisResult.

Environment variables:
  OPENAI_API_KEY   — API key (required unless using a local base_url)
  OPENAI_BASE_URL  — override endpoint (defaults to DeepSeek)
  TRAINER_SENTENCE_MODEL — sentence model name (defaults to "deepseek-v4-pro")
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.ai.ai_json_schemas import (
    SENTENCE_ANALYSIS_SCHEMA,
    SENTENCE_ANALYSIS_SCHEMA_V2,
    SENTENCE_ANALYSIS_SCHEMA_V3,
)
from app.ai.ai_provider_config import get_ai_provider_settings, get_sentence_analysis_model
from app.ai.ai_response_cache import compute_content_hash, get_cached, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.db_connection import DatabaseConnection

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_PREDICT_PROMPT_NAME = "sentence_analysis_predict"
_DIAGNOSE_PROMPT_NAME = "sentence_analysis_diagnose"
_PROMPT_VERSION = "v5"

# Correction suffix appended on retry to guide the LLM back on track
_RETRY_SUFFIX = (
    "\n\n[CORRECTION NEEDED] Your previous response was not valid JSON or "
    "failed schema validation. Return ONLY a raw JSON object — no markdown "
    "fences, no commentary — matching the schema above exactly."
)


@dataclass
class SentenceAnalysisResult:
    data: dict
    cache_id: int
    from_cache: bool
    is_stale: bool     # True if served from a different prompt_version
    is_valid: bool     # False if both attempts failed validation


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_sentence(
    db: DatabaseConnection,
    sentence_text: str,
    context: str = "",
    chapter_title: str = "",
    related_cards: str = "",
    learner_profile: str = "",
    user_translation: str | None = None,
    user_structure: str | None = None,
    model: str | None = None,
    prompt_version: str = _PROMPT_VERSION,
    force_refresh: bool = False,
) -> SentenceAnalysisResult:
    """
    Analyse *sentence_text* and return a structured result.

    Raises:
        FileNotFoundError  — prompt template not found on disk
        RuntimeError       — LLM call failed (non-validation error)
    """
    model = get_sentence_analysis_model(model)
    cleaned_translation = _clean_optional_translation(user_translation)
    cleaned_structure = _clean_optional_text(user_structure)
    content_hash = compute_content_hash(
        sentence_text,
        context,
        cleaned_translation,
        cleaned_structure,
    )

    # --- Cache check ---
    cached = None if force_refresh else get_cached(db, content_hash, prompt_version, model)
    if cached is not None:
        return SentenceAnalysisResult(
            data=cached.data,
            cache_id=cached.cache_id,
            from_cache=True,
            is_stale=cached.is_stale,
            is_valid=cached.is_valid,
        )

    # --- Build prompt ---
    prompt_name = _prompt_name_for_translation(cleaned_translation)
    template = _load_prompt(prompt_name, prompt_version)
    prompt = _render(template, {
        "sentence":       sentence_text,
        "context":        context or "(none)",
        "chapter_title":  chapter_title or "(none)",
        "related_cards":  related_cards or "(none)",
        "learner_profile": learner_profile or "(none)",
        "user_translation": cleaned_translation or "(none)",
        "user_structure": cleaned_structure or "(none)",
    })

    schema = _sentence_analysis_schema(prompt_version)

    # --- First attempt ---
    raw = _call_llm(prompt, model)
    data, is_valid = _validate_attempt(raw, schema)

    if not is_valid:
        # --- Retry with correction ---
        raw = _call_llm(prompt + _RETRY_SUFFIX, model)
        data, is_valid = _validate_attempt(raw, schema)

    response_json = json.dumps(data) if is_valid else raw

    cache_id = save_to_cache(
        db,
        content_hash,
        prompt_version,
        model,
        response_json,
        is_valid,
        replace_valid=force_refresh,
    )

    return SentenceAnalysisResult(
        data=data if is_valid else {},
        cache_id=cache_id,
        from_cache=False,
        is_stale=False,
        is_valid=is_valid,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_prompt(name: str, version: str) -> str:
    path = _PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def _prompt_name_for_translation(user_translation: str | None) -> str:
    if user_translation:
        return _DIAGNOSE_PROMPT_NAME
    return _PREDICT_PROMPT_NAME


def _sentence_analysis_schema(prompt_version: str) -> dict:
    if prompt_version == "v1":
        return SENTENCE_ANALYSIS_SCHEMA
    if prompt_version == "v5":
        return SENTENCE_ANALYSIS_SCHEMA_V3
    return SENTENCE_ANALYSIS_SCHEMA_V2


def _clean_optional_translation(value: str | None) -> str | None:
    return _clean_optional_text(value)


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from prompt text."""
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    if end == -1:
        return text
    return text[end + 3:].lstrip("\n")


def _render(template: str, variables: dict[str, str]) -> str:
    """Replace {{ var }} placeholders."""
    for key, value in variables.items():
        template = template.replace(f"{{{{ {key} }}}}", value)
    return template


def _call_llm(prompt: str, model: str) -> str:
    """Call the LLM and return raw text. Raises RuntimeError on API failure."""
    try:
        import openai
        settings = get_ai_provider_settings(model)
        client = openai.OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url or None,
        )
        response = client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        raise RuntimeError(f"LLM call failed: {exc}") from exc


def _validate_attempt(raw: str, schema: dict) -> tuple[dict, bool]:
    """Try to parse and validate. Returns (data, is_valid)."""
    try:
        data = parse_and_validate(raw, schema)
        return data, True
    except Exception:
        return {}, False
