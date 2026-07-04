"""AI analysis workflow services for the FastAPI web interface."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.context_builder import build_sentence_prompt, get_sentence_info
from app.ai.ai_provider_config import get_ai_provider_settings, get_pro_analysis_model
from app.ai.ai_json_schemas import PARAGRAPH_LOGIC_LENS_SCHEMA
from app.ai.ai_response_cache import compute_content_hash, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.ai.llm_paragraph_analyzer import (
    analyze_paragraph_logic,
    build_paragraph_logic_prompt,
)
from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import (
    save_sentence_structure,
    save_sentence_translation,
)
from app.cards.word_card_service import get_word_card, record_word_card_diagnosis
from app.db_connection import DatabaseConnection
from app.web.config import _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION
from app.web.queries import (
    _active_sentence_prompt_version,
    _fetch_cache_metadata,
    _fetch_paragraph_for_logic,
    _fetch_sentence_analysis_payload,
    _fetch_sentence_for_analysis,
    _fetch_word_analysis_payload,
)

_WORD_ANALYSIS_FALLBACK_WARNING = (
    "New AI response failed validation. Showing previous saved analysis."
)
_JSON_FENCE_RE = re.compile(
    r"```[ \t]*(?:json)?[ \t]*\r?\n?(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_EXTERNAL_MODEL_NAME = "external-ai"
_PARAGRAPH_LOGIC_PROMPT_VERSION = _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION


@dataclass(frozen=True)
class AnalysisOutcome:
    """Result of an AI analysis workflow, independent of HTTP rendering."""

    payload: dict[str, Any] | None = None
    error: str | None = None
    status_code: int = 200
    retry: bool | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def error_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "error": self.error or ""}
        if self.retry is not None:
            payload["retry"] = self.retry
        return payload


def analyze_sentence_for_reader(
    db: DatabaseConnection,
    sentence_id: int,
    *,
    user_translation: str | None,
    user_structure: str | None = None,
    prefer_pro: bool = False,
    force_refresh: bool = False,
) -> AnalysisOutcome:
    """Analyze a sentence, save the result, and return its reader payload."""
    import app.web.fastapi_app as fastapi_app

    try:
        if user_translation is not None and user_translation.strip():
            save_sentence_translation(db, sentence_id, user_translation)
        if user_structure is not None and user_structure.strip():
            save_sentence_structure(db, sentence_id, user_structure)

        sentence = _fetch_sentence_for_analysis(db, sentence_id)
        context_text = _sentence_context_text(db, sentence_id)
        result = fastapi_app.analyze_sentence(
            db,
            sentence["text"],
            context=context_text,
            user_translation=sentence.get("user_translation") or None,
            user_structure=sentence.get("user_structure") or None,
            model=get_pro_analysis_model() if prefer_pro else None,
            force_refresh=force_refresh,
        )
        if not result.is_valid:
            return AnalysisOutcome(
                error="AI response failed validation.",
                status_code=502,
                retry=True,
            )

        cache_meta = _fetch_cache_metadata(db, result.cache_id)
        save_sentence_analysis(
            db,
            sentence_id,
            json.dumps(result.data, ensure_ascii=False),
            model=cache_meta.get("model") or get_ai_provider_settings().model,
            prompt_version=cache_meta.get("prompt_version")
            or _active_sentence_prompt_version(
                db,
                sentence.get("user_translation") or None,
            ),
            context=context_text,
        )
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    except (FileNotFoundError, RuntimeError) as exc:
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)

    payload = _fetch_sentence_analysis_payload(db, sentence_id)
    if payload is None:
        return AnalysisOutcome(error="Analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = result.from_cache
    payload["is_stale"] = bool(payload["is_stale"] or result.is_stale)
    return AnalysisOutcome(payload=payload)


def analyze_paragraph_logic_for_reader(
    db: DatabaseConnection,
    paragraph_id: int,
    *,
    prefer_pro: bool = False,
    force_refresh: bool = False,
) -> AnalysisOutcome:
    """Analyze a reader paragraph without attaching results to sentence cards."""
    try:
        paragraph = _fetch_paragraph_for_logic(db, paragraph_id)
        result = analyze_paragraph_logic(
            db,
            paragraph_text=paragraph["text"],
            sentence_lines=_paragraph_sentence_lines(paragraph),
            context=paragraph["context"],
            model=get_pro_analysis_model() if prefer_pro else None,
            force_refresh=force_refresh,
        )
        if not result.is_valid:
            return AnalysisOutcome(
                error="AI response failed validation.",
                status_code=502,
                retry=True,
            )
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    except (FileNotFoundError, RuntimeError) as exc:
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)

    return AnalysisOutcome(
        payload={
            "ok": True,
            "paragraph_id": paragraph_id,
            "cache_id": result.cache_id,
            "prompt_version": result.prompt_version,
            "active_prompt_version": _PARAGRAPH_LOGIC_PROMPT_VERSION,
            "model": result.model,
            "is_stale": result.is_stale,
            "from_cache": result.from_cache,
            "paragraph_text": paragraph["text"],
            "sentences": paragraph["sentences"],
            "context": paragraph["context"],
            "analysis": result.data,
        }
    )


def build_external_paragraph_logic_prompt(
    db: DatabaseConnection,
    paragraph_id: int,
) -> str:
    """Build a paste-ready external prompt for paragraph logic analysis."""
    paragraph = _fetch_paragraph_for_logic(db, paragraph_id)
    project_prompt = build_paragraph_logic_prompt(
        paragraph_text=paragraph["text"],
        sentence_lines=_paragraph_sentence_lines(paragraph),
        context=paragraph["context"],
    )
    return f"""你将帮助一名中文母语的英语学习者理解英文段落的论证结构。

请按下面顺序输出：

1. 先输出给人看的中文讲解，必须包含：
- 本段主张
- 每句在论证中的作用：必须引用原始英文句子文本，不要只写 sentence_id；使用清晰的专业角色标签，例如“核心主张 (claim)”“证据/理由 (evidence)”“限定/例外 (qualification)”等
- 证据、让步/反驳、隐藏前提（没有就说明没有）
- 作者立场
- 可能误读点
- 阅读检查动作

2. 最后单独输出一个 ```json 代码块```，用于保存到英语阅读理解专项训练系统。

JSON 规则：
- JSON 必须严格符合下方 PROJECT JSON CONTRACT 的 schema。
- argument_flow 每一项必须同时包含 sentence_id 和 sentence_text；sentence_text 写原始英文句子。
- argument_flow 的 connector_function 是可选字段；只有当它能帮助理解句间连接时才填写。
- role 必须按 PROJECT JSON CONTRACT 的 Role guide 判断；不要把背景或过渡句误标为 evidence。
- JSON 内不要写注释。
- JSON 后不要追加任何内容。
- 只输出一个 ```json 代码块```，不要输出其他代码块。
- 保存时系统只读取最后这个 JSON 代码块；中文讲解是给人看的。
- 如果 PROJECT JSON CONTRACT 要求“Return JSON only”，只把这条要求用于最后的 JSON 代码块；前面的中文讲解仍然要输出。

PROJECT JSON CONTRACT:

{project_prompt}
"""


def build_external_sentence_prompt(
    db: DatabaseConnection,
    sentence_id: int,
) -> str:
    """Build a paste-ready prompt for an external AI chat."""
    sentence = _fetch_sentence_for_analysis(db, sentence_id)
    project_prompt = build_sentence_prompt(
        db,
        sentence_id,
        user_translation=sentence.get("user_translation") or None,
        user_structure=sentence.get("user_structure") or None,
    )
    mode = "诊断模式" if sentence.get("user_translation") else "预测模式"
    return f"""你将帮助一名中文母语的英语学习者理解一个英文句子。

请按下面顺序输出：

1. 先输出给人看的中文讲解，必须包含：
- 句意
- 结构拆解
- 难点说明
- 推荐译文
- 可能的误读点

2. 最后单独输出一个 ```json 代码块```，用于保存到英语阅读理解专项训练系统。

JSON 规则：
- JSON 必须严格符合下方 PROJECT JSON CONTRACT 的 schema。
- JSON 内不要写注释。
- JSON 后不要追加任何内容。
- 如果 PROJECT JSON CONTRACT 要求“Return JSON only”，只把这条要求用于最后的 JSON 代码块；前面的中文讲解仍然要输出。
- 当前分析模式：{mode}

PROJECT JSON CONTRACT:

{project_prompt}
"""


def _paragraph_sentence_lines(paragraph: dict[str, Any]) -> str:
    return "\n".join(
        f'- sentence_id {row["id"]}: {row["text"]}'
        for row in paragraph.get("sentences", [])
    )


def save_external_sentence_analysis_for_reader(
    db: DatabaseConnection,
    sentence_id: int,
    *,
    external_result: str,
    user_translation: str | None = None,
    user_structure: str | None = None,
) -> AnalysisOutcome:
    """Save JSON produced by an external AI chat and return reader payload."""
    try:
        raw_json = extract_external_json_block(external_result)
        if user_translation is not None and user_translation.strip():
            save_sentence_translation(db, sentence_id, user_translation)
        if user_structure is not None and user_structure.strip():
            save_sentence_structure(db, sentence_id, user_structure)

        sentence = _fetch_sentence_for_analysis(db, sentence_id)
        context_text = _sentence_context_text(db, sentence_id)
        result = save_sentence_analysis(
            db,
            sentence_id,
            raw_json,
            model=_EXTERNAL_MODEL_NAME,
            prompt_version=_active_sentence_prompt_version(
                db,
                sentence.get("user_translation") or None,
            ),
            context=context_text,
        )
        if not result.is_valid:
            return AnalysisOutcome(
                error=f"External JSON failed validation: {result.error}",
                status_code=400,
                retry=False,
            )
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)

    payload = _fetch_sentence_analysis_payload(db, sentence_id)
    if payload is None:
        return AnalysisOutcome(error="External analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = False
    payload["is_stale"] = False
    return AnalysisOutcome(payload=payload)


def save_external_paragraph_logic_for_reader(
    db: DatabaseConnection,
    paragraph_id: int,
    *,
    external_result: str,
) -> AnalysisOutcome:
    """Validate and cache JSON produced by an external paragraph-analysis chat."""
    try:
        raw_json = extract_external_json_block(external_result)
        try:
            data = parse_and_validate(raw_json, PARAGRAPH_LOGIC_LENS_SCHEMA)
        except Exception as exc:
            return AnalysisOutcome(
                error=f"External JSON failed validation: {exc}",
                status_code=400,
                retry=False,
            )

        paragraph = _fetch_paragraph_for_logic(db, paragraph_id)
        cache_id = save_to_cache(
            db,
            compute_content_hash(paragraph["text"], paragraph["context"]),
            _PARAGRAPH_LOGIC_PROMPT_VERSION,
            _EXTERNAL_MODEL_NAME,
            json.dumps(data, ensure_ascii=False),
            True,
            replace_valid=True,
        )
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)

    return AnalysisOutcome(
        payload={
            "ok": True,
            "paragraph_id": paragraph_id,
            "cache_id": cache_id,
            "prompt_version": _PARAGRAPH_LOGIC_PROMPT_VERSION,
            "active_prompt_version": _PARAGRAPH_LOGIC_PROMPT_VERSION,
            "model": _EXTERNAL_MODEL_NAME,
            "is_stale": False,
            "from_cache": False,
            "paragraph_text": paragraph["text"],
            "sentences": paragraph["sentences"],
            "context": paragraph["context"],
            "analysis": data,
        }
    )


def extract_external_json_block(external_result: str) -> str:
    """Return the last fenced JSON block, or raw JSON when only JSON was pasted."""
    text = str(external_result or "").strip()
    matches = [match.strip() for match in _JSON_FENCE_RE.findall(text) if match.strip()]
    if matches:
        return matches[-1]
    if text.startswith("{") and text.endswith("}"):
        return text
    raise ValueError("Paste an external AI reply ending with a ```json code block```.")


def _sentence_context_text(db: DatabaseConnection, sentence_id: int) -> str:
    try:
        return str(get_sentence_info(db, sentence_id).get("context") or "")
    except Exception:
        return ""


def _fallback_word_analysis_payload(
    db: DatabaseConnection,
    card_id: int,
    *,
    warning: str = _WORD_ANALYSIS_FALLBACK_WARNING,
) -> dict[str, Any] | None:
    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return None
    payload["is_stale"] = True
    payload["from_cache"] = True
    payload["retry"] = True
    payload["warning"] = warning
    return payload


def analyze_word_card_for_reader(
    db: DatabaseConnection,
    card_id: int,
    *,
    context_text: str = "",
    prefer_pro: bool = False,
    force_refresh: bool = False,
) -> AnalysisOutcome:
    """Analyze a word card, attach the cache id, and return its reader payload."""
    import app.web.fastapi_app as fastapi_app

    card = get_word_card(db, card_id)
    if card is None:
        return AnalysisOutcome(error="Word card not found.", status_code=404)
    try:
        sentence = _fetch_sentence_for_analysis(db, card["first_sentence_id"])
        result = fastapi_app.analyze_word(
            db,
            surface_form=card["surface_form"],
            sentence_text=sentence["text"],
            context=context_text.strip(),
            learner_note=(card.get("user_note") or "").strip(),
            model=get_pro_analysis_model() if prefer_pro else None,
            allow_stale=False,
            force_refresh=force_refresh,
        )
        if not result.is_valid:
            payload = _fallback_word_analysis_payload(db, card_id)
            if payload is not None:
                return AnalysisOutcome(payload=payload)
            return AnalysisOutcome(
                error="AI response failed validation.",
                status_code=502,
                retry=True,
            )
        fastapi_app._update_word_card_analysis_id(db, card_id, result.cache_id)
        record_word_card_diagnosis(db, card_id, result.data)
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    except RuntimeError as exc:
        payload = _fallback_word_analysis_payload(db, card_id, warning=str(exc))
        if payload is not None:
            return AnalysisOutcome(payload=payload)
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)
    except FileNotFoundError as exc:
        return AnalysisOutcome(error=str(exc), status_code=502, retry=True)

    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return AnalysisOutcome(error="Analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = result.from_cache
    payload["is_stale"] = bool(payload["is_stale"] or result.is_stale)
    return AnalysisOutcome(payload=payload)
