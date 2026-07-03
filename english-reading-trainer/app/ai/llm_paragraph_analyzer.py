"""Paragraph-level argument analysis for the Logic Reading Lens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.ai.ai_json_schemas import PARAGRAPH_LOGIC_LENS_SCHEMA
from app.ai.ai_provider_config import get_ai_provider_settings, get_sentence_analysis_model
from app.ai.ai_response_cache import compute_content_hash, get_cached, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.db_connection import DatabaseConnection

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_PROMPT_NAME = "paragraph_logic_lens"
_PROMPT_FILE_VERSION = "v3"
_PROMPT_VERSION = "paragraph_logic_lens.v3"

_RETRY_SUFFIX = (
    "\n\n[CORRECTION NEEDED] Your previous response was not valid JSON or "
    "failed schema validation. Return ONLY a raw JSON object — no markdown "
    "fences, no commentary — matching the schema above exactly."
)


@dataclass(frozen=True)
class ParagraphLogicResult:
    data: dict
    cache_id: int
    from_cache: bool
    is_stale: bool
    is_valid: bool
    prompt_version: str
    model: str


def analyze_paragraph_logic(
    db: DatabaseConnection,
    *,
    paragraph_text: str,
    sentence_lines: str,
    context: str = "",
    model: str | None = None,
    force_refresh: bool = False,
) -> ParagraphLogicResult:
    """Analyze a paragraph's argument flow and cache the validated JSON."""
    resolved_model = get_sentence_analysis_model(model)
    content_hash = compute_content_hash(paragraph_text, context)

    cached = None if force_refresh else get_cached(
        db,
        content_hash,
        _PROMPT_VERSION,
        resolved_model,
    )
    if cached is not None:
        return ParagraphLogicResult(
            data=cached.data,
            cache_id=cached.cache_id,
            from_cache=True,
            is_stale=cached.is_stale,
            is_valid=cached.is_valid,
            prompt_version=cached.prompt_version,
            model=resolved_model,
        )

    prompt = build_paragraph_logic_prompt(
        paragraph_text=paragraph_text,
        sentence_lines=sentence_lines,
        context=context,
    )
    raw = _call_llm(prompt, resolved_model)
    data, is_valid = _validate_attempt(raw)

    if not is_valid:
        raw = _call_llm(prompt + _RETRY_SUFFIX, resolved_model)
        data, is_valid = _validate_attempt(raw)

    response_json = json.dumps(data, ensure_ascii=False) if is_valid else raw
    cache_id = save_to_cache(
        db,
        content_hash,
        _PROMPT_VERSION,
        resolved_model,
        response_json,
        is_valid,
        replace_valid=force_refresh,
    )

    return ParagraphLogicResult(
        data=data if is_valid else {},
        cache_id=cache_id,
        from_cache=False,
        is_stale=False,
        is_valid=is_valid,
        prompt_version=_PROMPT_VERSION,
        model=resolved_model,
    )


def build_paragraph_logic_prompt(
    *,
    paragraph_text: str,
    sentence_lines: str,
    context: str = "",
) -> str:
    """Build the project prompt used for paragraph logic analysis."""
    template = _load_prompt(_PROMPT_NAME, _PROMPT_FILE_VERSION)
    return _render(
        template,
        {
            "paragraph": paragraph_text,
            "sentence_lines": sentence_lines or "(none)",
            "context": context or "(none)",
        },
    )


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
    return text[end + 3 :].lstrip("\n")


def _render(template: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        template = template.replace(f"{{{{ {key} }}}}", value)
    return template


def _call_llm(prompt: str, model: str) -> str:
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


def _validate_attempt(raw: str) -> tuple[dict, bool]:
    try:
        data = parse_and_validate(raw, PARAGRAPH_LOGIC_LENS_SCHEMA)
        return data, True
    except Exception:
        return {}, False
