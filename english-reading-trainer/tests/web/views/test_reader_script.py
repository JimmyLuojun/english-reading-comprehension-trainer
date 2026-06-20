"""Tests for reader browser interaction script rendering."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.web.views.reader_script import _selection_script


def test_selection_script_matches_golden_fixture() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures/reader_selection_script.js"

    assert _selection_script() == fixture.read_text(encoding="utf-8")


def test_selection_script_contains_reader_toolbar_contracts() -> None:
    script = _selection_script()

    assert "selection-toolbar" in script
    assert "toolbar-analysis-word-form" in script
    assert "restoreProgress" in script
    assert "analysisHistory" in script
    assert 'document.getElementById("analysis-panel-tab")' in script
    assert "function openPanelPlaceholder()" in script
    assert 'panelTab.addEventListener("click", openPanelPlaceholder);' in script
    assert "Select a sentence or marked word, then choose AI analysis." in script


def test_analysis_panel_opens_at_top_without_progress_scroll_restore() -> None:
    script = _selection_script()
    open_panel = script[script.index("function openPanel()") :]
    open_panel = open_panel[: open_panel.index("function closePanel")]
    focus_after_render = script[script.index("function focusAnalysisPanelAfterRender") :]
    focus_after_render = focus_after_render[: focus_after_render.index("function openPanel")]
    restore_saved = script[script.index("async function restoreSavedAnalysisPanel") :]
    restore_saved = restore_saved[: restore_saved.index("function scheduleProgressSave")]
    restore_previous = script[script.index("function restorePreviousAnalysis") :]
    restore_previous = restore_previous[: restore_previous.index("function scrollAnalysisPanelToTop")]

    assert "function scrollAnalysisPanelToTop()" in script
    assert "panel.scrollTop = 0;" in script
    assert "function focusAnalysisPanelAfterRender(focusAfterRender)" in script
    assert 'if (focusAfterRender === "structure-feedback")' in focus_after_render
    assert "structureAttemptSection" in focus_after_render
    assert 'target?.scrollIntoView({ block: "start" });' in focus_after_render
    assert "scrollAnalysisPanelToTop();" in focus_after_render
    assert "scrollAnalysisPanelToTop();" in open_panel
    assert open_panel.index("panel.hidden = false;") < open_panel.index(
        "scrollAnalysisPanelToTop();"
    )
    assert "panel_scroll_top" not in script
    assert "panelScrollTop" not in restore_saved
    assert "previous.scrollTop || 0" in restore_previous


def test_analysis_panel_toolbar_auto_collapses_and_peeks() -> None:
    script = _selection_script()
    visibility = script[script.index("function updateAnalysisToolsVisibility") :]
    visibility = visibility[: visibility.index("function scrollAnalysisPanelToTop")]
    listeners = script[script.index('panel.addEventListener("click"') :]
    listeners = listeners[: listeners.index("if (panelUnmark)")]

    assert 'panel?.querySelector(".analysis-panel-header")' in script
    assert "ANALYSIS_TOOLS_COLLAPSE_SCROLL_TOP" in script
    assert "ANALYSIS_TOOLS_HOT_ZONE_PX" in script
    assert 'panel.classList.toggle("analysis-tools-collapsed", shouldCollapse);' in visibility
    assert (
        'panel.classList.toggle("analysis-tools-peeking", shouldCollapse && Boolean(peek));'
        in visibility
    )
    assert "pointerIsInAnalysisToolsHotZone(event)" in visibility
    assert 'target?.closest(".analysis-panel-header")' in visibility
    assert 'panel.addEventListener("scroll"' in listeners
    assert 'panel.addEventListener("mousemove", handleAnalysisPanelPointerMove);' in listeners
    assert 'panel.addEventListener("mouseleave"' in listeners
    assert 'panelHeader.addEventListener("focusin", syncAnalysisToolsFocusState);' in listeners
    assert 'panelHeader.addEventListener("focusout"' in listeners


def test_analysis_selection_toolbar_uses_cancellable_deferred_hide() -> None:
    script = _selection_script()

    assert "let toolbarHideTimer = null;" in script
    assert "let toolbarRepositionFrame = null;" in script
    assert "function clearScheduledToolbarHide()" in script
    assert "function scheduleToolbarHide(delay)" in script
    assert "function scheduleToolbarReposition()" in script
    assert "function setToolbarStatus(statusElement, message)" in script
    assert "scheduleToolbarHide(650);" in script
    assert 'const toolbarResizeObserver = new ResizeObserver(() => scheduleToolbarReposition());' in script
    assert "toolbarResizeObserver.observe(toolbar);" in script
    assert "window.setTimeout(() => {\n            hideToolbar();" not in script

    hide_toolbar = script[script.index("function hideToolbar()"):]
    hide_toolbar = hide_toolbar[:hide_toolbar.index("function setVisible")]
    assert "clearScheduledToolbarHide();" in hide_toolbar
    assert hide_toolbar.index("clearScheduledToolbarHide();") < hide_toolbar.index("hideAllPanels();")
    assert "window.cancelAnimationFrame(toolbarRepositionFrame);" in hide_toolbar

    position_toolbar = script[script.index("function positionToolbar(anchor)"):]
    position_toolbar = position_toolbar[:position_toolbar.index("function showToolbar")]
    assert "clearScheduledToolbarHide();" in position_toolbar
    assert position_toolbar.index("clearScheduledToolbarHide();") < position_toolbar.index(
        "toolbar.hidden = false;"
    )
    assert "if (toolbar.hidden || (!translationEditorOpen && !structureEditorOpen)) return;" in position_toolbar
    assert "positionToolbar(sentence.getBoundingClientRect());" in position_toolbar
    assert "statusElement.textContent = message;" in position_toolbar
    assert "scheduleToolbarReposition();" in position_toolbar


def test_analysis_selection_toolbar_reenables_buttons_when_shown() -> None:
    script = _selection_script()
    show_toolbar = script[script.index("function showAnalysisWordToolbar"):]
    show_toolbar = show_toolbar[:show_toolbar.index("function applyGlossaryHighlights")]

    assert "setAnalysisWordButtonsDisabled(false);" in show_toolbar
    assert show_toolbar.index("setAnalysisWordButtonsDisabled(false);") < show_toolbar.index(
        "setVisible(analysisWordForm, true);"
    )


def test_analysis_glossary_highlights_nested_word_sections() -> None:
    script = _selection_script()
    apply_highlights = script[script.index("function applyGlossaryHighlights"):]
    apply_highlights = apply_highlights[: apply_highlights.index("function refreshAnalysisGlossaryHighlights")]
    refresh_highlights = script[script.index("function refreshAnalysisGlossaryHighlights"):]
    refresh_highlights = refresh_highlights[: refresh_highlights.index("function setAnalysisWordButtonsDisabled")]
    render_vs_simpler = script[script.index("function renderVsSimpler"):]
    render_vs_simpler = render_vs_simpler[: render_vs_simpler.index("function renderWordAnalysis")]

    assert "document.createTreeWalker(element, NodeFilter.SHOW_TEXT" in apply_highlights
    assert 'parent.closest(".glossary-word, [data-word-card]")' in apply_highlights
    assert "textNode.replaceWith(fragment);" in apply_highlights
    assert "wordVsSimpler" in refresh_highlights
    assert "applyGlossaryHighlights(container);" in render_vs_simpler


def test_source_word_card_param_loads_saved_word_analysis() -> None:
    script = _selection_script()
    load_saved = script[script.index("async function loadSavedWordAnalysis"):]
    load_saved = load_saved[: load_saved.index("function clearEvidenceHighlight")]
    boot = script[script.index("restoreReaderProgress();"):]

    assert 'initialParams.get("word_card")' in script
    assert 'fetch(`/analysis/word/${cardId}`)' in load_saved
    assert "renderWordAnalysis(payload, seqAtRequest);" in load_saved
    assert "if (initialWordCardId)" in boot
    assert "loadSavedWordAnalysis(initialWordCardId)" in boot


def test_sentence_deep_link_opens_analysis_panel_without_auto_ai() -> None:
    script = _selection_script()
    opener = script[script.index("function openInitialSentenceAnalysis"):]
    opener = opener[: opener.index("function clearEvidenceHighlight")]
    boot = script[script.index("restoreReaderProgress();"):]

    assert 'initialParams.get("sentence_id")' in script
    assert 'initialParams.get("panel")' in script
    assert 'if (initialPanel !== "analysis" || !initialSentenceId) return;' in opener
    assert "sentence.scrollIntoView({ block: \"center\" });" in opener
    assert "loadSavedAnalysis(sentence.dataset.sentenceId);" in opener
    assert 'renderSentenceStudyPanel(sentence, "No saved AI analysis yet.");' in opener
    assert "openInitialSentenceAnalysis();" in boot


def test_sentence_analysis_panel_edits_translation_structure_and_takeaway() -> None:
    script = _selection_script()
    render_payload = script[script.index("function renderAnalysisPayload"):]
    render_payload = render_payload[: render_payload.index("function renderDiagnosis")]
    save_translation = script[script.index("async function savePanelTranslation"):]
    save_translation = save_translation[: save_translation.index("async function savePanelStructure")]
    save_structure = script[script.index("async function savePanelStructure"):]
    save_structure = save_structure[: save_structure.index("async function savePanelNote")]
    save_note = script[script.index("async function savePanelNote"):]
    save_note = save_note[: save_note.index("function renderVsSimpler")]
    retry = script[script.index('panelRetry.addEventListener("click"'):]
    retry = retry[: retry.index("async function saveWordDetailEdits")]

    assert 'document.getElementById("sentence-panel-translation")' in script
    assert 'document.getElementById("sentence-panel-analyzed-translation-section")' in script
    assert 'document.getElementById("sentence-panel-analyzed-translation")' in script
    assert 'document.getElementById("sentence-panel-translation-diff")' in script
    assert 'document.getElementById("sentence-panel-translation-diff-count")' in script
    assert 'document.getElementById("sentence-panel-translation-diff-list")' in script
    assert 'document.getElementById("analysis-structure-attempt-section")' in script
    assert 'document.getElementById("sentence-panel-analyzed-structure-section")' in script
    assert 'document.getElementById("sentence-panel-analyzed-structure")' in script
    assert 'document.getElementById("sentence-panel-structure-diff")' in script
    assert 'document.getElementById("sentence-panel-structure-diff-count")' in script
    assert 'document.getElementById("sentence-panel-structure-diff-list")' in script
    assert 'document.getElementById("sentence-panel-structure")' in script
    assert 'document.getElementById("analysis-structure-feedback-section")' in script
    assert 'document.getElementById("analysis-structure-feedback")' in script
    assert 'document.getElementById("analysis-blocking-point")' in script
    assert 'document.getElementById("analysis-clauses")' in script
    assert 'document.getElementById("analysis-modifiers-section")' in script
    assert 'document.getElementById("analysis-logic-markers-section")' in script
    assert 'document.getElementById("analysis-anaphora-section")' in script
    assert 'document.getElementById("analysis-back-to-whole")' in script
    assert 'document.getElementById("sentence-panel-note-suggestion")' in script
    assert 'document.getElementById("sentence-panel-note-accept")' in script
    assert 'document.getElementById("sentence-panel-note")' in script
    assert "renderSentenceStructure(analysis);" in render_payload
    assert "renderStructureFeedback(analysis.structure_feedback || null);" in render_payload
    assert '"Correct highlights"' in script
    assert '"Reference structure"' in script
    assert '"Corrected structure"' in script
    assert "analysis.blocking_point || \"\"" in render_payload
    assert "analysis.simplified_en || \"\"" in render_payload
    assert "setSentenceStudyFields(payload);" in render_payload
    assert "const INPUT_DIFF_PREVIEW_MAX = 34;" in script
    assert "function truncateDiffText(text, max = INPUT_DIFF_PREVIEW_MAX)" in script
    assert "function describeStructureLine(text, state)" in script
    assert 'return `${state.section} ${numbered[1]}`;' in script
    assert 'location: inputKind === "structure"' in script
    assert ': "译文",' in script
    assert "function translationTokenType(char)" in script
    assert "function tokenizeTranslation(value)" in script
    assert "function compactTranslationText(tokens)" in script
    assert "const TRANSLATION_MERGE_GAP = 1;" in script
    assert "function isNoiseTranslationChange(changedText)" in script
    assert "function groupTranslationRegions(operations)" in script
    assert "function analyzeTranslationDiff(snapshotValue, currentValue)" in script
    assert "function diffTranslationPhrases(snapshotValue, currentValue)" in script
    assert "function renderTranslationHighlight(target, snapshotValue, currentValue)" in script
    assert "function renderStructureHighlight(target, snapshotValue, currentValue)" in script
    assert 'mark.className = `diff-mark diff-mark-${region.kind}`;' in script
    assert 'if (inputKind === "translation")' in script
    assert 'else if (inputKind === "structure")' in script
    assert "renderTranslationHighlight(target, snapshot, current);" in script
    assert "renderStructureHighlight(target, snapshot, current);" in script
    assert "diffTranslationPhrases(snapshotValue, currentValue)" in script
    assert "function diffInputLines(snapshotValue, currentValue, inputKind)" in script
    assert 'appendInputDiffItem(list, "modified", "修改", removedLine, addedLine);' in script
    assert "function renderInputDiff(details, list, countTarget, snapshotValue, currentValue, inputKind)" in script
    assert "countTarget.textContent = list.childElementCount" in script
    assert "details.hidden = !list.childElementCount;" in script
    assert "function setAnalysisInputSnapshot(" in script
    assert "normalizeText(snapshot) !== normalizeText(current)" in script
    assert "renderInputDiff(diffDetails, diffList, diffCount, snapshot, current, inputKind);" in script
    assert "payload.analyzed_translation || \"\"" in script
    assert "payload.analyzed_structure || \"\"" in script
    assert "payload.analysis?.takeaway_suggestion || \"\"" in script
    assert "function acceptTakeawaySuggestion()" in script
    assert 'sentencePanelNoteAccept.addEventListener("click", acceptTakeawaySuggestion);' in script
    assert "payload.user_note || \"\"" in script
    assert "payload.user_structure || \"\"" in script
    assert "function toggleAnalysisSection(section, items)" in script
    assert "toggleAnalysisSection(modifiersSection, analysis.modifiers || []);" in script
    assert "toggleAnalysisSection(logicMarkersSection, analysis.logic_markers || []);" in script
    assert "toggleAnalysisSection(anaphoraSection, analysis.anaphora || []);" in script
    assert 'fetch(`/mark/sentence/${sentenceId}/translation`' in save_translation
    assert 'fetch(`/mark/sentence/${sentenceId}/structure`' in save_structure
    assert "markSentenceStructured" in save_structure
    assert 'fetch(`/mark/sentence/${sentenceId}`' in save_note
    assert 'method: "PATCH"' in save_note
    assert "updateSentenceNote(sentenceId, value);" in save_note
    assert "sentencePanelTranslation?.value || null" in retry
    assert "userStructure: sentencePanelStructure?.value || \"\"" in retry


def _extract_js_function(script: str, declaration: str) -> str:
    """Return one JS function (balanced braces) starting at *declaration*."""
    start = script.index(declaration)
    depth = 0
    index = script.index("{", start)
    while index < len(script):
        char = script[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script[start : index + 1]
        index += 1
    raise AssertionError(f"unterminated function: {declaration}")


def _run_translation_diff(old: str, new: str) -> dict:
    """Execute the real translation-diff JS in node and return its result."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node runtime not available for JS behavioural test")

    script = _selection_script()
    declarations = [
        "function translationTokenType(char)",
        "function tokenizeTranslation(value)",
        "function compactTranslationText(tokens)",
        "function diffUnits(oldUnits, newUnits)",
        "function visibleTranslationText(text)",
        "function isNoiseTranslationChange(changedText)",
        "function groupTranslationRegions(operations)",
        "function regionTranslationTexts(operations, region)",
        "function analyzeTranslationDiff(snapshotValue, currentValue)",
        "function diffTranslationPhrases(snapshotValue, currentValue)",
        "function oldTranslationText(operations)",
        "function renderTranslationHighlight(target, snapshotValue, currentValue)",
    ]
    body = "\n".join(_extract_js_function(script, decl) for decl in declarations)
    preamble = (
        'const normalizeText = (value) => value.replace(/\\s+/g, " ").trim();\n'
        "const INPUT_DIFF_PREVIEW_MAX = 34;\n"
        "const TRANSLATION_MERGE_GAP = 1;\n"
        'const TRANSLATION_FUNCTION_CHARS = "的了是着地得之乎者吗呢吧啊呀儿";\n'
    )
    harness = (
        "class FakeNode {\n"
        "  constructor(){this.children=[];this.className='';this._text='';"
        "this.classList={add:(c)=>{this.className=(this.className+' '+c).trim();}};}\n"
        "  set textContent(v){this._text=v;}\n"
        "  get textContent(){return this._text;}\n"
        "  append(...n){this.children.push(...n);}\n"
        "  replaceChildren(){this.children=[];}\n"
        "}\n"
        "const document={createElement:()=>new FakeNode(),"
        "createTextNode:(t)=>({kind:'#text',value:t})};\n"
        f"const OLD={json.dumps(old)};\n"
        f"const NEW={json.dumps(new)};\n"
        "const phrases=diffTranslationPhrases(OLD,NEW).map(p=>({"
        "kind:p.kind,before:p.before?p.before.text:null,after:p.after?p.after.text:null}));\n"
        "const target=new FakeNode();\n"
        "renderTranslationHighlight(target,OLD,NEW);\n"
        "const highlight=target.children.map(c=>c.kind==='#text'"
        "?{text:c.value}:{mark:c.className,text:c.textContent});\n"
        "process.stdout.write(JSON.stringify({phrases,highlight}));\n"
    )
    completed = subprocess.run(  # noqa: S603 - local node, fixed args
        [node, "--input-type=module", "-e", preamble + body + harness],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_translation_diff_is_phrase_level_and_drops_noise() -> None:
    result = _run_translation_diff(
        "算力被拓展到让它满足证明的需求。",
        "算力被消耗到让区块满足证明需求.",
    )

    # Phrase-level: two tight content edits, separated (gap "到让" > merge gap).
    assert result["phrases"] == [
        {"kind": "modified", "before": "拓展", "after": "消耗"},
        {"kind": "modified", "before": "它", "after": "区块"},
    ]
    # Noise (虚词 "的" deletion, "。"→"." punctuation) is not listed at all.

    # Inline highlight marks exactly the changed spans inside the analyzed text.
    marked = [seg["text"] for seg in result["highlight"] if "mark" in seg]
    assert marked == ["拓展", "它"]
    rebuilt = "".join(seg["text"] for seg in result["highlight"])
    assert rebuilt == "算力被拓展到让它满足证明的需求。"


def test_translation_diff_marks_insertion_point_and_keeps_only_punct_change() -> None:
    added = _run_translation_diff("他完成了任务", "他没有完成任务")
    assert added["phrases"] == [{"kind": "added", "before": None, "after": "没有"}]
    insert = [seg for seg in added["highlight"] if seg.get("mark", "").find("insert") >= 0]
    assert insert and insert[0]["text"] == "‸"

    # When the ONLY change is punctuation, it must still be surfaced (fallback).
    punct = _run_translation_diff("只改标点。", "只改标点!")
    assert punct["phrases"] == [{"kind": "modified", "before": "。", "after": "!"}]


def _run_structure_diff(old: str, new: str) -> dict:
    """Execute the real structure-highlight JS in node and return its result."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node runtime not available for JS behavioural test")

    script = _selection_script()
    # normalizeText is a const arrow, extract it as a single line
    ns_idx = script.index("const normalizeText")
    ns_end = script.index("\n", ns_idx)
    normalize_line = script[ns_idx : ns_end + 1]
    declarations = [
        "function describeStructureLine(text, state)",
        "function parseInputLines(value, inputKind)",
        "function diffUnits(oldUnits, newUnits)",
        "function diffInputLines(snapshotValue, currentValue, inputKind)",
        "function renderStructureHighlight(target, snapshotValue, currentValue)",
    ]
    body = normalize_line + "\n" + "\n".join(
        _extract_js_function(script, decl) for decl in declarations
    )

    harness = (
        "class FakeNode {\n"
        "  constructor(){this.children=[];this.className='';this._text='';"
        "this.classList={add:(c)=>{this.className=(this.className+' '+c).trim();}};}\n"
        "  set textContent(v){this._text=v;}\n"
        "  get textContent(){return this._text;}\n"
        "  append(...n){this.children.push(...n);}\n"
        "  replaceChildren(){this.children=[];}\n"
        "}\n"
        "const document={createElement:()=>new FakeNode(),"
        "createTextNode:(t)=>({kind:'#text',value:t})};\n"
        f"const OLD={json.dumps(old)};\n"
        f"const NEW={json.dumps(new)};\n"
        "const target=new FakeNode();\n"
        "renderStructureHighlight(target,OLD,NEW);\n"
        "const segments=target.children.map(c=>c.kind==='#text'"
        "?{text:c.value}:{mark:c.className,text:c.textContent||c._text});\n"
        "process.stdout.write(JSON.stringify({segments}));\n"
    )
    completed = subprocess.run(  # noqa: S603 - local node, fixed args
        [node, "--input-type=module", "-e", body + harness],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_structure_highlight_marks_changed_lines_inline() -> None:
    old = "主干：\n1. 算法处理数据\n修饰成分：\n1. 快速地"
    new = "主干：\n1. 算法高效处理数据\n修饰成分：\n1. 非常快速地"
    result = _run_structure_diff(old, new)
    segments = result["segments"]

    # Unchanged section header and modified content lines should be marked.
    marked = [s for s in segments if "mark" in s]
    assert len(marked) == 2  # noqa: PLR2004 - two changed lines

    # The marked items should contain the OLD text of the changed lines.
    marked_texts = [m["text"] for m in marked]
    assert "1. 算法处理数据" in marked_texts
    assert "1. 快速地" in marked_texts

    # Unchanged lines remain as plain text nodes.
    plain_texts = [s["text"] for s in segments if "mark" not in s]
    assert any("主干：" in t for t in plain_texts)
    assert any("修饰成分：" in t for t in plain_texts)


def test_word_analysis_panel_shows_role_in_sentence() -> None:
    script = _selection_script()
    render_word = script[script.index("function renderWordAnalysis"):]
    render_word = render_word[: render_word.index("async function saveAnalysisMeaningIfEmpty")]

    assert 'document.getElementById("analysis-word-role")' in script
    assert "a.role_in_sentence || \"—\"" in render_word
    assert "applyGlossaryHighlights(wordRole);" in render_word


def test_reader_script_supports_pro_reanalysis_button() -> None:
    script = _selection_script()
    request_word = script[script.index("async function requestWordAnalysis"):]
    request_word = request_word[: request_word.index("async function loadSavedWordAnalysis")]

    assert 'document.getElementById("analysis-panel-retry-pro")' in script
    assert 'body.set("prefer_pro", "1");' in request_word
    assert 'body.set("force_refresh", "1");' in request_word
    assert "params.set(\"force_refresh\", \"1\");" in script
    assert 'requestWordAnalysis(activeAnalysisWordCardId, { forceRefresh: true });' in script
    assert "sentencePanelTranslation?.value || null" in script
    assert "preferPro: true" in script
    assert "userStructure: sentencePanelStructure?.value || \"\"" in script


def test_analysis_toolbar_actions_run_on_single_click_only() -> None:
    script = _selection_script()
    action_helper = script[script.index("function analysisWordActionFromEvent"):]
    action_helper = action_helper[: action_helper.index('panel.addEventListener("click"')]
    click_handler = script[script.index('analysisWordForm.addEventListener("click"'):]
    click_handler = click_handler[: click_handler.index('sentenceForm.addEventListener("submit"')]

    assert "event.submitter ||" in action_helper
    assert 'target?.closest("[data-analysis-mark]")' in action_helper
    assert 'target?.closest("[data-analysis-analyze]")' in action_helper
    assert "analysisWordForm.contains(markButton)" in action_helper
    assert "analysisWordForm.contains(analyzeButton)" in action_helper

    assert 'analysisWordForm.addEventListener("submit"' not in script
    assert 'analysisWordForm.addEventListener("pointerdown"' not in script
    assert "analysisWordPointerActionHandled" not in script
    assert "if (analysisWordPointerActionHandled)" not in click_handler
    assert "runAnalysisWordAction(action);" in click_handler


def test_analysis_toolbar_action_in_progress_blocks_collapsed_selection_hide() -> None:
    script = _selection_script()
    mark_analysis = script[script.index("async function markAnalysisSelection"):]
    mark_analysis = mark_analysis[: mark_analysis.index("async function markReaderSelection")]
    update_toolbar = script[script.index("function updateToolbar()"):]
    update_toolbar = update_toolbar[: update_toolbar.index("function readProgress")]
    collapsed_selection = update_toolbar[
        update_toolbar.index("if (!selection || selection.rangeCount === 0 || selection.isCollapsed)") :
    ]
    collapsed_selection = collapsed_selection[: collapsed_selection.index("const range = selection.getRangeAt(0);")]

    assert "let analysisWordActionInProgress = false;" in script
    assert "analysisWordActionInProgress = true;" in mark_analysis
    assert "suppressCollapsedToolbarHideUntil = Date.now() + 1200;" in mark_analysis
    assert "analysisWordActionInProgress = false;" in mark_analysis
    assert "if (analysisWordActionInProgress) return;" in collapsed_selection


def test_analysis_rendering_does_not_close_active_translation_editor() -> None:
    script = _selection_script()
    helper = script[script.index("function hideToolbarUnlessEditing"):]
    helper = helper[: helper.index("function setVisible")]
    update_toolbar = script[script.index("function updateToolbar()"):]
    update_toolbar = update_toolbar[: update_toolbar.index("function readProgress")]
    guarded_helper = script[script.index("function maybeHideToolbarAfterRender"):]
    guarded_helper = guarded_helper[: guarded_helper.index("function setVisible")]
    study_panel = script[script.index("function renderSentenceStudyPanel"):]
    study_panel = study_panel[: study_panel.index("function renderAnalysisPayload")]
    render_payload = script[script.index("function renderAnalysisPayload"):]
    render_payload = render_payload[: render_payload.index("function renderDiagnosis")]
    render_word = script[script.index("function renderWordAnalysis"):]
    render_word = render_word[: render_word.index("async function saveAnalysisMeaningIfEmpty")]
    translation_analyze = script[script.index('translationAnalyze.addEventListener("click"'):]
    translation_analyze = translation_analyze[: translation_analyze.index('analysisOpen.addEventListener("click"')]

    assert "if (translationEditorOpen || structureEditorOpen) return;" in helper
    assert "if (translationEditorOpen || structureEditorOpen)" in update_toolbar
    assert "maybeSwitchOpenEditorToSelectedSentence();" in update_toolbar
    assert "hideToolbar();" in helper
    assert "if (readerToolbarBusy) return;" in guarded_helper
    assert "if (seqAtRequest !== toolbarInteractionSeq) return;" in guarded_helper
    assert "hideToolbarUnlessEditing();" in guarded_helper
    assert "maybeHideToolbarAfterRender(seqAtRequest);" in study_panel
    assert "maybeHideToolbarAfterRender(seqAtRequest);" in render_payload
    assert "maybeHideToolbarAfterRender(seqAtRequest);" in render_word
    assert "hideToolbar();" in translation_analyze


def test_open_toolbar_editor_switches_only_on_whole_sentence_selection() -> None:
    script = _selection_script()
    selection_helper = script[script.index("function selectedWholeSentenceFromCurrentSelection"):]
    selection_helper = selection_helper[: selection_helper.index("function switchOpenEditorToSentence")]
    switch_helper = script[script.index("function switchOpenEditorToSentence"):]
    switch_helper = switch_helper[: switch_helper.index("function selectedWordCardIds")]
    update_toolbar = script[script.index("function updateToolbar()"):]
    update_toolbar = update_toolbar[: update_toolbar.index("function readProgress")]

    assert "selectionInsideToolbar(range)" in selection_helper
    assert "selectionInsideAnalysisPanel(range)" in selection_helper
    assert "spans.length !== 1" in selection_helper
    assert 'normalizeText(sentence.textContent || "")' in selection_helper
    assert "translationEditorOpen && translationEditorDirty" in switch_helper
    assert "sentenceId: activeSentenceId" in switch_helper
    assert "value: translationText.value.trim()" in switch_helper
    assert "lastSavedValue: lastSavedTranslation" in switch_helper
    assert "activeSentenceId = sentence.dataset.sentenceId;" in switch_helper
    assert "translationText.value = activeSentenceTranslation;" in switch_helper
    assert "structureText.value = activeSentenceStructure || STRUCTURE_TEMPLATE;" in switch_helper
    assert "setEditingTarget(sentence);" in switch_helper
    assert "maybeSwitchOpenEditorToSelectedSentence();" in update_toolbar


def test_toolbar_editors_autosave_and_stay_open_until_closed() -> None:
    script = _selection_script()
    enqueue_translation = script[script.index("function enqueueTranslationSave"):]
    enqueue_translation = enqueue_translation[: enqueue_translation.index("function enqueueStructureSave")]
    schedule_translation = script[script.index("function scheduleTranslationAutoSave"):]
    schedule_translation = schedule_translation[: schedule_translation.index("function scheduleStructureAutoSave")]
    save_options = script[script.index("function captureToolbarSaveOptions"):]
    save_options = save_options[: save_options.index("function enqueueTranslationSave")]
    open_structure = script[script.index("function openStructureEditor"):]
    open_structure = open_structure[: open_structure.index("async function saveTranslationOnly")]
    save_translation = script[script.index("async function saveTranslationOnly"):]
    save_translation = save_translation[: save_translation.index("function markSentenceStructured")]
    save_structure = script[script.index("async function saveStructureOnly"):]
    save_structure = save_structure[: save_structure.index("async function deleteTranslationInPlace")]
    listeners = script[script.index('translationCancel.addEventListener("click"'):]
    listeners = listeners[: listeners.index('analysisOpen.addEventListener("click"')]
    scroll_listener = script[script.index('window.addEventListener("scroll"'):]
    scroll_listener = scroll_listener[: scroll_listener.index("if (window.visualViewport)")]

    assert 'const STRUCTURE_TEMPLATE = "主干：\\n从句：\\n修饰成分：\\n指代逻辑：";' in script
    assert "let translationAutoSaveTimer = null;" in script
    assert "let structureAutoSaveTimer = null;" in script
    assert "let translationEditorDirty = false;" in script
    assert "let structureEditorDirty = false;" in script
    assert "function scheduleTranslationAutoSave" in script
    assert "function scheduleStructureAutoSave" in script
    assert "function flushPendingToolbarAutoSaveOnPageHide" in script
    assert "sentenceId: options.sentenceId || activeSentenceId" in save_options
    assert "value: hasOption(options, \"value\")" in save_options
    assert "lastSavedValue: hasOption(options, \"lastSavedValue\")" in save_options
    assert "const saveOptions = captureToolbarSaveOptions(options, translationText, lastSavedTranslation);" in enqueue_translation
    assert "const sentenceId = activeSentenceId;" in schedule_translation
    assert "const value = translationText.value.trim();" in schedule_translation
    assert "const lastSavedValue = lastSavedTranslation;" in schedule_translation
    assert "enqueueTranslationSave({ automatic: true, keepOpen: true, sentenceId, value, lastSavedValue });" in schedule_translation
    assert "structureText.value = activeSentenceStructure || STRUCTURE_TEMPLATE;" in open_structure
    assert "translationEditorDirty = true;" in listeners
    assert "structureEditorDirty = true;" in listeners
    assert 'enqueueTranslationSave({ keepOpen: true });' in script
    assert 'enqueueStructureSave({ keepOpen: true });' in script
    assert "closeTranslationEditor();" in listeners
    assert "closeStructureEditor();" in listeners
    assert "if (!keepOpen)" in save_translation
    assert "if (!keepOpen)" in save_structure
    assert "hideToolbar();" in save_translation
    assert "hideToolbar();" in save_structure
    assert "const isCurrentEditor = () => sentenceId === activeSentenceId && translationEditorOpen;" in save_translation
    assert "fetch(`/mark/sentence/${sentenceId}/translation`" in save_translation
    assert "const sentence = document.getElementById(`sentence-${sentenceId}`);" in save_translation
    assert "if (isCurrentEditor())" in save_translation
    assert 'setToolbarStatus(translationStatus, "Auto saving...");' in script
    assert "setToolbarStatus(translationStatus, automatic ? \"Auto saved\" : \"Saved\");" in save_translation
    assert 'setToolbarStatus(structureStatus, "Auto saving...");' in script
    assert "setToolbarStatus(structureStatus, automatic ? \"Auto saved\" : \"Saved\");" in save_structure
    assert "if (!translationEditorOpen && !structureEditorOpen) hideToolbar();" in scroll_listener
    assert 'window.addEventListener("pagehide", flushPendingToolbarAutoSaveOnPageHide);' in script


def test_bare_structure_template_is_not_saved_or_analyzed() -> None:
    script = _selection_script()
    save_structure = script[script.index("async function saveStructureOnly"):]
    save_structure = save_structure[: save_structure.index("async function deleteTranslationInPlace")]
    schedule_structure = script[script.index("function scheduleStructureAutoSave"):]
    schedule_structure = schedule_structure[: schedule_structure.index("function sendPendingToolbarSave")]
    structure_analyze = script[script.index('structureAnalyze.addEventListener("click"'):]
    structure_analyze = structure_analyze[: structure_analyze.index('analysisOpen.addEventListener("click"')]

    # The shared helper treats the bare scaffold (labels + whitespace) as empty.
    assert "function structureAttemptHasContent(value)" in script
    assert (
        'const STRUCTURE_TEMPLATE_LABELS = ["主干：", "从句：", "修饰成分：", "指代逻辑："];'
        in script
    )
    assert "if (!structureAttemptHasContent(value) || value === lastSavedValue) return;" in schedule_structure
    assert "if (!structureAttemptHasContent(value)) {" in save_structure
    assert "Fill in your structure judgement first." in save_structure
    assert "if (!structureAttemptHasContent(value)) {" in structure_analyze
    assert "if (structureAttemptHasContent(value) && value !== lastSavedStructure) {" in script


def test_structure_only_analysis_focuses_structure_feedback_after_render() -> None:
    script = _selection_script()
    render_payload = script[script.index("function renderAnalysisPayload"):]
    render_payload = render_payload[: render_payload.index("function renderDiagnosis")]
    request_analysis = script[script.index("async function requestAnalysis"):]
    request_analysis = request_analysis[: request_analysis.index("function clearPanelAutoSaveTimers")]
    structure_analyze = script[script.index('structureAnalyze.addEventListener("click"'):]
    structure_analyze = structure_analyze[: structure_analyze.index('analysisOpen.addEventListener("click"')]
    analysis_open = script[script.index('analysisOpen.addEventListener("click"'):]
    analysis_open = analysis_open[: analysis_open.index('crossSentenceDelete.addEventListener("click"')]

    assert "renderOptions = {}" in render_payload
    assert 'focusAnalysisPanelAfterRender(options.focusAfterRender);' in render_payload
    assert "focusAfterRender: options.focusAfterRender" in request_analysis
    assert "const hasAnyTranslation = Boolean(translation);" in structure_analyze
    assert 'focusAfterRender: !hasAnyTranslation ? "structure-feedback" : undefined' in structure_analyze
    assert "const hasAnyTranslation = Boolean(translation);" in analysis_open
    assert 'structureAttemptHasContent(structure) && !hasAnyTranslation' in analysis_open
    assert "focusAfterRender," in analysis_open
    assert "userStructure: structure" in analysis_open
    assert "scrollAnalysisPanelToTop();" in script


def test_toolbar_editing_target_highlight_is_temporary() -> None:
    script = _selection_script()
    helper = script[script.index("function setEditingTarget(sentenceEl)"):]
    helper = helper[: helper.index("function selectedSentenceSpans")]
    hide_all = script[script.index("function hideAllPanels()"):]
    hide_all = hide_all[: hide_all.index("function clearScheduledToolbarHide")]
    open_translation = script[script.index("function openTranslationEditor()"):]
    open_translation = open_translation[: open_translation.index("function openStructureEditor")]
    open_structure = script[script.index("function openStructureEditor()"):]
    open_structure = open_structure[: open_structure.index("async function saveTranslationOnly")]
    listeners = script[script.index('translationAnalyze.addEventListener("click"'):]
    listeners = listeners[: listeners.index('crossSentenceDelete.addEventListener("click"')]
    click_handler = script[script.index('reader.addEventListener("click"'):]
    click_handler = click_handler[: click_handler.index('reader.addEventListener("dblclick"')]

    assert 'reader.querySelectorAll(".reader-sentence.editing-target")' in helper
    assert 'el.classList.remove("editing-target");' in helper
    assert 'sentenceEl.classList.add("editing-target");' in helper
    assert "setEditingTarget(null);" in hide_all
    assert "setEditingTarget(sentence);" in open_translation
    assert "setEditingTarget(sentence);" in open_structure
    assert "hideToolbar();" in listeners
    assert "hideToolbar();" in click_handler
    assert 'loadSavedAnalysis(sentence.dataset.sentenceId);' in click_handler
    assert "hasSelection" not in click_handler
    assert "selectionIntersectsElement(selection, sentence)" in click_handler
    assert "window.getSelection()?.removeAllRanges();" in click_handler
    assert 'enqueueTranslationSave({ keepOpen: true });' in script
    assert 'enqueueStructureSave({ keepOpen: true });' in script


def test_sentence_panel_structure_and_translation_autosave() -> None:
    script = _selection_script()
    study_fields = script[script.index("function setSentenceStudyFields(payload)"):]
    study_fields = study_fields[: study_fields.index("function clearPanelAutoSaveTimers")]
    request_analysis = script[script.index("async function requestAnalysis"):]
    request_analysis = request_analysis[: request_analysis.index("function clearPanelAutoSaveTimers")]

    assert "let panelStructureDirty = false;" in script
    assert "let panelTranslationDirty = false;" in script
    assert "function schedulePanelStructureAutoSave" in script
    assert "function schedulePanelTranslationAutoSave" in script
    assert "function enqueuePanelStructureSave" in script
    assert "function enqueuePanelTranslationSave" in script
    # Panel prefills the editable template so the learner fills only their gaps.
    assert "sentencePanelStructure.value = payload.user_structure || STRUCTURE_TEMPLATE;" in study_fields
    # Bare scaffold is not sent for analysis from the panel either.
    assert 'if (structureAttemptHasContent(structure)) params.set("user_structure", structure.trim());' in request_analysis
    # Pending panel edits flush on page hide and on panel close.
    assert "if (panelStructureDirty && activeAnalysisSentenceId && sentencePanelStructure) {" in script
    assert "if (panelStructureDirty) enqueuePanelStructureSave({ automatic: true });" in script
    assert "panelStructureDirty = true;" in script
    assert "panelTranslationDirty = true;" in script


def test_sentence_panel_takeaway_autosaves_and_flushes_empty_values() -> None:
    script = _selection_script()
    study_fields = script[script.index("function setSentenceStudyFields(payload)"):]
    study_fields = study_fields[: study_fields.index("function clearPanelAutoSaveTimers")]
    schedule_note = script[script.index("function schedulePanelNoteAutoSave"):]
    schedule_note = schedule_note[: schedule_note.index("async function savePanelTranslation")]
    save_note = script[script.index("async function savePanelNote"):]
    save_note = save_note[: save_note.index("function renderVsSimpler")]
    accept_suggestion = script[script.index("function acceptTakeawaySuggestion"):]
    accept_suggestion = accept_suggestion[: accept_suggestion.index("function sentenceTextForId")]
    listeners = script[script.index("if (sentencePanelNoteSave)"):]
    listeners = listeners[: listeners.index("if (sentencePanelNoteAccept)")]

    assert "let panelNoteAutoSaveTimer = null;" in script
    assert "let panelNoteSaveChain = Promise.resolve();" in script
    assert "let lastSavedPanelNote = \"\";" in script
    assert "let panelNoteDirty = false;" in script
    assert 'lastSavedPanelNote = (payload.user_note || "").trim();' in study_fields
    assert "function enqueuePanelNoteSave" in script
    assert "function schedulePanelNoteAutoSave" in script
    assert "if (value === lastSavedPanelNote) return;" in schedule_note
    assert 'enqueuePanelNoteSave({ automatic: true, sentenceId, value });' in schedule_note
    assert "const saveOptions = {" in script
    assert "sentenceId: options.sentenceId || activeAnalysisSentenceId" in script
    assert "value: hasValue ? String(options.value || \"\").trim()" in script
    assert 'method: "PATCH"' in save_note
    assert "new URLSearchParams({ user_note: value })" in save_note
    assert "lastSavedPanelNote = value;" in save_note
    assert 'automatic ? "Auto saved" : "Saved"' in save_note
    assert "if (panelNoteDirty) enqueuePanelNoteSave({ automatic: true });" in script
    assert "sendPendingPanelNoteSave(activeAnalysisSentenceId, value);" in script
    assert "keepalive: true" in script
    assert "panelNoteDirty = true;" in accept_suggestion
    assert "schedulePanelNoteAutoSave();" in accept_suggestion
    assert "panelNoteDirty = true;" in listeners
    assert "schedulePanelNoteAutoSave();" in listeners


def test_analysis_rendering_preserves_new_reader_toolbar_during_pending_ai() -> None:
    script = _selection_script()
    position_toolbar = script[script.index("function positionToolbar(anchor)"):]
    position_toolbar = position_toolbar[: position_toolbar.index("function showToolbar")]
    request_analysis = script[script.index("async function requestAnalysis"):]
    request_analysis = request_analysis[: request_analysis.index("async function savePanelTranslation")]
    request_word = script[script.index("async function requestWordAnalysis"):]
    request_word = request_word[: request_word.index("async function loadSavedWordAnalysis")]
    mark_reader = script[script.index("async function markReaderSelection"):]
    mark_reader = mark_reader[: mark_reader.index("function updateToolbar")]
    save_translation = script[script.index("async function saveTranslationOnly"):]
    save_translation = save_translation[: save_translation.index("async function deleteTranslationInPlace")]

    assert "let readerToolbarBusy = false;" in script
    assert "let toolbarInteractionSeq = 0;" in script
    assert "toolbarInteractionSeq += 1;" in position_toolbar
    assert "const seqAtRequest = toolbarInteractionSeq;" in request_analysis
    assert "renderAnalysisPayload(payload, {\n            seqAtRequest," in request_analysis
    assert "const seqAtRequest = toolbarInteractionSeq;" in request_word
    assert "renderWordAnalysis(payload, seqAtRequest);" in request_word
    assert "readerToolbarBusy = true;" in mark_reader
    assert "readerToolbarBusy = false;" in mark_reader
    assert "readerToolbarBusy = true;" in save_translation
    assert "readerToolbarBusy = false;" in save_translation


def test_analysis_panel_copy_buttons_use_payload_and_clipboard_fallback() -> None:
    script = _selection_script()
    copy_helper = script[script.index("function copyAnalysisPayload"):]
    copy_helper = copy_helper[: copy_helper.index("function showWordDetail")]
    sentence_builder = script[script.index("function buildSentenceAnalysisCopyText"):]
    sentence_builder = sentence_builder[: sentence_builder.index("function buildSentenceCopyText")]
    word_builder = script[script.index("function buildWordAnalysisCopyText"):]
    word_builder = word_builder[: word_builder.index("function buildWordCopyText")]
    clipboard = script[script.index("async function writeClipboard"):]
    clipboard = clipboard[: clipboard.index("function copyAnalysisPayload")]

    assert 'document.getElementById("analysis-copy-all")' in script
    assert 'document.getElementById("analysis-copy-source")' in script
    assert 'document.getElementById("analysis-copy-analysis")' in script
    assert 'copyAll.addEventListener("click", () => copyAnalysisPayload("all"))' in script
    assert 'copySource.addEventListener("click", () => copyAnalysisPayload("source"))' in script
    assert 'copyAnalysis.addEventListener("click", () => copyAnalysisPayload("analysis"))' in script
    assert "activeAnalysisPayload" in copy_helper
    assert "buildWordCopyText(activeAnalysisPayload, kind)" in copy_helper
    assert "buildSentenceCopyText(activeAnalysisPayload, kind)" in copy_helper
    assert "analysis.simplified_en" in sentence_builder
    assert "analysis.chinese_gloss" in sentence_builder
    assert "analysis.diagnosis_evidence" in sentence_builder
    assert "analysis.meaning_in_context" in word_builder
    assert "analysis.learner_note_check" in word_builder
    assert "navigator.clipboard?.writeText" in clipboard
    assert 'document.execCommand("copy")' in clipboard


def test_marked_sentence_click_toolbar_is_separate_from_saved_analysis_click() -> None:
    script = _selection_script()

    assert "function showMarkedSentenceToolbar(sentence)" in script
    assert "function selectionIntersectsElement(selection, element)" in script
    helper = script[script.index("function selectionIntersectsElement(selection, element)"):]
    helper = helper[: helper.index("function switchOpenEditorToSentence")]
    click_handler = script[script.index('reader.addEventListener("click"'):]
    click_handler = click_handler[:click_handler.index('document.addEventListener("selectionchange"')]

    assert "selection.getRangeAt(index).intersectsNode(element)" in helper
    assert "if (wordSpan && !selectionIntersectsElement(selection, wordSpan))" in click_handler
    assert "if (selectionIntersectsElement(selection, sentence)) return;" in click_handler
    assert "loadSavedAnalysis(sentence.dataset.sentenceId);" in click_handler
    assert "window.getSelection()?.removeAllRanges();" in click_handler
    assert 'if (sentence.dataset.marked === "1")' in click_handler
    assert "showMarkedSentenceToolbar(sentence);" in click_handler


def test_translation_editor_repositions_after_expanding() -> None:
    script = _selection_script()
    position_toolbar = script[script.index("function positionToolbar(anchor)"):]
    position_toolbar = position_toolbar[: position_toolbar.index("function showToolbar")]
    open_editor = script[script.index("function openTranslationEditor()"):]
    open_editor = open_editor[: open_editor.index("async function saveTranslationOnly")]

    assert "availableAbove" in position_toolbar
    assert "availableBelow" in position_toolbar
    assert "window.innerHeight - toolbarRect.height" in position_toolbar
    assert "const sentence = document.getElementById(`sentence-${activeSentenceId}`);" in open_editor
    assert "positionToolbar(sentence.getBoundingClientRect());" in open_editor
    assert open_editor.index("translationEditor.hidden = false;") < open_editor.index(
        "positionToolbar(sentence.getBoundingClientRect());"
    )


def test_saved_translation_does_not_mark_sentence_and_checks_translation() -> None:
    script = _selection_script()
    label_helper = script[script.index("function analysisButtonLabel"):]
    label_helper = label_helper[: label_helper.index("function markSentenceTranslated")]
    translated_helper = script[script.index("function markSentenceTranslated"):]
    translated_helper = translated_helper[: translated_helper.index("function clearSentenceTranslation")]
    clear_translation = script[script.index("function clearSentenceTranslation"):]
    clear_translation = clear_translation[: clear_translation.index("function showWordDetail")]
    save_translation = script[script.index("async function saveTranslationOnly"):]
    save_translation = save_translation[: save_translation.index("async function deleteTranslationInPlace")]
    delete_translation = script[script.index("async function deleteTranslationInPlace"):]
    delete_translation = delete_translation[: delete_translation.index("function setSentenceMode")]
    unmark_helper = script[script.index("function markSentenceSpanUnmarked"):]
    unmark_helper = unmark_helper[: unmark_helper.index("function markSentenceSpanMarked")]
    analysis_click = script[script.index('analysisOpen.addEventListener("click"'):]
    analysis_click = analysis_click[: analysis_click.index('crossSentenceDelete.addEventListener("click"')]

    assert 'const translationDelete = document.getElementById("toolbar-translation-delete");' in script
    assert '"Check translation"' in label_helper
    assert 'sentence.dataset.translation = translation;' in translated_helper
    assert "if (sentence.dataset.analysisId)" in translated_helper
    assert 'sentence.dataset.analysisStale = "1";' in translated_helper
    assert 'sentence.classList.add("analyzed-stale");' in translated_helper
    assert 'sentence.dataset.analysisId = "";' in translated_helper
    assert 'sentence.classList.add("translated");' in translated_helper
    assert 'sentence.classList.add("marked", "translated");' not in translated_helper
    assert 'sentence.classList.remove("analyzed", "analyzed-stale");' in translated_helper
    assert 'sentence.title = "Translation saved";' in translated_helper
    assert 'sentence.dataset.translation = "";' in clear_translation
    assert 'sentence.dataset.marked = "0";' in clear_translation
    assert (
        'sentence.classList.remove("translated", "marked", "analyzed", "analyzed-stale");'
        in clear_translation
    )
    assert 'sentence.removeAttribute("title");' in clear_translation
    assert "markSentenceTranslated(sentence, value);" in save_translation
    assert 'fetch(url, { method: "DELETE" })' in delete_translation
    assert "clearSentenceTranslation(sentence);" in delete_translation
    assert 'translationDelete.hidden = !activeSentenceTranslation;' in script
    assert 'translationDelete.hidden = !wholeSentence || !activeSentenceTranslation;' in script
    assert 'translationDelete.addEventListener("click", deleteTranslationInPlace);' in script
    assert 'sentence.dataset.translation = "";' not in unmark_helper
    assert "const translation = activeSentenceTranslation || null;" in analysis_click
    assert "requestAnalysis(sentenceId, translation, {" in analysis_click
    assert "focusAfterRender," in analysis_click


def test_translation_update_preserves_analysis_id_as_stale() -> None:
    script = _selection_script()
    translated_helper = script[script.index("function markSentenceTranslated"):]
    translated_helper = translated_helper[: translated_helper.index("function clearSentenceTranslation")]
    save_panel_translation = script[script.index("async function savePanelTranslation"):]
    save_panel_translation = save_panel_translation[: save_panel_translation.index("async function savePanelNote")]

    assert "if (sentence.dataset.analysisId)" in translated_helper
    assert 'sentence.dataset.analysisStale = "1";' in translated_helper
    assert 'sentence.classList.add("analyzed-stale");' in translated_helper
    assert 'sentence.dataset.analysisId = "";' in translated_helper
    assert 'sentence.classList.remove("analyzed", "analyzed-stale");' in translated_helper
    assert "activeAnalysisPayload.is_stale = true;" in save_panel_translation
    assert "Analysis is stale. Reanalyze when ready." in save_panel_translation


def test_reader_script_propagates_lexical_type_and_refreshes_body_highlights() -> None:
    script = _selection_script()
    decorate = script[script.index("function decorateWordCardElement"):]
    decorate = decorate[: decorate.index("function clearWordCardElement")]
    glossary = script[script.index("function glossaryHighlightFragment"):]
    glossary = glossary[: glossary.index("function applyGlossaryHighlights")]
    apply_highlights = script[script.index("function applyGlossaryHighlights"):]
    apply_highlights = apply_highlights[: apply_highlights.index("function refreshAnalysisGlossaryHighlights")]
    mark_analysis = script[script.index("async function markAnalysisSelection"):]
    mark_analysis = mark_analysis[: mark_analysis.index("async function markReaderSelection")]

    assert "lexical_type: card.lexical_type || \"\"" in script
    assert "element.dataset.lexicalType = card.lexical_type || \"\";" in decorate
    assert "span.dataset.lexicalType = entry.card.lexical_type || \"\";" in glossary
    assert 'parent.closest(".glossary-word, [data-word-card]")' in apply_highlights
    assert "function refreshReaderGlossaryHighlights()" in script
    assert "refreshReaderGlossaryHighlights();" in mark_analysis


def test_reader_script_supports_bare_key_sentence_shortcut() -> None:
    script = _selection_script()
    shortcut = script[script.index("function handleReaderShortcut"):]
    shortcut = shortcut[: shortcut.index("function captureReadingAnchor")]

    assert "function sentenceFromSelectionOrViewport()" in script
    assert "function selectWholeSentence(sentence)" in script
    assert 'document.addEventListener("keydown", handleReaderShortcut);' in script
    # macOS global hotkey tools steal modifier combos, so the shortcut uses bare keys:
    # it must bail out when any modifier is held and ignore IME composition.
    assert "event.altKey" in shortcut
    assert "event.ctrlKey" in shortcut
    assert "event.metaKey" in shortcut
    assert "event.isComposing" in shortcut
    # Match the physical key via event.code rather than event.key (layout-independent).
    assert 'event.code === "KeyS"' in shortcut
    assert 'event.code === "KeyT"' in shortcut
    assert "eventTargetIsTextInput(event)" in shortcut
    assert "range.selectNodeContents(sentence);" in script
    assert "selection.removeAllRanges();" in script
    assert "selection.addRange(range);" in script
    assert "updateToolbar();" in script
    assert "if (isTranslate)" in shortcut


def test_translated_sentence_double_click_shortcut_preserves_word_card_priority() -> None:
    script = _selection_script()
    shortcut = script[script.index("function openTranslatedSentenceShortcut"):]
    shortcut = shortcut[: shortcut.index("function showAnalysisWordToolbar")]
    double_click = script[script.index('reader.addEventListener("dblclick"'):]
    double_click = double_click[: double_click.index('document.addEventListener("selectionchange"')]

    assert "if (!sentence?.dataset.translation?.trim()) return false;" in shortcut
    assert "loadSavedAnalysis(activeSentenceId);" in shortcut
    assert "showMarkedSentenceToolbar(sentence);" in shortcut
    assert "openTranslationEditor();" in shortcut
    assert 'const wordSpan = event.target.closest("[data-word-card]");' in double_click
    assert "showWordDetail(wordSpan);" in double_click
    assert 'const sentence = event.target.closest("[data-sentence-id]");' in double_click
    assert "!sentence.dataset.translation?.trim()" in double_click
    assert "window.getSelection()?.removeAllRanges();" in double_click
    assert "openTranslatedSentenceShortcut(sentence);" in double_click


def test_sentence_analysis_renders_similar_past_mistakes() -> None:
    script = _selection_script()
    render_payload = script[script.index("function renderAnalysisPayload"):]
    render_payload = render_payload[: render_payload.index("function renderDiagnosis")]
    render_similar = script[script.index("function renderSimilarMistakes"):]
    render_similar = render_similar[: render_similar.index("function updateSentenceAnalysisState")]

    assert "const ERROR_CHECK_TIPS = {" in script
    assert "renderSimilarMistakes(payload, analysis);" in render_payload
    assert "const mistakes = payload.similar_mistakes || [];" in render_similar
    assert "Same diagnosed error code in an active translated Review sentence." in render_similar
    assert "mistake.shared_error_codes || []" in render_similar
    assert 'comparisonLine("Current", evidenceTextForCode(analysis.diagnosis_evidence, code))' in render_similar
    assert 'comparisonLine("Past", evidenceTextForCode(mistake.diagnosis_evidence, code))' in render_similar
    assert 'comparisonLine("Next check", tip)' in render_similar


def test_word_detail_explain_saves_edits_before_analysis() -> None:
    script = _selection_script()
    save_helper = script[script.index("async function saveWordDetailEdits"):]
    save_helper = save_helper[: save_helper.index('wordDetailSave.addEventListener("click"')]
    explain_handler = script[script.index('wordDetailExplain.addEventListener("click"'):]
    explain_handler = explain_handler[: explain_handler.index("if (wordDetailViewCard)")]

    assert 'fetch(`/mark/word/${cardId}`, { method: "PATCH", body })' in save_helper
    assert "updateWordCardElements(cardId, meaning, note);" in save_helper
    assert "const saved = await saveWordDetailEdits({ hideAfter: false });" in explain_handler
    assert "if (!saved) return;" in explain_handler
    assert "requestWordAnalysis(cardId, { pushCurrent: !panel.hidden });" in explain_handler


def test_word_analysis_renders_learner_note_check_without_overwriting_notes() -> None:
    script = _selection_script()
    loading_word = script[script.index("function setPanelLoadingWord"):]
    loading_word = loading_word[: loading_word.index("function renderAnalysisError")]
    render_word = script[script.index("function renderWordAnalysis"):]
    render_word = render_word[: render_word.index("async function saveAnalysisMeaningIfEmpty")]

    assert 'document.getElementById("analysis-word-note-check-section")' in script
    assert 'document.getElementById("analysis-word-note-check")' in script
    assert "wordNoteCheckSection.hidden = true;" in loading_word
    assert "const check = a.learner_note_check || {};" in render_word
    assert 'status !== "not_provided"' in render_word
    assert "wordPanelNote.value = distinctUserNote" in render_word
    assert "wordPanelNote.value = check" not in render_word


def test_word_analysis_renders_payload_warning_before_stale_message() -> None:
    script = _selection_script()
    render_word = script[script.index("function renderWordAnalysis"):]
    render_word = render_word[: render_word.index("async function saveAnalysisMeaningIfEmpty")]

    assert "panelStatus.textContent = payload.warning" in render_word
    assert 'payload.is_stale ? "Analysis is stale. Reanalyze when ready."' in render_word
