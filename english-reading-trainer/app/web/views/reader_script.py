"""Browser script for reader selection and analysis interactions."""

from __future__ import annotations

def _selection_script() -> str:
    return r"""
    (() => {
      const reader = document.querySelector("[data-reader]");
      const toolbar = document.getElementById("selection-toolbar");
      if (!reader || !toolbar) return;

      const returnTo = reader.dataset.returnTo || window.location.pathname;
      const wordIndexElement = document.getElementById("word-card-index");
      const wordCards = JSON.parse(wordIndexElement?.textContent || "{}");
      const glossaryEntries = [];
      const seenGlossaryTerms = new Set();
      const sentenceForm = document.getElementById("toolbar-sentence-form");
      const sentenceSubmit = document.getElementById("toolbar-sentence-submit");
      const sentenceDelete = document.getElementById("toolbar-sentence-delete");
      const translationOpen = document.getElementById("toolbar-translation-open");
      const structureOpen = document.getElementById("toolbar-structure-open");
      const translationDelete = document.getElementById("toolbar-translation-delete");
      const analysisOpen = document.getElementById("toolbar-analysis-open");
      const translationForm = document.getElementById("toolbar-translation-form");
      const translationValue = document.getElementById("toolbar-translation-value");
      const translationEditor = document.getElementById("toolbar-translation-editor");
      const translationText = document.getElementById("toolbar-translation-text");
      const translationCancel = document.getElementById("toolbar-translation-cancel");
      const translationSave = document.getElementById("toolbar-translation-save");
      const translationAnalyze = document.getElementById("toolbar-translation-analyze");
      const translationStatus = document.getElementById("toolbar-translation-status");
      const structureEditor = document.getElementById("toolbar-structure-editor");
      const structureText = document.getElementById("toolbar-structure-text");
      const structureCancel = document.getElementById("toolbar-structure-cancel");
      const structureSave = document.getElementById("toolbar-structure-save");
      const structureAnalyze = document.getElementById("toolbar-structure-analyze");
      const structureStatus = document.getElementById("toolbar-structure-status");
      const wordForm = document.getElementById("toolbar-word-form");
      const wordSentenceId = document.getElementById("toolbar-word-sentence-id");
      const wordSurfaceForm = document.getElementById("toolbar-word-surface-form");
      const analysisWordForm = document.getElementById("toolbar-analysis-word-form");
      const analysisWordSentenceId = document.getElementById("toolbar-analysis-word-sentence-id");
      const analysisWordSurfaceForm = document.getElementById("toolbar-analysis-word-surface-form");
      const analysisWordStatus = document.getElementById("toolbar-analysis-word-status");
      const wordDetail = document.getElementById("toolbar-word-detail");
      const wordDetailSurface = document.getElementById("toolbar-word-detail-surface");
      const wordDetailMeaning = document.getElementById("toolbar-word-detail-meaning");
      const wordDetailNote = document.getElementById("toolbar-word-detail-note");
      const wordDetailSave = document.getElementById("toolbar-word-detail-save");
      const wordDetailExplain = document.getElementById("toolbar-word-detail-explain");
      const wordDetailViewCard = document.getElementById("toolbar-word-detail-view-card");
      const wordDetailRemove = document.getElementById("toolbar-word-detail-remove");
      const crossSentence = document.getElementById("toolbar-cross-sentence");
      const crossSentenceDelete = document.getElementById("toolbar-cross-sentence-delete");
      const dismissButton = document.getElementById("toolbar-dismiss");
      const panel = document.getElementById("analysis-panel");
      const panelHeader = panel?.querySelector(".analysis-panel-header");
      const panelTab = document.getElementById("analysis-panel-tab");
      const panelClose = document.getElementById("analysis-panel-close");
      const panelReturn = document.getElementById("analysis-panel-return");
      const panelRetry = document.getElementById("analysis-panel-retry");
      const panelRetryPro = document.getElementById("analysis-panel-retry-pro");
      const panelPrevious = document.getElementById("analysis-panel-previous");
      const panelUnmark = document.getElementById("analysis-panel-unmark");
      const panelKicker = document.getElementById("analysis-panel-kicker");
      const panelTitle = document.getElementById("analysis-panel-title");
      const panelMeta = document.getElementById("analysis-panel-meta");
      const panelStatus = document.getElementById("analysis-panel-status");
      const copyAll = document.getElementById("analysis-copy-all");
      const copySource = document.getElementById("analysis-copy-source");
      const copyAnalysis = document.getElementById("analysis-copy-analysis");
      const copyStatus = document.getElementById("analysis-copy-status");
      const wordPronunciation = document.getElementById("analysis-word-pronunciation");
      const sentenceSections = document.getElementById("analysis-sentence-sections");
      const wordSections = document.getElementById("analysis-word-sections");
      const simplified = document.getElementById("analysis-simplified");
      const gloss = document.getElementById("analysis-gloss");
      const blockingPoint = document.getElementById("analysis-blocking-point");
      const skeleton = document.getElementById("analysis-skeleton");
      const clauses = document.getElementById("analysis-clauses");
      const modifiersSection = document.getElementById("analysis-modifiers-section");
      const modifiers = document.getElementById("analysis-modifiers");
      const logicMarkersSection = document.getElementById("analysis-logic-markers-section");
      const logicMarkers = document.getElementById("analysis-logic-markers");
      const anaphoraSection = document.getElementById("analysis-anaphora-section");
      const anaphora = document.getElementById("analysis-anaphora");
      const diagnosis = document.getElementById("analysis-diagnosis");
      const backToWhole = document.getElementById("analysis-back-to-whole");
      const sentencePanelTranslation = document.getElementById("sentence-panel-translation");
      const sentencePanelTranslationSave = document.getElementById("sentence-panel-translation-save");
      const sentencePanelTranslationStatus = document.getElementById("sentence-panel-translation-status");
      const sentencePanelStructure = document.getElementById("sentence-panel-structure");
      const sentencePanelStructureSave = document.getElementById("sentence-panel-structure-save");
      const sentencePanelStructureStatus = document.getElementById("sentence-panel-structure-status");
      const structureFeedbackSection = document.getElementById("analysis-structure-feedback-section");
      const structureFeedback = document.getElementById("analysis-structure-feedback");
      const sentencePanelNoteSuggestion = document.getElementById("sentence-panel-note-suggestion");
      const sentencePanelNoteAccept = document.getElementById("sentence-panel-note-accept");
      const sentencePanelNote = document.getElementById("sentence-panel-note");
      const sentencePanelNoteSave = document.getElementById("sentence-panel-note-save");
      const sentencePanelNoteStatus = document.getElementById("sentence-panel-note-status");
      const wordRole = document.getElementById("analysis-word-role");
      const wordAnalysisMeaning = document.getElementById("analysis-word-meaning");
      const wordAnalysisMeaningZh = document.getElementById("analysis-word-meaning-zh");
      const wordRegister = document.getElementById("analysis-word-register");
      const wordWhy = document.getElementById("analysis-word-why");
      const wordVsSimpler = document.getElementById("analysis-word-vs-simpler");
      const wordNoteCheckSection = document.getElementById("analysis-word-note-check-section");
      const wordNoteCheck = document.getElementById("analysis-word-note-check");
      const wordAnalysisMorphology = document.getElementById("analysis-word-morphology");
      const wordAnalysisErrors = document.getElementById("analysis-word-errors");
      const wordPanelMeaning = document.getElementById("word-panel-meaning");
      const wordPanelNote = document.getElementById("word-panel-note");
      const wordPanelSave = document.getElementById("word-panel-save");
      const wordPanelSaveStatus = document.getElementById("word-panel-save-status");
      const bookId = reader.dataset.bookId || "";
      const chapterIdx = Number.parseInt(reader.dataset.chapterIdx || "1", 10);
      const progressKey = bookId ? `reader:progress:book:${bookId}` : "";
      const initialParams = new URLSearchParams(window.location.search);
      const initialWordCardId = initialParams.get("word_card") || "";
      const initialSentenceId = initialParams.get("sentence_id") || "";
      const initialPanel = initialParams.get("panel") || "";
      const MAX_ANALYSIS_CONTEXT_TEXT = 1600;
      const ANALYSIS_TOOLS_COLLAPSE_SCROLL_TOP = 56;
      const ANALYSIS_TOOLS_HOT_ZONE_PX = 84;
      const AUTOSAVE_DELAY_MS = 700;
      const STRUCTURE_TEMPLATE = "主干：\n从句：\n修饰成分：\n指代逻辑：";
      const STRUCTURE_TEMPLATE_LABELS = ["主干：", "从句：", "修饰成分：", "指代逻辑："];

      // The structure editors prefill STRUCTURE_TEMPLATE as real text so the
      // learner can fill in only the parts they are unsure of. Treat a value
      // that is just the bare scaffold (labels + whitespace, no real content)
      // as empty so we never save it or burn an AI call on an empty attempt.
      function structureAttemptHasContent(value) {
        let text = String(value || "");
        for (const label of STRUCTURE_TEMPLATE_LABELS) {
          text = text.split(label).join("");
        }
        return text.replace(/\s+/g, "").length > 0;
      }

      const ERROR_CODE_LABELS = {
        G01: "G01 长主语识别失败",
        G02: "G02 后置定语修饰对象判断错",
        G03: "G03 嵌套从句边界混乱",
        G04: "G04 倒装 / 强调结构",
        G05: "G05 非谓语动词作用判断错",
        G06: "G06 省略 / 替代识别失败",
        G07: "G07 平行结构对应失败",
        L01: "L01 多义词义项判断错",
        L02: "L02 假朋友 / 形近词混淆",
        L03: "L03 搭配不熟（动名 / 形名 / 介词）",
        L04: "L04 词根 / 词族联想不足",
        L05: "L05 习语 / 固定短语未识别",
        L06: "L06 学术词汇陌生",
        D01: "D01 代词指代对象判断错",
        D02: "D02 让步 / 对比逻辑误读",
        D03: "D03 因果 / 推论连词误读",
        D04: "D04 信息焦点判断错",
        D05: "D05 篇章衔接回指失败",
        I01: "I01 隐含关系推断失败",
        I02: "I02 言外之意 / 立场推断失败",
        X00: "X00 其他",
      };

      const ERROR_CHECK_TIPS = {
        G01: "先找完整主语边界，再找真正的主句谓语。",
        G02: "先确认后置修饰语修饰哪个名词，再翻译主句动作。",
        G03: "先分清每个从句的起止位置，再判断它在主句里承担什么成分。",
        G04: "先还原正常语序，再判断强调或倒装改变了哪个焦点。",
        G05: "先判断非谓语是在修饰名词、补充动作，还是表示目的/结果。",
        G06: "先补出被省略或替代的成分，再连回前文。",
        G07: "先把并列项一一配对，确认它们共享同一个语法角色。",
        L01: "先根据上下文限定词义，不要直接套最熟悉的义项。",
        L02: "先检查它是否是假朋友或形近词，再确认词性和语境义。",
        L03: "先把搭配整体理解，再决定动词、名词或介词之间的关系。",
        L04: "先用词根词族辅助判断，再回到上下文验证。",
        L05: "先检查是否是固定短语或习语，不要逐词硬译。",
        L06: "先用句中功能判断学术词的大方向，再精修中文表达。",
        D01: "先回指最近且语义匹配的实体，再检查数和逻辑是否一致。",
        D02: "先找让步/对比两边，重点通常落在主句或转折后的信息。",
        D03: "先判断连词表达原因、结果还是推论，再翻译逻辑方向。",
        D04: "先判断句子真正强调的新信息，不要把背景信息当重点。",
        D05: "先把 this/these/such 等衔接词连回前文整件事或概念。",
        I01: "先检查句间或分句间是否有未明说的因果、转折、让步或条件关系。",
        I02: "先检查 so-called、may、in theory、some 等词是否在表达作者立场或保留态度。",
      };

      let activeSentenceId = null;
      let activeSentenceTranslation = "";
      let activeSentenceStructure = "";
      let activeWordCardId = null;
      let activeWordCardIds = [];
      let activeCrossSentenceIds = [];
      let activeWordDetailCardId = null;
      let activeAnalysisSentenceId = null;
      let activeAnalysisSourceSentenceId = null;
      let activeAnalysisWordCardId = null;
      let activeAnalysisPayload = null;
      let activeAnalysisLabel = "";
      let analysisHistory = [];
      let activeWordDetailFromAnalysis = false;
      let panelMode = "sentence";
      let translationEditorOpen = false;
      let structureEditorOpen = false;
      let progressTimer = null;
      let toolbarHideTimer = null;
      let translationAutoSaveTimer = null;
      let structureAutoSaveTimer = null;
      let analysisWordActionInProgress = false;
      let readerToolbarBusy = false;
      let toolbarInteractionSeq = 0;
      let activeSelectionAnalysisContextText = "";
      let copyStatusTimer = null;
      let translationSaveChain = Promise.resolve();
      let structureSaveChain = Promise.resolve();
      let lastSavedTranslation = "";
      let lastSavedStructure = "";
      let translationEditorDirty = false;
      let structureEditorDirty = false;
      let panelTranslationAutoSaveTimer = null;
      let panelStructureAutoSaveTimer = null;
      let panelTranslationSaveChain = Promise.resolve();
      let panelStructureSaveChain = Promise.resolve();
      let lastSavedPanelTranslation = "";
      let lastSavedPanelStructure = "";
      let panelTranslationDirty = false;
      let panelStructureDirty = false;
      const wordAnalysisContextByCardId = new Map();
      let suppressNextUpdate = false;
      let suppressCollapsedToolbarHideUntil = 0;

      if (bookId) {
        window.localStorage.setItem("reader:last-book-id", bookId);
      }

      const normalizeText = (value) => value.replace(/\s+/g, " ").trim();
      const normalizeContextText = (value) => normalizeText(String(value || "")).slice(0, MAX_ANALYSIS_CONTEXT_TEXT);
      const lemmaKey = (value) => normalizeText(value).toLowerCase();
      const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const distinctUserNote = (note, meaning) => {
        const cleanNote = String(note || "").trim();
        if (!cleanNote) return "";
        return cleanNote === String(meaning || "").trim() ? "" : cleanNote;
      };
      let glossaryRegex = null;

      function addGlossaryEntry(term, entry) {
        const key = lemmaKey(String(term || ""));
        if (!key || seenGlossaryTerms.has(key)) return;
        seenGlossaryTerms.add(key);
        glossaryEntries.push({
          key,
          pattern: escapeRegExp(key).replace(/\s+/g, "\\s+"),
          card: entry,
        });
      }

      function rebuildGlossaryRegex() {
        glossaryEntries.sort((a, b) => b.key.length - a.key.length);
        glossaryRegex = glossaryEntries.length
          ? new RegExp(`(^|[^A-Za-z0-9])(${glossaryEntries.map((entry) => entry.pattern).join("|")})(?=$|[^A-Za-z0-9])`, "gi")
          : null;
      }

      function registerWordCard(card) {
        if (!card || !card.id || !card.lemma) return;
        const key = lemmaKey(card.lemma);
        wordCards[key] = {
          id: card.id,
          surface_form: card.surface_form || card.lemma,
          lexical_type: card.lexical_type || "",
          current_meaning: card.current_meaning || "",
          user_note: distinctUserNote(card.user_note, card.current_meaning),
        };
        const entry = {
          lemma: card.lemma,
          id: card.id,
          surface: card.surface_form || "",
          lexical_type: card.lexical_type || "",
          meaning: card.current_meaning || "",
          note: distinctUserNote(card.user_note, card.current_meaning),
        };
        addGlossaryEntry(card.lemma, entry);
        addGlossaryEntry(card.surface_form, entry);
      }

      function unregisterWordCard(cardId) {
        const id = String(cardId || "");
        if (!id) return;
        for (const [key, card] of Object.entries(wordCards)) {
          if (String(card.id || "") === id) {
            delete wordCards[key];
          }
        }
        for (let index = glossaryEntries.length - 1; index >= 0; index -= 1) {
          if (String(glossaryEntries[index].card.id || "") === id) {
            glossaryEntries.splice(index, 1);
          }
        }
        seenGlossaryTerms.clear();
        glossaryEntries.forEach((entry) => seenGlossaryTerms.add(entry.key));
        rebuildGlossaryRegex();
      }

      for (const [lemma, card] of Object.entries(wordCards)) {
        registerWordCard({
          id: card.id,
          lemma,
          surface_form: card.surface_form || "",
          lexical_type: card.lexical_type || "",
          current_meaning: card.current_meaning || "",
          user_note: card.user_note || "",
        });
      }
      rebuildGlossaryRegex();

      function toolbarContainsFocus() {
        return Boolean(document.activeElement && toolbar.contains(document.activeElement));
      }

      function blurToolbarFocus() {
        if (toolbarContainsFocus() && typeof document.activeElement.blur === "function") {
          document.activeElement.blur();
        }
      }

      function selectionInsideToolbar(range) {
        const node = range.commonAncestorContainer;
        const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
        return Boolean(element && toolbar.contains(element));
      }

      function selectionInsideAnalysisPanel(range) {
        const node = range.commonAncestorContainer;
        const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
        return Boolean(element && panel && panel.contains(element));
      }

      function analysisContextFromElement(element) {
        if (!element || !panel || !panel.contains(element)) return "";
        const source = element.closest?.(".analysis-text, .vs-simpler-item, .analysis-section");
        return normalizeContextText(source?.textContent || "");
      }

      function analysisContextFromRange(range) {
        const node = range.commonAncestorContainer;
        const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
        return analysisContextFromElement(element);
      }

      function clearTranslationAutoSaveTimer() {
        if (translationAutoSaveTimer !== null) {
          window.clearTimeout(translationAutoSaveTimer);
          translationAutoSaveTimer = null;
        }
      }

      function clearStructureAutoSaveTimer() {
        if (structureAutoSaveTimer !== null) {
          window.clearTimeout(structureAutoSaveTimer);
          structureAutoSaveTimer = null;
        }
      }

      function enqueueTranslationSave(options = {}) {
        translationSaveChain = translationSaveChain
          .catch(() => {})
          .then(() => saveTranslationOnly(options));
        return translationSaveChain;
      }

      function enqueueStructureSave(options = {}) {
        structureSaveChain = structureSaveChain
          .catch(() => {})
          .then(() => saveStructureOnly(options));
        return structureSaveChain;
      }

      function scheduleTranslationAutoSave(delay = AUTOSAVE_DELAY_MS) {
        clearTranslationAutoSaveTimer();
        if (!translationEditorOpen || !activeSentenceId) return;
        const value = translationText.value.trim();
        if (!value || value === lastSavedTranslation) return;
        translationStatus.textContent = "Auto saving...";
        translationAutoSaveTimer = window.setTimeout(() => {
          translationAutoSaveTimer = null;
          enqueueTranslationSave({ automatic: true, keepOpen: true });
        }, delay);
      }

      function scheduleStructureAutoSave(delay = AUTOSAVE_DELAY_MS) {
        clearStructureAutoSaveTimer();
        if (!structureEditorOpen || !activeSentenceId) return;
        const value = structureText.value.trim();
        if (!structureAttemptHasContent(value) || value === lastSavedStructure) return;
        structureStatus.textContent = "Auto saving...";
        structureAutoSaveTimer = window.setTimeout(() => {
          structureAutoSaveTimer = null;
          enqueueStructureSave({ automatic: true, keepOpen: true });
        }, delay);
      }

      function sendPendingToolbarSave(url, fieldName, value) {
        const text = String(value || "").trim();
        if (!text) return;
        const body = new URLSearchParams({ [fieldName]: text, return_to: returnTo }).toString();
        if (navigator.sendBeacon && navigator.sendBeacon(url, body)) return;
        fetch(url, {
          method: "POST",
          headers: {"Content-Type": "application/x-www-form-urlencoded"},
          body,
          keepalive: true,
        }).catch(() => {});
      }

      function flushPendingToolbarAutoSaveOnPageHide() {
        clearTranslationAutoSaveTimer();
        clearStructureAutoSaveTimer();
        if (translationEditorOpen && translationEditorDirty && activeSentenceId) {
          const value = translationText.value.trim();
          if (value && value !== lastSavedTranslation) {
            sendPendingToolbarSave(
              `/mark/sentence/${activeSentenceId}/translation`,
              "user_translation",
              value,
            );
          }
        }
        if (structureEditorOpen && structureEditorDirty && activeSentenceId) {
          const value = structureText.value.trim();
          if (structureAttemptHasContent(value) && value !== lastSavedStructure) {
            sendPendingToolbarSave(
              `/mark/sentence/${activeSentenceId}/structure`,
              "user_structure",
              value,
            );
          }
        }
        if (panelStructureDirty && activeAnalysisSentenceId && sentencePanelStructure) {
          const value = (sentencePanelStructure.value || "").trim();
          if (structureAttemptHasContent(value) && value !== lastSavedPanelStructure) {
            sendPendingToolbarSave(
              `/mark/sentence/${activeAnalysisSentenceId}/structure`,
              "user_structure",
              value,
            );
          }
        }
        if (panelTranslationDirty && activeAnalysisSentenceId && sentencePanelTranslation) {
          const value = (sentencePanelTranslation.value || "").trim();
          if (value && value !== lastSavedPanelTranslation) {
            sendPendingToolbarSave(
              `/mark/sentence/${activeAnalysisSentenceId}/translation`,
              "user_translation",
              value,
            );
          }
        }
      }

      async function closeTranslationEditor() {
        clearTranslationAutoSaveTimer();
        const saved = translationEditorDirty
          ? await enqueueTranslationSave({ automatic: true, keepOpen: true })
          : true;
        if (saved !== false) hideToolbar();
      }

      async function closeStructureEditor() {
        clearStructureAutoSaveTimer();
        const saved = structureEditorDirty
          ? await enqueueStructureSave({ automatic: true, keepOpen: true })
          : true;
        if (saved !== false) hideToolbar();
      }

      function hideTranslationEditor() {
        clearTranslationAutoSaveTimer();
        translationEditor.hidden = true;
        translationEditorOpen = false;
        translationStatus.textContent = "";
        if (translationEditor.contains(document.activeElement)) {
          blurToolbarFocus();
        }
      }

      function hideStructureEditor() {
        clearStructureAutoSaveTimer();
        structureEditor.hidden = true;
        structureEditorOpen = false;
        structureStatus.textContent = "";
        if (structureEditor.contains(document.activeElement)) {
          blurToolbarFocus();
        }
      }

      function hideAllPanels() {
        hideTranslationEditor();
        hideStructureEditor();
        setVisible(sentenceForm, false);
        setVisible(wordForm, false);
        setVisible(analysisWordForm, false);
        setVisible(wordDetail, false);
        activeWordDetailFromAnalysis = false;
        setVisible(crossSentence, false);
        analysisOpen.hidden = true;
      }

      function clearScheduledToolbarHide() {
        if (toolbarHideTimer !== null) {
          window.clearTimeout(toolbarHideTimer);
          toolbarHideTimer = null;
        }
      }

      function scheduleToolbarHide(delay) {
        clearScheduledToolbarHide();
        toolbarHideTimer = window.setTimeout(() => {
          toolbarHideTimer = null;
          hideToolbar();
        }, delay);
      }

      function hideToolbar() {
        clearScheduledToolbarHide();
        hideAllPanels();
        toolbar.hidden = true;
        activeSentenceId = null;
        activeSentenceTranslation = "";
        activeSentenceStructure = "";
        activeWordCardId = null;
        activeWordCardIds = [];
        activeCrossSentenceIds = [];
        activeWordDetailCardId = null;
        activeWordDetailFromAnalysis = false;
        wordDetailRemove.dataset.cardId = "";
        crossSentenceDelete.dataset.sentenceIds = "";
        blurToolbarFocus();
      }

      function hideToolbarUnlessEditing() {
        if (translationEditorOpen || structureEditorOpen) return;
        hideToolbar();
      }

      function maybeHideToolbarAfterRender(seqAtRequest) {
        if (readerToolbarBusy) return;
        if (seqAtRequest !== toolbarInteractionSeq) return;
        hideToolbarUnlessEditing();
      }

      function setVisible(element, visible) {
        element.hidden = !visible;
      }

      function selectedSentenceSpans(range) {
        return Array.from(reader.querySelectorAll("[data-sentence-id]")).filter((span) => {
          try {
            if (!range.intersectsNode(span)) return false;
            // Exclude span when range only touches its trailing boundary
            if (range.startContainer === span && range.startOffset >= span.childNodes.length) return false;
            return true;
          } catch {
            return false;
          }
        });
      }

      function selectedWordCardIds(range) {
        const ids = Array.from(reader.querySelectorAll("[data-word-card]"))
          .filter((span) => {
            try {
              return range.intersectsNode(span);
            } catch {
              return false;
            }
          })
          .map((span) => span.dataset.wordCard)
          .filter(Boolean);
        return Array.from(new Set(ids));
      }

      function selectedReadingElement() {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
        const range = selection.getRangeAt(0);
        if (selectionInsideToolbar(range) || selectionInsideAnalysisPanel(range)) return null;
        const node = range.commonAncestorContainer;
        const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
        return element?.closest?.("[data-word-card], [data-sentence-id]")
          || selectedSentenceSpans(range)[0]
          || null;
      }

      function elementFromNode(node) {
        return node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement || null;
      }

      function topVisibleSentence() {
        const sentences = Array.from(reader.querySelectorAll("[data-sentence-id]"));
        for (const sentence of sentences) {
          const rect = sentence.getBoundingClientRect();
          if (rect.bottom >= 0 && rect.top <= window.innerHeight) return sentence;
        }
        return sentences[0] || null;
      }

      function sentenceFromSelectionOrViewport() {
        const selection = window.getSelection();
        if (selection && selection.rangeCount > 0) {
          const range = selection.getRangeAt(0);
          if (!selectionInsideToolbar(range) && !selectionInsideAnalysisPanel(range)) {
            const element = elementFromNode(selection.anchorNode);
            const sentence = element?.closest?.("[data-sentence-id]");
            if (sentence) return sentence;
          }
        }
        return topVisibleSentence();
      }

      function selectWholeSentence(sentence) {
        if (!sentence) return false;
        const range = document.createRange();
        range.selectNodeContents(sentence);
        const selection = window.getSelection();
        if (!selection) return false;
        selection.removeAllRanges();
        selection.addRange(range);
        updateToolbar();
        return true;
      }

      function eventTargetIsTextInput(event) {
        return Boolean(event.target?.closest?.("input, textarea, select, [contenteditable='true']"));
      }

      function handleReaderShortcut(event) {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        if (event.isComposing || eventTargetIsTextInput(event)) return;
        // macOS global hotkey tools intercept every modifier combo (Option+S/T were stolen),
        // so use bare physical keys matched via event.code (layout- and modifier-independent).
        // The reader text is non-editable, so plain S/T never collide with typing here.
        const isSelect = event.code === "KeyS";
        const isTranslate = event.code === "KeyT";
        if (!isSelect && !isTranslate) return;
        event.preventDefault();
        const sentence = sentenceFromSelectionOrViewport();
        if (!sentence || !selectWholeSentence(sentence)) return;
        if (isTranslate) {
          activeSentenceId = sentence.dataset.sentenceId;
          activeSentenceTranslation = sentence.dataset.translation || "";
          openTranslationEditor();
        }
      }

      function captureReadingAnchor(target) {
        const targetElement = target?.closest?.("[data-word-card], [data-sentence-id]");
        const activeWordElement = activeWordDetailCardId
          ? reader.querySelector(`[data-word-card="${activeWordDetailCardId}"]`)
          : null;
        const activeSentenceElement = activeSentenceId
          ? document.getElementById(`sentence-${activeSentenceId}`)
          : null;
        const element = targetElement
          || selectedReadingElement()
          || activeWordElement
          || activeSentenceElement;
        if (!element) return { scrollY: window.scrollY };
        return {
          element,
          scrollY: window.scrollY,
          top: element.getBoundingClientRect().top,
        };
      }

      function restoreReadingAnchor(anchor) {
        if (!anchor) return;
        if (anchor.element && anchor.element.isConnected) {
          const delta = anchor.element.getBoundingClientRect().top - anchor.top;
          if (delta) window.scrollBy(0, delta);
          return;
        }
        window.scrollTo(0, anchor.scrollY || 0);
      }

      function decorateWordCardElement(element, card) {
        if (!element || !card) return;
        const meaning = card.current_meaning || "";
        element.dataset.wordCard = String(card.id || "");
        element.dataset.lexicalType = card.lexical_type || "";
        element.dataset.meaning = meaning;
        element.dataset.note = distinctUserNote(card.user_note, meaning);
      }

      function clearWordCardElement(element) {
        if (!element) return;
        element.removeAttribute("data-word-card");
        element.removeAttribute("data-card-id");
        element.removeAttribute("data-meaning");
        element.removeAttribute("data-note");
        element.removeAttribute("data-lemma");
        element.removeAttribute("data-lexical-type");
        element.classList.remove("glossary-word", "marked-word", "word-analysis-active");
      }

      function updateWordCardElements(cardId, meaning, note) {
        if (!cardId) return;
        document.querySelectorAll(`[data-word-card="${cardId}"], .glossary-word[data-card-id="${cardId}"]`).forEach((span) => {
          span.dataset.meaning = meaning;
          span.dataset.note = note;
        });
      }

      function selectedReaderRangeClone() {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
        const range = selection.getRangeAt(0);
        if (selectionInsideToolbar(range) || selectionInsideAnalysisPanel(range)) return null;
        return range.cloneRange();
      }

      function applyWordCardToRange(range, card) {
        if (!range || !card) return null;
        const span = document.createElement("span");
        decorateWordCardElement(span, card);
        try {
          const contents = range.extractContents();
          span.appendChild(contents);
          range.insertNode(span);
          return span;
        } catch {
          return null;
        }
      }

      function configureCrossSentenceActions(spans) {
        activeCrossSentenceIds = spans
          .filter((span) => span.dataset.marked === "1")
          .map((span) => span.dataset.sentenceId)
          .filter(Boolean);
        crossSentenceDelete.dataset.sentenceIds = activeCrossSentenceIds.join(",");
        crossSentenceDelete.textContent =
          `Unmark ${activeCrossSentenceIds.length} sentence${activeCrossSentenceIds.length === 1 ? "" : "s"}`;
        setVisible(crossSentenceDelete, activeCrossSentenceIds.length > 0);
      }

      function positionToolbar(anchor) {
        clearScheduledToolbarHide();
        toolbar.hidden = false;
        toolbarInteractionSeq += 1;
        requestAnimationFrame(() => {
          const toolbarRect = toolbar.getBoundingClientRect();
          const viewportPadding = 8;
          const gap = 10;
          const availableAbove = anchor.top - viewportPadding - gap;
          const availableBelow = window.innerHeight - anchor.bottom - viewportPadding - gap;
          const maxViewportTop = Math.max(
            viewportPadding,
            window.innerHeight - toolbarRect.height - viewportPadding,
          );
          let viewportTop;
          if (toolbarRect.height <= availableAbove) {
            viewportTop = anchor.top - toolbarRect.height - gap;
          } else if (toolbarRect.height <= availableBelow) {
            viewportTop = anchor.bottom + gap;
          } else if (availableBelow >= availableAbove) {
            viewportTop = Math.min(anchor.bottom + gap, maxViewportTop);
          } else {
            viewportTop = Math.max(viewportPadding, anchor.top - toolbarRect.height - gap);
          }
          const clampedTop = Math.max(viewportPadding, Math.min(viewportTop, maxViewportTop));
          const centeredLeft = window.scrollX + anchor.left + (anchor.width / 2) - (toolbarRect.width / 2);
          const maxLeft = window.scrollX + window.innerWidth - toolbarRect.width - viewportPadding;
          const left = Math.max(window.scrollX + viewportPadding, Math.min(centeredLeft, maxLeft));
          toolbar.style.top = `${window.scrollY + clampedTop}px`;
          toolbar.style.left = `${left}px`;
        });
      }

      function showToolbar(range) {
        const rect = range.getBoundingClientRect();
        const fallbackRect = range.getClientRects()[0];
        const anchor = rect.width || rect.height ? rect : fallbackRect;
        if (!anchor) { hideToolbar(); return; }
        positionToolbar(anchor);
      }

      function fillWordDetail(cardId, surface, meaning, note) {
        activeWordDetailCardId = String(cardId || "");
        const cleanMeaning = meaning || "";
        wordDetailSurface.textContent = surface || "";
        wordDetailMeaning.value = cleanMeaning;
        wordDetailNote.value = distinctUserNote(note, cleanMeaning);
        wordDetailRemove.dataset.cardId = activeWordDetailCardId;
        if (wordDetailViewCard) wordDetailViewCard.dataset.cardId = activeWordDetailCardId;
      }

      function analysisButtonLabel(sentence) {
        if (sentence?.dataset.translation?.trim()) return "Check translation";
        return sentence?.dataset.analysisId ? "Open analysis panel" : "AI analysis";
      }

      function markSentenceTranslated(sentence, translation) {
        if (!sentence) return;
        sentence.dataset.translation = translation;
        if (sentence.dataset.analysisId) {
          sentence.dataset.analysisStale = "1";
          sentence.classList.remove("analyzed");
          sentence.classList.add("analyzed-stale");
        } else {
          sentence.dataset.analysisId = "";
          sentence.dataset.analysisStale = "0";
          sentence.classList.remove("analyzed", "analyzed-stale");
        }
        sentence.classList.add("translated");
        sentence.title = "Translation saved";
      }

      function clearSentenceTranslation(sentence) {
        if (!sentence) return;
        sentence.dataset.translation = "";
        sentence.dataset.marked = "0";
        sentence.dataset.analysisId = "";
        sentence.dataset.analysisStale = "0";
        sentence.classList.remove("translated", "marked", "analyzed", "analyzed-stale");
        sentence.removeAttribute("title");
      }

      function updateSentenceNote(sentenceId, note) {
        const sentence = document.getElementById(`sentence-${sentenceId}`);
        if (sentence) sentence.dataset.note = note || "";
        if (activeAnalysisPayload && String(activeAnalysisPayload.sentence_id || "") === String(sentenceId)) {
          activeAnalysisPayload.user_note = note || "";
        }
      }

      function acceptTakeawaySuggestion() {
        const suggestion = (sentencePanelNoteSuggestion?.textContent || "").trim();
        if (!suggestion || !sentencePanelNote) return;
        sentencePanelNote.value = suggestion;
        sentencePanelNote.focus();
        if (sentencePanelNoteStatus) {
          sentencePanelNoteStatus.textContent = "Suggestion inserted. Edit or save it.";
        }
      }

      function sentenceTextForId(sentenceId) {
        return normalizeText(document.getElementById(`sentence-${sentenceId}`)?.textContent || "");
      }

      function appendCopyLine(lines, label, value) {
        const text = Array.isArray(value)
          ? value.filter(Boolean).join("; ")
          : String(value || "").trim();
        if (text) lines.push(`${label}: ${text}`);
      }

      function appendCopyItems(lines, label, items, formatter) {
        const formatted = (items || []).map(formatter).filter(Boolean);
        if (formatted.length) lines.push(`${label}:\n- ${formatted.join("\n- ")}`);
      }

      function buildSentenceSourceCopyText(payload) {
        const lines = [];
        appendCopyLine(lines, "Original sentence", sentenceTextForId(payload.sentence_id));
        appendCopyLine(lines, "Your translation", payload.user_translation);
        appendCopyLine(lines, "Your structure attempt", payload.user_structure);
        return lines;
      }

      function buildSentenceAnalysisCopyText(payload) {
        const analysis = payload.analysis || {};
        const lines = [];
        appendCopyLine(lines, "Simplified English", analysis.simplified_en);
        appendCopyLine(lines, "Chinese meaning", analysis.chinese_gloss);
        appendCopyLine(lines, "Blocking point", analysis.blocking_point);
        appendCopyLine(lines, "Subject skeleton", analysis.subject_skeleton);
        appendCopyItems(lines, "Clauses", analysis.clauses, (item) => {
          const type = item.type ? `${item.type}: ` : "";
          const role = item.role ? ` — ${item.role}` : "";
          return `${type}${item.text || ""}${role}`.trim();
        });
        appendCopyItems(lines, "Modifiers", analysis.modifiers, (item) => {
          const modifier = item.modifier || "";
          const target = item.target || "";
          const type = item.type ? ` (${item.type})` : "";
          return `${modifier} -> ${target}${type}`.trim();
        });
        appendCopyItems(lines, "Logic markers", analysis.logic_markers, (item) => {
          return `${item.marker || ""} -> ${item.function || ""}`.trim();
        });
        appendCopyItems(lines, "Anaphora", analysis.anaphora, (item) => {
          return `${item.pronoun || ""} -> ${item.refers_to || ""}`.trim();
        });
        appendCopyLine(
          lines,
          "Diagnosis basis",
          analysis.diagnosis_basis === "user_translation"
            ? "Based on your translation"
            : "Predicted without a translation",
        );
        const errorCodes = analysis.diagnosis_basis === "user_translation"
          ? analysis.diagnosed_error_types
          : analysis.predicted_error_types;
        appendCopyLine(lines, "Error types", (errorCodes || []).map((code) => ERROR_CODE_LABELS[code] || code));
        appendCopyItems(lines, "Diagnosis evidence", analysis.diagnosis_evidence, (item) => {
          const code = item.error_type ? `${ERROR_CODE_LABELS[item.error_type] || item.error_type}: ` : "";
          return `${code}${item.evidence || ""}`.trim();
        });
        appendCopyItems(
          lines,
          "Structure feedback",
          analysis.structure_feedback?.missed_or_wrong || [],
          (item) => {
            const code = item.error_code ? `${ERROR_CODE_LABELS[item.error_code] || item.error_code}: ` : "";
            return `${code}${item.learner_claim || ""} -> ${item.correction || ""} ${item.reason || ""}`.trim();
          },
        );
        appendCopyLine(lines, "Corrected structure", analysis.structure_feedback?.corrected_structure);
        appendCopyLine(
          lines,
          "Why it matters for translation",
          analysis.structure_feedback?.why_it_matters_for_translation,
        );
        appendCopyLine(lines, "Next structure check", analysis.structure_feedback?.next_check);
        appendCopyItems(lines, "Similar past mistakes", payload.similar_mistakes, (item) => {
          const codes = (item.shared_error_codes || []).map((code) => ERROR_CODE_LABELS[code] || code).join(", ");
          const sentence = item.sentence_text || "";
          return [codes, sentence].filter(Boolean).join(" | ");
        });
        appendCopyLine(lines, "Takeaway suggestion", analysis.takeaway_suggestion);
        appendCopyLine(lines, "Takeaway", payload.user_note);
        return lines;
      }

      function buildSentenceCopyText(payload, kind) {
        const source = buildSentenceSourceCopyText(payload);
        const analysis = buildSentenceAnalysisCopyText(payload);
        if (kind === "source") return source;
        if (kind === "analysis") return analysis;
        return source.concat(analysis);
      }

      function buildWordSourceCopyText(payload) {
        const lines = [];
        appendCopyLine(lines, "Word or phrase", payload.surface_form || payload.lemma);
        appendCopyLine(lines, "Source sentence", sentenceTextForId(payload.sentence_id));
        appendCopyLine(lines, "Context", wordAnalysisContextByCardId.get(String(payload.card_id || "")));
        return lines;
      }

      function buildWordAnalysisCopyText(payload) {
        const analysis = payload.analysis || {};
        const lines = [];
        appendCopyLine(lines, "In this sentence", analysis.role_in_sentence);
        appendCopyLine(lines, "Meaning in context", analysis.meaning_in_context);
        appendCopyLine(lines, "Chinese meaning", analysis.chinese_meaning || analysis.chinese_gloss);
        appendCopyLine(lines, "Register", analysis.register);
        appendCopyLine(lines, "Why this word", analysis.why_this_word);
        appendCopyItems(lines, "vs. simpler alternatives", analysis.vs_simpler, (item) => {
          return `${item.simpler || ""}: ${item.difference || ""}`.trim();
        });
        const check = analysis.learner_note_check || {};
        appendCopyLine(
          lines,
          "Takeaway check",
          [check.status, check.feedback, check.corrected_understanding].filter(Boolean).join(" "),
        );
        const root = analysis.morphology?.root || "";
        const family = (analysis.morphology?.family || []).join(", ");
        appendCopyLine(lines, "Morphology", root ? (family ? `${root} -> ${family}` : root) : family);
        appendCopyLine(
          lines,
          "Predicted error types",
          (analysis.predicted_error_types || []).map((code) => ERROR_CODE_LABELS[code] || code),
        );
        appendCopyLine(lines, "Definition", wordPanelMeaning?.value);
        appendCopyLine(lines, "Takeaway", wordPanelNote?.value);
        return lines;
      }

      function buildWordCopyText(payload, kind) {
        const source = buildWordSourceCopyText(payload);
        const analysis = buildWordAnalysisCopyText(payload);
        if (kind === "source") return source;
        if (kind === "analysis") return analysis;
        return source.concat(analysis);
      }

      function setCopyStatus(message) {
        if (!copyStatus) return;
        copyStatus.textContent = message;
        if (copyStatusTimer !== null) window.clearTimeout(copyStatusTimer);
        copyStatusTimer = window.setTimeout(() => {
          copyStatusTimer = null;
          if (copyStatus) copyStatus.textContent = "";
        }, 1500);
      }

      async function writeClipboard(text) {
        if (!text.trim()) {
          setCopyStatus("Nothing to copy");
          return;
        }
        try {
          if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
          await navigator.clipboard.writeText(text);
          setCopyStatus("Copied");
        } catch {
          const textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          const copied = document.execCommand("copy");
          textarea.remove();
          setCopyStatus(copied ? "Copied" : "Copy failed");
        }
      }

      function copyAnalysisPayload(kind) {
        if (!activeAnalysisPayload) {
          setCopyStatus("Nothing to copy");
          return;
        }
        const isWord = panelMode === "word" || (activeAnalysisLabel && activeAnalysisLabel !== "sentence");
        const parts = isWord
          ? buildWordCopyText(activeAnalysisPayload, kind)
          : buildSentenceCopyText(activeAnalysisPayload, kind);
        writeClipboard(parts.filter(Boolean).join("\n"));
      }

      function showWordDetail(span) {
        suppressNextUpdate = true;
        suppressCollapsedToolbarHideUntil = Date.now() + 250;
        hideAllPanels();
        activeWordDetailFromAnalysis = Boolean(panel && panel.contains(span));
        fillWordDetail(
          span.dataset.wordCard,
          span.textContent,
          span.dataset.meaning,
          span.dataset.note,
        );
        setVisible(wordDetail, true);
        positionToolbar(span.getBoundingClientRect());
      }

      function showMarkedSentenceToolbar(sentence) {
        suppressNextUpdate = true;
        suppressCollapsedToolbarHideUntil = Date.now() + 250;
        hideAllPanels();
        activeSentenceId = sentence.dataset.sentenceId;
        activeSentenceTranslation = sentence.dataset.translation || "";
        activeSentenceStructure = sentence.dataset.structure || "";
        activeWordCardId = null;
        activeWordCardIds = [];

        sentenceForm.action = `/mark/sentence/${activeSentenceId}`;
        translationForm.action = `/mark/sentence/${activeSentenceId}/translation`;
        sentenceSubmit.hidden = true;
        sentenceDelete.hidden = sentence.dataset.marked !== "1";
        translationOpen.hidden = false;
        structureOpen.hidden = false;
        translationDelete.hidden = !activeSentenceTranslation;
        analysisOpen.hidden = false;
        translationOpen.textContent = activeSentenceTranslation ? "Update translation" : "Write translation";
        structureOpen.textContent = activeSentenceStructure ? "Update structure" : "Write structure";
        analysisOpen.textContent = analysisButtonLabel(sentence);
        configureCrossSentenceActions([]);
        setVisible(sentenceForm, true);
        positionToolbar(sentence.getBoundingClientRect());
      }

      function openTranslatedSentenceShortcut(sentence) {
        if (!sentence?.dataset.translation?.trim()) return false;
        activeSentenceId = sentence.dataset.sentenceId;
        activeSentenceTranslation = sentence.dataset.translation || "";
        activeSentenceStructure = sentence.dataset.structure || "";
        if (sentence.dataset.analysisId) {
          hideToolbar();
          loadSavedAnalysis(activeSentenceId);
          return true;
        }
        showMarkedSentenceToolbar(sentence);
        openTranslationEditor();
        return true;
      }

      function showAnalysisWordToolbar(range, selectedText) {
        if (!activeAnalysisSourceSentenceId) {
          hideToolbar();
          return;
        }
        hideAllPanels();
        activeSelectionAnalysisContextText = analysisContextFromRange(range);
        analysisWordForm.dataset.contextText = activeSelectionAnalysisContextText;
        analysisWordSentenceId.value = activeAnalysisSourceSentenceId;
        analysisWordSurfaceForm.value = selectedText;
        if (analysisWordStatus) analysisWordStatus.textContent = "";
        setAnalysisWordButtonsDisabled(false);
        setVisible(analysisWordForm, true);
        showToolbar(range);
      }

      function glossaryHighlightFragment(text) {
        if (!glossaryRegex || !text.trim()) return null;
        glossaryRegex.lastIndex = 0;
        const fragment = document.createDocumentFragment();
        let cursor = 0;
        let hasHit = false;
        let match = glossaryRegex.exec(text);
        while (match) {
          const prefix = match[1] || "";
          const token = match[2] || "";
          const tokenStart = match.index + prefix.length;
          const tokenEnd = tokenStart + token.length;
          const entry = glossaryEntries.find((candidate) => candidate.key === lemmaKey(token));
          if (entry) {
            if (tokenStart > cursor) {
              fragment.appendChild(document.createTextNode(text.slice(cursor, tokenStart)));
            }
            const span = document.createElement("span");
            span.className = "glossary-word";
            span.textContent = text.slice(tokenStart, tokenEnd);
            span.dataset.wordCard = String(entry.card.id || "");
            span.dataset.cardId = String(entry.card.id || "");
            span.dataset.meaning = entry.card.meaning || "";
            span.dataset.note = entry.card.note || "";
            span.dataset.lemma = entry.card.lemma || "";
            span.dataset.lexicalType = entry.card.lexical_type || "";
            fragment.appendChild(span);
            cursor = tokenEnd;
            hasHit = true;
          }
          match = glossaryRegex.exec(text);
        }
        if (!hasHit) return;
        if (cursor < text.length) {
          fragment.appendChild(document.createTextNode(text.slice(cursor)));
        }
        return fragment;
      }

      function applyGlossaryHighlights(element) {
        if (!element || !glossaryRegex) return;
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
          acceptNode(node) {
            if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
            const parent = node.parentElement;
            if (parent && parent.closest(".glossary-word, [data-word-card]")) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
          },
        });
        const textNodes = [];
        let node = walker.nextNode();
        while (node) {
          textNodes.push(node);
          node = walker.nextNode();
        }
        textNodes.forEach((textNode) => {
          const fragment = glossaryHighlightFragment(textNode.nodeValue || "");
          if (fragment) textNode.replaceWith(fragment);
        });
      }

      function refreshAnalysisGlossaryHighlights() {
        [
          simplified, gloss, blockingPoint, skeleton, clauses, modifiers, logicMarkers,
          anaphora, backToWhole, wordRole, wordAnalysisMeaning, wordRegister, wordWhy,
          wordVsSimpler, wordAnalysisMorphology,
        ]
          .forEach((element) => applyGlossaryHighlights(element));
      }

      function refreshReaderGlossaryHighlights() {
        applyGlossaryHighlights(reader);
      }

      function setAnalysisWordButtonsDisabled(disabled) {
        analysisWordForm.querySelectorAll("button").forEach((button) => {
          button.disabled = disabled;
        });
      }

      async function markAnalysisSelection(lexicalType, analyzeAfter) {
        const sentenceId = analysisWordSentenceId.value;
        const surfaceForm = analysisWordSurfaceForm.value.trim();
        if (!sentenceId || !surfaceForm) return;
        const contextText = analysisWordForm.dataset.contextText || activeSelectionAnalysisContextText || "";
        analysisWordActionInProgress = true;
        suppressCollapsedToolbarHideUntil = Date.now() + 1200;
        if (analysisWordStatus) analysisWordStatus.textContent = analyzeAfter ? "Saving and analyzing..." : "Saving...";
        setAnalysisWordButtonsDisabled(true);
        try {
          const body = new URLSearchParams({
            sentence_id: sentenceId,
            surface_form: surfaceForm,
            lexical_type: lexicalType,
            return_to: returnTo,
          });
          const response = await fetch("/mark/word", {
            method: "POST",
            headers: {
              Accept: "application/json",
              "X-Requested-With": "fetch",
            },
            body,
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            if (analysisWordStatus) analysisWordStatus.textContent = payload.error || "Save failed.";
            return;
          }
          registerWordCard(payload.word_card);
          rebuildGlossaryRegex();
          refreshAnalysisGlossaryHighlights();
          refreshReaderGlossaryHighlights();
          if (payload.card_id && contextText.trim()) {
            wordAnalysisContextByCardId.set(String(payload.card_id), contextText.trim());
          }
          if (analyzeAfter) {
            window.getSelection()?.removeAllRanges();
            hideToolbar();
            requestWordAnalysis(String(payload.card_id), {
              contextText,
              pushCurrent: !panel.hidden,
            });
            return;
          }
          if (analysisWordStatus) analysisWordStatus.textContent = "Saved";
          window.getSelection()?.removeAllRanges();
          scheduleToolbarHide(650);
        } catch (error) {
          if (analysisWordStatus) analysisWordStatus.textContent = `Save failed: ${error}`;
        } finally {
          setAnalysisWordButtonsDisabled(false);
          analysisWordActionInProgress = false;
        }
      }

      async function markReaderSelection(lexicalType, submitter) {
        const sentenceId = wordSentenceId.value;
        const surfaceForm = wordSurfaceForm.value.trim();
        if (!sentenceId || !surfaceForm) return;
        const anchor = captureReadingAnchor(submitter);
        const range = selectedReaderRangeClone();
        const body = new URLSearchParams({
          sentence_id: sentenceId,
          surface_form: surfaceForm,
          lexical_type: lexicalType,
          return_to: returnTo,
        });
        readerToolbarBusy = true;
        try {
          const response = await fetch("/mark/word", {
            method: "POST",
            headers: {
              Accept: "application/json",
              "X-Requested-With": "fetch",
            },
            body,
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            window.location.assign(response.url || returnTo);
            return;
          }
          registerWordCard(payload.word_card);
          rebuildGlossaryRegex();
          const marked = applyWordCardToRange(range, payload.word_card);
          if (marked && activeSentenceId) {
            const sentence = document.getElementById(`sentence-${activeSentenceId}`);
            if (sentence) sentence.normalize();
          }
          window.getSelection()?.removeAllRanges();
          hideToolbar();
          restoreReadingAnchor(anchor);
        } catch {
          window.location.assign(returnTo);
        } finally {
          readerToolbarBusy = false;
        }
      }

      function updateToolbar() {
        if (suppressNextUpdate) {
          suppressNextUpdate = false;
          return;
        }
        if (translationEditorOpen || structureEditorOpen) return;
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
          if (analysisWordActionInProgress) return;
          if (Date.now() < suppressCollapsedToolbarHideUntil) return;
          if (toolbarContainsFocus()) return;
          hideToolbar();
          return;
        }

        const range = selection.getRangeAt(0);
        if (selectionInsideToolbar(range)) return;
        const selectedText = selection.toString().trim();
        const normalizedSelection = normalizeText(selectedText);
        if (!normalizedSelection) {
          hideToolbar();
          return;
        }

        if (selectionInsideAnalysisPanel(range)) {
          showAnalysisWordToolbar(range, selectedText);
          return;
        }

        const spans = selectedSentenceSpans(range);
        if (!spans.length) {
          hideToolbar();
          return;
        }

        hideAllPanels();
        if (spans.length > 1) {
          configureCrossSentenceActions(spans);
          setVisible(crossSentence, true);
          showToolbar(range);
          return;
        }

        const sentence = spans[0];
        activeSentenceId = sentence.dataset.sentenceId;
        activeSentenceTranslation = sentence.dataset.translation || "";
        activeSentenceStructure = sentence.dataset.structure || "";
        const wholeSentence = normalizedSelection === normalizeText(sentence.textContent || "");
        const markedSentence = sentence.dataset.marked === "1";
        const selectedCardIds = selectedWordCardIds(range);
        const existingWord = selectedCardIds.length ? null : wordCards[lemmaKey(selectedText)];
        activeWordCardIds = selectedCardIds.length
          ? selectedCardIds
          : (existingWord ? [String(existingWord.id)] : []);
        activeWordCardId = activeWordCardIds.length ? activeWordCardIds[0] : null;

        sentenceForm.action = `/mark/sentence/${activeSentenceId}`;
        translationForm.action = `/mark/sentence/${activeSentenceId}/translation`;
        sentenceSubmit.hidden = !wholeSentence || markedSentence;
        sentenceDelete.hidden = !wholeSentence || !markedSentence;
        translationOpen.hidden = !wholeSentence;
        structureOpen.hidden = !wholeSentence;
        translationDelete.hidden = !wholeSentence || !activeSentenceTranslation;
        analysisOpen.hidden = false;
        translationOpen.textContent = activeSentenceTranslation ? "Update translation" : "Write translation";
        structureOpen.textContent = activeSentenceStructure ? "Update structure" : "Write structure";
        analysisOpen.textContent = analysisButtonLabel(sentence);

        wordSentenceId.value = activeSentenceId;
        wordSurfaceForm.value = selectedText;
        configureCrossSentenceActions([]);
        if (wholeSentence) {
          setVisible(sentenceForm, true);
        } else if (activeWordCardId) {
          const detailSpan = reader.querySelector(`[data-word-card="${activeWordCardId}"]`);
          if (detailSpan) {
            fillWordDetail(
              activeWordCardId,
              detailSpan.textContent,
              detailSpan.dataset.meaning,
              detailSpan.dataset.note,
            );
          } else {
            fillWordDetail(
              activeWordCardId,
              existingWord?.surface_form || selectedText,
              existingWord?.current_meaning,
              existingWord?.user_note,
            );
          }
          setVisible(wordDetail, true);
        } else {
          setVisible(wordForm, true);
        }
        showToolbar(range);
      }

      function readProgress() {
        if (!progressKey) return null;
        try {
          return JSON.parse(window.localStorage.getItem(progressKey) || "null");
        } catch {
          return null;
        }
      }

      function restoreReaderProgress() {
        if (reader.dataset.restoreProgress !== "1") return;
        const saved = readProgress();
        if (!saved) return null;
        const savedChapter = Number.parseInt(saved.chapter_idx, 10);
        if (savedChapter && savedChapter !== chapterIdx) {
          window.location.replace(`/read/${bookId}?chapter=${savedChapter}&restore=1`);
          return null;
        }
        const sentenceId = Number.parseInt(saved.top_sentence_id, 10);
        if (sentenceId) {
          window.setTimeout(() => {
            document.getElementById(`sentence-${sentenceId}`)?.scrollIntoView({ block: "start" });
          }, 0);
        }
        return saved;
      }

      function topSentenceId() {
        const spans = Array.from(reader.querySelectorAll("[data-sentence-id]"));
        for (const span of spans) {
          const rect = span.getBoundingClientRect();
          if (rect.bottom >= 0) {
            return Number.parseInt(span.dataset.sentenceId, 10);
          }
        }
        return spans.length ? Number.parseInt(spans[spans.length - 1].dataset.sentenceId, 10) : null;
      }

      function saveReaderProgress() {
        if (!progressKey) return;
        const sentenceId = topSentenceId();
        if (!sentenceId) return;
        window.localStorage.setItem(progressKey, JSON.stringify({
          chapter_idx: chapterIdx,
          top_sentence_id: sentenceId,
          analysis_state: currentAnalysisState(),
          ts: new Date().toISOString(),
        }));
      }

      function currentAnalysisState() {
        if (!panel || panel.hidden) return { open: false };
        const state = {
          open: true,
          mode: panelMode,
        };
        if (panelMode === "word" && activeAnalysisWordCardId) {
          state.card_id = activeAnalysisWordCardId;
          state.source_sentence_id = activeAnalysisSourceSentenceId || "";
        } else if (activeAnalysisSentenceId) {
          state.sentence_id = activeAnalysisSentenceId;
        }
        return state;
      }

      async function restoreSavedAnalysisPanel(saved) {
        const state = saved?.analysis_state || {};
        if (!state.open) return false;
        if (state.mode === "word" && state.card_id) {
          await loadSavedWordAnalysis(String(state.card_id));
        } else if (state.sentence_id) {
          const sentence = document.getElementById(`sentence-${state.sentence_id}`);
          if (!sentence) return false;
          activeSentenceId = sentence.dataset.sentenceId;
          activeSentenceTranslation = sentence.dataset.translation || "";
          if (sentence.dataset.analysisId) {
            await loadSavedAnalysis(sentence.dataset.sentenceId);
          } else {
            renderSentenceStudyPanel(sentence, "No saved AI analysis yet.");
          }
        } else {
          openPanelPlaceholder();
        }
        return true;
      }

      function scheduleProgressSave() {
        window.clearTimeout(progressTimer);
        progressTimer = window.setTimeout(saveReaderProgress, 300);
      }

      async function deleteWordCardsAndReload(cardIds) {
        const ids = cardIds.filter(Boolean);
        if (!ids.length) return;
        const anchor = captureReadingAnchor(wordDetailRemove);
        readerToolbarBusy = true;
        try {
          for (const cardId of ids) {
            const separator = `/mark/word/${cardId}`.includes("?") ? "&" : "?";
            const response = await fetch(
              `/mark/word/${cardId}${separator}return_to=${encodeURIComponent(returnTo)}`,
              { method: "DELETE" },
            );
            if (!response.ok) {
              window.location.assign(response.url || returnTo);
              return;
            }
          }
          ids.forEach((cardId) => {
            unregisterWordCard(cardId);
            reader.querySelectorAll(`[data-word-card="${cardId}"]`).forEach(clearWordCardElement);
          });
          window.getSelection()?.removeAllRanges();
          hideToolbar();
          restoreReadingAnchor(anchor);
        } finally {
          readerToolbarBusy = false;
        }
      }

      async function deleteAnalysisWordCardInPlace(cardId) {
        const id = String(cardId || "");
        if (!id) return;
        const scrollTop = panel.scrollTop;
        const response = await fetch(
          `/mark/word/${id}?return_to=${encodeURIComponent(returnTo)}`,
          { method: "DELETE" },
        );
        if (!response.ok) {
          window.location.assign(response.url || returnTo);
          return;
        }
        unregisterWordCard(id);
        document.querySelectorAll(`[data-word-card="${id}"], .glossary-word[data-card-id="${id}"]`).forEach((span) => {
          span.removeAttribute("data-word-card");
          span.removeAttribute("data-card-id");
          span.removeAttribute("data-meaning");
          span.removeAttribute("data-note");
          span.removeAttribute("data-lemma");
          span.classList.remove("glossary-word", "marked-word", "word-analysis-active");
        });
        hideToolbar();
        refreshAnalysisGlossaryHighlights();
        panel.scrollTop = scrollTop;
      }

      function markSentenceSpanUnmarked(sentenceId) {
        const sentence = document.getElementById(`sentence-${sentenceId}`);
        if (!sentence) return;
        sentence.classList.remove("marked", "analyzed", "analyzed-stale");
        sentence.dataset.marked = "0";
        sentence.dataset.analysisId = "";
        sentence.dataset.analysisStale = "0";
      }

      function markSentenceSpanMarked(sentenceId) {
        const sentence = document.getElementById(`sentence-${sentenceId}`);
        if (!sentence) return;
        sentence.classList.add("marked");
        sentence.dataset.marked = "1";
      }

      async function markSentenceInPlace(sentenceId) {
        if (!sentenceId) return;
        const anchor = captureReadingAnchor();
        const body = new URLSearchParams({ return_to: returnTo });
        readerToolbarBusy = true;
        try {
          const response = await fetch(`/mark/sentence/${sentenceId}`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          if (!response.ok) {
            window.location.assign(response.url || returnTo);
            return;
          }
          markSentenceSpanMarked(sentenceId);
          window.getSelection()?.removeAllRanges();
          hideToolbar();
          restoreReadingAnchor(anchor);
        } catch {
          window.location.assign(returnTo);
        } finally {
          readerToolbarBusy = false;
        }
      }

      async function deleteSentenceCardsInPlace(sentenceIds) {
        const ids = Array.from(new Set(sentenceIds.filter(Boolean)));
        if (!ids.length) return;
        const anchor = captureReadingAnchor();
        ids.forEach(markSentenceSpanUnmarked);
        readerToolbarBusy = true;
        try {
          const requests = ids.map((sentenceId) => {
            const url = `/mark/sentence/${sentenceId}?return_to=${encodeURIComponent(returnTo)}`;
            return fetch(url, { method: "DELETE" }).then((response) => ({
              sentenceId,
              response,
            }));
          });
          const results = await Promise.all(requests);
          const failed = results.find((result) => !result.response.ok);
          if (failed) {
            window.location.assign(failed.response.url || returnTo);
            return;
          }
          window.getSelection()?.removeAllRanges();
          hideToolbar();
          restoreReadingAnchor(anchor);
        } finally {
          readerToolbarBusy = false;
        }
      }

      function openTranslationEditor() {
        if (!activeSentenceId) return;
        const sentence = document.getElementById(`sentence-${activeSentenceId}`);
        if (structureEditorOpen && structureEditorDirty) {
          clearStructureAutoSaveTimer();
          enqueueStructureSave({ automatic: true, keepOpen: true });
        }
        hideStructureEditor();
        clearTranslationAutoSaveTimer();
        translationText.value = activeSentenceTranslation;
        lastSavedTranslation = activeSentenceTranslation.trim();
        translationEditorDirty = false;
        translationEditor.hidden = false;
        translationEditorOpen = true;
        translationStatus.textContent = "";
        setVisible(wordForm, false);
        setVisible(wordDetail, false);
        setVisible(crossSentence, false);
        requestAnimationFrame(() => {
          if (sentence) positionToolbar(sentence.getBoundingClientRect());
          translationText.focus();
        });
      }

      function openStructureEditor() {
        if (!activeSentenceId) return;
        const sentence = document.getElementById(`sentence-${activeSentenceId}`);
        if (translationEditorOpen && translationEditorDirty) {
          clearTranslationAutoSaveTimer();
          enqueueTranslationSave({ automatic: true, keepOpen: true });
        }
        hideTranslationEditor();
        clearStructureAutoSaveTimer();
        structureText.value = activeSentenceStructure || STRUCTURE_TEMPLATE;
        lastSavedStructure = activeSentenceStructure.trim();
        structureEditorDirty = false;
        structureEditor.hidden = false;
        structureEditorOpen = true;
        structureStatus.textContent = "";
        setVisible(wordForm, false);
        setVisible(wordDetail, false);
        setVisible(crossSentence, false);
        requestAnimationFrame(() => {
          if (sentence) positionToolbar(sentence.getBoundingClientRect());
          structureText.focus();
        });
      }

      async function saveTranslationOnly(options = {}) {
        clearTranslationAutoSaveTimer();
        const automatic = Boolean(options.automatic);
        const keepOpen = Boolean(options.keepOpen);
        const value = translationText.value.trim();
        if (!value) {
          if (!automatic) {
            translationStatus.textContent = "Enter a translation first, or use AI analysis without saving.";
          }
          return true;
        }
        if (value === lastSavedTranslation) {
          translationEditorDirty = false;
          if (!automatic) translationStatus.textContent = "Saved";
          return true;
        }
        if (!activeSentenceId) return;
        const anchor = captureReadingAnchor();
        translationStatus.textContent = "Saving...";
        const body = new URLSearchParams({ user_translation: value, return_to: returnTo });
        readerToolbarBusy = true;
        try {
          const response = await fetch(`/mark/sentence/${activeSentenceId}/translation`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          if (!response.ok) {
            if (automatic || keepOpen) throw new Error("Save failed");
            window.location.assign(response.url || returnTo);
            return false;
          }
          const sentence = document.getElementById(`sentence-${activeSentenceId}`);
          markSentenceTranslated(sentence, value);
          activeSentenceTranslation = value;
          lastSavedTranslation = value;
          translationEditorDirty = false;
          translationDelete.hidden = false;
          translationOpen.textContent = "Update translation";
          analysisOpen.textContent = "Check translation";
          translationStatus.textContent = automatic ? "Auto saved" : "Saved";
          if (!keepOpen) {
            window.getSelection()?.removeAllRanges();
            hideToolbar();
            restoreReadingAnchor(anchor);
          }
          return true;
        } catch (error) {
          if (automatic || keepOpen) {
            translationStatus.textContent = `Save failed: ${error}`;
            return false;
          }
          window.location.assign(returnTo);
          return false;
        } finally {
          readerToolbarBusy = false;
        }
      }

      function markSentenceStructured(sentence, structure) {
        if (!sentence) return;
        sentence.dataset.structure = structure;
        if (sentence.dataset.analysisId) {
          sentence.dataset.analysisStale = "1";
          sentence.classList.remove("analyzed");
          sentence.classList.add("analyzed-stale");
        }
      }

      async function saveStructureOnly(options = {}) {
        clearStructureAutoSaveTimer();
        const automatic = Boolean(options.automatic);
        const keepOpen = Boolean(options.keepOpen);
        const value = structureText.value.trim();
        if (!structureAttemptHasContent(value)) {
          if (!automatic) structureStatus.textContent = "Fill in your structure judgement first.";
          return true;
        }
        if (value === lastSavedStructure) {
          structureEditorDirty = false;
          if (!automatic) structureStatus.textContent = "Saved";
          return true;
        }
        if (!activeSentenceId) return;
        const anchor = captureReadingAnchor();
        structureStatus.textContent = "Saving...";
        const body = new URLSearchParams({ user_structure: value, return_to: returnTo });
        readerToolbarBusy = true;
        try {
          const response = await fetch(`/mark/sentence/${activeSentenceId}/structure`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          if (!response.ok) {
            if (automatic || keepOpen) throw new Error("Save failed");
            window.location.assign(response.url || returnTo);
            return false;
          }
          const sentence = document.getElementById(`sentence-${activeSentenceId}`);
          markSentenceStructured(sentence, value);
          activeSentenceStructure = value;
          lastSavedStructure = value;
          structureEditorDirty = false;
          structureOpen.textContent = "Update structure";
          structureStatus.textContent = automatic ? "Auto saved" : "Saved";
          if (!keepOpen) {
            window.getSelection()?.removeAllRanges();
            hideToolbar();
            restoreReadingAnchor(anchor);
          }
          return true;
        } catch (error) {
          if (automatic || keepOpen) {
            structureStatus.textContent = `Save failed: ${error}`;
            return false;
          }
          window.location.assign(returnTo);
          return false;
        } finally {
          readerToolbarBusy = false;
        }
      }

      async function deleteTranslationInPlace() {
        if (!activeSentenceId) return;
        const sentenceId = activeSentenceId;
        const anchor = captureReadingAnchor(translationDelete);
        readerToolbarBusy = true;
        try {
          const url = `/mark/sentence/${sentenceId}/translation?return_to=${encodeURIComponent(returnTo)}`;
          const response = await fetch(url, { method: "DELETE" });
          if (!response.ok) {
            window.location.assign(response.url || returnTo);
            return;
          }
          const sentence = document.getElementById(`sentence-${sentenceId}`);
          clearSentenceTranslation(sentence);
          activeSentenceTranslation = "";
          window.getSelection()?.removeAllRanges();
          hideToolbar();
          restoreReadingAnchor(anchor);
        } catch {
          window.location.assign(returnTo);
        } finally {
          readerToolbarBusy = false;
        }
      }

      function setSentenceMode() {
        panelMode = "sentence";
        if (panelKicker) panelKicker.textContent = "Sentence analysis";
        if (panelTitle) panelTitle.textContent = "AI Analysis";
        if (wordPronunciation) {
          wordPronunciation.hidden = true;
          wordPronunciation.dataset.speakText = "";
        }
        if (sentenceSections) sentenceSections.hidden = false;
        if (wordSections) wordSections.hidden = true;
        if (panelUnmark) panelUnmark.hidden = false;
      }

      function setWordMode() {
        panelMode = "word";
        if (panelKicker) panelKicker.textContent = "Word analysis";
        if (panelTitle) panelTitle.textContent = "Word Analysis";
        if (sentenceSections) sentenceSections.hidden = true;
        if (wordSections) wordSections.hidden = false;
        if (panelUnmark) panelUnmark.hidden = true;
      }

      function updatePreviousAnalysisButton() {
        if (!panelPrevious) return;
        const previous = analysisHistory[analysisHistory.length - 1];
        panelPrevious.hidden = !previous;
        panelPrevious.textContent = previous?.label
          ? `Back to ${previous.label} analysis`
          : "Back to previous analysis";
      }

      function clearAnalysisHistory() {
        analysisHistory = [];
        updatePreviousAnalysisButton();
      }

      function currentAnalysisSnapshot() {
        if (!activeAnalysisPayload) return null;
        return {
          mode: panelMode,
          payload: activeAnalysisPayload,
          label: activeAnalysisLabel || (panelMode === "word" ? "previous word" : "sentence"),
          scrollTop: panel.scrollTop,
        };
      }

      function pushCurrentAnalysis() {
        const snapshot = currentAnalysisSnapshot();
        if (!snapshot) return;
        analysisHistory.push(snapshot);
        updatePreviousAnalysisButton();
      }

      function restorePreviousAnalysis() {
        const previous = analysisHistory.pop();
        if (!previous) return;
        if (previous.mode === "word") {
          renderWordAnalysis(previous.payload);
        } else {
          renderAnalysisPayload(previous.payload);
        }
        updatePreviousAnalysisButton();
        window.setTimeout(() => {
          panel.scrollTop = previous.scrollTop || 0;
          updateAnalysisToolsVisibility(false);
        }, 0);
      }

      function updateAnalysisToolsVisibility(peek) {
        if (!panel || panel.hidden) return;
        const shouldCollapse = panel.scrollTop > ANALYSIS_TOOLS_COLLAPSE_SCROLL_TOP;
        panel.classList.toggle("analysis-tools-collapsed", shouldCollapse);
        panel.classList.toggle("analysis-tools-peeking", shouldCollapse && Boolean(peek));
      }

      function pointerIsInAnalysisToolsHotZone(event) {
        if (!panel) return false;
        const rect = panel.getBoundingClientRect();
        return event.clientX >= rect.right - ANALYSIS_TOOLS_HOT_ZONE_PX
          && event.clientX <= rect.right
          && event.clientY >= rect.top
          && event.clientY <= rect.bottom;
      }

      function handleAnalysisPanelPointerMove(event) {
        const target = event.target?.closest ? event.target : null;
        const inHeader = Boolean(target?.closest(".analysis-panel-header"));
        updateAnalysisToolsVisibility(inHeader || pointerIsInAnalysisToolsHotZone(event));
      }

      function syncAnalysisToolsFocusState() {
        updateAnalysisToolsVisibility(Boolean(panelHeader?.contains(document.activeElement)));
      }

      function scrollAnalysisPanelToTop() {
        if (!panel) return;
        panel.scrollTop = 0;
        updateAnalysisToolsVisibility(false);
      }

      function openPanel() {
        panel.hidden = false;
        scrollAnalysisPanelToTop();
        if (panelTab) panelTab.hidden = true;
        document.body.classList.add("analysis-open");
        updatePreviousAnalysisButton();
        saveReaderProgress();
      }

      function closePanel() {
        panel.hidden = true;
        if (panelTranslationDirty) enqueuePanelTranslationSave({ automatic: true });
        if (panelStructureDirty) enqueuePanelStructureSave({ automatic: true });
        clearPanelAutoSaveTimers();
        panelTranslationDirty = false;
        panelStructureDirty = false;
        if (panelTab) panelTab.hidden = false;
        document.body.classList.remove("analysis-open");
        if (panelUnmark) panelUnmark.hidden = true;
        activeAnalysisSourceSentenceId = null;
        activeAnalysisPayload = null;
        activeAnalysisLabel = "";
        clearAnalysisHistory();
        clearEvidenceHighlight();
        reader.querySelectorAll("[data-word-card].word-analysis-active").forEach((el) => {
          el.classList.remove("word-analysis-active");
        });
        saveReaderProgress();
      }

      function openPanelPlaceholder() {
        setSentenceMode();
        activeAnalysisSentenceId = null;
        activeAnalysisSourceSentenceId = null;
        activeAnalysisPayload = null;
        activeAnalysisLabel = "";
        clearAnalysisHistory();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = "Select a sentence or marked word, then choose AI analysis.";
        panelMeta.textContent = "";
        panelRetry.hidden = true;
        if (panelRetryPro) panelRetryPro.hidden = true;
        simplified.textContent = "";
        gloss.textContent = "";
        skeleton.textContent = "";
        clearSentenceStructure();
        diagnosis.replaceChildren();
        if (sentencePanelTranslation) sentencePanelTranslation.value = "";
        if (sentencePanelStructure) sentencePanelStructure.value = "";
        if (sentencePanelNote) sentencePanelNote.value = "";
        if (sentencePanelNoteSuggestion) sentencePanelNoteSuggestion.textContent = "";
        if (sentencePanelNoteAccept) sentencePanelNoteAccept.hidden = true;
        if (sentencePanelTranslationStatus) sentencePanelTranslationStatus.textContent = "";
        if (sentencePanelStructureStatus) sentencePanelStructureStatus.textContent = "";
        if (sentencePanelNoteStatus) sentencePanelNoteStatus.textContent = "";
        renderStructureFeedback(null);
      }

      function setPanelLoading(message) {
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = message;
        panelMeta.textContent = "";
        panelRetry.hidden = true;
        if (panelRetryPro) panelRetryPro.hidden = true;
        simplified.textContent = "";
        gloss.textContent = "";
        skeleton.textContent = "";
        clearSentenceStructure();
        diagnosis.replaceChildren();
        if (sentencePanelTranslation) sentencePanelTranslation.value = "";
        if (sentencePanelStructure) sentencePanelStructure.value = "";
        if (sentencePanelNote) sentencePanelNote.value = "";
        if (sentencePanelNoteSuggestion) sentencePanelNoteSuggestion.textContent = "";
        if (sentencePanelNoteAccept) sentencePanelNoteAccept.hidden = true;
        if (sentencePanelTranslationStatus) sentencePanelTranslationStatus.textContent = "";
        if (sentencePanelStructureStatus) sentencePanelStructureStatus.textContent = "";
        if (sentencePanelNoteStatus) sentencePanelNoteStatus.textContent = "";
        renderStructureFeedback(null);
      }

      function setPanelLoadingWord(message) {
        setWordMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = message;
        panelMeta.textContent = "";
        panelRetry.hidden = true;
        if (panelRetryPro) panelRetryPro.hidden = true;
        if (wordAnalysisMeaning) wordAnalysisMeaning.textContent = "";
        if (wordAnalysisMeaningZh) wordAnalysisMeaningZh.textContent = "";
        if (wordRole) wordRole.textContent = "";
        if (wordRegister) wordRegister.textContent = "";
        if (wordWhy) wordWhy.textContent = "";
        if (wordVsSimpler) wordVsSimpler.replaceChildren();
        if (wordNoteCheckSection) wordNoteCheckSection.hidden = true;
        if (wordNoteCheck) wordNoteCheck.textContent = "";
        if (wordAnalysisMorphology) wordAnalysisMorphology.textContent = "";
        if (wordAnalysisErrors) wordAnalysisErrors.textContent = "";
        if (wordPanelMeaning) wordPanelMeaning.value = "";
        if (wordPanelNote) wordPanelNote.value = "";
        if (wordPanelSaveStatus) wordPanelSaveStatus.textContent = "";
        if (wordPronunciation) {
          wordPronunciation.hidden = true;
          wordPronunciation.dataset.speakText = "";
        }
      }

      function renderAnalysisError(message, retryable) {
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status error";
        panelStatus.textContent = message;
        panelRetry.hidden = !retryable || !activeAnalysisSentenceId;
        if (panelRetryPro) panelRetryPro.hidden = !retryable || !activeAnalysisSentenceId;
      }

      function renderWordAnalysisError(message, retryable) {
        setWordMode();
        openPanel();
        panelStatus.className = "analysis-status error";
        panelStatus.textContent = message;
        panelRetry.hidden = !retryable;
        if (panelRetryPro) panelRetryPro.hidden = !retryable;
      }

      function setSentenceStudyFields(payload) {
        clearPanelAutoSaveTimers();
        if (sentencePanelTranslation) {
          sentencePanelTranslation.value = payload.user_translation || "";
          lastSavedPanelTranslation = (payload.user_translation || "").trim();
          panelTranslationDirty = false;
        }
        if (sentencePanelStructure) {
          sentencePanelStructure.value = payload.user_structure || STRUCTURE_TEMPLATE;
          lastSavedPanelStructure = (payload.user_structure || "").trim();
          panelStructureDirty = false;
        }
        if (sentencePanelNote) {
          sentencePanelNote.value = payload.user_note || "";
        }
        if (sentencePanelNoteSuggestion) {
          sentencePanelNoteSuggestion.textContent = payload.analysis?.takeaway_suggestion || "";
        }
        if (sentencePanelNoteAccept) {
          sentencePanelNoteAccept.hidden = !(payload.analysis?.takeaway_suggestion || "").trim();
        }
        if (sentencePanelTranslationStatus) sentencePanelTranslationStatus.textContent = "";
        if (sentencePanelStructureStatus) sentencePanelStructureStatus.textContent = "";
        if (sentencePanelNoteStatus) sentencePanelNoteStatus.textContent = "";
      }

      function clearSentenceStructure() {
        if (blockingPoint) blockingPoint.textContent = "";
        if (clauses) clauses.replaceChildren();
        if (modifiers) modifiers.replaceChildren();
        if (logicMarkers) logicMarkers.replaceChildren();
        if (anaphora) anaphora.replaceChildren();
        if (modifiersSection) modifiersSection.hidden = true;
        if (logicMarkersSection) logicMarkersSection.hidden = true;
        if (anaphoraSection) anaphoraSection.hidden = true;
        if (backToWhole) backToWhole.textContent = "";
      }

      function appendAnalysisList(container, items, formatter) {
        if (!container) return;
        container.replaceChildren();
        if (!items.length) {
          const empty = document.createElement("p");
          empty.className = "analysis-text muted";
          empty.textContent = "—";
          container.append(empty);
          return;
        }
        for (const item of items) {
          const p = document.createElement("p");
          p.className = "analysis-text";
          p.textContent = formatter(item);
          container.append(p);
          applyGlossaryHighlights(p);
        }
      }

      function toggleAnalysisSection(section, items) {
        if (!section) return;
        section.hidden = !items.length;
      }

      function renderSentenceStructure(analysis) {
        if (clauses) {
          appendAnalysisList(clauses, analysis.clauses || [], (item) => {
            const type = item.type ? `${item.type}: ` : "";
            const role = item.role ? ` — ${item.role}` : "";
            return `${type}${item.text || ""}${role}`;
          });
        }
        toggleAnalysisSection(modifiersSection, analysis.modifiers || []);
        if (modifiers) {
          appendAnalysisList(modifiers, analysis.modifiers || [], (item) => {
            const target = item.target || "";
            const modifier = item.modifier || "";
            const type = item.type ? ` (${item.type})` : "";
            return `${modifier} → ${target}${type}`;
          });
        }
        toggleAnalysisSection(logicMarkersSection, analysis.logic_markers || []);
        if (logicMarkers) {
          appendAnalysisList(logicMarkers, analysis.logic_markers || [], (item) => {
            return `${item.marker || ""} → ${item.function || ""}`;
          });
        }
        toggleAnalysisSection(anaphoraSection, analysis.anaphora || []);
        if (anaphora) {
          appendAnalysisList(anaphora, analysis.anaphora || [], (item) => {
            return `${item.pronoun || ""} → ${item.refers_to || ""}`;
          });
        }
      }

      function renderStructureFeedback(feedback) {
        if (!structureFeedbackSection || !structureFeedback) return;
        structureFeedback.replaceChildren();
        if (!feedback) {
          structureFeedbackSection.hidden = true;
          return;
        }
        structureFeedbackSection.hidden = false;
        const status = document.createElement("p");
        status.className = "analysis-text";
        status.textContent = feedback.is_correct
          ? "Your structure attempt is correct."
          : "Your structure attempt needs correction.";
        structureFeedback.append(status);

        const items = feedback.missed_or_wrong || [];
        for (const item of items) {
          const block = document.createElement("article");
          block.className = "similar-mistake-comparison";
          const code = item.error_code || "";
          const codeLine = document.createElement("p");
          codeLine.className = "analysis-codes";
          codeLine.textContent = ERROR_CODE_LABELS[code] || code;
          const claim = comparisonLine("Your claim", item.learner_claim || "");
          const correction = comparisonLine("Correction", item.correction || "");
          const reason = comparisonLine("Why", item.reason || "");
          block.append(codeLine, claim, correction, reason);
          structureFeedback.append(block);
        }

        structureFeedback.append(
          comparisonLine("Corrected structure", feedback.corrected_structure || ""),
          comparisonLine(
            "Translation impact",
            feedback.why_it_matters_for_translation || "",
          ),
          comparisonLine("Next check", feedback.next_check || ""),
        );
        applyGlossaryHighlights(structureFeedback);
      }

      function renderSentenceStudyPanel(sentence, message, seqAtRequest = toolbarInteractionSeq) {
        maybeHideToolbarAfterRender(seqAtRequest);
        const sentenceId = sentence?.dataset.sentenceId || "";
        activeAnalysisPayload = {
          sentence_id: sentenceId,
          user_translation: sentence?.dataset.translation || "",
          user_structure: sentence?.dataset.structure || "",
          user_note: sentence?.dataset.note || "",
        };
        activeAnalysisLabel = "sentence";
        activeAnalysisSentenceId = sentenceId;
        activeAnalysisSourceSentenceId = sentenceId;
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = message || "";
        panelMeta.textContent = "";
        panelRetry.hidden = !sentenceId;
        if (panelRetryPro) panelRetryPro.hidden = !sentenceId;
        simplified.textContent = "";
        gloss.textContent = "";
        skeleton.textContent = "";
        clearSentenceStructure();
        diagnosis.replaceChildren();
        renderStructureFeedback(null);
        setSentenceStudyFields(activeAnalysisPayload);
      }

      function renderAnalysisPayload(payload, seqAtRequest = toolbarInteractionSeq) {
        const analysis = payload.analysis || {};
        maybeHideToolbarAfterRender(seqAtRequest);
        activeAnalysisPayload = payload;
        activeAnalysisLabel = "sentence";
        activeAnalysisSentenceId = String(payload.sentence_id || activeAnalysisSentenceId || "");
        activeAnalysisSourceSentenceId = activeAnalysisSentenceId;
        setSentenceMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = payload.is_stale ? "Analysis is stale. Reanalyze when ready." : "";
        panelRetry.hidden = false;
        if (panelRetryPro) panelRetryPro.hidden = false;
        setSentenceStudyFields(payload);
        panelMeta.textContent = [
          `prompt ${payload.prompt_version || "unknown"}`,
          payload.model || "model unknown",
          payload.is_stale ? "stale" : "current",
          payload.from_cache ? "cache" : "fresh",
        ].join(" · ");
        simplified.textContent = analysis.simplified_en || "";
        gloss.textContent = analysis.chinese_gloss || "";
        if (blockingPoint) blockingPoint.textContent = analysis.blocking_point || "";
        skeleton.textContent = analysis.subject_skeleton || "";
        if (backToWhole) backToWhole.textContent = analysis.simplified_en || "";
        applyGlossaryHighlights(simplified);
        applyGlossaryHighlights(gloss);
        if (blockingPoint) applyGlossaryHighlights(blockingPoint);
        applyGlossaryHighlights(skeleton);
        if (backToWhole) applyGlossaryHighlights(backToWhole);
        renderSentenceStructure(analysis);
        renderDiagnosis(analysis);
        renderStructureFeedback(analysis.structure_feedback || null);
        renderSimilarMistakes(payload, analysis);
      }

      function renderDiagnosis(analysis) {
        diagnosis.replaceChildren();
        const basis = document.createElement("p");
        basis.className = "analysis-text muted";
        basis.textContent = analysis.diagnosis_basis === "user_translation"
          ? "Based on your translation"
          : "Predicted without a translation";
        diagnosis.append(basis);

        const codes = analysis.diagnosis_basis === "user_translation"
          ? (analysis.diagnosed_error_types || [])
          : (analysis.predicted_error_types || []);
        if (codes.length) {
          const codeLine = document.createElement("p");
          codeLine.className = "analysis-codes";
          codeLine.textContent = codes.map((c) => ERROR_CODE_LABELS[c] || c).join("  ·  ");
          diagnosis.append(codeLine);
        }

        const evidence = analysis.diagnosis_evidence || [];
        if (!evidence.length) {
          const empty = document.createElement("p");
          empty.className = "analysis-text";
          empty.textContent = codes.length ? "No detailed evidence saved." : "No specific issue found.";
          diagnosis.append(empty);
          return;
        }

        for (const item of evidence) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "evidence-item";
          const code = item.error_type || "OK";
          const text = item.evidence || "";
          const codeLabel = ERROR_CODE_LABELS[code] || code;
          button.textContent = `${codeLabel}: ${text}`;
          button.addEventListener("mouseenter", () => highlightEvidence(text));
          button.addEventListener("mouseleave", clearEvidenceHighlight);
          button.addEventListener("click", () => highlightEvidence(text));
          diagnosis.append(button);
        }
      }

      function renderSimilarMistakes(payload, analysis) {
        const mistakes = payload.similar_mistakes || [];
        if (!mistakes.length) return;
        const section = document.createElement("div");
        section.className = "similar-mistakes";
        const title = document.createElement("h4");
        title.textContent = "Similar past mistake";
        section.append(title);
        const intro = document.createElement("p");
        intro.className = "analysis-text muted";
        intro.textContent = "Same diagnosed error code in an active translated Review sentence.";
        section.append(intro);

        for (const mistake of mistakes) {
          const item = document.createElement("article");
          item.className = "similar-mistake";
          const codes = mistake.shared_error_codes || [];
          const codeLine = document.createElement("p");
          codeLine.className = "analysis-codes";
          codeLine.textContent = codes.map((code) => ERROR_CODE_LABELS[code] || code).join("  ·  ");
          item.append(codeLine);

          const source = document.createElement("p");
          source.className = "similar-mistake-source";
          source.textContent = mistake.sentence_text || "";
          item.append(source);

          if (mistake.user_translation) {
            const translation = document.createElement("p");
            translation.className = "analysis-translation";
            translation.textContent = `Your past translation: ${mistake.user_translation}`;
            item.append(translation);
          }

          for (const code of codes) {
            const comparison = document.createElement("div");
            comparison.className = "similar-mistake-comparison";
            comparison.append(
              comparisonLine("Current", evidenceTextForCode(analysis.diagnosis_evidence, code)),
              comparisonLine("Past", evidenceTextForCode(mistake.diagnosis_evidence, code)),
            );
            const tip = ERROR_CHECK_TIPS[code];
            if (tip) comparison.append(comparisonLine("Next check", tip));
            item.append(comparison);
          }

          section.append(item);
        }
        diagnosis.append(section);
      }

      function evidenceTextForCode(evidence, code) {
        const found = (evidence || []).find((item) => item.error_type === code);
        return found?.evidence || "No detailed evidence saved.";
      }

      function comparisonLine(label, text) {
        const line = document.createElement("p");
        line.className = "similar-mistake-line";
        const strong = document.createElement("strong");
        strong.textContent = `${label}: `;
        line.append(strong, document.createTextNode(text || ""));
        return line;
      }

      function updateSentenceAnalysisState(sentenceId, payload) {
        const sentence = document.getElementById(`sentence-${sentenceId}`);
        if (!sentence) return;
        sentence.dataset.marked = "1";
        sentence.dataset.analysisId = payload.cache_id || "";
        sentence.dataset.analysisStale = payload.is_stale ? "1" : "0";
        sentence.dataset.translation = payload.user_translation || sentence.dataset.translation || "";
        sentence.dataset.structure = payload.user_structure || sentence.dataset.structure || "";
        sentence.dataset.note = payload.user_note || sentence.dataset.note || "";
        sentence.classList.add("marked");
        if (sentence.dataset.translation.trim()) {
          sentence.classList.add("translated");
          sentence.title = "Translation saved";
        }
        sentence.classList.remove("analyzed", "analyzed-stale");
        sentence.classList.add(payload.is_stale ? "analyzed-stale" : "analyzed");
      }

      async function loadSavedAnalysis(sentenceId) {
        activeAnalysisSentenceId = sentenceId;
        clearAnalysisHistory();
        const seqAtRequest = toolbarInteractionSeq;
        setPanelLoading("Loading analysis...");
        try {
          const response = await fetch(`/analysis/sentence/${sentenceId}`);
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderAnalysisError(payload.error || "No saved analysis found.", Boolean(payload.retry));
            return;
          }
          renderAnalysisPayload(payload, seqAtRequest);
        } catch (error) {
          renderAnalysisError(`Could not load analysis: ${error}`, true);
        }
      }

      async function requestAnalysis(sentenceId, translation, options = {}) {
        activeAnalysisSentenceId = sentenceId;
        clearAnalysisHistory();
        const seqAtRequest = toolbarInteractionSeq;
        setPanelLoading(options.preferPro ? "Analyzing sentence with Pro..." : "Analyzing sentence...");
        const params = new URLSearchParams();
        params.set("return_to", returnTo);
        if (translation && translation.trim()) params.set("user_translation", translation.trim());
        const structure = Object.prototype.hasOwnProperty.call(options, "userStructure")
          ? options.userStructure
          : (sentencePanelStructure?.value || document.getElementById(`sentence-${sentenceId}`)?.dataset.structure || "");
        if (structureAttemptHasContent(structure)) params.set("user_structure", structure.trim());
        if (options.preferPro) params.set("prefer_pro", "1");
        if (options.forceRefresh) params.set("force_refresh", "1");
        try {
          const response = await fetch(`/analysis/sentence/${sentenceId}`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: params.toString(),
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderAnalysisError(payload.error || "Analysis failed.", Boolean(payload.retry));
            return;
          }
          updateSentenceAnalysisState(sentenceId, payload);
          renderAnalysisPayload(payload, seqAtRequest);
        } catch (error) {
          renderAnalysisError(`Analysis failed: ${error}`, true);
        }
      }

      function clearPanelAutoSaveTimers() {
        if (panelTranslationAutoSaveTimer !== null) {
          window.clearTimeout(panelTranslationAutoSaveTimer);
          panelTranslationAutoSaveTimer = null;
        }
        if (panelStructureAutoSaveTimer !== null) {
          window.clearTimeout(panelStructureAutoSaveTimer);
          panelStructureAutoSaveTimer = null;
        }
      }

      function enqueuePanelTranslationSave(options = {}) {
        panelTranslationSaveChain = panelTranslationSaveChain
          .catch(() => {})
          .then(() => savePanelTranslation(options));
        return panelTranslationSaveChain;
      }

      function enqueuePanelStructureSave(options = {}) {
        panelStructureSaveChain = panelStructureSaveChain
          .catch(() => {})
          .then(() => savePanelStructure(options));
        return panelStructureSaveChain;
      }

      function schedulePanelTranslationAutoSave(delay = AUTOSAVE_DELAY_MS) {
        if (panelTranslationAutoSaveTimer !== null) {
          window.clearTimeout(panelTranslationAutoSaveTimer);
          panelTranslationAutoSaveTimer = null;
        }
        if (!activeAnalysisSentenceId || !sentencePanelTranslation) return;
        const value = (sentencePanelTranslation.value || "").trim();
        if (!value || value === lastSavedPanelTranslation) return;
        if (sentencePanelTranslationStatus) sentencePanelTranslationStatus.textContent = "Auto saving...";
        panelTranslationAutoSaveTimer = window.setTimeout(() => {
          panelTranslationAutoSaveTimer = null;
          enqueuePanelTranslationSave({ automatic: true });
        }, delay);
      }

      function schedulePanelStructureAutoSave(delay = AUTOSAVE_DELAY_MS) {
        if (panelStructureAutoSaveTimer !== null) {
          window.clearTimeout(panelStructureAutoSaveTimer);
          panelStructureAutoSaveTimer = null;
        }
        if (!activeAnalysisSentenceId || !sentencePanelStructure) return;
        const value = (sentencePanelStructure.value || "").trim();
        if (!structureAttemptHasContent(value) || value === lastSavedPanelStructure) return;
        if (sentencePanelStructureStatus) sentencePanelStructureStatus.textContent = "Auto saving...";
        panelStructureAutoSaveTimer = window.setTimeout(() => {
          panelStructureAutoSaveTimer = null;
          enqueuePanelStructureSave({ automatic: true });
        }, delay);
      }

      async function savePanelTranslation(options = {}) {
        const automatic = Boolean(options.automatic);
        const sentenceId = activeAnalysisSentenceId;
        const value = (sentencePanelTranslation?.value || "").trim();
        if (!sentenceId) return true;
        if (!value) {
          if (!automatic && sentencePanelTranslationStatus) {
            sentencePanelTranslationStatus.textContent = "Enter a translation first.";
          }
          return true;
        }
        if (value === lastSavedPanelTranslation) {
          panelTranslationDirty = false;
          if (!automatic && sentencePanelTranslationStatus) {
            sentencePanelTranslationStatus.textContent = "Saved";
          }
          return true;
        }
        if (sentencePanelTranslationStatus) sentencePanelTranslationStatus.textContent = "Saving...";
        const body = new URLSearchParams({ user_translation: value, return_to: returnTo });
        try {
          const response = await fetch(`/mark/sentence/${sentenceId}/translation`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          if (!response.ok) throw new Error("Save failed");
          markSentenceTranslated(document.getElementById(`sentence-${sentenceId}`), value);
          activeSentenceTranslation = value;
          lastSavedPanelTranslation = value;
          panelTranslationDirty = false;
          if (activeAnalysisPayload) {
            activeAnalysisPayload.user_translation = value;
            activeAnalysisPayload.is_stale = true;
          }
          if (panelStatus) panelStatus.textContent = "Analysis is stale. Reanalyze when ready.";
          if (sentencePanelTranslationStatus) {
            sentencePanelTranslationStatus.textContent = automatic ? "Auto saved" : "Saved";
          }
          return true;
        } catch (error) {
          if (sentencePanelTranslationStatus) sentencePanelTranslationStatus.textContent = `Save failed: ${error}`;
          return false;
        }
      }

      async function savePanelStructure(options = {}) {
        const automatic = Boolean(options.automatic);
        const sentenceId = activeAnalysisSentenceId;
        const value = (sentencePanelStructure?.value || "").trim();
        if (!sentenceId) return true;
        if (!structureAttemptHasContent(value)) {
          if (!automatic && sentencePanelStructureStatus) {
            sentencePanelStructureStatus.textContent = "Fill in your structure judgement first.";
          }
          return true;
        }
        if (value === lastSavedPanelStructure) {
          panelStructureDirty = false;
          if (!automatic && sentencePanelStructureStatus) {
            sentencePanelStructureStatus.textContent = "Saved";
          }
          return true;
        }
        if (sentencePanelStructureStatus) sentencePanelStructureStatus.textContent = "Saving...";
        const body = new URLSearchParams({ user_structure: value, return_to: returnTo });
        try {
          const response = await fetch(`/mark/sentence/${sentenceId}/structure`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          if (!response.ok) throw new Error("Save failed");
          markSentenceStructured(document.getElementById(`sentence-${sentenceId}`), value);
          activeSentenceStructure = value;
          lastSavedPanelStructure = value;
          panelStructureDirty = false;
          if (activeAnalysisPayload) {
            activeAnalysisPayload.user_structure = value;
            activeAnalysisPayload.is_stale = true;
          }
          if (panelStatus) panelStatus.textContent = "Analysis is stale. Reanalyze when ready.";
          if (sentencePanelStructureStatus) {
            sentencePanelStructureStatus.textContent = automatic ? "Auto saved" : "Saved";
          }
          return true;
        } catch (error) {
          if (sentencePanelStructureStatus) sentencePanelStructureStatus.textContent = `Save failed: ${error}`;
          return false;
        }
      }

      async function savePanelNote() {
        const sentenceId = activeAnalysisSentenceId;
        const value = (sentencePanelNote?.value || "").trim();
        if (!sentenceId) return;
        if (sentencePanelNoteStatus) sentencePanelNoteStatus.textContent = "Saving...";
        const body = new URLSearchParams({ user_note: value });
        try {
          const response = await fetch(`/mark/sentence/${sentenceId}`, {
            method: "PATCH",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          if (!response.ok) throw new Error("Save failed");
          updateSentenceNote(sentenceId, value);
          if (sentencePanelNoteStatus) sentencePanelNoteStatus.textContent = "Saved";
        } catch (error) {
          if (sentencePanelNoteStatus) sentencePanelNoteStatus.textContent = `Save failed: ${error}`;
        }
      }

      function renderVsSimpler(container, items) {
        container.replaceChildren();
        if (!items.length) { container.textContent = "—"; return; }
        for (const item of items) {
          const p = document.createElement("p");
          p.className = "vs-simpler-item analysis-text";
          const strong = document.createElement("strong");
          strong.textContent = item.simpler || "";
          p.append(strong);
          p.append(document.createTextNode(": " + (item.difference || "")));
          container.append(p);
        }
        applyGlossaryHighlights(container);
      }

      function renderWordAnalysis(payload, seqAtRequest = toolbarInteractionSeq) {
        const a = payload.analysis || {};
        maybeHideToolbarAfterRender(seqAtRequest);
        activeAnalysisPayload = payload;
        activeAnalysisLabel = (payload.surface_form || payload.lemma || "word").trim();
        activeAnalysisWordCardId = String(payload.card_id || "");
        activeAnalysisSourceSentenceId = String(payload.sentence_id || "");
        setWordMode();
        openPanel();
        panelStatus.className = "analysis-status";
        panelStatus.textContent = payload.warning
          || (payload.is_stale ? "Analysis is stale. Reanalyze when ready." : "");
        panelRetry.hidden = false;
        if (panelRetryPro) panelRetryPro.hidden = false;
        panelMeta.textContent = [
          `prompt ${payload.prompt_version || "unknown"}`,
          payload.model || "model unknown",
          payload.from_cache ? "cache" : "fresh",
        ].join(" · ");
        reader.querySelectorAll("[data-word-card].word-analysis-active").forEach((el) => {
          el.classList.remove("word-analysis-active");
        });
        if (payload.card_id) {
          const wordSpan = reader.querySelector(`[data-word-card="${payload.card_id}"]`);
          if (wordSpan) wordSpan.classList.add("word-analysis-active");
        }
        const speakText = (payload.surface_form || payload.lemma || "").trim();
        if (wordPronunciation) {
          wordPronunciation.dataset.speakText = speakText;
          wordPronunciation.hidden = !speakText;
        }
        if (wordRole) {
          wordRole.textContent = a.role_in_sentence || "—";
          applyGlossaryHighlights(wordRole);
        }
        if (wordAnalysisMeaning) {
          wordAnalysisMeaning.textContent = a.meaning_in_context || "—";
          applyGlossaryHighlights(wordAnalysisMeaning);
        }
        if (wordAnalysisMeaningZh) {
          const chineseMeaning = a.chinese_meaning || a.chinese_gloss || "";
          wordAnalysisMeaningZh.textContent = chineseMeaning ? `中文：${chineseMeaning}` : "中文：—";
        }
        if (wordRegister) {
          wordRegister.textContent = a.register || "—";
          applyGlossaryHighlights(wordRegister);
        }
        if (wordWhy) {
          wordWhy.textContent = a.why_this_word || "—";
          applyGlossaryHighlights(wordWhy);
        }
        if (wordVsSimpler) renderVsSimpler(wordVsSimpler, a.vs_simpler || []);
        if (wordNoteCheckSection && wordNoteCheck) {
          const check = a.learner_note_check || {};
          const status = (check.status || "").trim();
          const statusLabels = {
            correct: "Correct.",
            partly_correct: "Partly correct.",
            incorrect: "Incorrect.",
            not_enough_information: "Not enough information.",
          };
          const shouldShow = status && status !== "not_provided";
          wordNoteCheckSection.hidden = !shouldShow;
          if (shouldShow) {
            const parts = [
              statusLabels[status] || "",
              check.feedback || "",
              check.corrected_understanding || "",
            ].filter(Boolean);
            wordNoteCheck.textContent = parts.join(" ");
            applyGlossaryHighlights(wordNoteCheck);
          } else {
            wordNoteCheck.textContent = "";
          }
        }
        const root = a.morphology?.root || "";
        const family = (a.morphology?.family || []).join(", ");
        if (wordAnalysisMorphology) {
          wordAnalysisMorphology.textContent = root
            ? (family ? `${root} → ${family}` : root)
            : (family || "—");
          applyGlossaryHighlights(wordAnalysisMorphology);
        }
        if (wordAnalysisErrors) {
          const codes = a.predicted_error_types || [];
          wordAnalysisErrors.textContent = codes.length
            ? codes.map((c) => ERROR_CODE_LABELS[c] || c).join("  ·  ")
            : "—";
        }
        const cardId = String(payload.card_id || "");
        const noteSpan = cardId
          ? document.querySelector(`[data-word-card="${cardId}"], .glossary-word[data-card-id="${cardId}"]`)
          : null;
        const panelMeaning = noteSpan?.dataset.meaning || "";
        if (wordPanelMeaning) wordPanelMeaning.value = panelMeaning;
        if (wordPanelNote) wordPanelNote.value = distinctUserNote(noteSpan?.dataset.note, panelMeaning);
        if (wordPanelSaveStatus) wordPanelSaveStatus.textContent = "";
        saveAnalysisMeaningIfEmpty(cardId, a.meaning_in_context || "");
      }

      async function saveAnalysisMeaningIfEmpty(cardId, meaning) {
        const cleanMeaning = (meaning || "").trim();
        if (!cardId || !cleanMeaning) return;
        const spans = Array.from(document.querySelectorAll(`[data-word-card="${cardId}"], .glossary-word[data-card-id="${cardId}"]`));
        const hasMeaning = spans.some((span) => (span.dataset.meaning || "").trim());
        if (hasMeaning) return;
        const existingNote = distinctUserNote(spans[0]?.dataset.note, "");
        const body = new URLSearchParams({ current_meaning: cleanMeaning, user_note: existingNote });
        const resp = await fetch(`/mark/word/${cardId}`, { method: "PATCH", body });
        if (!resp.ok) return;
        spans.forEach((span) => {
          span.dataset.meaning = cleanMeaning;
        });
        if (activeWordDetailCardId === cardId) {
          wordDetailMeaning.value = cleanMeaning;
        }
        if (wordPanelMeaning && activeAnalysisWordCardId === cardId) {
          wordPanelMeaning.value = cleanMeaning;
        }
      }

      async function requestWordAnalysis(cardId, options = {}) {
        if (options.pushCurrent) {
          pushCurrentAnalysis();
        } else if (panel.hidden) {
          clearAnalysisHistory();
        }
        activeAnalysisWordCardId = cardId;
        const contextText = normalizeContextText(
          options.contextText || wordAnalysisContextByCardId.get(String(cardId)) || "",
        );
        const seqAtRequest = toolbarInteractionSeq;
        setPanelLoadingWord(options.preferPro ? "Analyzing word with Pro..." : "Analyzing word...");
        hideToolbar();
        try {
          const body = new URLSearchParams();
          if (options.preferPro) body.set("prefer_pro", "1");
          if (options.forceRefresh) body.set("force_refresh", "1");
          if (contextText) body.set("context_text", contextText);
          const response = await fetch(`/analysis/word/${cardId}`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: body.toString(),
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderWordAnalysisError(payload.error || "Word analysis failed.", Boolean(payload.retry));
            return;
          }
          renderWordAnalysis(payload, seqAtRequest);
        } catch (error) {
          renderWordAnalysisError(`Word analysis failed: ${error}`, true);
        }
      }

      async function loadSavedWordAnalysis(cardId) {
        if (!cardId) return;
        clearAnalysisHistory();
        activeAnalysisWordCardId = cardId;
        const seqAtRequest = toolbarInteractionSeq;
        setPanelLoadingWord("Loading word analysis...");
        hideToolbar();
        try {
          const response = await fetch(`/analysis/word/${cardId}`);
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            renderWordAnalysisError(payload.error || "No saved word analysis found.", Boolean(payload.retry));
            return;
          }
          renderWordAnalysis(payload, seqAtRequest);
        } catch (error) {
          renderWordAnalysisError(`Could not load word analysis: ${error}`, true);
        }
      }

      function openInitialSentenceAnalysis() {
        if (initialPanel !== "analysis" || !initialSentenceId) return;
        const sentence = document.getElementById(`sentence-${initialSentenceId}`);
        if (!sentence) return;
        window.setTimeout(() => {
          sentence.scrollIntoView({ block: "center" });
          activeSentenceId = sentence.dataset.sentenceId;
          activeSentenceTranslation = sentence.dataset.translation || "";
          if (sentence.dataset.analysisId) {
            loadSavedAnalysis(sentence.dataset.sentenceId);
            return;
          }
          renderSentenceStudyPanel(sentence, "No saved AI analysis yet.");
        }, 0);
      }

      function clearEvidenceHighlight() {
        reader.querySelectorAll(".analysis-highlight").forEach((node) => {
          node.replaceWith(document.createTextNode(node.textContent || ""));
        });
        reader.querySelectorAll(".analysis-highlight-fallback").forEach((node) => {
          node.classList.remove("analysis-highlight-fallback");
        });
      }

      function evidencePhrase(text) {
        const matches = Array.from(text.matchAll(/[\"'“‘`]([^\"'“”‘’`]{3,120})[\"'”’`]/g));
        if (matches.length) {
          return matches.sort((a, b) => b[1].length - a[1].length)[0][1];
        }
        return normalizeText(text).slice(0, 80);
      }

      function highlightEvidence(text) {
        clearEvidenceHighlight();
        const sentence = activeAnalysisSentenceId
          ? document.getElementById(`sentence-${activeAnalysisSentenceId}`)
          : null;
        if (!sentence) return;
        const phrase = evidencePhrase(text).toLowerCase();
        if (!phrase) {
          sentence.classList.add("analysis-highlight-fallback");
          return;
        }
        const walker = document.createTreeWalker(sentence, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node) {
          const index = (node.nodeValue || "").toLowerCase().indexOf(phrase);
          if (index >= 0) {
            const range = document.createRange();
            range.setStart(node, index);
            range.setEnd(node, index + phrase.length);
            const mark = document.createElement("span");
            mark.className = "analysis-highlight";
            range.surroundContents(mark);
            return;
          }
          node = walker.nextNode();
        }
        sentence.classList.add("analysis-highlight-fallback");
      }

      toolbar.addEventListener("mousedown", (event) => {
        if (event.target.closest("textarea, input")) return;
        event.preventDefault();
      });
      reader.addEventListener("mousedown", () => {
        if (toolbarContainsFocus()) {
          blurToolbarFocus();
        }
      });
      sentenceDelete.addEventListener("click", () => {
        if (activeSentenceId) deleteSentenceCardsInPlace([activeSentenceId]);
      });
      translationOpen.addEventListener("click", openTranslationEditor);
      translationCancel.addEventListener("click", () => {
        closeTranslationEditor();
      });
      translationSave.addEventListener("click", () => {
        enqueueTranslationSave({ keepOpen: true });
      });
      translationText.addEventListener("input", () => {
        translationEditorDirty = true;
        scheduleTranslationAutoSave();
      });
      translationDelete.addEventListener("click", deleteTranslationInPlace);
      translationAnalyze.addEventListener("click", () => {
        clearTranslationAutoSaveTimer();
        const sentenceId = activeSentenceId;
        const value = translationText.value.trim();
        hideToolbar();
        if (sentenceId) requestAnalysis(sentenceId, value || null);
      });
      structureOpen.addEventListener("click", openStructureEditor);
      structureCancel.addEventListener("click", () => {
        closeStructureEditor();
      });
      structureSave.addEventListener("click", () => {
        enqueueStructureSave({ keepOpen: true });
      });
      structureText.addEventListener("input", () => {
        structureEditorDirty = true;
        scheduleStructureAutoSave();
      });
      structureAnalyze.addEventListener("click", () => {
        clearStructureAutoSaveTimer();
        const sentenceId = activeSentenceId;
        const value = structureText.value.trim();
        const translation = activeSentenceTranslation || null;
        if (!structureAttemptHasContent(value)) {
          structureStatus.textContent = "Fill in your structure judgement first.";
          return;
        }
        hideToolbar();
        if (sentenceId) {
          requestAnalysis(sentenceId, translation, {
            userStructure: value,
          });
        }
      });
      analysisOpen.addEventListener("click", () => {
        if (!activeSentenceId) return;
        const anchor = captureReadingAnchor(analysisOpen);
        const sentenceId = activeSentenceId;
        const translation = activeSentenceTranslation || null;
        const sentence = document.getElementById(`sentence-${activeSentenceId}`);
        hideToolbar();
        restoreReadingAnchor(anchor);
        if (sentence?.dataset.analysisId) loadSavedAnalysis(sentenceId);
        else requestAnalysis(sentenceId, translation);
      });
      crossSentenceDelete.addEventListener("click", () => {
        const ids = (crossSentenceDelete.dataset.sentenceIds || "")
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean);
        if (ids.length) deleteSentenceCardsInPlace(ids);
      });
      dismissButton.addEventListener("click", () => {
        window.getSelection()?.removeAllRanges();
        hideToolbar();
      });
      panelClose.addEventListener("click", closePanel);
      panelReturn.addEventListener("click", closePanel);
      if (panelTab) {
        panelTab.addEventListener("click", openPanelPlaceholder);
      }
      if (copyAll) copyAll.addEventListener("click", () => copyAnalysisPayload("all"));
      if (copySource) copySource.addEventListener("click", () => copyAnalysisPayload("source"));
      if (copyAnalysis) copyAnalysis.addEventListener("click", () => copyAnalysisPayload("analysis"));
      if (panelPrevious) {
        panelPrevious.addEventListener("click", restorePreviousAnalysis);
      }
      if (sentencePanelTranslationSave) {
        sentencePanelTranslationSave.addEventListener("click", () => {
          enqueuePanelTranslationSave();
        });
      }
      if (sentencePanelTranslation) {
        sentencePanelTranslation.addEventListener("input", () => {
          panelTranslationDirty = true;
          schedulePanelTranslationAutoSave();
        });
      }
      if (sentencePanelStructureSave) {
        sentencePanelStructureSave.addEventListener("click", () => {
          enqueuePanelStructureSave();
        });
      }
      if (sentencePanelStructure) {
        sentencePanelStructure.addEventListener("input", () => {
          panelStructureDirty = true;
          schedulePanelStructureAutoSave();
        });
      }
      if (sentencePanelNoteSave) {
        sentencePanelNoteSave.addEventListener("click", savePanelNote);
      }
      if (sentencePanelNoteAccept) {
        sentencePanelNoteAccept.addEventListener("click", acceptTakeawaySuggestion);
      }
      function showGlossaryWordDetail(hit) {
        const selection = window.getSelection();
        if (selection && !selection.isCollapsed) return;
        if (!hit.dataset.cardId) return;
        const contextText = analysisContextFromElement(hit);
        if (contextText) {
          wordAnalysisContextByCardId.set(String(hit.dataset.cardId), contextText);
        }
        showWordDetail(hit);
      }
      function analysisWordActionFromEvent(event) {
        const target = event.submitter || (event.target?.closest ? event.target : event.target?.parentElement);
        const markButton = target?.closest("[data-analysis-mark]");
        if (markButton && analysisWordForm.contains(markButton)) {
          return {
            analyzeAfter: false,
            lexicalType: markButton.dataset.analysisMark || "word",
          };
        }
        const analyzeButton = target?.closest("[data-analysis-analyze]");
        if (analyzeButton && analysisWordForm.contains(analyzeButton)) {
          return {
            analyzeAfter: true,
            lexicalType: analyzeButton.dataset.analysisAnalyze || "word",
          };
        }
        return null;
      }
      function runAnalysisWordAction(action) {
        markAnalysisSelection(action.lexicalType, action.analyzeAfter);
      }
      panel.addEventListener("click", (event) => {
        const hit = event.target.closest(".glossary-word");
        if (!hit) return;
        event.stopPropagation();
        showGlossaryWordDetail(hit);
      });
      panel.addEventListener("scroll", () => {
        updateAnalysisToolsVisibility(false);
      }, { passive: true });
      panel.addEventListener("mousemove", handleAnalysisPanelPointerMove);
      panel.addEventListener("mouseleave", () => {
        updateAnalysisToolsVisibility(false);
      });
      if (panelHeader) {
        panelHeader.addEventListener("focusin", syncAnalysisToolsFocusState);
        panelHeader.addEventListener("focusout", () => {
          window.setTimeout(syncAnalysisToolsFocusState, 0);
        });
      }
      if (panelUnmark) {
        panelUnmark.addEventListener("click", async () => {
          const sentenceId = activeAnalysisSentenceId;
          if (!sentenceId) return;
          closePanel();
          await deleteSentenceCardsInPlace([sentenceId]);
        });
      }
      wordForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const lexicalType = event.submitter?.value || "word";
        markReaderSelection(lexicalType, event.submitter);
      });
      analysisWordForm.addEventListener("click", (event) => {
        const action = analysisWordActionFromEvent(event);
        if (!action) return;
        event.preventDefault();
        event.stopPropagation();
        runAnalysisWordAction(action);
      });
      sentenceForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (event.submitter === sentenceSubmit && activeSentenceId) {
          markSentenceInPlace(activeSentenceId);
        }
      });
      panelRetry.addEventListener("click", () => {
        if (panelMode === "word" && activeAnalysisWordCardId) {
          requestWordAnalysis(activeAnalysisWordCardId, { forceRefresh: true });
        } else if (activeAnalysisSentenceId) {
          requestAnalysis(
            activeAnalysisSentenceId,
            sentencePanelTranslation?.value || null,
            {
              forceRefresh: true,
              userStructure: sentencePanelStructure?.value || "",
            },
          );
        }
      });
      if (panelRetryPro) {
        panelRetryPro.addEventListener("click", () => {
          if (panelMode === "word" && activeAnalysisWordCardId) {
            requestWordAnalysis(
              activeAnalysisWordCardId,
              { preferPro: true, forceRefresh: true },
            );
          } else if (activeAnalysisSentenceId) {
            requestAnalysis(
              activeAnalysisSentenceId,
              sentencePanelTranslation?.value || null,
              {
                preferPro: true,
                forceRefresh: true,
                userStructure: sentencePanelStructure?.value || "",
              },
            );
          }
        });
      }
      async function saveWordDetailEdits(options = {}) {
        if (!activeWordDetailCardId) return;
        const cardId = activeWordDetailCardId;
        const meaning = wordDetailMeaning.value;
        const note = wordDetailNote.value;
        const body = new URLSearchParams({ current_meaning: meaning, user_note: note });
        readerToolbarBusy = true;
        try {
          const resp = await fetch(`/mark/word/${cardId}`, { method: "PATCH", body });
          if (resp.ok) {
            updateWordCardElements(cardId, meaning, note);
            if (options.hideAfter !== false) hideToolbar();
            return true;
          }
          return false;
        } finally {
          readerToolbarBusy = false;
        }
      }
      wordDetailSave.addEventListener("click", () => {
        saveWordDetailEdits();
      });
      wordDetailRemove.addEventListener("click", () => {
        const cardId = wordDetailRemove.dataset.cardId;
        if (!cardId) return;
        if (activeWordDetailFromAnalysis) {
          deleteAnalysisWordCardInPlace(cardId);
          return;
        }
        deleteWordCardsAndReload([cardId]);
      });
      if (wordDetailExplain) {
        wordDetailExplain.addEventListener("click", async () => {
          const cardId = activeWordDetailCardId;
          if (!cardId) return;
          const saved = await saveWordDetailEdits({ hideAfter: false });
          if (!saved) return;
          requestWordAnalysis(cardId, { pushCurrent: !panel.hidden });
        });
      }
      if (wordDetailViewCard) {
        wordDetailViewCard.addEventListener("click", () => {
          const cardId = activeWordDetailCardId || wordDetailViewCard.dataset.cardId;
          if (!cardId) return;
          saveReaderProgress();
          window.sessionStorage.setItem("glossary_return_url", window.location.href);
          window.location.href = `/cards#card-${cardId}`;
        });
      }
      if (wordPanelSave) {
        wordPanelSave.addEventListener("click", async () => {
          if (!activeAnalysisWordCardId) return;
          const cardId = activeAnalysisWordCardId;
          const meaning = wordPanelMeaning?.value || "";
          const note = wordPanelNote?.value || "";
          const body = new URLSearchParams({ current_meaning: meaning, user_note: note });
          const resp = await fetch(`/mark/word/${cardId}`, { method: "PATCH", body });
          if (resp.ok) {
            updateWordCardElements(cardId, meaning, note);
            if (wordPanelSaveStatus) {
              wordPanelSaveStatus.textContent = "Saved ✓";
              window.setTimeout(() => {
                if (wordPanelSaveStatus) wordPanelSaveStatus.textContent = "";
              }, 1500);
            }
          }
        });
      }
      reader.addEventListener("click", (event) => {
        const selection = window.getSelection();
        const hasSelection = selection && !selection.isCollapsed;
        const wordSpan = event.target.closest("[data-word-card]");
        if (wordSpan && !hasSelection) {
          showWordDetail(wordSpan);
          return;
        }
        const sentence = event.target.closest("[data-sentence-id]");
        if (!sentence) return;
        if (hasSelection) return;
        if (sentence.dataset.analysisId) {
          loadSavedAnalysis(sentence.dataset.sentenceId);
          return;
        }
        if (sentence.dataset.marked === "1") {
          showMarkedSentenceToolbar(sentence);
        }
      });
      reader.addEventListener("dblclick", (event) => {
        const wordSpan = event.target.closest("[data-word-card]");
        if (wordSpan) {
          event.preventDefault();
          showWordDetail(wordSpan);
          return;
        }
        const sentence = event.target.closest("[data-sentence-id]");
        if (!sentence || !sentence.dataset.translation?.trim()) return;
        event.preventDefault();
        window.getSelection()?.removeAllRanges();
        openTranslatedSentenceShortcut(sentence);
      });
      document.addEventListener("keydown", handleReaderShortcut);
      document.addEventListener("selectionchange", () => window.setTimeout(updateToolbar, 0));
      window.addEventListener("scroll", () => {
        if (!translationEditorOpen && !structureEditorOpen) hideToolbar();
        scheduleProgressSave();
      }, { passive: true });
      if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", () => {
          if (!translationEditorOpen && !structureEditorOpen) return;
          const keyboardInset = Math.max(
            10,
            window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop + 10,
          );
          toolbar.style.bottom = `${keyboardInset}px`;
        });
      }
      window.addEventListener("pagehide", flushPendingToolbarAutoSaveOnPageHide);
      window.addEventListener("pagehide", saveReaderProgress);
      const restoredProgress = restoreReaderProgress();
      if (initialWordCardId) {
        window.setTimeout(() => loadSavedWordAnalysis(initialWordCardId), 0);
      } else if (initialPanel === "analysis" && initialSentenceId) {
        openInitialSentenceAnalysis();
      } else {
        restoreSavedAnalysisPanel(restoredProgress).then((restoredPanel) => {
          if (!restoredPanel) openInitialSentenceAnalysis();
        });
      }
    })();
    """
