"""Tests for reader browser interaction script rendering."""

from __future__ import annotations

from app.web.views.reader_script import _selection_script


def test_selection_script_contains_reader_toolbar_contracts() -> None:
    script = _selection_script()

    assert "selection-toolbar" in script
    assert "toolbar-analysis-word-form" in script
    assert "restoreProgress" in script
    assert "analysisHistory" in script


def test_analysis_selection_toolbar_uses_cancellable_deferred_hide() -> None:
    script = _selection_script()

    assert "let toolbarHideTimer = null;" in script
    assert "function clearScheduledToolbarHide()" in script
    assert "function scheduleToolbarHide(delay)" in script
    assert "scheduleToolbarHide(650);" in script
    assert "window.setTimeout(() => {\n            hideToolbar();" not in script

    hide_toolbar = script[script.index("function hideToolbar()"):]
    hide_toolbar = hide_toolbar[:hide_toolbar.index("function setVisible")]
    assert "clearScheduledToolbarHide();" in hide_toolbar
    assert hide_toolbar.index("clearScheduledToolbarHide();") < hide_toolbar.index("hideAllPanels();")

    position_toolbar = script[script.index("function positionToolbar(anchor)"):]
    position_toolbar = position_toolbar[:position_toolbar.index("function showToolbar")]
    assert "clearScheduledToolbarHide();" in position_toolbar
    assert position_toolbar.index("clearScheduledToolbarHide();") < position_toolbar.index(
        "toolbar.hidden = false;"
    )


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
    assert 'parent.closest(".glossary-word")' in apply_highlights
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
    assert "renderWordAnalysis(payload);" in load_saved
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


def test_sentence_analysis_panel_edits_translation_and_takeaway() -> None:
    script = _selection_script()
    render_payload = script[script.index("function renderAnalysisPayload"):]
    render_payload = render_payload[: render_payload.index("function renderDiagnosis")]
    save_translation = script[script.index("async function savePanelTranslation"):]
    save_translation = save_translation[: save_translation.index("async function savePanelNote")]
    save_note = script[script.index("async function savePanelNote"):]
    save_note = save_note[: save_note.index("function renderVsSimpler")]
    retry = script[script.index('panelRetry.addEventListener("click"'):]
    retry = retry[: retry.index("async function saveWordDetailEdits")]

    assert 'document.getElementById("sentence-panel-translation")' in script
    assert 'document.getElementById("sentence-panel-note")' in script
    assert "setSentenceStudyFields(payload);" in render_payload
    assert "payload.user_note || \"\"" in script
    assert 'fetch(`/mark/sentence/${sentenceId}/translation`' in save_translation
    assert 'fetch(`/mark/sentence/${sentenceId}`' in save_note
    assert 'method: "PATCH"' in save_note
    assert "updateSentenceNote(sentenceId, value);" in save_note
    assert "sentencePanelTranslation?.value || null" in retry


def test_reader_script_supports_pro_reanalysis_button() -> None:
    script = _selection_script()
    request_word = script[script.index("async function requestWordAnalysis"):]
    request_word = request_word[: request_word.index("async function loadSavedWordAnalysis")]

    assert 'document.getElementById("analysis-panel-retry-pro")' in script
    assert 'body.set("prefer_pro", "1");' in request_word
    assert 'requestWordAnalysis(activeAnalysisWordCardId, { preferPro: true });' in script
    assert "sentencePanelTranslation?.value || null" in script
    assert "{ preferPro: true }" in script


def test_analysis_toolbar_actions_run_on_pointerdown_before_click() -> None:
    script = _selection_script()
    action_helper = script[script.index("function analysisWordActionFromEvent"):]
    action_helper = action_helper[: action_helper.index('panel.addEventListener("click"')]
    submit_handler = script[script.index('analysisWordForm.addEventListener("submit"'):]
    submit_handler = submit_handler[: submit_handler.index('analysisWordForm.addEventListener("pointerdown"')]
    pointer_handler = script[script.index('analysisWordForm.addEventListener("pointerdown"'):]
    pointer_handler = pointer_handler[: pointer_handler.index('analysisWordForm.addEventListener("click"')]
    click_handler = script[script.index('analysisWordForm.addEventListener("click"'):]
    click_handler = click_handler[: click_handler.index('sentenceForm.addEventListener("submit"')]

    assert "event.submitter ||" in action_helper
    assert 'target?.closest("[data-analysis-mark]")' in action_helper
    assert 'target?.closest("[data-analysis-analyze]")' in action_helper
    assert "analysisWordForm.contains(markButton)" in action_helper
    assert "analysisWordForm.contains(analyzeButton)" in action_helper

    assert "event.preventDefault();" in submit_handler
    assert "runAnalysisWordAction(action);" in submit_handler
    assert "event.preventDefault();" in pointer_handler
    assert "event.stopPropagation();" in pointer_handler
    assert "analysisWordPointerActionHandled = true;" in pointer_handler
    assert "runAnalysisWordAction(action);" in pointer_handler
    assert "markAnalysisSelection(" not in pointer_handler

    assert "if (analysisWordPointerActionHandled)" in click_handler
    assert "analysisWordPointerActionHandled = false;" in click_handler
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


def test_marked_sentence_click_toolbar_is_separate_from_saved_analysis_click() -> None:
    script = _selection_script()

    assert "function showMarkedSentenceToolbar(sentence)" in script
    click_handler = script[script.index('reader.addEventListener("click"'):]
    click_handler = click_handler[:click_handler.index('document.addEventListener("selectionchange"')]
    assert "loadSavedAnalysis(sentence.dataset.sentenceId);" in click_handler
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
    assert "requestAnalysis(sentenceId, activeSentenceTranslation || null);" in analysis_click


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
