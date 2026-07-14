"""AI analysis workflow services for the FastAPI web interface."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.context_builder import build_sentence_prompt, build_word_prompt, get_sentence_info
from app.ai.ai_provider_config import get_ai_provider_settings, get_pro_analysis_model
from app.ai.ai_json_schemas import PARAGRAPH_LOGIC_LENS_SCHEMA
from app.ai.ai_response_cache import compute_content_hash, save_to_cache
from app.ai.json_output_validator import parse_and_validate
from app.ai.llm_paragraph_analyzer import (
    analyze_paragraph_logic,
    build_paragraph_logic_prompt,
)
from app.ai.analysis_saver import _word_analysis_schema, save_sentence_analysis
from app.cards.sentence_card_service import (
    save_sentence_structure,
    save_sentence_translation,
)
from app.cards.word_card_service import (
    create_or_update_word_card,
    get_word_card,
    list_word_card_sources,
    record_word_card_diagnosis,
)
from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.web.config import _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION
from app.web.queries import (
    _active_sentence_prompt_version,
    _active_word_prompt_version,
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
_EXTERNAL_SENTENCE_DEFAULT_CONFIDENCE = 0.8
_MAX_SENTENCE_ERROR_CODES = 3
_MAX_WORD_ERROR_CODES = 2
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
- 最后 JSON 的顶层必须包含 PROJECT JSON CONTRACT 要求的所有字段，尤其不要漏掉 `confidence`。
- `confidence` 是必填顶层字段，必须是 0.0 到 1.0 之间的数字；不确定时也要给出合理置信度，例如 0.82。
- 输出最终 JSON 前，先自检这些顶层字段都存在：`subject_skeleton`, `clauses`, `modifiers`, `logic_markers`, `anaphora`, `simplified_en`, `chinese_gloss`, `blocking_point`, `argument_role`, `argument_role_reason`, `argument_role_check`, `predicted_error_types`, `diagnosis_basis`, `diagnosed_error_types`, `diagnosis_evidence`, `takeaway_suggestion`, `confidence`。
- JSON 内不要写注释。
- JSON 后不要追加任何内容。
- 只输出一个 ```json 代码块```，不要输出其他代码块。
- 保存时系统只读取最后这个 JSON 代码块；中文讲解是给人看的。
- 如果 PROJECT JSON CONTRACT 要求“Return JSON only”，只把这条要求用于最后的 JSON 代码块；前面的中文讲解仍然要输出。
- 当前分析模式：{mode}

PROJECT JSON CONTRACT:

{project_prompt}
"""


def build_external_word_prompt_for_selection(
    db: DatabaseConnection,
    *,
    sentence_id: int,
    surface_form: str,
    lexical_type: str,
    start_offset: int | None = None,
    end_offset: int | None = None,
    learner_note: str = "",
) -> dict[str, Any]:
    """Build an external word prompt from a fresh Reader selection."""
    selection = _validated_word_selection(
        db,
        sentence_id=sentence_id,
        surface_form=surface_form,
        lexical_type=lexical_type,
        start_offset=start_offset,
        end_offset=end_offset,
    )
    prompt = _external_word_prompt(
        db,
        sentence_id=sentence_id,
        surface_form=selection["surface_form"],
        lexical_type=selection["lexical_type"],
        learner_note=learner_note,
    )
    return {
        "ok": True,
        "sentence_id": sentence_id,
        "surface_form": selection["surface_form"],
        "lexical_type": selection["lexical_type"],
        "start_offset": selection["start_offset"],
        "end_offset": selection["end_offset"],
        "prompt": prompt,
    }


def build_external_word_prompt_for_card(
    db: DatabaseConnection,
    card_id: int,
) -> dict[str, Any]:
    """Build an external word prompt for an existing word card."""
    card = get_word_card(db, card_id)
    if card is None:
        raise ValueError("Word card not found.")
    sentence_id = int(card["first_sentence_id"])
    prompt = _external_word_prompt(
        db,
        sentence_id=sentence_id,
        surface_form=str(card["surface_form"] or ""),
        lexical_type=str(card.get("lexical_type") or LexicalType.WORD.value),
        learner_note=str(card.get("user_note") or ""),
    )
    return {
        "ok": True,
        "card_id": card_id,
        "sentence_id": sentence_id,
        "surface_form": card["surface_form"],
        "lexical_type": card.get("lexical_type") or LexicalType.WORD.value,
        "prompt": prompt,
    }


def _external_word_prompt(
    db: DatabaseConnection,
    *,
    sentence_id: int,
    surface_form: str,
    lexical_type: str,
    learner_note: str = "",
) -> str:
    project_prompt = build_word_prompt(db, sentence_id, surface_form)
    note_line = learner_note.strip() or "(none)"
    return f"""你将帮助一名中文母语的英语学习者快速理解英文原文中的陌生词、短语或搭配。

请按下面顺序输出：

1. 先输出给人看的中文讲解，第一行必须精确标明：
目标项：{surface_form}（{lexical_type}）

然后继续讲解，必须包含：
- 目标项在本句中的准确意思
- 它在句子中的语法/语义作用
- 容易误读的地方
- 作者为什么选这个表达而不是更简单表达
- 一个最短记忆提示

2. 最后单独输出一个 ```json 代码块```，用于保存到英语阅读理解专项训练系统。

JSON 规则：
- JSON 必须严格符合下方 PROJECT JSON CONTRACT 的 schema。
- lexical_type 必须优先使用：{lexical_type}
- TARGET ITEM 必须保持为：{surface_form}
- lemma 可以写词典形或规范形式；但 role_in_sentence 必须明确点名本次选中的表层形式 “{surface_form}”。
- learner_note_check 只评价 learner note，不要让 learner note 覆盖本句语境义。
- JSON 内不要写注释。
- JSON 后不要追加任何内容。
- 只输出一个 ```json 代码块```，不要输出其他代码块。
- 保存时系统只读取最后这个 JSON 代码块；中文讲解是给人看的。
- 如果 PROJECT JSON CONTRACT 要求“Return JSON only”或“Do NOT output anything outside JSON”，只把这条要求用于最后的 JSON 代码块；前面的中文讲解仍然要输出。

CURRENT SELECTION:
- target item: {surface_form}
- lexical_type: {lexical_type}
- learner note: {note_line}

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
        raw_json = _normalize_external_sentence_json(
            extract_external_json_block(external_result)
        )
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


def save_external_word_analysis_for_selection(
    db: DatabaseConnection,
    *,
    sentence_id: int,
    surface_form: str,
    lexical_type: str,
    external_result: str,
    start_offset: int | None = None,
    end_offset: int | None = None,
    learner_note: str = "",
) -> AnalysisOutcome:
    """Validate external JSON, create/update the selected word card, and render it."""
    try:
        selection = _validated_word_selection(
            db,
            sentence_id=sentence_id,
            surface_form=surface_form,
            lexical_type=lexical_type,
            start_offset=start_offset,
            end_offset=end_offset,
        )
        validation = _validate_external_word_json(
            db,
            sentence_id=sentence_id,
            surface_form=selection["surface_form"],
            lexical_type=selection["lexical_type"],
            external_result=external_result,
        )
        if validation.is_error:
            return validation
        card_id, _created = create_or_update_word_card(
            db,
            sentence_id,
            selection["surface_form"],
            LexicalType(selection["lexical_type"]),
            user_note=learner_note,
            source_start_offset=selection["start_offset"],
            source_end_offset=selection["end_offset"],
            selected_text=selection["surface_form"],
        )
        outcome = _attach_external_word_analysis(
            db,
            card_id,
            surface_form=selection["surface_form"],
            data=validation.payload["analysis"],
            prompt_version=validation.payload["prompt_version"],
            sentence_text=validation.payload["sentence_text"],
        )
        if outcome.is_error:
            return outcome
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)

    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return AnalysisOutcome(error="External word analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = False
    payload["is_stale"] = False
    payload["word_card"] = _word_card_payload(db, card_id)
    payload["source"] = _matching_word_source(
        db,
        card_id=card_id,
        sentence_id=sentence_id,
        surface_form=selection["surface_form"],
        start_offset=selection["start_offset"],
        end_offset=selection["end_offset"],
    )
    return AnalysisOutcome(payload=payload)


def save_external_word_analysis_for_card(
    db: DatabaseConnection,
    card_id: int,
    *,
    external_result: str,
) -> AnalysisOutcome:
    """Validate external JSON and replace an existing word card analysis."""
    card = get_word_card(db, card_id)
    if card is None:
        return AnalysisOutcome(error="Word card not found.", status_code=404)
    validation = _validate_external_word_json(
        db,
        sentence_id=int(card["first_sentence_id"]),
        surface_form=str(card["surface_form"] or ""),
        lexical_type=str(card.get("lexical_type") or LexicalType.WORD.value),
        external_result=external_result,
    )
    if validation.is_error:
        return validation
    outcome = _attach_external_word_analysis(
        db,
        card_id,
        surface_form=str(card["surface_form"] or ""),
        data=validation.payload["analysis"],
        prompt_version=validation.payload["prompt_version"],
        sentence_text=validation.payload["sentence_text"],
    )
    if outcome.is_error:
        return outcome
    payload = _fetch_word_analysis_payload(db, card_id)
    if payload is None:
        return AnalysisOutcome(error="External word analysis was not saved.", status_code=500, retry=True)
    payload["from_cache"] = False
    payload["is_stale"] = False
    payload["word_card"] = _word_card_payload(db, card_id)
    return AnalysisOutcome(payload=payload)


def _validate_external_word_json(
    db: DatabaseConnection,
    *,
    sentence_id: int,
    surface_form: str,
    lexical_type: str = LexicalType.WORD.value,
    external_result: str,
) -> AnalysisOutcome:
    try:
        raw_json = _normalize_external_word_json(
            extract_external_json_block(external_result),
            lexical_type=lexical_type,
        )
        prompt_version = _active_word_prompt_version(db)
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    try:
        data = parse_and_validate(raw_json, _word_analysis_schema(prompt_version))
    except Exception as exc:
        return AnalysisOutcome(
            error=f"External JSON failed validation: {exc}",
            status_code=400,
            retry=False,
        )
    try:
        sentence = _fetch_sentence_for_analysis(db, sentence_id)
    except ValueError as exc:
        return AnalysisOutcome(error=str(exc), status_code=400, retry=False)
    return AnalysisOutcome(
        payload={
            "analysis": data,
            "prompt_version": prompt_version,
            "sentence_text": str(sentence["text"] or ""),
            "surface_form": surface_form,
        }
    )


def _attach_external_word_analysis(
    db: DatabaseConnection,
    card_id: int,
    *,
    surface_form: str,
    data: dict[str, Any],
    prompt_version: str,
    sentence_text: str,
) -> AnalysisOutcome:
    cache_id = save_to_cache(
        db,
        compute_content_hash(surface_form + " | " + sentence_text, ""),
        prompt_version,
        _EXTERNAL_MODEL_NAME,
        json.dumps(data, ensure_ascii=False),
        True,
        replace_valid=True,
    )
    with db.get_connection() as conn:
        conn.execute(
            """UPDATE word_cards
                  SET current_meaning = ?,
                      pos = ?,
                      lexical_type = ?,
                      ai_analysis_id = ?,
                      archived_at = NULL
                WHERE id = ? AND archived_at IS NULL""",
            (
                data.get("meaning_in_context", ""),
                data.get("pos", ""),
                data.get("lexical_type", LexicalType.WORD.value),
                cache_id,
                card_id,
            ),
        )
    record_word_card_diagnosis(db, card_id, data)
    return AnalysisOutcome(payload={"ok": True})


def extract_external_json_block(external_result: str) -> str:
    """Return the last fenced JSON block, or raw JSON when only JSON was pasted."""
    text = str(external_result or "").strip()
    matches = [match.strip() for match in _JSON_FENCE_RE.findall(text) if match.strip()]
    if matches:
        return matches[-1]
    if text.startswith("{") and text.endswith("}"):
        return text
    embedded = _largest_embedded_json_object(text)
    if embedded:
        return embedded
    raise ValueError("Paste an external AI reply ending with a ```json code block```.")


def _largest_embedded_json_object(text: str) -> str:
    decoder = json.JSONDecoder()
    best = ""
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidate = text[index:end].strip()
            if len(candidate) > len(best):
                best = candidate
    return best


def _normalize_external_sentence_json(raw_json: str) -> str:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return raw_json
    if not isinstance(data, dict):
        return raw_json
    if "confidence" not in data:
        data["confidence"] = _EXTERNAL_SENTENCE_DEFAULT_CONFIDENCE
    for field in ("predicted_error_types", "diagnosed_error_types"):
        error_codes = data.get(field)
        if isinstance(error_codes, list):
            data[field] = error_codes[:_MAX_SENTENCE_ERROR_CODES]
    return json.dumps(data, ensure_ascii=False)


def _normalize_external_word_json(raw_json: str, *, lexical_type: str) -> str:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return raw_json
    if not isinstance(data, dict):
        return raw_json
    try:
        data["lexical_type"] = LexicalType(lexical_type).value
    except ValueError:
        return raw_json
    error_codes = data.get("predicted_error_types")
    if isinstance(error_codes, list):
        data["predicted_error_types"] = error_codes[:_MAX_WORD_ERROR_CODES]
    return json.dumps(data, ensure_ascii=False)


def _sentence_context_text(db: DatabaseConnection, sentence_id: int) -> str:
    try:
        return str(get_sentence_info(db, sentence_id).get("context") or "")
    except Exception:
        return ""


def _validated_word_selection(
    db: DatabaseConnection,
    *,
    sentence_id: int,
    surface_form: str,
    lexical_type: str,
    start_offset: int | None = None,
    end_offset: int | None = None,
) -> dict[str, Any]:
    clean_surface = surface_form.strip()
    if not clean_surface:
        raise ValueError("surface_form must not be empty.")
    try:
        clean_type = LexicalType(lexical_type or LexicalType.WORD.value).value
    except ValueError as exc:
        raise ValueError(f"Invalid lexical_type: {lexical_type}") from exc
    if (start_offset is None) != (end_offset is None):
        raise ValueError("selection offsets must include both start and end.")

    sentence = _fetch_sentence_for_analysis(db, sentence_id)
    sentence_text = str(sentence["text"] or "")
    selected_text = clean_surface
    if start_offset is not None and end_offset is not None:
        if start_offset < 0 or end_offset <= start_offset or end_offset > len(sentence_text):
            raise ValueError("selection offsets are outside the sentence text.")
        selected_text = sentence_text[start_offset:end_offset]
        if selected_text != clean_surface:
            raise ValueError("selection offsets do not match the selected text.")

    return {
        "surface_form": selected_text,
        "lexical_type": clean_type,
        "start_offset": start_offset,
        "end_offset": end_offset,
    }


def _word_card_payload(db: DatabaseConnection, card_id: int) -> dict[str, Any] | None:
    card = get_word_card(db, card_id)
    if card is None:
        return None
    return {
        "id": card["id"],
        "lemma": card["lemma"],
        "surface_form": card["surface_form"],
        "lexical_type": card["lexical_type"],
        "current_meaning": card.get("current_meaning") or "",
        "user_note": card.get("user_note") or "",
    }


def _matching_word_source(
    db: DatabaseConnection,
    *,
    card_id: int,
    sentence_id: int,
    surface_form: str,
    start_offset: int | None,
    end_offset: int | None,
) -> dict[str, Any] | None:
    source_key = surface_form.lower().strip()
    for source in list_word_card_sources(db, card_id):
        if int(source["sentence_id"]) != int(sentence_id):
            continue
        if str(source["source_key"]) != source_key:
            continue
        if start_offset is not None and end_offset is not None:
            if source["start_offset"] != start_offset or source["end_offset"] != end_offset:
                continue
        elif source["start_offset"] is not None or source["end_offset"] is not None:
            continue
        return {
            "id": source["id"],
            "sentence_id": source["sentence_id"],
            "start_offset": source["start_offset"],
            "end_offset": source["end_offset"],
            "selected_text": source["selected_text"] or "",
        }
    return None


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
