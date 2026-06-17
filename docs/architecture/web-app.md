# Web App 与阅读交互

本文件保存 Web 技术栈、阅读交互、阅读视图、诊断面板、词卡提示和浮层状态机设计。当前 FastAPI 拆分决策见 `docs/decisions/2026-06-17-fastapi-web-split.md`。

## 12. 技术栈与目录结构

```text
后端          Python 3.11+
数据库        SQLite + WAL 模式
NLP           spaCy en_core_web_sm + pysbd
AI            OpenAI 兼容接口（含可替换 base_url）
EPUB          ebooklib + BeautifulSoup
CLI           Typer
JSON 校验     jsonschema
测试          pytest + pytest-cov（见下方"测试规范"）
```

**测试规范（强制）**

- 每个 `.py` 源文件必须有对应 `tests/<mirror_path>/test_<name>.py`。
- 覆盖正常路径、边界、异常、空输入；不允许"无测试合入"。
- 外部依赖（LLM / 网络 / 文件 IO）默认 mock；**SQL schema 与 migration 用真实 SQLite 集成测试**。
- 覆盖率目标 ≥ 90% 行覆盖；`sm2_scheduler` / `ai_response_cache` / `json_output_validator` 三个模块要求 100%。
- 全部测试可用 `pytest tests/` 离线运行，无外部网络与环境变量依赖。

```text
english-reading-trainer/
  app/
    db_models.py                       -- SQLAlchemy / dataclass 模型定义
    db_connection.py                   -- SQLite 连接、WAL、migration runner
    importers/
      txt_importer.py                  -- TXT → Book/Chapter/Paragraph/Sentence
      epub_importer.py                 -- EPUB → 同上（ebooklib + BeautifulSoup）
    nlp/
      sentence_segmenter.py            -- 句子切分（pysbd）
      english_lemmatizer.py            -- lemmatization（spaCy en_core_web_sm）
    ai/
      llm_sentence_analyzer.py         -- 难句结构化分析（调用 LLM）
      llm_word_analyzer.py             -- 词 / 短语 / 搭配分析
      ai_response_cache.py             -- §5 缓存读写
      json_output_validator.py         -- §9 jsonschema 校验 + 重试
      ai_json_schemas.py               -- §9 JSON Schema 定义
    cards/
      sentence_card_service.py         -- 句卡 CRUD + 标签关联
      word_card_service.py             -- 词卡 CRUD + 标签关联
      similar_card_finder.py           -- §8 相似提醒
    review/
      sm2_scheduler.py                 -- §7 SM-2 算法
      daily_review_queue.py            -- §7.5 每日预算与混合
    profile/
      learner_profile_generator.py     -- §11 画像生成
    cli_entry.py                       -- Typer 主入口
  prompts/
    sentence_analysis.v1.md
    word_analysis.v1.md
    profile_summary.v1.md
  docs/
    design.md                          -- 本文档
  data/
    reading_trainer.db
  tests/                               -- 镜像 app/ 目录结构，每个源文件一份测试
    importers/
      test_txt_importer.py
      test_epub_importer.py
    nlp/
      test_sentence_segmenter.py
      test_english_lemmatizer.py
    ai/
      test_llm_sentence_analyzer.py
      test_llm_word_analyzer.py
      test_ai_response_cache.py
      test_json_output_validator.py
    cards/
      test_sentence_card_service.py
      test_word_card_service.py
      test_similar_card_finder.py
    review/
      test_sm2_scheduler.py
      test_daily_review_queue.py
    profile/
      test_learner_profile_generator.py
    test_db_connection.py              -- SQLite 真实集成测试，不 mock
```

`[已确认 2026-06-14]`

---
---

## 14. 阅读交互：选中即操作（取代每句挂表单）

### 14.1 痛点

第一版 Web UI 把每个句子下方挂"Mark sentence / Mark word"两个表单，视觉嘈杂，打断连贯阅读，且强迫用户对每个句子做决策。这与"阅读为主、卡点为辅"的产品定位相反。

### 14.2 目标交互

参考微信读书：阅读页只渲染干净正文。用户操作由**文本选中**触发——选中即弹出紧贴选区的浮层工具条，未选中时完全无干扰。

### 14.3 行为映射

```text
选中文本与某个完整句子匹配   → 浮层显示：
  · 标为难句           POST /mark/sentence/<id>
  · 写下我的理解        → 弹出译文输入框，与难句一起入库（见 §15）
  · AI 分析            POST /analyze/sentence/<id>
  · 查词              （第二版）

选中文本是句中片段        → 浮层显示：
  · 标为生词           POST /mark/word（surface_form=选中文本）
  · 标为短语            ↑ 同上，lexical_type=phrase
  · 标为搭配            ↑ 同上，lexical_type=collocation
  · 查词              （第二版）

未选中                  → 浮层隐藏
```

### 14.4 DOM 与定位

- 每个句子在 HTML 中包一层 `<span data-sentence-id="N" data-chapter-id="M">...</span>`。
- 前端用原生 `selectionchange` 事件监听选区变化。
- 通过 `Range.getBoundingClientRect()` 定位浮层位置（贴近选区上方或下方）。
- 通过 `Range.commonAncestorContainer` 反查所在的 `data-sentence-id`，作为后端调用的目标。
- 当选区跨越多个句子时，浮层禁用所有"句级"操作，只允许取消选区。

### 14.5 实现范围

- 不引入前端框架，仅用原生 JavaScript（约 80 行）。
- 浮层中的"提交"行为复用现有 POST 端点；后端无需为浮层新增控制层。
- 面向单用户场景，不做 IE / 极旧浏览器兼容。

### 14.6 撤销与重标

每个"标记"按钮在选区命中**已标记**对象时变为"取消标记"，避免误标后无法挽回。

| 选区目标   | 当前状态     | 浮层显示                   |
| ------ | -------- | ---------------------- |
| 句子     | unmarked | 标为难句 / 写下我的理解 / AI 分析  |
| 句子     | marked   | 取消标记 / 修改我的理解 / 打开分析面板 |
| 词 / 短语 | 未收录      | 标为生词 / 标为短语 / 标为搭配     |
| 词 / 短语 | 已收录      | 已在卡库 ✓ / 从卡库移除         |

后端新增：

```text
DELETE /mark/sentence/<id>
DELETE /mark/word/<id>
```

为避免破坏 review 历史，删除采用**软删除**：

```sql
ALTER TABLE sentence_cards ADD COLUMN archived_at;   -- NULL = active
ALTER TABLE word_cards     ADD COLUMN archived_at;
```

`archived_at IS NOT NULL` 的卡片从复习队列（§7.5）、相似提醒（§8）、画像统计（§11）中排除；`review_logs` 保留，便于复盘"我为什么误标了它"。

`[新增 2026-06-15]`

### 14.7 "Clear" 按钮语义修正

当前 "Clear" 按钮的实际行为是 `window.getSelection().removeAllRanges()` + `hideToolbar()`——**仅取消文字选区，不触及任何卡片数据**。但用户自然地将其理解为"清除我的标记（黄色高亮）"，造成点击后页面无变化的困惑。

修正：将按钮文案改为 **"Dismiss"**（取消选区），语义准确，不再暗示会删除标记。

### 14.8 跨句选区批量取消标记

**场景**：用户已经掌握了某个难句群，想一次性清除多个句子的黄色高亮，同时保留句子内的词卡下划线。

**当前缺口**：跨句选区（`spans.length > 1`）时，浮层只显示词标记按钮 + "Selection spans sentences" + "Clear"，没有取消难句标记的路径。单句 "Unmark sentence" 按钮只在 `spans.length === 1` 时出现。

**行为设计**：

```text
跨句选区（选中 N 个句子）
  ├── 若选中范围内有已标记句子（M 个）
  │     └── 显示 "Unmark M sentences" 按钮
  │           → 并发 DELETE /mark/sentence/{id}（每个 marked 句子一个请求）
  │           → DOM 乐观更新：移除对应 span 的 .marked / .analyzed / .analyzed-stale class
  │           → 词卡 span（[data-word-card]）不受影响，下划线保留
  │           → 全部请求完成后收起浮层，取消选区
  └── 若选中范围内无已标记句子
        └── 不显示该按钮（无需操作）
```

**词卡保留的原因**：`DELETE /mark/sentence/{id}` 只软删 `sentence_cards` 表（`archived_at`），`word_cards` 是完全独立的表，不受影响。用户在该句子内标记过的生词/短语下划线天然保留，无需额外处理。

**前端实现要点**：

```javascript
// 在 updateToolbar() 的跨句分支中
const markedSpans = spans.filter(s => s.dataset.marked === "1");
unmarkSentencesBtn.hidden = markedSpans.length === 0;
unmarkSentencesBtn.textContent =
  `Unmark ${markedSpans.length} sentence${markedSpans.length > 1 ? "s" : ""}`;
unmarkSentencesBtn.dataset.sentenceIds =
  markedSpans.map(s => s.dataset.sentenceId).join(",");

// 点击处理
const ids = unmarkSentencesBtn.dataset.sentenceIds.split(",").filter(Boolean);
await Promise.all(ids.map(id =>
  fetch(`/mark/sentence/${id}`, { method: "DELETE" })
));
// 乐观更新 DOM
ids.forEach(id => {
  const span = reader.querySelector(`[data-sentence-id="${id}"]`);
  if (!span) return;
  span.classList.remove("marked", "analyzed", "analyzed-stale");
  span.dataset.marked = "0";
});
window.getSelection()?.removeAllRanges();
hideToolbar();
```

`[新增 2026-06-15]`

---
---

## 17. 阅读视图排版（取代数据表样式）

### 17.1 痛点

现行 `/read/<book_id>` 把每个句子渲染为带边框的 `<article class="sentence">` 卡片，前缀显示 `#ID`，主区域宽 1180px，15px 系统无衬线字体、1.5 行高。这是给"数据表 / 管理后台"用的样式，不适合长时间英文阅读。

§14 解决"操作干扰"，本节解决"排版根本不是给人读的"。两节合并才构成 WeChat 读书式体验。

### 17.2 段落渲染（启用既有 paragraphs 表）

`txt_importer` / `epub_importer` 已经把段落写入 `paragraphs` 表，每个 sentence 持有 `paragraph_id`。阅读视图按 `paragraph_id` 分组渲染：

```html
<article class="reader">
  <h1 class="reader-title">{book.title}</h1>
  <h2 class="reader-chapter">Chapter {idx}: {chapter.title}</h2>

  <p class="reader-para">
    <span data-sentence-id="17">Far from being mere ephemeral manifestations...</span>
    <span data-sentence-id="18">Recent neuroimaging paradigm shifts...</span>
  </p>

  <p class="reader-para">
    <span data-sentence-id="19">In this intricate biological milieu...</span>
    ...
  </p>
</article>
```

- 句子边界对用户**不可见**，仅作为 §14 选区映射用。
- 句子 ID 只存在于 `data-sentence-id` 属性，不渲染到正文。
- 句间用一个空格连接，不换行。

### 17.3 排版与字体

```css
.reader {
  max-width: 680px;
  margin: 32px auto 96px;
  padding: 0 16px;
}
.reader-title    { font-size: 28px; margin: 0 0 4px; }
.reader-chapter  { font-size: 16px; color: var(--muted); margin: 0 0 32px; font-weight: 400; }
.reader-para {
  font-family: Georgia, "Source Han Serif SC", "Songti SC", serif;
  font-size: 18px;
  line-height: 1.75;
  margin: 0 0 1.2em;
  color: #1a1a1a;
}
```

理由：

- `max-width: 680px` 落在英文长文阅读舒适带（每行 60–75 字符）。
- 衬线字体 + 1.75 行高 + 18px 是 Kindle / 微信读书的常见组合。
- 中文衬线后备 `Source Han Serif SC`（思源宋体）/ `Songti SC`，便于将来导入中文文本时复用。

### 17.4 卡片移除与标记态可视化

阅读流去卡片化，已标记的内容用**纸书荧光笔风**而不是边框来提示：

```css
[data-sentence-id].marked {
  background: linear-gradient(transparent 60%, #ffe58a 60%);
}
[data-word-card] {
  text-decoration: underline dotted #f59e0b;
  text-underline-offset: 3px;
}
```

- 删除 `.sentence` 容器的 `background / border / padding / margin`，阅读流不再有"卡片感"。
- 已标记为难句的句子加底色高亮。
- 已圈出的生词/短语用橙色点状下划线。

### 17.5 顶部导航与全局样式隔离

- 现有顶部 `nav` 在阅读视图保留，但视觉权重降级（高度收窄、滚动时半透明）。
- 阅读视图主区域**不继承** `main { width: min(1180px, ...) }`，独立用 `.reader { max-width: 680px }` 覆盖。
- 其他页面（`/books` / `/cards` / `/review` / `/profile`）维持当前管理后台样式，不强行套用阅读字体。

### 17.6 移动端

- 阅读视图在屏宽 `<= 780px` 时改用：`padding: 0 20px`、`font-size: 17px`、`line-height: 1.7`。
- §14 浮层在移动端贴底显示，类似 iOS 的 share sheet 样式（避免覆盖正在选中的文字）。

### 17.7 主题（暂缓）

夜间 / 米黄 / 高对比三主题挪到第二版。第一版只做白底黑字，避免主题切换牵动 §14 浮层与高亮色的视觉调试。

### 17.8 阅读进度持久化

单机单用户场景，第一版只持久化到 `localStorage`，不写 DB。

```text
key:   "reader:progress:book:<book_id>"
value: { "chapter_idx": N, "top_sentence_id": M, "ts": ... }
```

- **写入**：滚动停止 300ms 后，记录当前视口顶部最近的 `data-sentence-id`。
- **读取**：访问 `/read/<book_id>` **不带 ********************************************************`chapter`******************************************************** 参数**时回到上次 `chapter_idx`；DOM 渲染完成后用 `getElementById` + `scrollIntoView` 定位到 `top_sentence_id`。
- 显式带 `chapter` 参数时不恢复，让用户能精确跳章。

不做 DB 持久化的理由：跨设备同步在第一版排除（§0）；DB 写入频繁会拖慢阅读体验，`localStorage` 写入是同步零延迟。

`[新增 2026-06-15]`

### 17.9 章节边界连续导航

**目标**：导入书籍进入阅读页后，用户不必回到书籍详情页逐章点击 `Read`。当前章节开头可以跳到上一章节结尾，当前章节结尾可以跳到下一章节开始，形成连续阅读体验。

#### 17.9.1 导航规则

- `/read/{book_id}?chapter={idx}` 渲染当前章节时，同时查询同一本书中 `chapters.idx` 相邻的上一节与下一节。
- `chapters.idx` 继续作为 EPUB spine 阅读顺序和 URL key；`frontmatter` / `chapter` / `appendix` / `backmatter` 都按原书顺序自然串联，不只串联 `section_kind='chapter'` 的正文。
- 当前章节正文顶部提供稳定锚点 `#chapter-start`，正文底部提供稳定锚点 `#chapter-end`。
- 上一节链接指向 `/read/{book_id}?chapter={prev_idx}#chapter-end`，用于到达上一章节结尾。
- 下一节链接指向 `/read/{book_id}?chapter={next_idx}#chapter-start`，用于到达下一章节开头。
- 第一节不显示"上一节"，最后一节不显示"下一节"。

#### 17.9.2 与阅读进度的关系

上下节链接都显式携带 `chapter` 参数，因此不会触发 §17.8 的"不带 `chapter` 参数时恢复 localStorage 进度"逻辑。浏览器原生 hash 滚动负责定位到章节开头或结尾，不需要新增 JavaScript。

从下一节点击"上一节"时，页面加载后会滚动到 `#chapter-end`。随后 §17.8 的滚动停止写入逻辑会把接近章末的 `top_sentence_id` 写回 `localStorage`。这是预期行为：用户下次不带 `chapter` 参数打开本书时，应回到最近实际阅读的位置，而不是回到该章节开头。后续维护时不要把这类章末进度写入当作 bug 修掉。

#### 17.9.3 空章节容错

第一版不跳过空章节，保持 EPUB spine 的忠实阅读顺序。如果相邻 spine 项只有标题、没有段落或 `chapter_blocks`，跳转后会显示现有空章节提示，用户可再次点击上一节 / 下一节继续前进。

后续可优化为：计算 prev/next 时跳过没有 `paragraphs` 且没有 `chapter_blocks` 的章节。但这会让 UI 顺序与 EPUB spine 不完全一一对应，先不纳入本轮实现。

#### 17.9.4 视觉位置

- 上一节 / 下一节导航放在 `.reader` 正文容器内，不放进全局顶部 `nav`。
- 上一节链接放在第一个内容块前；下一节链接放在最后一个内容块后。
- 样式比正文小一号，使用 muted 灰色与轻量边距，避免抢占阅读区焦点。
- 链接文字使用相邻章节的 `_section_label()` 展示，例如 `上一节：Preface`、`下一节：Chapter 2: How Bitcoin Works`。

#### 17.9.5 不做项

- 不改 schema，不新增迁移。
- 不新增 JS 状态机；只依赖普通链接与 hash。
- 不在本轮实现键盘章节导航。`[` 上一节、`]` 下一节这类快捷键留到第二版，与 §0 的"键盘快捷键暂缓"保持一致。

#### 17.9.6 测试要求

- route-level 测试用 `TestClient` 覆盖中间章节同时出现上一节与下一节链接。
- 第一节不出现上一节链接，最后一节不出现下一节链接。
- 上一节链接包含 `#chapter-end`，下一节链接包含 `#chapter-start`。
- EPUB frontmatter 与正文之间按 `chapters.idx` 连续导航，验证不是只在 `section_kind='chapter'` 内跳转。

`[新增 2026-06-16]`

---
---

## 18. 端到端动线与诊断面板

### 18.1 状态图（选中 → 标记 → 诊断 → 复习）

```text
[阅读中]
   │ 选中文本
   ▼
[浮层显示]
   ├── 整句选区
   │     ├── 标为难句     → 立即建 sentence_card → 句子高亮 → 回阅读
   │     ├── 写下我的理解 → 浮层就地展开 textarea（见 18.2）
   │     │                  ├── 仅保存       → 写 user_translation，回阅读
   │     │                  └── 保存并 AI 分析 → 写 user_translation + 异步触发分析（见 18.3）
   │     └── AI 分析      → 右侧推入分析面板
   │           ├── 缓存命中 → 立即渲染
   │           ├── 调用成功 → 写 ai_cache，渲染
   │           └── 调用失败 → 错误提示 + 重试按钮
   │
   └── 片段选区
         └── 标为生词/短语/搭配 → 建 word_card → 词组下划线 → 回阅读
```

### 18.2 译文输入的浮层形态

"写下我的理解"**不跳页、不开模态**。浮层就地变形为输入区：

```
┌────────────────────────────────────────────────────────┐
│ 选中：Far from being mere ephemeral manifestations...  │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 在此输入你的中文理解（可空提交）                   │ │
│ │                                                    │ │
│ └────────────────────────────────────────────────────┘ │
│ [取消]              [仅保存]      [保存并 AI 分析]     │
└────────────────────────────────────────────────────────┘
```

- "仅保存"：写入 `sentence_cards.user_translation`，不触发 LLM 调用，省钱。
- "保存并 AI 分析"：写入译文 + 立即触发诊断 + 推入分析面板（见 18.3）。

### 18.3 分析面板布局

分析面板从屏幕右侧推入，宽 ~360px，主阅读区压缩到 ~480px。**不离开阅读页**：

```
┌──────────────────────────┬──────────────────────────────┐
│ 阅读区                   │ 分析面板                     │
│                          │                              │
│ Far from being mere      │ ── 简化英文 ──              │
│ ephemeral ⟨manifestations│ Cultural artifacts shape ...│
│  of socio-historical⟩... │                              │
│                          │ ── 中文释义 ──              │
│ (悬浮 evidence 行时，    │ 文化产物对大脑施加了...     │
│  对应短语在原文中加底色)│                              │
│                          │ ── 诊断错因 ──              │
│                          │ 🔴 G02 后置定语修饰对象判断│
│                          │   "underpinning" 是后置定语 │
│                          │   修饰 consensus；你的译文  │
│                          │   未体现修饰方向             │
│                          │                              │
│                          │ ── 主干 ──                  │
│                          │ artifacts exert pressure ...│
│                          │                              │
│                          │ [重新分析] [关闭面板]       │
└──────────────────────────┴──────────────────────────────┘
```

- 面板内容来自 `ai_cache` 最新有效记录；显示 `prompt_version` 与 `is_stale` 状态。
- **联动高亮**：鼠标悬浮 `diagnosis_evidence` 某条 → 原文里对应短语加底色。
- 面板可关闭；关闭不丢状态，下次点 "AI 分析" 或点已分析的句子直接复用。

### 18.4 标记状态的视觉编码

每个句子在阅读视图里有 4 种装饰，递进表达"我对它做过什么"：

```text
unmarked         无装饰
marked           黄色荧光笔底色（§17.4）
analyzed         黄色底色 + 左侧 1px 实线蓝条（暗示有 AI 分析可看）
analyzed-stale   黄色底色 + 左侧 1px 虚线蓝条（prompt 版本变了，可重算）
```

点击已 `analyzed` 的句子，浮层第一项变为"打开分析面板"（不重复调用 LLM）。

### 18.5 移动端

屏宽 < 780px：

- 浮层贴底显示（§14.6 已说）。
- 分析面板**全屏覆盖**而非右侧推入；顶部加"返回阅读"按钮。
- 译文输入框占满底部，软键盘弹起时面板自动避让（用 `visualViewport` API）。
- 联动高亮在移动端用**点击**而非悬浮触发。

`[新增 2026-06-15]`

---
---

## 19. 词卡悬浮提示与备注编辑

### 19.1 场景

用户在阅读过程中看到带点状下划线的词/短语（已标为 word\_card），想**点击查看自己之前查阅过的释义或记录的备注**，而不必离开阅读页跳转到 `/cards` 列表。

当前 `word_cards` 表已有 `current_meaning TEXT` 和 `user_note TEXT` 字段，但阅读视图没有读取和展示它们的入口。本节补全这条交互。

### 19.2 数据传递（无额外查询）

阅读视图已经在渲染时加载全章所有 `word_cards`。只需在 `_highlight_word_cards()` 把 `current_meaning` 和 `user_note` 写入 `data-*` 属性：

```html
<span data-word-card="42"
      data-meaning="珊瑚礁"
      data-note="重要生态系统">Coral reefs</span>
```

无新 SQL 查询；字段为空时 `data-meaning=""` / `data-note=""`。

### 19.3 浮层行为（点击已标记词）

点击 `[data-word-card]` span 时，浮层进入**词卡详情模式**，替代默认的"Mark word / Mark phrase"按钮组：

```
┌──────────────────────────────────────┐
│ Coral reefs                          │  ← surface_form，只读
│ ────────────────────────────────────  │
│ 释义  [珊瑚礁________________]       │  ← current_meaning，可编辑
│ 备注  [重要生态系统___________]      │  ← user_note，可编辑
│                                      │
│ [保存]              [从卡片移除]     │
└──────────────────────────────────────┘
```

- 两个字段均为单行 `<input>`，可空。
- "保存"：`PATCH /mark/word/{card_id}` → 更新 `current_meaning` + `user_note`，浮层收起。
- "从卡片移除"：等同现有 `DELETE /mark/word/{card_id}`，移除下划线。
- 点击词以外区域（`selectionchange` 为空）：浮层隐藏，不保存。

### 19.4 后端接口

新增端点：

```
PATCH /mark/word/{card_id}
Body (form): current_meaning=..., user_note=...
```

对应服务函数 `update_word_card_note(db, card_id, current_meaning, user_note)`：

```sql
UPDATE word_cards
SET current_meaning = ?, user_note = ?
WHERE id = ? AND archived_at IS NULL
```

成功返回 `303 See Other` 重定向（与现有 mark 端点一致）；或 AJAX 场景返回 `204 No Content`。

### 19.5 数据流全图

```
点击 [data-word-card] span
  │
  ├── 读 data-meaning / data-note / data-word-card
  │
  ▼
浮层词卡详情模式
  ├── 用户编辑释义/备注
  │   └── 点"保存" → PATCH /mark/word/{card_id} → 204
  │                  → 更新 span 的 data-* 属性（乐观更新）
  │                  → 浮层收起
  │
  └── 点"从卡片移除" → DELETE /mark/word/{card_id}
                      → 移除 span 的 data-word-card 属性及下划线样式
                      → 浮层收起
```

### 19.6 与复习卡的关系

`current_meaning` 和 `user_note` 在 SM-2 复习时已经展示于卡片正面/背面。阅读页的编辑直接写入同一行，复习页实时生效，不存在两套数据。

### 19.7 排除项

- 不做历史版本记录（覆盖写即可）。
- 不做多行富文本——释义和备注都是短字符串，`<input>` 够用。
- AI 查词（调 LLM 自动填 `current_meaning`）挪到第二版。

`[新增 2026-06-15]`

---
---

## 20. 浮层状态机修复与词卡详情入口统一

### 20.1 背景

§19 实现后回归测试发现两个用户可见 bug，已用 Playwright headless 在 `/read/4?chapter=1` 复现（无 JS Console 报错，无 HTTP 错误，纯前端状态机问题）：

**Bug A — 单击已标记词，浮层瞬间消失**

执行链：

1. 用户点击带点状下划线的词（如 `ontological`）
2. `reader.click` 处理器命中 `wordSpan && !hasSelection` → `showWordDetail()` 显示 wordDetail
3. 浏览器随后触发 `selectionchange`（点击移动光标，即使 collapsed 也算变化）
4. `updateToolbar()` 见 `selection.isCollapsed === true` → 调用 `hideToolbar()`
5. `hideToolbar()` 关闭整个 `#selection-toolbar` 并隐藏 wordDetail
6. 用户体验：点击毫无反应

**Bug B — 双击已标记词，wordDetail 与 wordExisting 同时显示**

执行链：

1. 双击的第一次 click 触发：选区尚未建立，`showWordDetail()` 运行，wordDetail 可见
2. 双击建立选区 = 词本身 → `selectionchange` → `updateToolbar()`
3. `updateToolbar()` 走 `spans.length === 1 && activeWordCardId` 分支 → `setVisible(wordExisting, true)`
4. **但全程不调用 \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****`setVisible(wordDetail, false)`**，wordDetail 残留
5. 用户体验：两个面板叠加，存在两组 "Remove from cards" 按钮，操作语义重复

### 20.2 根因

`#selection-toolbar` 内部有 5 个独立 group（`sentenceForm` / `wordForm` / `wordExisting` / `wordDetail` / `crossSentence`），但**没有集中互斥控制**：

- `showWordDetail()` 进入时主动隐藏其他 4 个 group，行为正确。
- `updateToolbar()` 处理选区变化时只管 `sentenceForm` / `wordForm` / `wordExisting` / `crossSentence` 四组，**从不触碰 \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****`wordDetail`**。

并且 `wordDetail` 的入口（`reader.click` 监听器）与 `wordExisting` 的入口（`updateToolbar` 中的 `activeWordCardId` 分支）**职责重叠**：前者要求 "无选区"，后者要求 "选区命中已有词卡"。两种交互路径都指向同一信息（释义/备注/移除），却使用两套不同 UI。

附带小问题：`#toolbar-sentence-form` 与 `#toolbar-word-form` 在 HTML 里缺少默认 `hidden` 属性，初次渲染时若浮层被强制可见，这两个 form 会默认展示。

### 20.3 修复策略：合并 wordExisting 进 wordDetail

不再保留 wordExisting 这条单独的"已在卡片中"路径。**只要选区或点击命中一个已存在的 word\_card，统一显示 wordDetail**。理由：

- wordDetail 是 wordExisting 的超集：除"Remove from cards"按钮外，还提供释义/备注编辑。
- 用户对"已标记词"只有两类需求：查看/编辑笔记、取消标记。一个面板足够。
- 移除冗余 group，状态机分支减少。

### 20.4 状态机统一规则

`#selection-toolbar` 内最多显示一个"主面板"，互斥规则用集中函数实现：

```js
function hideAllPanels() {
  setVisible(sentenceForm, false);
  setVisible(wordForm, false);
  setVisible(wordDetail, false);
  setVisible(crossSentence, false);
  hideTranslationEditor();
}
```

`updateToolbar()` 与 `showWordDetail()` 在显示任何一个 group 之前**必须先调用 \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****`hideAllPanels()`**。

状态判定优先级（自顶向下）：

| 条件                           | 显示                                        |
| ---------------------------- | ----------------------------------------- |
| 选区为空 / collapsed             | （隐藏整个 toolbar）                            |
| `spans.length > 1`（跨句）       | `crossSentence`                           |
| `spans.length === 1` 且整句选中   | `sentenceForm`（含 Mark / Translation / AI） |
| `spans.length === 1` 且命中已有词卡 | **`wordDetail`**                          |
| `spans.length === 1` 且未命中词卡  | `wordForm`（Mark word/phrase/collocation）  |

`reader.click` 处理器对 `[data-word-card]` 的单击保持不变，仍调用 `showWordDetail()`，但需要解决 Bug A。

### 20.5 修复 Bug A：抑制"刚打开 wordDetail 后立即被 selectionchange 关闭"

引入一个一次性抑制标记：

```js
let suppressNextUpdate = false;

function showWordDetail(span) {
  hideAllPanels();
  activeWordDetailCardId = span.dataset.wordCard;
  wordDetailSurface.textContent = span.textContent;
  wordDetailMeaning.value = span.dataset.meaning || "";
  wordDetailNote.value = span.dataset.note || "";
  wordDetailRemove.dataset.cardId = activeWordDetailCardId;
  setVisible(wordDetail, true);
  positionToolbar(span.getBoundingClientRect());
  suppressNextUpdate = true;  // 阻挡紧跟而来的 collapsed-selection 关闭
}

function updateToolbar() {
  if (suppressNextUpdate) { suppressNextUpdate = false; return; }
  if (translationEditorOpen || toolbar.contains(document.activeElement)) return;
  // ... 原有逻辑
}
```

`suppressNextUpdate` 只在点击-显示 wordDetail 这一条路径上设置，影响范围最小。

另一种实现方案：把点击 wordSpan 时的选区主动设为词的范围（`window.getSelection().selectAllChildren(span)`），让后续 `updateToolbar` 走 "选区命中已有词卡" 分支自然显示 wordDetail。**不采用此方案**，因为这会让阅读时点击词变成"选中词"，改变了用户的选区上下文，影响后续多句拖选。

### 20.6 修复 Bug B：updateToolbar 在所有分支入口先 hideAllPanels

```js
function updateToolbar() {
  if (suppressNextUpdate) { suppressNextUpdate = false; return; }
  if (translationEditorOpen || toolbar.contains(document.activeElement)) return;
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    hideToolbar();
    return;
  }
  // ... 计算 spans / activeWordCardId / wholeSentence ...

  hideAllPanels();  // ← 关键：统一收拢所有 group
  if (spans.length > 1) {
    configureCrossSentenceActions(spans);
    setVisible(crossSentence, true);
    showToolbar(range);
    return;
  }
  if (activeWordCardId) {
    // 选区命中已有词卡 → 复用 wordDetail
    const span = reader.querySelector(`[data-word-card="${activeWordCardId}"]`);
    if (span) {
      activeWordDetailCardId = activeWordCardId;
      wordDetailSurface.textContent = span.textContent;
      wordDetailMeaning.value = span.dataset.meaning || "";
      wordDetailNote.value = span.dataset.note || "";
      wordDetailRemove.dataset.cardId = activeWordCardId;
      setVisible(wordDetail, true);
    }
  } else if (wholeSentence) {
    sentenceForm.action = `/mark/sentence/${activeSentenceId}`;
    // ... 配置 Mark / Translation / AI 按钮
    setVisible(sentenceForm, true);
  } else {
    setVisible(wordForm, true);
  }
  showToolbar(range);
}
```

`activeWordCardIds.length > 1`（多选区跨多个词卡）的情况退化为：在 wordDetail 中显示第一个，"Remove from cards" 按钮的 `data-card-id` 仍支持批量传入（保留现有 `wordDelete` 逻辑作为底层调用）。短期可只支持单卡，未来若有需求再扩展。

### 20.7 HTML 默认状态修正

`#toolbar-sentence-form` 与 `#toolbar-word-form` 加默认 `hidden` 属性，避免初始渲染或 toolbar 强制可见时短暂闪现：

```html
<form id="toolbar-sentence-form" method="post" class="toolbar-group" hidden>...</form>
<form id="toolbar-word-form" method="post" action="/mark/word" class="toolbar-group" hidden>...</form>
```

JS 在显示前调用 `setVisible(form, true)` 即可，与现有惯例一致。

### 20.8 删除 wordExisting

移除以下元素及其所有引用：

- HTML `#toolbar-word-existing` 整个 div
- JS 变量 `wordExisting`、`wordDelete`
- JS 中 `setVisible(wordExisting, ...)` 调用
- `wordDelete.addEventListener("click", ...)` 事件

`wordDetail` 中的 "Remove from cards" 按钮（`wordDetailRemove`）承担所有"取消词卡"操作。批量删除（来自跨词选区）若保留，可由 wordDetail 内部读取 `activeWordCardIds` 字段决定按钮文案与行为。

### 20.9 测试用例

新增 Playwright 集成测试 `tests/web/test_reader_toolbar_state.py`（沿用 §15.7 模式，TestClient 启服务，Playwright 驱动）：

| 用例                    | 期望                                                           |
| --------------------- | ------------------------------------------------------------ |
| 加载页面后立即检查             | toolbar hidden；所有 group hidden                               |
| 单击 `[data-word-card]` | toolbar visible；**仅** wordDetail visible，其余 hidden           |
| 双击 `[data-word-card]` | 同上：**仅** wordDetail visible（不应有 wordExisting）                |
| 点击 wordDetail 内"Save" | PATCH 成功，span 的 `data-meaning`/`data-note` 更新，toolbar hidden |
| 拖选跨两句                 | crossSentence visible，wordDetail hidden                      |
| 拖选整句                  | sentenceForm visible，wordDetail hidden                       |
| 拖选未标记词                | wordForm visible，wordDetail hidden                           |
| wordDetail 显示后立即点击空白  | toolbar hidden（验证 `suppressNextUpdate` 不会漏关）                 |

后端测试不变（§19 已覆盖 PATCH 端点）。

### 20.10 排除项

- 不引入正式状态机库（XState 等），用集中函数 + 优先级表足够。
- 不做点击-选词联动（不调用 `selectAllChildren`），见 §20.5 拒因。
- wordDetail 的多卡批量删除若工作量过大可降级为单卡，不阻塞本次修复。
- 词汇 AI 按钮（解释 / 搭配 / 易混）留给后续词汇 AI 分析面板改进（见 §22），本节只修状态机。

`[新增 2026-06-15]`

---
