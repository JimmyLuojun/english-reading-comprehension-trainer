# AI 分析、缓存与 Prompt

本文件保存 AI 响应缓存、输出 schema、prompt 版本、用户译文诊断、provider 配置和词汇分析面板相关设计。

## 5. AI 响应缓存

### 5.1 缓存键

```text
content_hash = SHA256(normalize(sentence_text) + context_window_text)
cache_key    = (content_hash, prompt_version, model)
```

### 5.2 失效策略

**默认：惰性迁移 + 显式重算指令。**

- Prompt 版本升级时**不自动清空旧缓存**。
- 卡片读取时优先用最新 `prompt_version` 的缓存；若无，则用旧版本并在 UI 标记 `stale`。
- 提供 `re-analyze` 命令对单张卡 / 一本书 / 全库强制重算。

**理由**：全量重算贵且不可逆；惰性迁移让用户决定何时花这笔钱。

`[已确认 2026-06-14]`

---
---

## 9. AI 输出 JSON Schema

### 9.1 句子分析

```json
{
  "subject_skeleton": "string",
  "clauses": [
    {"type": "main|relative|noun|adverbial", "text": "string", "role": "string"}
  ],
  "modifiers": [{"target": "string", "modifier": "string", "type": "string"}],
  "logic_markers": [{"marker": "string", "function": "concession|contrast|cause|..."}],
  "anaphora": [{"pronoun": "string", "refers_to": "string"}],
  "simplified_en": "string",
  "chinese_gloss": "string",
  "predicted_error_types": ["G02", "D01"],
  "confidence": 0.0
}
```

### 9.2 词汇分析

```json
{
  "lemma": "string",
  "lexical_type": "word|phrase|collocation",
  "pos": "string",
  "meaning_in_context": "string",
  "common_collocations": ["string"],
  "near_synonyms": ["string"],
  "confusable_with": ["string"],
  "morphology": {"root": "string", "family": ["string"]},
  "predicted_error_types": ["L01"],
  "confidence": 0.0
}
```

### 9.3 校验

- 所有 AI 响应在写入 `ai_cache` 前必须通过 `jsonschema` 校验。
- 校验失败 → 重试一次 → 仍失败则记录原始响应到 `ai_cache.response_json` 但标 `is_valid=false`，不暴露给卡片。

`[已确认 2026-06-14]`

---
---

## 10. Prompt 版本管理

- 所有 prompt 存在 `prompts/` 目录，**版本号写在文件名**（如 `sentence_analysis.v3.md`）。
- 每次启动时同步到 `prompt_versions` 表，`is_active=true` 的为当前生效版本。
- 修改 prompt **必须新建版本号**，禁止原地编辑历史版本。
- 每个版本的修改原因记录在文件头部 frontmatter。

`[已确认 2026-06-14]`

---
---

## 15. 用户译文驱动 AI 诊断（取代纯预测）

### 15.1 痛点

§9.1 的 `predicted_error_types` 是 AI 看着句子结构"猜"普通学习者可能犯什么错，与具体用户的真实理解偏差脱钩。这种"拍脑袋预测"既不准，也无法反映用户的实际薄弱点。

### 15.2 设计原则

**有证据时做诊断，无证据时做预测，二者不混用。**

- 用户提供译文 → AI 根据"原文 vs 用户译文"定位理解偏差，给出**诊断错因**。
- 用户未提供译文 → AI 退回当前预测模式，但结果在 UI 上明确标注为"预测"，仅作为弱信号。

### 15.3 数据模型变更（修订 §1.2）

`sentence_cards` 表新增字段：

```sql
user_translation         -- 用户译文，可空
translation_created_at   -- 译文写入时间，可空
```

不破坏现有数据：旧卡 `user_translation` 为 NULL，AI 分析自动走预测分支。

第一版只存"最新一次"译文，不做历史版本。用户重新提交译文即覆盖旧值，并触发缓存重算（见 §15.4）。

### 15.4 缓存键变更（修订 §5.1）

```text
content_hash = SHA256(
    normalize(sentence_text)
    + context_window_text
    + normalize(user_translation or "")
)
```

同一句话配不同译文 → 不同 `content_hash` → 不共享缓存。这是必须的：诊断结果依赖于译文。

### 15.5 AI 输出 Schema 变更（修订 §9.1）

句子分析输出新增一组字段，与原字段并存：

```json
{
  "...": "（§9.1 原有字段保留）",

  "diagnosis_basis": "predicted | user_translation",

  "diagnosed_error_types": ["G02", "D01"],
  "diagnosis_evidence": [
    {
      "error_type": "G02",
      "evidence": "原文 'the orthodox consensus underpinning evolutionary psychology' 中 underpinning 是后置定语修饰 consensus；用户译文未体现修饰方向。"
    }
  ]
}
```

- `diagnosis_basis = "user_translation"` 时，`diagnosed_error_types` 与 `diagnosis_evidence` 必填，`predicted_error_types` 可空。
- `diagnosis_basis = "predicted"` 时，反之。

`diagnosed_error_types` 是后续画像（§11）与队列优先级（§7.5 错因覆盖度）的**首选信号源**；`predicted_error_types` 只作为退化补充，权重显著低于诊断结果。

**"无错"的表达**：若 AI 判断译文与原文一致，`diagnosed_error_types: []`，并在 `diagnosis_evidence` 中给一条 `error_type: "OK"`（不在 §2 枚举里，仅作肯定信号）。UI 渲染为"理解正确 ✓"，避免必填字段逼 AI 编造错因。

### 15.6 Prompt 分版（修订 §10）

按交互模式拆为两套 Prompt，各自独立版本号管理：

```text
prompts/
  sentence_analysis_predict.v1.md    -- 无译文，预测模式
  sentence_analysis_diagnose.v1.md   -- 有译文，诊断模式
```

诊断版的核心指令是"找出译文与原文之间的具体偏差，归类到 §2 错因封闭枚举；不得编造未在译文中体现的错误"。

`[新增 2026-06-15]`

---
---

## 16. AI Provider 配置

第一版与未来均使用 OpenAI 兼容接口，通过环境变量切换：

```text
OPENAI_API_KEY    — API key
OPENAI_BASE_URL   — endpoint（DeepSeek / OpenAI / Ollama / Azure 等）
TRAINER_MODEL     — 模型名，默认 deepseek-chat
```

**默认 Provider：DeepSeek。** 其 API 与 OpenAI SDK 完全兼容，默认配置为：

```text
OPENAI_BASE_URL=https://api.deepseek.com/v1
TRAINER_MODEL=deepseek-chat
```

现有 `llm_sentence_analyzer.py` / `llm_word_analyzer.py` 无需改动代码即可切换。

`[新增 2026-06-15]`

---
---

## 22. 词汇 AI 分析面板改进

### 22.1 背景与用户反馈

词汇 AI 分析功能实现后通过真实使用发现四个问题（来自 2026-06-15 用户截图反馈）：

1. **原文无高亮**：面板打开后看不出分析的是哪个词，需要在原文中定位被分析词的 span。
2. **错因码不可读**：`L02, L06` 对用户毫无意义，需展开为完整中文描述。
3. **内容结构与学习目标错位**：当前面板是"字典视角"（这个词是什么意思），用户需要的是"写作者视角"（作者为什么用这个词而不用更简单的词）。列出 `near_synonyms` 和 `common_collocations` 的价值不如直接解释 register 差异和用词动机。
4. **面板内无笔记区**：点击"Explain word"后浮层关闭，用户在看完 AI 分析之后无处记录自己的理解——两个动作（读 AI → 写笔记）被割裂。

### 22.2 修复一：原文词汇高亮

**触发**：`renderWordAnalysis(payload)` 调用时。

**行为**：

- 在 reader 中找到 `[data-word-card="{card_id}"]` span（取第一个可见的）。
- 给该 span 加 CSS class `word-analysis-active`（加背景色+轮廓，区别于普通词卡的点状下划线）。
- 面板关闭（`closePanel()`）时移除该 class。

**CSS**：

```css
[data-word-card].word-analysis-active {
  background: #fef9c3;
  border-radius: 2px;
  outline: 2px solid #f59e0b;
  outline-offset: 1px;
}
```

不复用 `analysis-highlight`（那是句子证据高亮，蓝色）；词汇高亮用黄色系，与词卡点状下划线颜色一致，视觉语言统一。

### 22.3 修复二：错因码展开为中文描述

在 JS 中维护一张查找表（与 §2 枚举一致，不依赖后端）：

```js
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
  X00: "X00 其他",
};
```

`renderWordAnalysis()` 和 `renderDiagnosis()`（句子分析错因）都调用同一个展开函数。

### 22.4 修复三：prompt v2——写作者视角

#### 22.4.1 核心问题

v1 prompt 生成的是字典释义视角：

- `meaning_in_context`：这个词在这里是什么意思
- `common_collocations`：这个词常见搭配
- `near_synonyms`：近义词列表

但用户学习目标是：**我已经能理解句子大意，现在想知道作者为什么用这个词而不用更简单的词**。即：

- register（语域）是什么，比 basic/simple 更正式/学术？
- 这个词比近义词多出了哪个蕴含义？
- 如果我下次写作，什么场景该用，替换成简单词后会损失什么？

#### 22.4.2 新 JSON Schema（word\_analysis.v2）

删除 `common_collocations`，合并 `near_synonyms` 和 `confusable_with` 进新字段 `vs_simpler`，增加 `register` 和 `why_this_word`：

```json
{
  "lemma": "<base form>",
  "lexical_type": "<word | phrase | collocation>",
  "pos": "<noun | verb | adjective | adverb | preposition | conjunction | phrase | other>",
  "meaning_in_context": "<1-2 句，精确描述该词在本句语义，不超过 30 词>",
  "register": "<academic | formal | literary | neutral | colloquial | technical>",
  "why_this_word": "<2-4 句：解释作者为何选用此词而非更简单的近义词；重点说明语域差异、蕴含义差异、搭配限制；举 1 个替换成简单词后语义/语感会有何损失的对比>",
  "vs_simpler": [
    {
      "simpler": "<更简单的近义词，如 basic>",
      "difference": "<1-2 句：两者的核心差异>"
    }
  ],
  "morphology": {
    "root": "<拉丁/希腊词根；无则空串>",
    "family": ["<同根词 2-4 个；无则空列表>"]
  },
  "predicted_error_types": ["<1-2 个错误代码>"],
  "confidence": 0.0
}
```

`vs_simpler` 列 1-3 条，代替原来的 `near_synonyms` + `confusable_with` 扁平列表。删除 `common_collocations`（搭配信息已隐含在 `why_this_word` 的对比分析中）。

#### 22.4.3 prompt v2 核心变化

`word_analysis.v2.md` 相对 v1：

- **任务说明**：帮助中国学习者理解"作者为什么选这个词，而不是更简单的近义词"。

- `why_this_word` **Few-shot 示例**示范对比分析：

  > `rudimentary` vs `basic`——rudimentary 属于学术正式语域，专指"处于早期发展阶段、功能尚不成熟"，带有时间/进化维度（evolutionary stage）；basic 是中性通用词，只表示"不复杂"，无发展阶段的蕴含。学术文本用 rudimentary 能精确表达"功能性尚不完整"，替换成 basic 后这层含义消失。

- 删除 `common_collocations` 生成指令。

- `vs_simpler` 要求与 `why_this_word` 呼应，每条 simpler 词来自正文已分析的对比。

#### 22.4.4 版本管理

新文件 `prompts/word_analysis.v2.md`，v1 保留（已有 `ai_cache` 引用 v1）。`prompt_versions` 表新增一行 `is_active=1` 指向 v2。`analyze_word()` 默认使用最新活跃版本。

### 22.5 修复四：面板内用户笔记区

#### 22.5.1 位置与布局

Word Analysis 面板，AI 内容（`#analysis-word-sections`）之后、footer 按钮之前，新增 `#word-panel-notes` section：

```
┌──────────────────────────────────────┐
│ WORD ANALYSIS                        │
│ Word Analysis           [Close panel]│
│ ─────────────────────────────────    │
│ [Meaning in context]                 │
│ [Why this word]                      │
│ [vs. simpler]                        │
│ [Morphology]                         │
│ [Predicted error types]              │
│ ─────────────────────────────────    │
│ My notes                             │
│ Definition  [___________________]    │  ← current_meaning
│ Notes       [___________________]    │  ← user_note
│                            [Save]    │
└──────────────────────────────────────┘
```

#### 22.5.2 数据流

- **预填充**：`renderWordAnalysis()` 时从 `[data-word-card="{card_id}"]` span 读取 `data-meaning` 和 `data-note` 填入输入框，无额外网络请求。
- **保存**：点 Save → `PATCH /mark/word/{card_id}`（已有端点）→ 同步更新 span 的 `data-meaning` / `data-note` → 显示 1.5 秒"Saved ✓"状态提示，不关闭面板。
- **与浮层 wordDetail 的关系**：两处编辑同一字段，保存逻辑相同，数据一致，互不冲突。

#### 22.5.3 新 HTML 元素（纳入 `#analysis-word-sections` 内）

```html
<section id="word-panel-notes" class="analysis-section">
  <h3>My notes</h3>
  <div class="word-notes-fields">
    <label class="word-notes-label">Definition
      <input id="word-panel-meaning" type="text" placeholder="My definition…">
    </label>
    <label class="word-notes-label">Notes
      <input id="word-panel-note" type="text" placeholder="My understanding…">
    </label>
  </div>
  <div class="word-notes-actions">
    <button id="word-panel-save" type="button">Save</button>
    <span id="word-panel-save-status" class="toolbar-status" aria-live="polite"></span>
  </div>
</section>
```

`word-panel-notes` 放在 `#analysis-word-sections` 内部，随 `setWordMode()` / `setSentenceMode()` 自动显/隐，无需单独控制。

### 22.6 实施顺序

1. `word_analysis.v2.md` + `WORD_ANALYSIS_SCHEMA_V2`（`ai_json_schemas.py`）
2. `_analysis_panel()` HTML：新增 `word-panel-notes`；替换 `collocations`/`synonyms` section 为 `why_this_word`/`register`/`vs_simpler` section
3. JS：`ERROR_CODE_LABELS` 查找表；`renderWordAnalysis()` 适配新字段；词汇高亮（`word-analysis-active`）；笔记预填充 + `word-panel-save` 事件
4. CSS：`.word-analysis-active`；`.word-notes-*`
5. 测试：新 schema 校验测试；笔记保存集成测试；`renderWordAnalysis()` 新字段渲染测试

### 22.7 排除项

- 不做笔记历史版本（覆盖写）。
- 不做笔记与 AI `why_this_word` 的对比/评分（留后续）。
- `register` 字段仅展示，不驱动复习队列排序（留后续）。
- 不删除 `word_analysis.v1.md`，已有缓存引用 v1。
- `vs_simpler` 目前只展示，不与复习卡绑定（留后续）。

`[新增 2026-06-15]`

---
