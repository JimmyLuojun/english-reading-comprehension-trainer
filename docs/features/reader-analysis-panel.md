# Reader Analysis Panel

本文件保存 AI 分析解释词汇回链、覆盖式分析面板和阅读页操作后保持当前位置的设计。

## §26 AI 分析解释词汇回链

`[新增 2026-06-16]`

目标：AI analysis 面板的解释文字中，如果出现已收录在 `word_cards` 的词或短语，自动高亮并支持回到卡片页查看。

### §26.1 交互

- 分析面板文本继续支持选中触发标记工具栏；工具栏提供 `Mark word` / `Mark phrase` / `Mark collocation` / `AI analysis`，使解释中的陌生词、词组和搭配都能按正确类型处理。
- 分析面板内的标记操作必须使用 `fetch` 异步提交，成功后保留当前解释面板，不跳回阅读正文。
- 分析面板内点击 `AI analysis` 时，先异步创建或恢复词卡，再立即打开该词卡的 Word Analysis；当前解释进入 `analysisHistory`，用户可用 `Back to {word} analysis` 回到上一层解释。
- 已收录词在分析面板中显示为明显高亮词；hover 或 click 打开已有词卡详情浮层，展示 `current_meaning` / note，并提供 `Save` / `Explain word` / `View card` / `Remove from Cards`。
- 打开或切换 AI analysis 面板时，只渲染高亮，不自动打开词卡详情浮层；详情浮层只能由用户主动点击某个已高亮的词、词组或搭配触发。
- 在 AI analysis 面板内点击 `Remove from Cards` 时，必须原地异步删除词卡：保持当前解释面板和滚动位置，关闭小浮层，移除该词的高亮并刷新当前解释内容，不跳回阅读正文。
- 从某个词的解释中继续点击高亮词的 `Explain word` 时，分析面板底部在 `Reanalyze` 与 `Back to reading` 之间显示 `Back to {word} analysis`，点击后恢复上一层解释内容和滚动位置，便于先查陌生词再继续阅读原词解释。
- `View card` 保存当前阅读 URL 到 `sessionStorage`，跳转到 `/cards#card-{word_card_id}`。
- Cards 页面检测到来源 URL 后，在标题区域注入 `Back to reading` 链接，点击可返回原阅读位置。
- Cards 表格列名为 Notes，只展示并编辑用户本人填写的 `user_note`；若历史 `user_note` 与 Definition/AI meaning 完全相同则显示为空。Definition（`current_meaning`）仍保留在词卡详情/解释面板中，不在 Cards 表格主列伪装成用户笔记。Review reveal 的 `Your note` 只显示非空且不同于 Definition/AI meaning 的 `user_note`；没有用户 note 时只显示 `AI meaning` 或不显示 reveal。

### §26.2 实现

- 复用阅读页已有的 `word-card-index` JSON，不新增 API。
- `POST /mark/word` 保留普通表单 redirect；当请求带 `X-Requested-With: fetch` 或 `Accept: application/json` 时返回 `{ok, card_id, created, word_card}`，供 analysis 面板无刷新更新前端状态。
- 前端用 `lemma` 与 `surface_form` 构建大小写不敏感 glossary 索引。
- analysis 标记成功后，把返回的词卡写入前端 `wordCards` / `glossaryEntries`，重建 glossary regex，并对当前分析字段重新执行高亮。
- 高亮只处理文本节点：AI 字段先用 `textContent` 写入，再用 `DocumentFragment` 拆分文本并插入 `<span class="glossary-word">`，避免把 AI 输出作为 HTML 注入。
- hover/click 高亮词时如果页面仍有非折叠选区，则不打开词卡浮层，保证与选中解释文字后标词的流程互不抢占。
- 词卡详情浮层不绑定 `mouseover` 自动打开，只响应 `.glossary-word` 的 `click`；`renderAnalysisPayload()` / `renderWordAnalysis()` 每次渲染前先隐藏已有详情浮层，避免上一次状态残留。
- 词卡详情浮层记录来源是否在 analysis 面板内：正文来源的 `Remove from Cards` 保持原有删除后返回阅读页行为；analysis 来源的删除走 `fetch DELETE /mark/word/{id}`，成功后从 `wordCards` / `glossaryEntries` 删除对应卡片并重建高亮。
- 前端维护仅存在于当前阅读页的 `analysisHistory` 栈；只有从当前打开的分析面板内继续 `Explain word` 才压入上一层 payload，返回上一层时直接用已保存 payload 重渲染，不重新请求 AI。
- 当词卡 `current_meaning` 为空，用户通过 `Explain word` 生成词汇 AI analysis 后，前端用 `meaning_in_context` 回填空释义，后续打开浮层即可看到意思。
- 词卡详情浮层必须限制在 viewport 内：输入框不撑开容器，操作按钮允许换行，避免在窄屏或高缩放下覆盖/溢出阅读内容。

### §26.3 测试

- 路由级测试覆盖阅读页脚本/样式、Cards 行锚点、返回脚本。
- 路由级测试覆盖 `POST /mark/word` 的 JSON/AJAX 返回，且普通表单 redirect 行为保持不变。
- 浏览器级测试覆盖分析面板自动高亮、hover 打开词卡详情、`View card` 跳转到 `/cards#card-{id}`、Cards 页返回链接。
- 浏览器级测试覆盖从词解释继续 `Explain word` 后显示上一层解释返回按钮，并能恢复原词解释。
- 浏览器级测试覆盖在 analysis 面板内选中文本后可无刷新 `Mark phrase`，以及 `AI analysis` 可直接进入新词解释并返回上一层解释。
- 浏览器级测试覆盖打开 analysis 面板不会自动显示词卡详情浮层；只有点击高亮词才显示。
- 浏览器级测试覆盖 analysis 面板内 `Remove from Cards` 不改变 URL、不关闭 analysis 面板，并会移除当前解释内对应高亮。

---
---

## §27 AI 分析覆盖式面板

`[新增 2026-06-16]`

目标：AI analysis 打开后不再挤压阅读正文，不改变正文行宽、换行和滚动节奏。

### §27.1 交互

- AI analysis 仍由用户主动点击触发，不能 hover 自动打开。
- 打开后显示为右侧覆盖式 drawer，而不是阅读布局中的右栏。
- 阅读正文保持原宽度、原居中位置和当前滚动位置；drawer 只覆盖右侧可视区域。
- drawer 内部独立滚动，正文滚动不被 drawer 内容撑开。
- `Back to reading` 关闭 drawer；`Back to previous analysis` 继续在 drawer 内恢复上一层解释；`Reanalyze` 只刷新当前分析。
- 打开 drawer 时关闭临时 selection toolbar / word detail 浮层，避免多个浮层重叠。
- 移动端 drawer 使用接近全屏宽度，避免窄屏中出现横向滚动。

### §27.2 实现

- 保留现有 `#analysis-panel` DOM、AI 请求、渲染、嵌套 `analysisHistory` 和保存 notes 的逻辑。
- CSS 将 `.analysis-panel` 设为 `position: fixed`，右侧贴边，宽度 `min(520px, 92vw)`，`overflow-y: auto`。
- `body.analysis-open` 只表达面板打开状态，不再改变 `.reader` 的 `max-width`、`margin-left` 或 `margin-right`。
- 移动端使用 `inset: 0` / `width: 100%`，保留独立滚动。
- 面板层级高于正文和普通 toolbar，但不应高到遮住系统级浏览器 UI。

### §27.3 测试

- 路由级测试断言 reader 页面包含 fixed analysis drawer 样式。
- 路由级测试断言不存在 `.reader-page.analysis-open .reader` 的布局挤压规则。
- 浏览器验证打开 analysis 后 `.reader` 宽度不变，`#analysis-panel` 可见且 fixed，关闭后隐藏。

---
---

## §28 阅读页操作后保持当前位置

`[新增 2026-06-17]`

目标：阅读页中点击 `Mark word` / `Mark phrase` / `Mark collocation` / `AI analysis` / `Remove from cards` / 保存翻译等操作后，不跳到页面顶部，用户应留在被操作的词、词组、搭配或句子附近继续阅读。

### §28.1 要避免的负面后果

- 常见操作不能依赖整页 reload/redirect，否则长文章中会回到顶部或恢复到不相关的历史进度。
- 不能只保存 `window.scrollY`，因为标记/删除会改变 DOM 包装，纯 scrollY 在内容高度变化后可能不准。
- 不能破坏当前 `/read/{book_id}?chapter=...#sentence-...` URL 和章节锚点。
- 恢复滚动后不能保留旧 toolbar 坐标；操作完成后应隐藏 toolbar，避免浮层漂在错误位置。
- `Remove from cards` 成功后不能残留 `data-word-card` 高亮状态。

### §28.2 实现

- 前端新增 `captureReadingAnchor(target)` / `restoreReadingAnchor(anchor)`：优先记录当前选择或被点击词卡所在元素及其 `getBoundingClientRect().top`，元素消失时才回退到 `scrollY`。
- `Mark word` / `Mark phrase` / `Mark collocation` 拦截 `toolbar-word-form` submit，改用 `fetch POST /mark/word` 并请求 JSON；成功后把返回词卡注册进前端索引，给当前选区原地包上 `data-word-card`，清空选区并恢复锚点。
- `Remove from cards` 在阅读正文中改为 `fetch DELETE /mark/word/{id}`；成功后从前端词卡索引删除，并移除正文中对应 `data-word-card` / meaning / note 属性，再恢复锚点。
- 句子 unmark、句子 mark、保存翻译同样使用 `fetch` 原地更新 DOM 状态，避免 redirect。
- `AI analysis` 只打开覆盖式 drawer，不调用 `scrollIntoView()`，并在打开前后保持阅读锚点。

### §28.3 测试

- 路由级测试断言阅读页脚本包含 reading anchor capture/restore 和 word form fetch 提交流程。
- 浏览器级测试覆盖：滚动到页面中部后标记一个未收录词，URL 不变、页面不回顶部、选区位置保持、该词出现 `data-word-card`。
- 浏览器级测试覆盖：滚动后删除正文词卡，URL 不变、页面不回顶部、对应高亮移除。

---

## §29 最小递归式 AI 分析

`[新增 2026-06-18]`

目标：让 AI analysis 支持“整句理解 → 局部拆解 → 回到整句 → 留下可复用检查点”的阅读训练闭环，同时不引入第二套复习系统、不新增表、不重做面板架构。

### §29.1 要避免的负面后果

- 不新增 `recursive_parse` 嵌套树；现有 `clauses` / `modifiers` / `anaphora` / `logic_markers` 已能表达结构拆解。
- 不新增 `review_question` / `review_answer` / `Quiz me later`；Review 仍只使用既有 SM-2 卡片、Takeaway 和 Similar past mistake。
- 不把词汇 prompt 拆出多个高度重叠字段；词义、作者用词动机、近义替换差异仍由现有字段承担。
- 不新增 panel↔正文高亮组件；需要高亮时优先复用已有 evidence/glossary 高亮。
- 不修改历史 prompt 文件；所有 prompt 优化都通过新版本落地。

### §29.2 Prompt 增量

句子分析新版本只新增两个字段：

- `blocking_point`：本句真正影响理解的 1 个卡点。诊断模式必须来自用户译文证据；预测模式取最可能误读处。
- `takeaway_suggestion`：一句可直接保存为 Takeaway 的检查点，固定为“遇到 [结构/搭配]，先检查 [动作]，否则易犯 [错误码]。”。

词 / 词组 / 固定搭配分析新版本只新增一个字段：

- `role_in_sentence`：目标项在本句中的句法或语义作用，以及理解错会怎样带偏整句。

### §29.3 Panel 增量

句子面板按递归阅读路径重排：

1. 整句答案：`simplified_en` + `chinese_gloss`。
2. 本句卡点：`blocking_point`。
3. 结构拆解：主干、从句、修饰、指代、逻辑，复用已有字段。
4. 诊断证据与 Similar past mistake。
5. 回到整句：再次显示 `simplified_en`。
6. Takeaway：在现有 Takeaway 编辑区上方显示 `takeaway_suggestion`，提供 `Accept suggestion` 按钮把建议填入现有输入框，再复用现有保存接口。

词面板只新增 `In this sentence` 区块，显示 `role_in_sentence`。

### §29.4 测试

- Prompt 测试覆盖新版本文件存在、frontmatter、字段名、错误码和模板变量。
- Schema 测试覆盖当前句子 prompt v3（复用 v2 JSON schema）与词 v5 必填字段，并保留旧版本兼容。
- Reader view/script 测试覆盖新增 panel 区块、建议 Takeaway 预填按钮和词汇 `role_in_sentence` 渲染。
- Web 变更继续运行 `app/web` ruff；非微小改动继续运行全量测试。

---
