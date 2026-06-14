"""
Word / phrase / collocation analysis pipeline (§9.2 + §5 of design.md).

Mirrors llm_sentence_analyzer.py but uses the word_analysis prompt and schema.
Content hash includes the surface_form so the same word in different contexts
can produce different cached entries.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.ai.ai_json_schemas import WORD_ANALYSIS_SCHEMA
from app.ai.ai_response_cache import compute_content_hash, get_cached, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.db_connection import DatabaseConnection

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_DEFAULT_MODEL = "gpt-4o-mini"
_PROMPT_NAME = "word_analysis"
_PROMPT_VERSION = "v1"

_RETRY_SUFFIX = (
    "\n\n[CORRECTION NEEDED] Your previous response was not valid JSON or "
    "failed schema validation. Return ONLY a raw JSON object — no markdown "
    "fences, no commentary — matching the schema above exactly."
)


@dataclass
class WordAnalysisResult:
    data: dict
    cache_id: int
    from_cache: bool
    is_stale: bool
    is_valid: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_word(
    db: DatabaseConnection,
    surface_form: str,
    sentence_text: str,
    context: str = "",
    related_cards: str = "",
    learner_profile: str = "",
    model: str | None = None,
    prompt_version: str = _PROMPT_VERSION,
) -> WordAnalysisResult:
    """
    Analyse *surface_form* as it appears in *sentence_text*.

    Raises:
        FileNotFoundError — prompt template not found
        RuntimeError      — LLM call failed
    """
    model = model or os.environ.get("TRAINER_MODEL", _DEFAULT_MODEL)
    # Include surface_form in hash so same word in different sentences
    # can share a cache entry, but explicit context changes produce new ones.
    content_hash = compute_content_hash(
        surface_form + " | " + sentence_text, context
    )

    cached = get_cached(db, content_hash, prompt_version, model)
    if cached is not None:
        return WordAnalysisResult(
            data=cached.data,
            cache_id=cached.cache_id,
            from_cache=True,
            is_stale=cached.is_stale,
            is_valid=cached.is_valid,
        )

    template = _load_prompt(_PROMPT_NAME, prompt_version)
    prompt = _render(template, {
        "surface_form":   surface_form,
        "sentence":       sentence_text,
        "context":        context or "(none)",
        "related_cards":  related_cards or "(none)",
        "learner_profile": learner_profile or "(none)",
    })

    raw = _call_llm(prompt, model)
    data, is_valid = _validate_attempt(raw, WORD_ANALYSIS_SCHEMA)

    if not is_valid:
        raw = _call_llm(prompt + _RETRY_SUFFIX, model)
        data, is_valid = _validate_attempt(raw, WORD_ANALYSIS_SCHEMA)

    response_json = json.dumps(data) if is_valid else raw

    cache_id = save_to_cache(
        db, content_hash, prompt_version, model, response_json, is_valid
    )

    return WordAnalysisResult(
        data=data if is_valid else {},
        cache_id=cache_id,
        from_cache=False,
        is_stale=False,
        is_valid=is_valid,
    )


# ---------------------------------------------------------------------------
# Internal helpers  (identical to llm_sentence_analyzer — shared via copy)
# ---------------------------------------------------------------------------

def _load_prompt(name: str, version: str) -> str:
    path = _PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    if end == -1:
        return text
    return text[end + 3:].lstrip("\n")


def _render(template: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        template = template.replace(f"{{{{ {key} }}}}", value)
    return template


def _call_llm(prompt: str, model: str) -> str:
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
    try:
        data = parse_and_validate(raw, schema)
        return data, True
    except Exception:
        return {}, False
