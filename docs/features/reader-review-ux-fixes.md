# Reader / Review 交互修复批次 (B1/B3/A2/B2/A1/B4) — Executable Plan

Status: implemented (2026-06-18)

来源：用户在阅读器与 Review 中报告的 6 个问题。本批次以**最小改动**修 4 个确定性 bug、
1 项配色、1 个新快捷键，不重构、不引新依赖。Reader 客户端逻辑全部在
`english-reading-trainer/app/web/views/reader_script.py`；样式在 `views/styles.py`；
Review/Cards 在 `views/review.py` / `views/cards.py` / `app/review/daily_review_queue.py`。
服务端句子/词渲染在 `views/reader.py`。

所有行号基于当前分支 `codex-step-15-user-translation-diagnosis`，实现前请按符号名再次定位（行号会漂移）。

## 用户确认的取舍

1. **B2 配色**：按词性分色 —— word=绿 / phrase=紫 / idiom=橙；句子保留黄。
2. **B4 快捷键**：`Alt+S` 选中"光标所在整句"并弹 toolbar（不是右键，是键盘键）；可选 `Alt+T` 直接开翻译框。
3. 全部实现 + 补/改单测 + 跑全量 `pytest`。

## Risks to avoid（先列规避项）

1. **B1 修复不能让 toolbar 永不关闭。** 只在 `translationEditorOpen === true`（用户正在翻译框打字）
   时跳过 `hideToolbar`；编辑器关闭后必须恢复正常隐藏，否则分析面板打开后 toolbar 会赖着不走。
2. **B3 不能简单"保留 analysisId 不变"。** 翻译变更后旧分析已与新译文不一致，必须标记 `analysis-stale`
   （保留指针 + 置 `analyzed-stale`），不能让用户误以为分析是最新的。`saveTranslationOnly`（toolbar 首次写译文、
   此时通常无分析）行为不变。
3. **B2 有前后端依赖，不能只改 CSS。** 当前正文 `[data-word-card]` span 不携带词性
   （`reader.py:_highlight_word_cards` 只输出 `data-meaning`/`data-note`）。按词性分色必须先把
   `lexical_type` 透传到 span 和 glossary 高亮 span，否则 CSS 选择器无锚点。改完要确认旧数据
   （无 lexical_type 的历史词卡）有合理回退色。
4. **B2 不动句子黄色。** `[data-sentence-id].marked` 的 `#ffe58a`（`styles.py:301`）保持不变，
   只改 `[data-word-card]`（`:333`）和面板内 `.glossary-word`（`:547`）。
5. **A2 SQL 改动用真实 SQLite 集成测试。** 句子 SQL 新增 `takeaway` 列属 schema/查询变更，
   按 AGENTS.md 不可 mock，必须真实 SQLite 跑。
6. **A1 先实测再改。** "选项点不动"可能是事件竞态，也可能是 `activeAnalysisSourceSentenceId` 为空。
   动手前用 TestClient + 手动复现确认主因，避免改错地方。
7. **无测试不合入。** 每步同步改/加测试，跑 `ruff check app/web` + 全量
   `english-reading-trainer/.venv/bin/python -m pytest tests/`。

## 落地顺序

B1 → B3 → A2 → B2 → A1 → B4。B2 先于 A1，因为 A1 的"正文同词补高亮"复用 B2 的 `data-lexical-type`。

---

## Step 1 — B1：AI 分析完成不再关掉正在写的翻译浮层

**根因（确定）**：分析结果返回后，`renderAnalysisPayload`（`reader_script.py:~1462`）、
`renderWordAnalysis`（`:~1728`）、`renderSentenceStudyPanel`（`:~1435`）无条件调用 `hideToolbar()`；
`hideToolbar → hideAllPanels → hideTranslationEditor`（`:~292`）会清掉用户为**另一个**句子打开、写到一半的翻译框
（`translationEditor.hidden=true` / `translationEditorOpen=false`）。

时序：点句 1 的 AI analysis → 选句 2 → 打开翻译框打字 → 句 1 分析返回 → `hideToolbar()` 把翻译框干掉。

**改动**：
- 新增 `hideToolbarUnlessEditing()`：`if (translationEditorOpen) return;` 否则 `hideToolbar()`。
- 把上述三个 render 函数里的 `hideToolbar()` 换成 `hideToolbarUnlessEditing()`。
- `translationAnalyze` 处理器（`:~1976`）维持自身的显式 `hideToolbar()`（同句翻译→分析，编辑器应关），不改。

**测试**：`tests/web/views/test_reader_script.py` 断言 render 函数体引用 `hideToolbarUnlessEditing` 且
新函数包含 `translationEditorOpen` 早退守卫。

## Step 2 — B3：已分析句子可重新弹出旧分析

**根因（确定）**：`savePanelTranslation`（`:~1663`）保存后调 `markSentenceTranslated`（`:~530`），
该函数 `dataset.analysisId=""` 并移除 `analyzed` class；点击处理器（`:~2203`）靠 `analysisId` 才走
`loadSavedAnalysis`，被清空后退化为只弹 toolbar / 无响应。所以"在面板里改过译文的句子"之后点击调不出旧分析。

**改动**：
- `markSentenceTranslated(sentence, translation)`：若 `sentence.dataset.analysisId` 已存在，
  **保留** `analysisId`，去掉 `analyzed`、加 `analyzed-stale`、`dataset.analysisStale="1"`；
  仅当原本无 analysisId 时才走现有清空逻辑。
- 点击处理器（`:~2203`）：把 `if (sentence.dataset.analysisId)` 判定保持（stale 仍有 analysisId，自然命中）。
  确认 `loadSavedAnalysis` 对 stale 分析能正常返回（`/analysis/sentence/{id}` 返回最近缓存，已支持）。

**测试**：`test_reader_script.py` 断言 `markSentenceTranslated` 含 stale 分支；
如有 `/analysis/sentence` 路由测试，补一条"改译文后仍可取回分析"用例。

## Step 3 — A2：Review 术语统一 + 句子同时显示译文与 takeaway

**根因（确定）**：句子卡 `answer` 取 `sc.user_translation`（`daily_review_queue.py:173`），
但 reveal 标签写死 "Your note"（`review.py:49`）——句子的 "Your note" 其实是译文，且没展示 takeaway。
词卡 `answer` 才是 takeaway。

**改动**：
1. `daily_review_queue.py`：句子 SQL（`_sentence_due_sql`）增 `COALESCE(sc.user_note,'') AS takeaway`；
   dataclass `DueCard`（`:~41`）加 `takeaway: str = ""`；`_row_to_due_card`（`:~306`）映射。
   （词卡 SQL 无 takeaway 列时给 `'' AS takeaway` 保持列对齐。）
2. `review.py` `_review_answer_cell`（`:43`）按 `item.card_type` 渲染：
   - 句子：**Translation** 行（`item.answer`，即 user_translation）+ **Takeaway** 行（`item.takeaway`）。
   - 词/词组/俗语：**Takeaway** 行（`item.answer`，即 user_note）+ **AI meaning** 行（`item.ai_meaning`）。
   - 弃用 "Your note" 文案。
3. `cards.py` 词卡表头 "Notes"（`:55`）改 "Takeaway"，与句子列（已叫 Takeaway）和 Review 统一。

**测试**：
- `tests/review/test_daily_review_queue.py`（真实 SQLite）：断言句子 DueCard 带 `takeaway`。
- `tests/web/views/test_review.py`：断言句子行出现 "Translation"+"Takeaway"、词行出现 "Takeaway"+"AI meaning"，
  且不再出现 "Your note"。
- `tests/web/views/test_cards.py`：断言词卡表头为 "Takeaway"。

## Step 4 — B2：按词性分色（word=绿 / phrase=紫 / idiom=橙 / 句子=黄）

**根因**：正文词高亮 `[data-word-card]`（`styles.py:333`）与句子 marked（`:301`）都是黄色系，难区分；
且 span 不带词性，无法按 POS 分色。

**改动**：
1. 服务端：`reader.py:_highlight_word_cards`（`:211`）给 word-card span 增
   `data-lexical-type="{card['lexical_type']}"`；确认 reader 的 word_cards 查询带出 `lexical_type`
   （若没有，补到 `queries/reader.py` 的 SELECT）。
2. 客户端：`reader_script.py` `decorateWordCardElement`（`:416`）写入 `dataset.lexicalType`；
   `registerWordCard`/glossary `entry` 带上 `lexical_type`；`glossaryHighlightFragment`（`:636`）
   给生成的 `.glossary-word` span 加 `data-lexical-type`。
3. 样式：`styles.py` 用 `[data-word-card][data-lexical-type="word"|"phrase"|"idiom"]` 三套色相
   （绿 ≈ `rgba(16,185,129,..)` / 紫 ≈ `rgba(168,85,247,..)` / 橙 ≈ `rgba(249,115,22,..)`，
   下划线同色加深）；缺失/未知词性回退到现有黄绿默认。面板内 `.glossary-word`（`:547`）同样按词性着色。
   句子 `#ffe58a` 不动。

**测试**：
- `tests/web/views/test_reader.py`：断言 word-card span 含 `data-lexical-type`。
- `tests/web/views/test_styles.py`：断言三套词性选择器与颜色存在、句子黄色未变。
- `test_reader_script.py`：断言 glossary span 输出 `data-lexical-type`。

## Step 5 — A1：面板内选词二次分析（选项点不动 + 无标记色）

**根因（待实测确认主因）**：
1. `analysisWordForm` 同时绑 `pointerdown`/`click`/`submit` + `analysisWordPointerActionHandled` 去抖
   （`:~2070-2102`），叠加 toolbar `mousedown` 的 `preventDefault`（`:~1960`），竞态导致"点了没反应"；
   或 `showAnalysisWordToolbar`（`:~620`）在 `activeAnalysisSourceSentenceId` 为空时直接 `hideToolbar()`，选项根本不出。
2. 标记成功后仅 `refreshAnalysisGlossaryHighlights()`（只刷面板），正文同词未补高亮 → 回正文看"没有标记色"。

**改动**：
- 实测确认主因后，把三重事件绑定收敛为单一 `click`（移除 pointerdown 去抖竞态）；若主因是
  `activeAnalysisSourceSentenceId` 为空，则在进入面板词分析时正确赋值/兜底。
- `markAnalysisSelection`（`:~711`）成功后，除面板高亮外对**正文**同 lemma 补高亮（复用 Step 4 的
  `data-lexical-type`，给正文 text node 应用 `applyGlossaryHighlights` 或插入 word-card span）。

**测试**：先以 TestClient + 手动复现记录主因；再补 `test_reader_script.py` 断言事件绑定收敛、
标记后正文高亮被刷新。

## Step 6 — B4：裸键 `S` / `T` 选中光标所在整句（新功能）

**现状**：reader 无任何键盘处理（仅 cards 页有 `Cmd+Enter`）。

**改动**：
- `reader_script.py` 加 `document.addEventListener("keydown", handleReaderShortcut)`：
  - `S`：取当前选区/光标 `anchorNode` 最近的 `[data-sentence-id]`（无选区时用视口顶部可见句兜底），
    用 `Range` 选中整句、`selection.removeAllRanges()+addRange()`，再 `updateToolbar()` 弹出该句 toolbar。
  - `T`：在上一步基础上直接 `openTranslationEditor()`。
  - 在输入框/textarea/contenteditable 聚焦或 IME 组字时不拦截。

**键位迭代（2026-06-19）**：最初用 `Alt+S`/`Alt+T`，但用户机器上 macOS 全局热键工具（启动器、
截图工具）会在浏览器收到事件前抢占所有 Option 组合键 —— `Alt+S` 弹出第三方浮层、`Alt+T` 触发截图。
中间尝试过 `event.code`（绕开 Option 改写 `event.key` 的问题）仍无效，因为事件根本到不了浏览器。
**最终改为裸键 `S`/`T`（无修饰键）**：macOS 全局热键必须带修饰键，裸键不会被系统抢占；reader 正文不可编辑，
裸字母不会与正常输入冲突。匹配仍用 `event.code === "KeyS"/"KeyT"`（布局无关），并在任意
`altKey/ctrlKey/metaKey` 或 `isComposing` 时早退。

**测试**：`test_reader_script.py::test_reader_script_supports_bare_key_sentence_shortcut`
断言 keydown 处理器存在、对修饰键/IME 早退、用 `event.code` 匹配裸键、调用整句选中 + `updateToolbar`。

## Step 7 — analysis 面板可读性：正文字号对齐 + 中英双语醒目标签（2026-06-19）

**来源**：用户反馈面板正文字号比原文小、`Simplified English`/`Chinese gloss` 等标签不够贴切醒目。

**改动**：
- `reader.py`：句子分析面板各 `<h3>`/`<h4>` 标签改为中英双语结构
  `<span class="section-label-zh">中文</span><span class="section-label-en">English</span>`
  （简化英文 / 中文释义 / 阅读卡点 / 句子结构 + 主干骨架·从句·修饰成分·逻辑连接词·指代关系 /
  问题诊断 / 回到整句 / 我的翻译 / 收获）；`Chinese gloss` 这一生僻措辞改为 `Chinese meaning`。
  英文文本仍作为子串保留，旧的顺序/存在性断言不受影响。
- `styles.py`：`.analysis-text` 字号设为 `20px`（对齐 `.reader-para` 原文字号），行高 1.7；
  `.analysis-section h3` 加左侧 `4px` 主题色色条、`.section-label-zh` 用 16px 主题强调色、
  `.section-label-en` 用小号大写灰字作副标，`h4` 用更轻的同款样式。

**测试**：`test_reader.py::test_analysis_panel_labels_are_bilingual`、
`test_styles.py::test_css_analysis_panel_body_matches_reading_size` 与
`test_css_analysis_section_labels_are_prominent_bilingual`。

---

## 完成口径

- 每步：改代码 + 同步测试 → `english-reading-trainer/.venv/bin/python -m ruff check app/web`
  → `english-reading-trainer/.venv/bin/python -m pytest tests/`（报告实际 `sys.executable`）。
- 全部完成后更新 `STATUS.md`，并把本文件 Status 改为 implemented。
