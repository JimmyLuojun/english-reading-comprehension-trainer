"""
Sentence analysis pipeline (§9.1 + §5 of design.md).

Pipeline per call:
  1. Compute content_hash from sentence + context.
  2. Check ai_response_cache → return CachedEntry if hit.
  3. Load prompt template, fill variables, call LLM.
  4. Validate JSON response (jsonschema + semantic checks).
  5. On failure, retry once with an explicit correction instruction.
  6. Save result to cache (is_valid reflects whether validation passed).
  7. Return SentenceAnalysisResult.

Environment variables:
  OPENAI_API_KEY   — API key (required unless using a local base_url)
  OPENAI_BASE_URL  — override endpoint (e.g. Ollama, Azure, Claude-compatible)
  TRAINER_MODEL    — default model name (falls back to "gpt-4o-mini")
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.ai.ai_json_schemas import SENTENCE_ANALYSIS_SCHEMA
from app.ai.ai_response_cache import CachedEntry, compute_content_hash, get_cached, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.db_connection import DatabaseConnection

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_DEFAULT_MODEL = "gpt-4o-mini"
_PROMPT_NAME = "sentence_analysis"
_PROMPT_VERSION = "v1"

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
    model: str | None = None,
    prompt_version: str = _PROMPT_VERSION,
) -> SentenceAnalysisResult:
    """
    Analyse *sentence_text* and return a structured result.

    Raises:
        FileNotFoundError  — prompt template not found on disk
        RuntimeError       — LLM call failed (non-validation error)
    """
    model = model or os.environ.get("TRAINER_MODEL", _DEFAULT_MODEL)
    content_hash = compute_content_hash(sentence_text, context)

    # --- Cache check ---
    cached = get_cached(db, content_hash, prompt_version, model)
    if cached is not None:
        return SentenceAnalysisResult(
            data=cached.data,
            cache_id=cached.cache_id,
            from_cache=True,
            is_stale=cached.is_stale,
            is_valid=cached.is_valid,
        )

    # --- Build prompt ---
    template = _load_prompt(_PROMPT_NAME, prompt_version)
    prompt = _render(template, {
        "sentence":       sentence_text,
        "context":        context or "(none)",
        "chapter_title":  chapter_title or "(none)",
        "related_cards":  related_cards or "(none)",
        "learner_profile": learner_profile or "(none)",
    })

    # --- First attempt ---
    raw = _call_llm(prompt, model)
    data, is_valid = _validate_attempt(raw, SENTENCE_ANALYSIS_SCHEMA)

    if not is_valid:
        # --- Retry with correction ---
        raw = _call_llm(prompt + _RETRY_SUFFIX, model)
        data, is_valid = _validate_attempt(raw, SENTENCE_ANALYSIS_SCHEMA)

    response_json = json.dumps(data) if is_valid else raw

    cache_id = save_to_cache(
        db, content_hash, prompt_version, model, response_json, is_valid
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
        client = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
        )
        response = client.chat.completions.create(
            model=model,
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
