"""Tests for web AI analysis workflow services."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.db_connection import DatabaseConnection
from app.web.services import analysis

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _seed_sentence_text(db: DatabaseConnection, text: str) -> int:
    with db.get_connection() as conn:
        book_id = conn.execute(
            "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
            "VALUES ('B', '', 'txt', ?, '2026-01-01T00:00:00+00:00')",
            (f"hash_service_{abs(hash(text))}",),
        ).lastrowid
        chapter_id = conn.execute(
            "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
            "VALUES (?, 1, 'Ch', 0, 1)",
            (book_id,),
        ).lastrowid
        paragraph_id = conn.execute(
            "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
            "VALUES (?, 1, 0, 1)",
            (chapter_id,),
        ).lastrowid
        return conn.execute(
            """INSERT INTO sentences
               (book_id, chapter_id, paragraph_id, idx, text, text_hash,
                char_offset_start, char_offset_end)
               VALUES (?, ?, ?, 0, ?, ?, 0, ?)""",
            (book_id, chapter_id, paragraph_id, text, f"sent_{abs(hash(text))}", len(text)),
        ).lastrowid


def _valid_paragraph_logic() -> dict:
    return {
        "paragraph_main_claim": "Consult the importer or freight forwarder first.",
        "argument_flow": [
            {
                "sentence_id": 57819,
                "sentence_text": "The first step is to ask your foreign customer.",
                "role": "claim",
                "reason": "States the core recommendation.",
            },
            {
                "sentence_id": 57820,
                "sentence_text": "Correct information helps the customer clear customs.",
                "role": "evidence",
                "reason": "Explains the practical benefit.",
            },
        ],
        "evidence": ["Correct information helps customs clearance."],
        "concession_or_counterpoint": "",
        "hidden_assumption": "Importers know local requirements.",
        "author_stance": "Practical and instructive.",
        "possible_misreading": "Treating common documents as universally enough.",
        "reading_check": "Notice the qualification after the common list.",
        "takeaway_suggestion": "Watch for exceptions after general guidance.",
    }


def _valid_word_analysis() -> dict:
    return {
        "lemma": "evidence",
        "lexical_type": "word",
        "pos": "verb",
        "meaning_in_context": "shown to exist or be present in an observable way",
        "chinese_meaning": "被证明存在",
        "role_in_sentence": "It modifies the nearby noun and narrows the claim.",
        "register": "formal",
        "why_this_word": "Evidenced is more formal than shown and fits analytic prose.",
        "vs_simpler": [
            {
                "simpler": "shown",
                "difference": "Shown is plainer; evidenced implies proof or trace.",
            }
        ],
        "learner_note_check": {
            "status": "not_provided",
            "feedback": "",
            "corrected_understanding": "",
        },
        "morphology": {"root": "", "family": ["evidence", "evident"]},
        "predicted_error_types": ["L01"],
        "confidence": 0.9,
    }


def test_analysis_outcome_error_payload_omits_retry_when_unspecified() -> None:
    outcome = analysis.AnalysisOutcome(error="missing", status_code=404)

    assert outcome.error_payload() == {"ok": False, "error": "missing"}


def test_analyze_word_card_for_reader_returns_404_for_missing_card(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "get_word_card", lambda db, card_id: None)

    outcome = analysis.analyze_word_card_for_reader(object(), 123)

    assert outcome.status_code == 404
    assert outcome.error_payload() == {"ok": False, "error": "Word card not found."}


def test_analyze_sentence_for_reader_maps_invalid_ai_response(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        fastapi_app,
        "analyze_sentence",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
    )

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }


def test_analyze_paragraph_logic_for_reader_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_for_logic",
        lambda db, paragraph_id: {
            "text": "First. Second.",
            "context": "Previous paragraph: Setup.",
            "sentences": [{"id": 10, "text": "First."}],
        },
    )
    monkeypatch.setattr(
        analysis,
        "analyze_paragraph_logic",
        lambda *args, **kwargs: SimpleNamespace(
            data={"paragraph_main_claim": "Claim"},
            cache_id=9,
            from_cache=False,
            is_stale=False,
            is_valid=True,
            prompt_version="paragraph_logic_lens.v4",
            model="model",
        ),
    )

    outcome = analysis.analyze_paragraph_logic_for_reader(object(), 3)

    assert outcome.is_error is False
    assert outcome.payload == {
        "ok": True,
        "paragraph_id": 3,
        "cache_id": 9,
        "prompt_version": "paragraph_logic_lens.v4",
        "active_prompt_version": "paragraph_logic_lens.v4",
        "model": "model",
        "is_stale": False,
        "from_cache": False,
        "paragraph_text": "First. Second.",
        "sentences": [{"id": 10, "text": "First."}],
        "context": "Previous paragraph: Setup.",
        "analysis": {"paragraph_main_claim": "Claim"},
    }


def test_analyze_paragraph_logic_for_reader_maps_invalid_ai_response(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_for_logic",
        lambda db, paragraph_id: {"text": "First.", "context": "", "sentences": []},
    )
    monkeypatch.setattr(
        analysis,
        "analyze_paragraph_logic",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )

    outcome = analysis.analyze_paragraph_logic_for_reader(object(), 3)

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }


def test_analyze_paragraph_logic_for_reader_maps_value_error(monkeypatch) -> None:
    def fail_fetch(db, paragraph_id):
        raise ValueError("Paragraph id=3 not found.")

    monkeypatch.setattr(analysis, "_fetch_paragraph_for_logic", fail_fetch)

    outcome = analysis.analyze_paragraph_logic_for_reader(object(), 3)

    assert outcome.status_code == 400
    assert outcome.error_payload() == {
        "ok": False,
        "error": "Paragraph id=3 not found.",
        "retry": False,
    }


def test_analyze_paragraph_logic_for_reader_maps_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_for_logic",
        lambda db, paragraph_id: {"text": "First.", "context": "", "sentences": []},
    )

    def fail_analysis(*args, **kwargs):
        raise RuntimeError("LLM call failed")

    monkeypatch.setattr(analysis, "analyze_paragraph_logic", fail_analysis)

    outcome = analysis.analyze_paragraph_logic_for_reader(object(), 3)

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "LLM call failed",
        "retry": True,
    }


def test_build_external_paragraph_logic_prompt_wraps_project_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_for_logic",
        lambda db, paragraph_id: {
            "text": "First. Second.",
            "context": "Previous paragraph: Setup.",
            "sentences": [{"id": 10, "text": "First."}],
        },
    )
    monkeypatch.setattr(
        analysis,
        "build_paragraph_logic_prompt",
        lambda paragraph_text, sentence_lines, context: (
            f"PROJECT PARAGRAPH {paragraph_text} {sentence_lines} {context}"
        ),
    )

    prompt = analysis.build_external_paragraph_logic_prompt(object(), 3)

    assert "段落的论证结构" in prompt
    assert "```json 代码块```" in prompt
    assert "只输出一个 ```json 代码块```" in prompt
    assert "系统只读取最后这个 JSON 代码块" in prompt
    assert "必须引用原始英文句子文本" in prompt
    assert "sentence_text 写原始英文句子" in prompt
    assert "专业角色标签" in prompt
    assert "Role guide" in prompt
    assert "不要把背景或过渡句误标为 evidence" in prompt
    assert "PROJECT PARAGRAPH First. Second." in prompt
    assert "sentence_id 10" in prompt


def test_save_external_paragraph_logic_accepts_markdown_reply(monkeypatch) -> None:
    saved: dict[str, object] = {}
    valid_json = _valid_paragraph_logic()

    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_for_logic",
        lambda db, paragraph_id: {
            "text": "First. Second.",
            "context": "Previous paragraph: Setup.",
            "sentences": [{"id": 57819, "text": "First."}],
        },
    )

    def fake_save_to_cache(*args, **kwargs):
        saved["args"] = args
        saved["kwargs"] = kwargs
        return 42

    monkeypatch.setattr(analysis, "save_to_cache", fake_save_to_cache)

    outcome = analysis.save_external_paragraph_logic_for_reader(
        object(),
        3,
        external_result=(
            "## 中文讲解\n\n"
            "先给人看的解释。\n\n"
            "```json\n"
            f"{json.dumps(valid_json, ensure_ascii=False)}\n"
            "```"
        ),
    )

    assert outcome.is_error is False
    assert outcome.payload == {
        "ok": True,
        "paragraph_id": 3,
        "cache_id": 42,
        "prompt_version": "paragraph_logic_lens.v4",
        "active_prompt_version": "paragraph_logic_lens.v4",
        "model": "external-ai",
        "is_stale": False,
        "from_cache": False,
        "paragraph_text": "First. Second.",
        "sentences": [{"id": 57819, "text": "First."}],
        "context": "Previous paragraph: Setup.",
        "analysis": valid_json,
    }
    assert saved["args"][2] == "paragraph_logic_lens.v4"
    assert saved["args"][3] == "external-ai"
    assert saved["args"][5] is True
    assert saved["kwargs"] == {"replace_valid": True}


def test_save_external_paragraph_logic_reports_validation_error(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_paragraph_for_logic",
        lambda db, paragraph_id: {"text": "First.", "context": "", "sentences": []},
    )

    outcome = analysis.save_external_paragraph_logic_for_reader(
        object(),
        3,
        external_result='```json\n{"bad": true}\n```',
    )

    assert outcome.status_code == 400
    assert outcome.error_payload()["ok"] is False
    assert outcome.error_payload()["retry"] is False
    assert outcome.error_payload()["error"].startswith("External JSON failed validation:")


def test_save_external_paragraph_logic_maps_value_error(monkeypatch) -> None:
    def fail_fetch(db, paragraph_id):
        raise ValueError("Paragraph id=3 not found.")

    monkeypatch.setattr(analysis, "_fetch_paragraph_for_logic", fail_fetch)

    outcome = analysis.save_external_paragraph_logic_for_reader(
        object(),
        3,
        external_result=(
            "```json\n"
            f"{json.dumps(_valid_paragraph_logic(), ensure_ascii=False)}\n"
            "```"
        ),
    )

    assert outcome.status_code == 400
    assert outcome.error_payload() == {
        "ok": False,
        "error": "Paragraph id=3 not found.",
        "retry": False,
    }


def test_analyze_sentence_for_reader_maps_value_error(monkeypatch) -> None:
    def fail_fetch(db, sentence_id):
        raise ValueError("Sentence id=1 not found.")

    monkeypatch.setattr(analysis, "_fetch_sentence_for_analysis", fail_fetch)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
    )

    assert outcome.status_code == 400
    assert outcome.error_payload() == {
        "ok": False,
        "error": "Sentence id=1 not found.",
        "retry": False,
    }


def test_analyze_sentence_for_reader_reports_when_payload_was_not_saved(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v1")
    monkeypatch.setattr(analysis, "save_sentence_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr(analysis, "_fetch_sentence_analysis_payload", lambda db, sid: None)
    monkeypatch.setattr(
        fastapi_app,
        "analyze_sentence",
        lambda *args, **kwargs: SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        ),
    )

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
    )

    assert outcome.status_code == 500
    assert outcome.error_payload() == {
        "ok": False,
        "error": "Analysis was not saved.",
        "retry": True,
    }


def test_extract_external_json_block_uses_last_json_fence() -> None:
    pasted = (
        "讲解\n"
        "```json\n"
        "{\"subject_skeleton\":\"old\"}\n"
        "```\n"
        "最后保存这个：\n"
        "```JSON\n"
        "{\"subject_skeleton\":\"new\"}\n"
        "```"
    )

    assert analysis.extract_external_json_block(pasted) == '{"subject_skeleton":"new"}'


def test_extract_external_json_block_accepts_raw_json() -> None:
    assert analysis.extract_external_json_block('{"ok": true}') == '{"ok": true}'


def test_extract_external_json_block_accepts_embedded_raw_json() -> None:
    pasted = '说明文字 “{"outer": {"inner": true}, "subject_skeleton": "It happens"}”，'

    assert analysis.extract_external_json_block(pasted) == (
        '{"outer": {"inner": true}, "subject_skeleton": "It happens"}'
    )


def test_extract_external_json_block_rejects_free_text() -> None:
    outcome = analysis.save_external_sentence_analysis_for_reader(
        object(),
        1,
        external_result="Only an explanation, no JSON.",
    )

    assert outcome.status_code == 400
    assert "```json code block```" in outcome.error_payload()["error"]


def test_build_external_sentence_prompt_wraps_project_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {
            "text": "The cat sat.",
            "user_translation": "猫坐着。",
            "user_structure": "主干：cat sat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "build_sentence_prompt",
        lambda db, sentence_id, user_translation=None, user_structure=None: (
            f"PROJECT PROMPT {user_translation} {user_structure}"
        ),
    )

    prompt = analysis.build_external_sentence_prompt(object(), 1)

    assert "先输出给人看的中文讲解" in prompt
    assert "```json 代码块```" in prompt
    assert "当前分析模式：诊断模式" in prompt
    assert "尤其不要漏掉 `confidence`" in prompt
    assert "`confidence` 是必填顶层字段" in prompt
    assert "`takeaway_suggestion`, `confidence`" in prompt
    assert "只输出一个 ```json 代码块```" in prompt
    assert "PROJECT PROMPT 猫坐着。 主干：cat sat" in prompt


def test_build_external_word_prompt_for_selection_uses_offsets_and_contract(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The blocker was evidenced clearly."},
    )
    monkeypatch.setattr(
        analysis,
        "build_word_prompt",
        lambda db, sentence_id, surface_form: f"PROJECT WORD {sentence_id} {surface_form}",
    )

    payload = analysis.build_external_word_prompt_for_selection(
        object(),
        sentence_id=9,
        surface_form="evidenced",
        lexical_type="word",
        start_offset=16,
        end_offset=25,
    )

    assert payload["ok"] is True
    assert payload["surface_form"] == "evidenced"
    assert payload["lexical_type"] == "word"
    assert payload["start_offset"] == 16
    assert payload["end_offset"] == 25
    assert "陌生词、短语或搭配" in payload["prompt"]
    assert "目标项：evidenced（word）" in payload["prompt"]
    assert "lexical_type 必须优先使用：word" in payload["prompt"]
    assert "TARGET ITEM 必须保持为：evidenced" in payload["prompt"]
    assert "role_in_sentence 必须明确点名本次选中的表层形式 “evidenced”" in payload[
        "prompt"
    ]
    assert "PROJECT WORD 9 evidenced" in payload["prompt"]


def test_build_external_word_prompt_for_selection_rejects_bad_offsets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The blocker was evidenced clearly."},
    )

    try:
        analysis.build_external_word_prompt_for_selection(
            object(),
            sentence_id=9,
            surface_form="evidenced",
            lexical_type="word",
            start_offset=0,
            end_offset=3,
        )
    except ValueError as exc:
        assert str(exc) == "selection offsets do not match the selected text."
    else:
        raise AssertionError("Expected ValueError")


def test_build_external_word_prompt_for_card_uses_note(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 9,
            "surface_form": "evidenced",
            "lexical_type": "word",
            "user_note": "不是名词 evidence",
        },
    )
    monkeypatch.setattr(
        analysis,
        "build_word_prompt",
        lambda db, sentence_id, surface_form: f"PROJECT WORD {sentence_id} {surface_form}",
    )

    payload = analysis.build_external_word_prompt_for_card(object(), 7)

    assert payload["ok"] is True
    assert payload["card_id"] == 7
    assert payload["sentence_id"] == 9
    assert "learner note: 不是名词 evidence" in payload["prompt"]


def test_save_external_word_selection_returns_word_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_validated_word_selection",
        lambda *args, **kwargs: {
            "surface_form": "evidenced",
            "lexical_type": "word",
            "start_offset": 16,
            "end_offset": 25,
        },
    )
    def fake_create_or_update_word_card(*args, **kwargs):
        captured["create_args"] = (args, kwargs)
        return 7, True

    def fake_validate_external_word_json(*args, **kwargs):
        captured["validate_args"] = (args, kwargs)
        return analysis.AnalysisOutcome(
            payload={
                "analysis": _valid_word_analysis(),
                "prompt_version": "v5",
                "sentence_text": "The blocker was evidenced clearly.",
            }
        )

    def fake_attach_external_word_analysis(*args, **kwargs):
        captured["attach_args"] = (args, kwargs)
        return analysis.AnalysisOutcome(payload={"ok": True})

    monkeypatch.setattr(
        analysis,
        "create_or_update_word_card",
        fake_create_or_update_word_card,
    )
    monkeypatch.setattr(
        analysis,
        "_validate_external_word_json",
        fake_validate_external_word_json,
    )
    monkeypatch.setattr(
        analysis,
        "_attach_external_word_analysis",
        fake_attach_external_word_analysis,
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"ok": True, "card_id": card_id, "is_stale": True},
    )
    monkeypatch.setattr(
        analysis,
        "_word_card_payload",
        lambda db, card_id: {"id": card_id, "surface_form": "evidenced"},
    )
    monkeypatch.setattr(
        analysis,
        "_matching_word_source",
        lambda *args, **kwargs: {"id": 3, "sentence_id": 9},
    )

    outcome = analysis.save_external_word_analysis_for_selection(
        object(),
        sentence_id=9,
        surface_form="evidenced",
        lexical_type="word",
        start_offset=16,
        end_offset=25,
        external_result='```json\n{"lemma":"evidence"}\n```',
    )

    assert outcome.is_error is False
    assert outcome.payload == {
        "ok": True,
        "card_id": 7,
        "is_stale": False,
        "from_cache": False,
        "word_card": {"id": 7, "surface_form": "evidenced"},
        "source": {"id": 3, "sentence_id": 9},
    }
    assert captured["create_args"][0][1:4] == (9, "evidenced", analysis.LexicalType.WORD)
    assert captured["validate_args"][1]["surface_form"] == "evidenced"
    assert captured["attach_args"][1]["surface_form"] == "evidenced"


def test_save_external_word_card_returns_404_for_missing_card(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "get_word_card", lambda db, card_id: None)

    outcome = analysis.save_external_word_analysis_for_card(
        object(),
        7,
        external_result="{}",
    )

    assert outcome.status_code == 404
    assert outcome.error_payload() == {"ok": False, "error": "Word card not found."}


def test_save_external_word_selection_preserves_selected_card_when_lemma_differs(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "external_word.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence_text(db, "The blocker was evidenced clearly.")

    outcome = analysis.save_external_word_analysis_for_selection(
        db,
        sentence_id=sentence_id,
        surface_form="evidenced",
        lexical_type="word",
        start_offset=16,
        end_offset=25,
        external_result=(
            "中文讲解\n"
            "```json\n"
            f"{json.dumps(_valid_word_analysis(), ensure_ascii=False)}\n"
            "```"
        ),
    )

    assert outcome.is_error is False
    assert outcome.payload is not None
    assert outcome.payload["surface_form"] == "evidenced"
    assert outcome.payload["analysis"]["lemma"] == "evidence"
    assert outcome.payload["source"]["start_offset"] == 16
    assert outcome.payload["source"]["end_offset"] == 25
    assert outcome.payload["word_card"]["surface_form"] == "evidenced"
    assert outcome.payload["word_card"]["current_meaning"] == (
        "shown to exist or be present in an observable way"
    )
    with db.get_connection() as conn:
        rows = conn.execute("SELECT lemma, surface_form FROM word_cards").fetchall()
    assert [(row["lemma"], row["surface_form"]) for row in rows] == [
        ("evidenced", "evidenced")
    ]


def test_save_external_word_selection_rejects_invalid_json_before_card_create(
    tmp_path: Path,
) -> None:
    db = DatabaseConnection(tmp_path / "external_word_invalid.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence_text(db, "The blocker was evidenced clearly.")

    outcome = analysis.save_external_word_analysis_for_selection(
        db,
        sentence_id=sentence_id,
        surface_form="evidenced",
        lexical_type="word",
        start_offset=16,
        end_offset=25,
        external_result='```json\n{"bad": true}\n```',
    )

    assert outcome.status_code == 400
    assert outcome.error_payload()["error"].startswith("External JSON failed validation:")
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM word_cards").fetchone()["count"]
    assert count == 0


def test_save_external_sentence_analysis_reuses_saver_and_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "save_sentence_translation",
        lambda db, sentence_id, value: captured.update(translation=value),
    )
    monkeypatch.setattr(
        analysis,
        "save_sentence_structure",
        lambda db, sentence_id, value: captured.update(structure=value),
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": "猫坐着。"},
    )
    def fake_active_sentence_prompt_version(db, user_translation):
        captured["prompt_basis"] = user_translation
        return "v6"

    monkeypatch.setattr(
        analysis,
        "_active_sentence_prompt_version",
        fake_active_sentence_prompt_version,
    )

    def fake_save_sentence_analysis(
        db,
        sentence_id,
        raw_json,
        model,
        prompt_version,
        context="",
    ):
        captured.update(
            sentence_id=sentence_id,
            raw_json=raw_json,
            model=model,
            prompt_version=prompt_version,
            context=context,
        )
        return SimpleNamespace(is_valid=True, error="")

    monkeypatch.setattr(analysis, "save_sentence_analysis", fake_save_sentence_analysis)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"ok": True, "sentence_id": sentence_id, "is_stale": True},
    )

    outcome = analysis.save_external_sentence_analysis_for_reader(
        object(),
        3,
        external_result='```json\n{"subject_skeleton":"cat sat"}\n```',
        user_translation="猫坐着。",
        user_structure="主干：cat sat",
    )

    assert outcome.is_error is False
    assert outcome.payload == {
        "ok": True,
        "sentence_id": 3,
        "is_stale": False,
        "from_cache": False,
    }
    saved_json = json.loads(str(captured.pop("raw_json")))
    assert captured == {
        "translation": "猫坐着。",
        "structure": "主干：cat sat",
        "prompt_basis": "猫坐着。",
        "sentence_id": 3,
        "model": "external-ai",
        "prompt_version": "v6",
        "context": "",
    }
    assert saved_json == {
        "subject_skeleton": "cat sat",
        "confidence": 0.8,
    }


def test_save_external_sentence_analysis_adds_missing_confidence_for_v7_json(
    tmp_path,
    monkeypatch,
) -> None:
    db = DatabaseConnection(tmp_path / "external_sentence_missing_confidence.db")
    db.apply_migrations(MIGRATIONS_DIR)
    sentence_id = _seed_sentence_text(
        db,
        "Well, it just so happens that since Breslin has gotten closer to "
        "Rottmayer, Rottmayer has developed a new edge to his defiance that "
        "wasn't there before.",
    )
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v7")

    pasted = {
        "subject_skeleton": "It happens",
        "clauses": [
            {
                "type": "main",
                "text": "Well, it just so happens",
                "role": "main predication introducing a formal sentence pattern",
            },
            {
                "type": "noun",
                "text": (
                    "that since Breslin has gotten closer to Rottmayer, "
                    "Rottmayer has developed a new edge to his defiance that "
                    "wasn't there before"
                ),
                "role": "subject clause post-posed after dummy it",
            },
        ],
        "modifiers": [
            {"target": "happens", "modifier": "just so", "type": "adverb"},
        ],
        "logic_markers": [{"marker": "since", "function": "cause"}],
        "anaphora": [{"pronoun": "it", "refers_to": "dummy subject"}],
        "simplified_en": "Coincidentally, Rottmayer became newly defiant.",
        "chinese_gloss": "碰巧的是，罗特梅耶的态度里多出了一股锋芒。",
        "blocking_point": "Isolating the nested since clause.",
        "argument_role": "claim",
        "argument_role_reason": "The sentence makes an accusatory observation.",
        "argument_role_check": "Check whether the correlation is being used as a claim.",
        "predicted_error_types": ["G03", "L01", "D01"],
        "diagnosis_basis": "predicted",
        "diagnosed_error_types": [],
        "diagnosis_evidence": [],
        "takeaway_suggestion": "先隔离 it happens that 内部的 since 从句。",
        "structure_feedback": {
            "is_correct": False,
            "missed_or_wrong": [
                {
                    "error_code": "G03",
                    "learner_claim": "since 是主语从句。",
                    "correction": "since 是嵌套在 that 从句内部的状语从句。",
                    "reason": "整个 that 块才是真正的主语从句。",
                }
            ],
            "correct_highlights": ["识别出 it happens that 句型。"],
            "corrected_structure": "It + happens + [that [since...], Rottmayer has developed ...].",
            "why_it_matters_for_translation": "避免把 it 当成普通指代代词。",
            "next_check": "先判断 it 是否为形式主语。",
        },
    }

    outcome = analysis.save_external_sentence_analysis_for_reader(
        db,
        sentence_id,
        external_result=json.dumps(pasted, ensure_ascii=False),
    )

    assert outcome.is_error is False
    assert outcome.payload is not None
    assert outcome.payload["analysis"]["confidence"] == 0.8
    assert outcome.payload["analysis"]["structure_feedback"]["is_correct"] is False


def test_save_external_sentence_analysis_reports_validation_error(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v6")
    monkeypatch.setattr(
        analysis,
        "save_sentence_analysis",
        lambda *a, **k: SimpleNamespace(is_valid=False, error="schema mismatch"),
    )

    outcome = analysis.save_external_sentence_analysis_for_reader(
        object(),
        1,
        external_result='```json\n{"bad": true}\n```',
    )

    assert outcome.status_code == 400
    assert outcome.error_payload() == {
        "ok": False,
        "error": "External JSON failed validation: schema mismatch",
        "retry": False,
    }


def test_save_external_sentence_analysis_reports_missing_saved_payload(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v6")
    monkeypatch.setattr(
        analysis,
        "save_sentence_analysis",
        lambda *a, **k: SimpleNamespace(is_valid=True, error=""),
    )
    monkeypatch.setattr(analysis, "_fetch_sentence_analysis_payload", lambda db, sid: None)

    outcome = analysis.save_external_sentence_analysis_for_reader(
        object(),
        1,
        external_result='```json\n{"subject_skeleton":"cat sat"}\n```',
    )

    assert outcome.status_code == 500
    assert outcome.error_payload() == {
        "ok": False,
        "error": "External analysis was not saved.",
        "retry": True,
    }


def test_analyze_sentence_for_reader_uses_pro_model_when_requested(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v1")
    monkeypatch.setattr(analysis, "save_sentence_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"is_stale": False},
    )
    monkeypatch.setattr(analysis, "get_pro_analysis_model", lambda: "deepseek-test-pro")

    def fake_analyze_sentence(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_sentence", fake_analyze_sentence)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
        prefer_pro=True,
    )

    assert outcome.is_error is False
    assert captured["model"] == "deepseek-test-pro"


def test_analyze_sentence_for_reader_passes_force_refresh(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v1")
    monkeypatch.setattr(analysis, "_sentence_context_text", lambda db, sentence_id: "Before. >>> The cat sat. <<< After.")

    def fake_save_sentence_analysis(*args, **kwargs):
        captured["saved_context"] = kwargs.get("context")

    monkeypatch.setattr(analysis, "save_sentence_analysis", fake_save_sentence_analysis)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"is_stale": False},
    )

    def fake_analyze_sentence(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_sentence", fake_analyze_sentence)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
        force_refresh=True,
    )

    assert outcome.is_error is False
    assert captured["force_refresh"] is True
    assert captured["context"] == "Before. >>> The cat sat. <<< After."
    assert captured["saved_context"] == "Before. >>> The cat sat. <<< After."


def test_analyze_sentence_for_reader_saves_and_passes_user_structure(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {
            "text": "The cat sat.",
            "user_translation": "",
            "user_structure": "主干：The cat sat",
        },
    )
    monkeypatch.setattr(analysis, "_fetch_cache_metadata", lambda db, cache_id: {})
    monkeypatch.setattr(analysis, "_active_sentence_prompt_version", lambda db, tr: "v5")
    monkeypatch.setattr(analysis, "save_sentence_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_analysis_payload",
        lambda db, sentence_id: {"is_stale": False},
    )

    def fake_save_structure(db, sentence_id, user_structure):
        saved["sentence_id"] = sentence_id
        saved["user_structure"] = user_structure

    def fake_analyze_sentence(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(analysis, "save_sentence_structure", fake_save_structure)
    monkeypatch.setattr(fastapi_app, "analyze_sentence", fake_analyze_sentence)

    outcome = analysis.analyze_sentence_for_reader(
        object(),
        1,
        user_translation=None,
        user_structure="主干：The cat sat",
    )

    assert outcome.is_error is False
    assert saved == {"sentence_id": 1, "user_structure": "主干：The cat sat"}
    assert captured["user_structure"] == "主干：The cat sat"


def test_analyze_word_card_for_reader_uses_pro_model_when_requested(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(analysis, "get_pro_analysis_model", lambda: "deepseek-test-pro")
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)
    monkeypatch.setattr(analysis, "record_word_card_diagnosis", lambda *a, **k: None)

    def fake_analyze_word(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_word", fake_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1, prefer_pro=True)

    assert outcome.is_error is False
    assert captured["model"] == "deepseek-test-pro"


def test_analyze_word_card_for_reader_passes_force_refresh(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)
    monkeypatch.setattr(analysis, "record_word_card_diagnosis", lambda *a, **k: None)

    def fake_analyze_word(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_word", fake_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1, force_refresh=True)

    assert outcome.is_error is False
    assert captured["force_refresh"] is True


def test_analyze_word_card_for_reader_falls_back_to_saved_payload_on_invalid_response(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"ok": True, "card_id": card_id, "is_stale": False},
    )

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.is_error is False
    assert outcome.payload["is_stale"] is True
    assert outcome.payload["from_cache"] is True
    assert outcome.payload["retry"] is True
    assert "failed validation" in outcome.payload["warning"]


def test_analyze_word_card_for_reader_keeps_502_without_saved_payload_on_invalid_response(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *args, **kwargs: SimpleNamespace(is_valid=False),
    )
    monkeypatch.setattr(analysis, "_fetch_word_analysis_payload", lambda db, card_id: None)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "AI response failed validation.",
        "retry": True,
    }


def test_analyze_word_card_for_reader_falls_back_to_saved_payload_on_runtime_error(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"ok": True, "card_id": card_id, "is_stale": False},
    )

    def fail_analyze_word(*args, **kwargs):
        raise RuntimeError("LLM call failed: timeout")

    monkeypatch.setattr(fastapi_app, "analyze_word", fail_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.is_error is False
    assert outcome.payload["is_stale"] is True
    assert outcome.payload["warning"] == "LLM call failed: timeout"


def test_analyze_word_card_for_reader_maps_value_error(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )

    def fail_fetch(db, sentence_id):
        raise ValueError("Sentence id=10 not found.")

    monkeypatch.setattr(analysis, "_fetch_sentence_for_analysis", fail_fetch)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.status_code == 400
    assert outcome.error_payload() == {
        "ok": False,
        "error": "Sentence id=10 not found.",
        "retry": False,
    }


def test_analyze_word_card_for_reader_maps_runtime_error_without_fallback(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(analysis, "_fetch_word_analysis_payload", lambda db, card_id: None)

    def fail_analyze_word(*args, **kwargs):
        raise RuntimeError("LLM call failed: timeout")

    monkeypatch.setattr(fastapi_app, "analyze_word", fail_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "LLM call failed: timeout",
        "retry": True,
    }


def test_analyze_word_card_for_reader_maps_file_not_found(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )

    def fail_analyze_word(*args, **kwargs):
        raise FileNotFoundError("prompt file missing")

    monkeypatch.setattr(fastapi_app, "analyze_word", fail_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.status_code == 502
    assert outcome.error_payload() == {
        "ok": False,
        "error": "prompt file missing",
        "retry": True,
    }


def test_analyze_word_card_for_reader_reports_when_payload_was_not_saved(
    monkeypatch,
) -> None:
    import app.web.fastapi_app as fastapi_app

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "cat",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The cat sat.", "user_translation": ""},
    )
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)
    monkeypatch.setattr(analysis, "record_word_card_diagnosis", lambda *a, **k: None)
    monkeypatch.setattr(analysis, "_fetch_word_analysis_payload", lambda db, card_id: None)
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *a, **k: SimpleNamespace(
            data={},
            cache_id=7,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        ),
    )

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.status_code == 500
    assert outcome.error_payload() == {
        "ok": False,
        "error": "Analysis was not saved.",
        "retry": True,
    }


def test_analyze_word_card_for_reader_passes_analysis_context(monkeypatch) -> None:
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "pristine",
            "user_note": "未被触碰过的",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "The original sentence lacks the target."},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)
    monkeypatch.setattr(analysis, "record_word_card_diagnosis", lambda *a, **k: None)

    def fake_analyze_word(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            data={},
            cache_id=1,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

    monkeypatch.setattr(fastapi_app, "analyze_word", fake_analyze_word)

    outcome = analysis.analyze_word_card_for_reader(
        object(),
        1,
        context_text=" A pristine ledger is untouched. ",
    )

    assert outcome.is_error is False
    assert captured["sentence_text"] == "The original sentence lacks the target."
    assert captured["context"] == "A pristine ledger is untouched."
    assert captured["learner_note"] == "未被触碰过的"


def test_analyze_word_card_for_reader_records_diagnosis_on_valid(monkeypatch) -> None:
    """Reader word analysis must persist error tags + misconception (gaps B/C)."""
    import app.web.fastapi_app as fastapi_app

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "tie",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "It ended in a tie.", "user_translation": ""},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )
    monkeypatch.setattr(fastapi_app, "_update_word_card_analysis_id", lambda *args: None)

    analysis_data = {
        "predicted_error_types": ["L01"],
        "learner_note_check": {"status": "incorrect", "corrected_understanding": "平局"},
    }

    def record(db, card_id, data):
        captured["card_id"] = card_id
        captured["data"] = data

    monkeypatch.setattr(analysis, "record_word_card_diagnosis", record)
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *a, **k: SimpleNamespace(
            data=analysis_data,
            cache_id=7,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        ),
    )

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.is_error is False
    assert captured["card_id"] == 1
    assert captured["data"] is analysis_data


def test_analyze_word_card_for_reader_skips_diagnosis_on_invalid(monkeypatch) -> None:
    """An invalid AI response must not write diagnosis onto the card."""
    import app.web.fastapi_app as fastapi_app

    called = {"value": False}

    monkeypatch.setattr(
        analysis,
        "get_word_card",
        lambda db, card_id: {
            "id": card_id,
            "first_sentence_id": 10,
            "surface_form": "tie",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_sentence_for_analysis",
        lambda db, sentence_id: {"text": "It ended in a tie."},
    )
    monkeypatch.setattr(
        analysis,
        "_fetch_word_analysis_payload",
        lambda db, card_id: {"is_stale": False},
    )

    def record(*a, **k):
        called["value"] = True

    monkeypatch.setattr(analysis, "record_word_card_diagnosis", record)
    monkeypatch.setattr(
        fastapi_app,
        "analyze_word",
        lambda *a, **k: SimpleNamespace(
            data={},
            cache_id=7,
            from_cache=False,
            is_stale=False,
            is_valid=False,
        ),
    )

    outcome = analysis.analyze_word_card_for_reader(object(), 1)

    assert outcome.is_error is False
    assert called["value"] is False
