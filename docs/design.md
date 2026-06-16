# 英语阅读理解专项训练系统 — 第 0 步技术设计

> **状态：已全部确认（2026-06-14）。**
> 评审记录：13 节全部 yes。两处偏离默认：
> (1) 复习算法改为 **SM-2**（默认是 Leitner，§7 已重写）；
> (2) §12 文件名改为自解释命名（`db_models.py` / `sentence_segmenter.py` / `sm2_scheduler.py` 等）。
> 下一步：按 §13 顺序开工。

---

## 0. 范围与非范围

**MVP 范围（第一版必做）**

- TXT / EPUB 导入
- 自动拆分 Book → Chapter → Paragraph → Sentence
- CLI 标记难句 / 生词 / 短语
- AI 难句结构化分析（带响应缓存）
- 生词卡 + lemma / 标签 / 原词三种相似提醒
- SM-2 复习队列
- 每 N 张卡生成一次能力画像摘要

**显式排除（第一版不做）**

- Web UI（第 9 步再做）
- PDF / OCR
- 向量检索 / 语义聚类
- 多设备同步
- Kindle / 微信读书 / Apple Books 自动同步
- 多用户（单机单用户）

`[已确认 2026-06-14]`

**增补排除（2026-06-15）**

- 多标签页 / 多客户端实时同步
- 键盘快捷键（Cmd+M 标句等，第二版）
- 字号 / 行距 / 主题切换（夜间 / 米黄 / 高对比）
- EPUB 中的复杂排版级图片 / 公式重建（第一版只按原书顺序展示图片、公式截图与图注）
- 可访问性 (a11y) / 屏幕阅读器适配
- 打印样式

`[新增 2026-06-15]`

---

## 1. 数据模型（SQLite）

### 1.1 表清单

```text
books
chapters
paragraphs
sentences
book_assets
chapter_blocks

sentence_cards
word_cards          -- 含单词与短语（见 §3）
review_logs

tags
error_types
sentence_card_tags
word_card_tags

ai_cache
learner_profile_snapshots
prompt_versions
```

### 1.2 关键字段

```sql
-- 文本层级
books(id, title, author, language, source_format, file_hash, imported_at,
      total_chapters, total_sentences)
chapters(id, book_id, idx, title, sentence_start, sentence_end,
         section_kind, chapter_number)
paragraphs(id, chapter_id, idx, sentence_start, sentence_end)
sentences(id, book_id, chapter_id, paragraph_id, idx,
          text, text_hash, char_offset_start, char_offset_end)
book_assets(id, book_id, source_href, media_type, storage_path,
            sha256, byte_size, alt_text, is_missing)
chapter_blocks(id, book_id, chapter_id, idx, kind,
               paragraph_id, asset_id, text, payload_json)

-- 卡片（SM-2 调度字段：ef / interval_days / repetitions）
sentence_cards(id, sentence_id, created_at, last_reviewed_at, review_count,
               mastery_state, ef, interval_days, repetitions, due_at,
               user_note, ai_analysis_id)
word_cards(id, lemma, surface_form, lexical_type,  -- word | phrase | collocation
           first_sentence_id, current_meaning, pos,
           created_at, last_reviewed_at, review_count,
           mastery_state, ef, interval_days, repetitions, due_at,
           occurrence_count, user_note, ai_analysis_id)

-- 复习（记录 SM-2 算法状态前后值，便于回放与调参）
review_logs(id, card_type, card_id, reviewed_at,
            quality,                                  -- 0-5（见 §7）
            outcome,                                  -- pass | partial | fail（UI 选项）
            ef_before, ef_after,
            interval_before, interval_after,
            repetitions_before, repetitions_after,
            latency_ms)

-- 标签 / 错因（多对多）
tags(id, name, category)              -- 用户自定义
error_types(id, code, name, layer)    -- 见 §2，封闭枚举
sentence_card_tags(card_id, tag_id)
word_card_tags(card_id, tag_id)
sentence_card_errors(card_id, error_type_id)
word_card_errors(card_id, error_type_id)

-- AI 缓存（见 §5）
ai_cache(id, content_hash, prompt_version, model, response_json, created_at)

-- 画像
learner_profile_snapshots(id, created_at, summary_md, payload_json,
                          cards_at_snapshot, sentences_at_snapshot)

-- Prompt 版本
prompt_versions(id, name, version, body_md, created_at, is_active)
```

### 1.3 说明

- `text_hash` 用 SHA256(normalized\_text)；用于跨书去重（见 §4）。
- `paragraphs` / `sentences` 继续作为复习、标注、AI 诊断的句子流；`chapter_blocks` 只补充阅读页的原书顺序和非文本媒体，不把图片塞进 `sentences`。
- `chapter_blocks.paragraph_id` 指向有句子流支撑的块（`prose` / `pre` / `table`），图片和缺失资源块为 `NULL`。
- `book_assets` 只存 EPUB 内资源元数据和文件系统相对路径；实际二进制写入 `data/assets/books/<book_id>/`。
- `mastery_state` 与 SM-2 状态字段并存：`ef / interval_days / repetitions` 是算法状态，`mastery_state` 是衍生标签（new / learning / mature / lapsed），由 `repetitions` 与 `ef` 派生（见 §7.4）。
- `due_at` 直接预计算下次到期，避免每次查询时算。
- `ai_analysis_id` 指向 `ai_cache`，不直接存 JSON 在卡片表里。

`[已确认 2026-06-14]`

---

## 2. 错误标签枚举（封闭表）

**原则**：第一版**封闭枚举**，禁止自由输入。后续根据使用频率增删，但任何时刻都是封闭集。

按"语言加工层"分三层，第一版各层 5–8 个标签：

### 2.1 语法层 `grammar`

```text
G01 长主语识别失败
G02 后置定语修饰对象判断错
G03 嵌套从句边界混乱
G04 倒装 / 强调结构
G05 非谓语动词（分词 / 不定式）作用判断错
G06 省略 / 替代识别失败
G07 平行结构对应失败
```

### 2.2 词汇层 `lexical`

```text
L01 多义词在当前语境的义项判断错
L02 假朋友 / 形近词混淆
L03 搭配（动名 / 形名 / 介词）不熟
L04 词根 / 词族联想不足
L05 习语 / 固定短语未识别
L06 学术词汇陌生
```

### 2.3 篇章层 `discourse`

```text
D01 代词指代对象判断错（it / they / which / that）
D02 让步 / 对比逻辑（while / although / however）误读
D03 因果 / 推论连词误读
D04 信息焦点（主述位）判断错
D05 篇章衔接（this / these / such）回指失败
```

**理由**：这套分类参考 L2 阅读研究中常见的"句法/词汇/篇章"三分。每个标签必须能在卡片上可操作、可统计、可对应到具体的复习题型。

`[已确认 2026-06-14]`

### 2.4 兜底类（增补）

```text
X00 其他（不属于上述三层；必须在 diagnosis_evidence 中说明）
```

- 兜底类**不计入** §7.5 的"top-3 高频错因"优先级，避免被 LLM 滥用为偷懒选项。
- 当 `X00` 在一段时间内反复出现，由开发者人工审视是否需要扩枚举。

`[新增 2026-06-15]`

---

## 3. 词汇卡的类型字段

`word_cards.lexical_type ∈ { word, phrase, collocation }`

- `word`：单词。如 `mitigate`。
- `phrase`：固定短语 / 习语。如 `give rise to`、`no sooner ... than`。
- `collocation`：高频搭配。如 `draw a conclusion`、`heavy rain`。

第一版统一存在 `word_cards` 表，不拆表。`lemma` 字段对 phrase / collocation 存归一化后的"提示形"（小写、去标点、占位符 `...` 代表可变成分）。

`[已确认 2026-06-14]`

---

## 4. 同句跨书去重策略

**默认**：基于 `text_hash` 去重句子内容，但保留多个出处。

- `sentences` 表按出处插入（同一文本可有多行，对应不同 `book_id`）。
- `sentence_cards` 通过 `sentence_id` 关联其中**一个**出处（用户首次标记的那次）。
- 但卡片上展示一个"也出现在"列表，通过 `text_hash` 反查其它出处。

**理由**：用户语境中卡点产生于"读到这本书的这段"，强行合并会丢上下文；但完全不去重会让"相似提醒"误报为新句子。这是折中。

`[已确认 2026-06-14]`

---

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

## 6. EPUB 重复导入的幂等性

**默认：按 ************************************************************`file_hash`************************************************************ 识别同一本书，更新元数据与章节结构，但不动卡片和复习记录。**

- 若 `file_hash` 命中：报告"已存在，是否更新结构？"；用户选更新则重新解析章节并尝试重新绑定 `sentences.text_hash`，绑不上的句子标记为 `orphaned`。
- 若 `file_hash` 不同但 `title + author` 命中：视为新版本，提示用户手动合并。
- 卡片和复习状态**永不因重导丢失**。

`[已确认 2026-06-14]`

---

## 7. 复习算法：SM-2

采用经典 SM-2（Piotr Wozniak）。每张卡持有三个状态：
`ef`（ease factor，默认 2.5，下限 1.3）、`interval_days`、`repetitions`。

### 7.1 状态初始值

```text
ef             = 2.5
interval_days  = 0      （未复习过）
repetitions    = 0
due_at         = created_at   （新卡立刻可进队列）
```

### 7.2 单次复习更新规则

记本次回答 `quality ∈ {0..5}`：

```text
若 quality < 3:
    repetitions   = 0
    interval_days = 1
若 quality >= 3:
    若 repetitions == 0: interval_days = 1
    若 repetitions == 1: interval_days = 6
    否则:                interval_days = round(interval_days * ef)
    repetitions += 1

ef_new = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
ef = max(1.3, ef_new)

due_at = reviewed_at + interval_days 天
```

### 7.3 UI 三选项 → quality 映射

CLI 只暴露三个按钮，内部映射到 SM-2 quality：

```text
pass     → quality = 5
partial  → quality = 3
fail     → quality = 1
```

第一版固定此映射；后续可在 settings 里调整。

### 7.4 mastery\_state 派生规则

`mastery_state` 不存算法状态，纯粹用作 UI 标签与统计分组，按以下规则派生：

```text
repetitions == 0                                       → new
1 <= repetitions <= 2                                  → learning
repetitions >= 3 且 ef >= 2.0 且 interval_days >= 21   → mature
最近一次 review_logs.quality < 3 且原本是 mature       → lapsed
```

### 7.5 每日队列预算与混合

到期卡片若超过预算，按以下规则筛选：

```text
每日上限            40 张（默认）
新卡 / 旧卡比例     10 / 30
句卡 / 词卡比例     1 / 3
错因覆盖度          每个 top-3 高频错因至少 3 张
排序优先级          fail（lapsed）> partial > 高频错因 > 低 ef（难卡） > 旧 due_at
```

`[已确认 2026-06-14]`

---

## 8. 相似提醒分层

**第一版（必做）**

```text
原词匹配        word_cards.surface_form 精确匹配
lemma 匹配      用 spaCy en_core_web_sm 做 lemmatization
标签重合        新句的预测错因标签与旧卡有交集
```

**第二版（暂不做）**

```text
词根 / 词族
近义词 / 易混词
搭配匹配
```

**第三版（远期）**

```text
向量检索
语义聚类
```

**默认使用** `spaCy en_core_web_sm`（约 50MB，纯 CPU，零外部依赖）。
不用 `md / lg / trf`，质量提升不抵其安装复杂度。

`[已确认 2026-06-14]`

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

## 10. Prompt 版本管理

- 所有 prompt 存在 `prompts/` 目录，**版本号写在文件名**（如 `sentence_analysis.v3.md`）。
- 每次启动时同步到 `prompt_versions` 表，`is_active=true` 的为当前生效版本。
- 修改 prompt **必须新建版本号**，禁止原地编辑历史版本。
- 每个版本的修改原因记录在文件头部 frontmatter。

`[已确认 2026-06-14]`

---

## 11. 能力画像生成时机

**默认：每完成 20 张卡片复习 OR 距上次画像超过 7 天，自动生成一次。**

- 生成时只取近 90 天数据。
- 输出到 `learner_profile_snapshots`，保留全部历史快照。
- 在 prompt 压缩时只用**最近一次** snapshot 的 `summary_md`。

`[已确认 2026-06-14]`

---

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

## 13. 开工顺序（确认后开始写代码）

```text
1. 建 SQLite schema + migration（含 §1 全部表）
2. 写错因枚举 seed（§2）和 prompt v1（§10）
3. 实现 TXT 导入 + pysbd 切句
4. 实现 EPUB 导入（ebooklib + BeautifulSoup + pysbd）
5. CLI：列书、读章节、标记难句/生词
6. AI 分析器（含缓存 + JSON 校验）
7. 相似提醒第一层（原词 / lemma / 标签）
8. SM-2 复习队列 + 每日预算
9. 能力画像生成
10. （后续）Streamlit / FastAPI UI
```

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
- **读取**：访问 `/read/<book_id>` **不带 ****************************************************`chapter`**************************************************** 参数**时回到上次 `chapter_idx`；DOM 渲染完成后用 `getElementById` + `scrollIntoView` 定位到 `top_sentence_id`。
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
4. **但全程不调用 \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****`setVisible(wordDetail, false)`**，wordDetail 残留
5. 用户体验：两个面板叠加，存在两组 "Remove from cards" 按钮，操作语义重复

### 20.2 根因

`#selection-toolbar` 内部有 5 个独立 group（`sentenceForm` / `wordForm` / `wordExisting` / `wordDetail` / `crossSentence`），但**没有集中互斥控制**：

- `showWordDetail()` 进入时主动隐藏其他 4 个 group，行为正确。
- `updateToolbar()` 处理选区变化时只管 `sentenceForm` / `wordForm` / `wordExisting` / `crossSentence` 四组，**从不触碰 \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****`wordDetail`**。

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

`updateToolbar()` 与 `showWordDetail()` 在显示任何一个 group 之前**必须先调用 \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****`hideAllPanels()`**。

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

## 21. 语音与发音：浏览器 TTS MVP 与服务端音频缓存

### 21.1 背景与目标

用户需要在词汇学习动线中听到单词、词组、习语的美式发音，首批覆盖以下三个位置：

1. **Cards 页**：`Word/Phrase` 列中的 word / phrase / collocation 可播放发音。
2. **Review Queue 页**：仅 `word` card 的 Prompt 可播放发音；`sentence` card 第一版不加，避免截断句子发音和复习泄题。
3. **Reader 的 Word Analysis 面板**：只给面板标题里的 word / phrase 一个发音按钮，不给 Meaning / Register / Why this word 等分析段落加按钮。

第一版不做阅读正文句子的 hover 发音按钮。正文句子播放属于独立交互，应后续单独设计。

### 21.2 Phase 1：浏览器 TTS MVP

Phase 1 使用浏览器 Web Speech API（`speechSynthesis`）播放发音，不改 SQLite schema，不新增音频文件，不引入外部服务成本。

实现范围：

- 在 `app/web/fastapi_app.py` 增加发音按钮渲染 helper，例如 `<button type="button" data-speak-text="ephemeral">▶</button>`。
- `_word_cards_table()`：在 `Word/Phrase` 单元格渲染发音按钮，播放 `surface_form`。
- `_due_table()`：只在 `item.card_type == CardType.WORD` 时给 Prompt 渲染发音按钮，播放完整 `item.prompt`；sentence card 仅展示文本。
- `_analysis_panel()` / `renderWordAnalysis(payload)`：Word Analysis 面板中的发音按钮播放 `payload.surface_form`，不要从分析段落内容推断发音文本。
- 全局 JS 用事件委托处理 `button[data-speak-text]`，避免每行单独绑定监听。

前端约束：

- 优先选择 `en-US` voice。`speechSynthesis.getVoices()` 首次可能返回空数组，必须监听 `voiceschanged` 后重新选择 voice。
- 每次播放前调用 `speechSynthesis.cancel()`，避免连续点击进入播放队列。
- 仅设置 `utterance.lang = "en-US"` 不足以保证 macOS Safari / Chrome 一定选到美式 voice，应显式按优先级挑选 voice：
  - `Samantha`（macOS）
  - `Google US English`（Chrome）
  - 任意 `lang === "en-US"` 的 voice
  - 最后回退到浏览器默认 voice
- 不承诺"纯正美式"。Phase 1 的 UI 文案只称为 `Play pronunciation` 或 `US pronunciation`。
- 如果浏览器不支持 `speechSynthesis`，按钮应禁用或静默标记不可用，页面不能报错。

### 21.3 Phase 1 测试要求

第一版只做 route-level 测试，不测试真实发音输出：

- Cards 页 HTML 包含 word / phrase / collocation 的 `data-speak-text` 发音入口。
- Review Queue 页只给 word card prompt 渲染 `data-speak-text`，不给 sentence card prompt 渲染。
- Reader Word Analysis 面板包含一个发音按钮入口，并在 `renderWordAnalysis(payload)` 时使用 `payload.surface_form` 设置播放文本。
- 前端 JS 包含 `voiceschanged` voice 选择逻辑和播放前 `speechSynthesis.cancel()`。

### 21.4 Phase 2：服务端音频缓存

如果后续需要稳定、可复现的高质量美式发音，再引入服务端 TTS 缓存。Phase 2 不阻塞 Phase 1。

建议新增 `pronunciation_audio_assets` 表，作为全局发音缓存，不挂 `word_cards` 外键。同一个词在多本书、多个卡片中共用缓存；删除卡片或删除书籍不自动删除音频。

建议字段：

- `id`
- `normalized_text`
- `accent`，例如 `en-US`
- `provider`
- `voice`
- `model`
- `mime_type`
- `duration_ms`
- `byte_size`
- `storage_path`
- `created_at`
- `last_accessed_at`

唯一键：

```sql
UNIQUE(normalized_text, accent, provider, voice, model)
```

音频文件路径不要只使用 `normalized_text` hash。应对完整缓存键计算 hash：

```text
sha256(accent|provider|voice|model|normalized_text)
```

存储路径采用 hash 分级目录，避免单目录文件过多：

```text
data/assets/audio/{hash[0:2]}/{hash}.mp3
```

Phase 2 的路由与服务：

- `app/audio/pronunciation_service.py`：负责文本规范化、查缓存、调用 TTS、写文件、写库。
- `GET /audio/pronunciation/{asset_hash}` 或等价路由：返回缓存音频，更新 `last_accessed_at`。
- UI 优先播放缓存音频；缓存不存在或生成失败时回退 Phase 1 浏览器 TTS。

Phase 2 测试要求：

- 测音频路由 200 / 404。
- 测 `pronunciation_service` 写库 + 写文件。
- 测文本 normalize 边界：大小写、前后标点、重复空格、词组和习语。
- 英式拼写 `colour` 与美式拼写 `color` 第一版不合并，除非后续新增词形归一化规则。
- GC 不自动跟随卡片删除；仅手动触发，或按 `last_accessed_at` 清理长期未访问且超过空间阈值的音频。

`[新增 2026-06-16]`

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

## 23. Cards 页与 Review Queue 信息增强

`[新增 2026-06-15]`

### 23.1 背景

Cards 页的 Word Cards 表目前只有 ID / Word / Type / State / Occ. 五列，用户填写的 Notes（`user_note`）不可见；AI 分析出的 `meaning_in_context` 也无处展示。Review Queue 页的 Answer 列只有 pass/partial/fail 按钮，复习时看不到自己的 note 作为自我核对依据。

### 23.2 Cards 页改动

**Word Cards 表新增三列：**

| 列              | 数据来源                                                                                      | 展示方式                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Notes**      | `word_cards.user_note`                                                                    | 明文；未填则显示 `—`；若历史数据中与 Definition/AI meaning 完全相同则视为空，避免自动内容伪装成用户笔记 |
| **AI Meaning** | `ai_cache.response_json → $.meaning_in_context`（通过 `word_cards.ai_analysis_id` LEFT JOIN） | `▶ Reveal` 触发 hover/focus 浮层；无分析则显示 `—`，不撑开表格行高 |
| **Source**     | `word_cards.first_sentence_id → sentences / chapters / books`                             | 链接到该词卡第一次出现的正文句子：`/read/{book_id}?chapter={chapter_idx}#sentence-{sentence_id}`；旁边已有 Occ. 列计数 |

**`list_word_cards`**\*\* SQL 改动（无 schema 迁移）：\*\*

```sql
SELECT wc.*,
       b.title  AS first_book_title,
       s.id     AS source_sentence_id,
       s.book_id AS source_book_id,
       c.idx    AS source_chapter_idx,
       s.text   AS source_sentence_text,
       json_extract(ac.response_json, '$.meaning_in_context') AS ai_meaning
FROM word_cards wc
LEFT JOIN sentences s  ON s.id  = wc.first_sentence_id
LEFT JOIN chapters  c  ON c.id  = s.chapter_id
LEFT JOIN books     b  ON b.id  = s.book_id
LEFT JOIN ai_cache  ac ON ac.id = wc.ai_analysis_id
WHERE wc.archived_at IS NULL
ORDER BY wc.occurrence_count DESC, wc.created_at DESC
LIMIT ? OFFSET ?
```

**关于"所有出现书籍"的分期策略：**

- **本期（§23）**：Source 列显示 "first seen in《书名》"（`first_sentence_id` 路径），并可点击跳转到第一次出现的正文句子；Occ. 列继续显示总次数。
- **后期（留 §25+）**：新增 `word_card_occurrences(word_card_id, sentence_id)` junction 表，每次在阅读器高亮词汇时写入；Source 列升级为所有出现位置的书名 / 章节 / 句子列表。

### 23.3 Review Queue 页改动

**数据层：**

- `_word_due_sql()` 加 `wc.user_note AS answer`，并且当 `user_note` 与 Definition/AI meaning 完全相同时不显示，避免自动填充内容伪装成用户 note
- `_sentence_due_sql()` 加 `COALESCE(sc.user_translation, '') AS answer`
- `_word_due_sql()` 对 word / phrase / collocation 额外 join `sentences / chapters / books`，按 `wc.first_sentence_id` 取第一次出现来源
- `ReviewQueueItem` 加字段 `answer: str = ""`、`source_book_title: str = ""`、`source_href: str = ""`（冻结 dataclass 需设默认值，向后兼容）

**UI 层：**

- Answer 列改为：先 `▶ Reveal` hover/focus 浮层展示 Your note / AI meaning，再跟 pass/partial/fail 按钮；浮层绝对定位，不参与表格布局，不改变行高
- 若 `answer` 和 `ai_meaning` 都为空则只显示按钮（兼容尚未填写 Notes 且尚无 AI analysis 的卡片）
- word / phrase / collocation 的 Prompt 保留发音按钮，同时让词条文本可点击跳转到来源正文；sentence card prompt 不加词汇来源链接

无 schema 迁移，全部为查询与 UI 层改动。

### 23.4 Cards / Review 到来源正文跳转

`[增补 2026-06-16]`

**目标**：在 Cards 页和 Review Queue 页，点击需要掌握的陌生单词、词组或习语，应能返回到它所在来源的正文。第一版默认返回该词卡第一次出现的位置，即 `word_cards.first_sentence_id`。

**统一跳转规则：**

```text
source_href = /read/{source_book_id}?chapter={source_chapter_idx}#sentence-{source_sentence_id}
```

- `source_book_id` 来自 `sentences.book_id`。
- `source_chapter_idx` 来自 `sentences.chapter_id → chapters.idx`，继续使用现有 reader URL key。
- `source_sentence_id` 使用 `word_cards.first_sentence_id`，与阅读页现有 `id="sentence-{id}"` 锚点一致。
- 若历史数据异常导致来源句子或章节缺失，UI 退化为纯文本书名或 `—`，不渲染坏链接。

**页面行为：**

- **Cards 页**：`Word/Phrase` 列或 `Source` 列均可作为入口；发音按钮必须仍是独立按钮，不能包进链接，避免点击播放时触发跳转。
- **Review Queue 页**：只对 `CardType.WORD` 的 prompt 渲染来源链接；sentence card prompt 保持纯文本，避免复习难句时产生额外导航干扰。
- 跳入 Reader 后由浏览器原生 hash 定位到 `#sentence-{id}`。阅读页给 `.reader-sentence` 设置 `scroll-margin-top`，并用 `:target` 或等价 class 高亮目标句子，帮助用户确认来源。

**不做项：**

- 本轮不追踪所有出现位置；`occurrence_count` 仍只表示累计次数。
- 本轮不新增 `word_card_occurrences` 表。等后续需要“查看所有出处”时再做 junction 表与多来源列表。

### 23.5 影响文件

| 文件                                                                                             | 改动类型                                |
| ---------------------------------------------------------------------------------------------- | ----------------------------------- |
| `app/cards/word_card_service.py` — `list_word_cards`                                           | 加来源句子、章节、书籍字段                       |
| `app/review/daily_review_queue.py` — `_word_due_sql` / `_sentence_due_sql` / `ReviewQueueItem` | 加 `answer` 与来源字段                    |
| `app/web/fastapi_app.py` — `_word_cards_table` / `_due_table` / CSS                            | UI 渲染                               |
| `tests/cards/test_word_card_service.py`                                                        | 验证新列                                |
| `tests/review/test_daily_review_queue.py`                                                      | 验证 `answer` 与来源字段                   |
| `tests/web/test_fastapi_app.py`                                                                | 验证 Cards / Review 来源链接与 Reader 目标高亮 |

---

## §24 Cards Notes 内联编辑、Review Reveal AI 含义、EPUB 导入接入

### §24.1 Cards 页 Notes 内联编辑

**目标**：用户可在 Cards 表格中直接编辑 Notes 列。Notes 只写入 `word_cards.user_note`，不把 Definition（`current_meaning`）或 AI meaning 自动填进去。

**方案**：JavaScript 内联编辑 + 复用已有 `PATCH /mark/word/{card_id}` 端点

渲染变更（`_word_cards_table`）：

```html
<!-- 旧 -->
<td>处于原始且简单的状态的事物</td>

<!-- 新 -->
<td>
  <span class="note-text" data-card-id="7">我的笔记</span>
  <button class="note-edit-btn" aria-label="edit notes">✎</button>
  <input class="note-input hidden" data-card-id="7" data-current-meaning="..." value="我的笔记">
</td>
```

JS 行为（注入到页面 `<script>` 末尾）：

- 点击 `.note-text` 或 `.note-edit-btn` → 隐藏 span+button，显示 input 并 focus
- `blur` 或 Enter → `PATCH /mark/word/{card_id}` with `user_note=<value>` and existing `current_meaning` → 成功后更新 span 文本，恢复显示
- Escape → 放弃编辑，恢复原值

不需要新后端端点。

### §24.2 Review Queue Reveal 也展示 AI 含义

**目标**：复习时 Reveal 区域除用户 note 外，也显示 AI 分析出的 `meaning_in_context`；Reveal 和 Cards 页 AI Meaning 都使用 hover/focus 浮层，避免向下展开导致表格单元格位置变化。

**变更点**：

1. `ReviewQueueItem` 增加字段：

   ```python
   ai_meaning: str = ""
   ```

2. `_word_due_sql()` 增加 JOIN：

   ```sql
   LEFT JOIN ai_cache ac ON ac.id = wc.ai_analysis_id
   ```

   新增列：

   ```sql
   COALESCE(json_extract(ac.response_json, '$.meaning_in_context'), '') AS ai_meaning
   ```

3. `_sentence_due_sql()` 补占位列：

   ```sql
   '' AS ai_meaning
   ```

4. `_item_from_row()` 填入：

   ```python
   ai_meaning=row.get("ai_meaning") or "",
   ```

5. `_review_answer_cell()` Reveal 浮层显示两段（各有内容才显示）：

   ```
   ▶ Reveal
     Your note:       我的易混备注
     AI meaning:      existing in or relating to an early stage of development
   ```

6. `_ai_meaning_cell()` 在 Cards 页渲染 `▶ Reveal` hover/focus 浮层，显示 `ai_meaning`，不使用 `<details>`，与 Review 的入口文案保持一致。

### §24.3 EPUB 导入完整性修复与 Web 层接入

**目标**：Import 页面支持 `.epub` 上传；CLI 和 Web 导入都能完整解析真实 EPUB，尤其是 iBooks 展开的 `.epub` 目录包，并避免丢失列表、代码块、术语表、表格等非 `<p>` 内容。

**已确认问题**：

- iBooks 本地书库中的 `Mastering Bitcoin.epub` 是目录包，内部包含 `META-INF/`、`mimetype`、`OEBPS/`，不是普通 ZIP 文件。当前 `import_epub()` 先调用 `Path.read_bytes()` 计算 hash，再调用 `ebooklib.epub.read_epub()`，两者都不能直接处理目录包。
- `_extract_paragraphs()` 当前逻辑是 `p_tags if p_tags else soup.find_all(_BLOCK_TAGS)`。只要某个 HTML 文件存在 `<p>`，同文件内的 `<li>`、`<dt>`、`<dd>`、`<pre>`、表格、图注等可见文本都会被跳过。
- `_MIN_PARA_LEN = 20` 会过滤短 `<dt>` 术语标题；如果不与对应 `<dd>` 合并，术语表会缺项。
- Web 层当前对 TXT 和 EPUB 共用 10 MB 上限，并使用 `await file.read()` 一次性读入内存。若提高 EPUB 上限，必须同时改成流式写临时文件。

#### §24.3.1 EPUB 源文件归一化

**决策**：支持 iBooks 目录包时，不手写 OPF/spine 解析层；检测到目录包后先打包成 deterministic 临时 EPUB ZIP，再复用现有 ebooklib 解析路径。

原因：

- 继续让 ebooklib 负责 EPUB metadata、manifest、spine、TOC 等标准解析，降低自写 OPF 解析的边界风险。
- 目录包只是存储形态不同，正文结构仍是 EPUB；归一化为 ZIP 后可以复用现有测试和导入流程。

实现要求：

- 新增源文件准备函数，例如 `_prepare_epub_source(file_path) -> PreparedEpubSource`：
  - 普通文件：直接使用原路径，`file_hash = sha256(file_bytes)`。
  - 目录包：校验存在 `META-INF/container.xml` 和 `mimetype`，打 deterministic 临时 ZIP，后续传给 `ebooklib.epub.read_epub()`。
- deterministic ZIP 规则：
  - `mimetype` 必须作为第一项写入，并使用 `ZIP_STORED`。
  - 其他文件按相对路径字典序写入。
  - 固定 `ZipInfo.date_time`、权限位、压缩方式，避免同一目录包每次生成不同 hash。
  - `file_hash` 使用 deterministic ZIP 字节 hash，或使用等价的稳定目录 hash（按相对路径排序，hash `path + bytes`）；二者必须在重复导入时稳定。
- `DuplicateBookError` 和 `_lookup_book_id_by_hash()` 必须使用同一套 hash 规则，避免目录包和上传 ZIP 的重复识别不一致。
- 临时 ZIP 在 import 结束后清理。

#### §24.3.2 正文块抽取策略

**决策**：把 `_extract_paragraphs()` 从“优先 `<p>`”改为“按 DOM 阅读顺序抽取可见文本块”。

抽取范围：

- prose：`p`、`blockquote`
- lists：`li`
- definition lists：`dt + 后续一个或多个 dd` 合并成一个块
- code：`pre` / 代码块，整块保留
- tables：优先按 `<tr>` 行级拼接单元格；必要时整表作为一个块，避免按 `td/th` 产生大量短碎片
- captions：`figcaption`、`caption`

去重规则：

- 遍历 DOM 时避免同时抽父块和子块。典型例子：`<div><p>...</p></div>` 只能产生一个段落。
- 已抽取节点的后代不再重复抽取；父节点只有在没有可抽取子块时才作为 fallback。
- 移除 `script`、`style`、`nav`、`aside`、`head` 等非正文区域。

切句规则：

- 普通 prose 块继续走 `segment_sentences()`。
- `pre`、代码块、表格块不走句子切分，作为一个完整块插入，避免代码和表格被 pysbd 切碎。
- 可用内部数据结构表达块类型，例如 `TextBlock(kind="prose" | "pre" | "table", text=...)`；数据库 schema 可以暂不变，仍写入 `sentences` 表，但插入逻辑按 `kind` 决定是否切句。

#### §24.3.3 Web 上传路径

**决策**：TXT 和 EPUB 使用不同上限，并把文件上传改成流式落盘。

建议：

- pasted text：继续使用 10 MB 上限。
- TXT 文件：可继续使用 10 MB 或单独设置更高上限。
- EPUB 文件：提高到 100 MB 或 200 MB；这是压缩包总大小，不代表正文大小。

实现要求：

- 不再对 EPUB 使用 `await file.read()` 一次性读入内存。
- `UploadFile` 分块读取并写入 `tempfile.NamedTemporaryFile` 或 `SpooledTemporaryFile`，边读边统计字节数，超过上限立即停止并返回 413。
- EPUB 上传完成后调用 `import_epub(db, tmp_path, ...)`；重复导入时用 importer 计算出的稳定 hash 查找已有书。
- Import 表单保留 `accept=".txt,.epub"`，说明文字使用 “TXT or EPUB”。

#### §24.3.4 既有导入数据修复

修复 importer 后，旧书不会自动补全内容，需要重导。

重导 `Mastering Bitcoin` 之前必须先确认没有引用：

```sql
SELECT COUNT(*)
FROM sentence_cards sc
JOIN sentences s ON s.id = sc.sentence_id
WHERE s.book_id = :book_id;

SELECT COUNT(*)
FROM word_cards wc
JOIN sentences s ON s.id = wc.first_sentence_id
WHERE s.book_id = :book_id;

SELECT COUNT(*)
FROM review_logs rl
JOIN sentence_cards sc ON sc.id = rl.card_id AND rl.card_type = 'sentence'
JOIN sentences s ON s.id = sc.sentence_id
WHERE s.book_id = :book_id;

SELECT COUNT(*)
FROM review_logs rl
JOIN word_cards wc ON wc.id = rl.card_id AND rl.card_type = 'word'
JOIN sentences s ON s.id = wc.first_sentence_id
WHERE s.book_id = :book_id;
```

- 四项均为 0：可删除旧 book 及其章节/段落/句子后重导。
- 任一项不为 0：不能直接删除；应按 §6 的重导幂等策略，通过 `text_hash` 迁移或重新绑定卡片与复习记录。

#### §24.3.5 EPUB 章节编号与阅读顺序

**决策**：把 EPUB spine 的阅读顺序和正文 “Chapter N” 编号拆开保存，避免 frontmatter/backmatter 消耗正文章节号。

原因：

- iBooks 会把 `Praise for Mastering Bitcoin`、`Preface`、`Quick Glossary` 等放在阅读顺序中，但不会把它们算作 Chapter 1。
- 当前 schema 只有 `chapters.idx`，同时承担阅读顺序和显示编号，导致 `Praise for Mastering Bitcoin` 被渲染成 `Chapter 1`。
- EPUB 顶层 TOC 和正文 HTML 通常带有足够语义：`epub:type="preface"`、`epub:type="chapter"`、`epub:type="appendix"`、`epub:type="index"` 等。

实现要求：

- `chapters.idx` 保持阅读顺序和 URL 键，不改成正文编号。
- 新增 `chapters.section_kind`：`frontmatter | chapter | appendix | backmatter`。
- 新增 `chapters.chapter_number`：仅对 `section_kind='chapter'` 写入正文编号；frontmatter、appendix、backmatter 为 `NULL`。
- `books.total_chapters` 表示正文 `chapter` 数量，不再表示 spine 文档总数。
- 默认打开 `/read/<book_id>` 或书籍详情页主按钮时跳到第一条 `section_kind='chapter'`；frontmatter 仍可从目录表点击阅读。
- TOC 标题映射只能使用文件级/顶层 TOC 项，不能让同一 HTML 文件里的 fragment 子目录项覆盖章节标题。例如 `ch01.html#sending_receiving` 不应覆盖 `ch01.html` 的 `1. Introduction`。

#### §24.3.6 测试要求

新增或更新 `tests/importers/test_epub_importer.py`：

- 普通 ZIP EPUB 仍可导入。
- iBooks 风格展开目录包可导入，并且复用 ebooklib 路径。
- 混合块 HTML：`p + li + dt/dd + pre + table + figcaption` 按阅读顺序入库。
- 父子嵌套去重：`<div><p>...</p></div>` 不重复生成段落。
- `dt + 多 dd` 合并正确。
- `pre`/代码块不被切句。
- 表格按行级或整表保留，不产生无意义短碎片。
- frontmatter 不消耗正文 Chapter 1 编号。
- 同一 HTML 文件里的 nested TOC fragment 不覆盖顶层章节标题。

新增或更新 Web 测试：

- `.epub` 上传走流式临时文件路径。
- EPUB 和 pasted text 的大小上限分别生效。
- 超限 EPUB 返回 413，不留下临时文件。
- 书籍详情页主按钮和 `/read/<book_id>` 默认进入第一正文章，而不是 frontmatter。

#### §24.3.7 EPUB 图片与阅读块保留

**目标**：EPUB 导入不仅保留文本，还要把书中原有图片、公式截图、图表截图和图注按 DOM 阅读顺序呈现在阅读页，帮助理解正文；同时不污染句子级哈希、SM-2 调度和复习队列。

**第一版边界**：

- 支持 `<img>`、`<figure>`、`<figcaption>` 和图片类 manifest 资源。
- 现有 `prose` / `pre` / `table` 文本块继续写入 `paragraphs` / `sentences`；同时映射为 `chapter_blocks`，用于阅读页按原顺序插入媒体。
- 第一版不追求 EPUB CSS 级 1:1 表格/图片布局；表格仍按现有文本块处理，复杂表格版式留到后续迭代。
- 公式图先按普通图片保存；若有 `alt`，写入资产元数据和 block payload，便于后续迁移到 MathML/KaTeX。

**Schema**：

```sql
book_assets(
  id, book_id, source_href, media_type, storage_path,
  sha256, byte_size, alt_text, is_missing
)

chapter_blocks(
  id, book_id, chapter_id, idx, kind,
  paragraph_id, asset_id, text, payload_json
)
```

- `kind` 第一版取值：`prose | pre | table | image | figure | missing_asset`。
- `paragraph_id` 对 `prose` / `pre` / `table` 可非空，因为它们仍对应句子流；`image` / `figure` / `missing_asset` 为 `NULL`。
- `asset_id` 对真实图片或缺失图片引用非空；纯文本块为 `NULL`。
- `text` 存图注、alt 或缺失资源提示；`payload_json` 存轻量结构化信息，例如 `source_href`、`alt`、`caption`。

**导入规则**：

- `_extract_text_blocks()` 升级为块抽取模型，继续复用 DOM 顺序遍历和 consumed 去重。
- `<figure>` 作为一个整体 block：提取第一张 `<img>`、`figcaption`、`alt`，并 consume 整个 figure，避免图注再作为独立 prose 段重复导入。
- 独立 `<img>` 作为 `image` block；无图注时使用 `alt` 作为辅助文本。
- EPUB href 解析必须相对当前 XHTML 文件目录，去除 fragment 并 URL decode，禁止路径穿越。
- iBooks 目录包中由缺失 manifest 资源生成的 stub，导入时要写 `book_assets.is_missing=1` 和 `missing_asset` block，不把 0 字节文件复制进最终 assets 目录。
- 真实图片写入临时 staging 目录；DB transaction 成功后再移动到 `data/assets/books/<book_id>/`。导入失败或 DB rollback 时清理 staging，避免半成品文件。

**阅读页规则**：

- 阅读页优先读取 `chapter_blocks`；如果旧书没有 block 数据，fallback 到当前按 `sentences -> paragraphs` 渲染。
- 文本块仍渲染为带 `data-sentence-id` 的句子 span，保持选中标句、标词、AI 诊断逻辑不变。
- `image` / `figure` 渲染为 `<figure>` + `<img>` + `<figcaption>`；图片最大宽度 100%，保持原比例。
- `missing_asset` 渲染为轻量占位提示，明确资源在源 EPUB 中缺失，而不是导入器漏抽。

---

## §25 删除导入材料（彻底删除 + 词卡 re-anchor）

### §25.1 背景

`books` 表同时承载 TXT 文章和 EPUB 书籍。当前没有任何删除入口，用户误导入或不再需要的材料只能用脚本手工清理，会留下 `chapters/paragraphs/sentences/sentence_cards/word_cards/review_logs/book_assets/chapter_blocks` 以及磁盘上的 EPUB 图片资源。

本节定义"从 Books 页删除一本书"的语义为**彻底删除**，而不是从列表隐藏。

### §25.2 设计原则

1. **句卡跟着书走**：`sentence_cards` 与某本书的具体句子强绑定，书没了卡就没了，复习历史一并清空。
2. **词卡尽量保留**：`word_cards` 按 `lemma` UNIQUE，可能在多本书中复习过。删书时优先把 `first_sentence_id` 迁移到剩余书中包含同一 lemma/短语的句子，**仅当再也找不到锚点时才删除**。
3. **可迁移词卡的 SM-2 状态与 `review_logs` 必须保留**，不允许在 re-anchor 之前粗暴删 `review_logs`。
4. **AI 缓存不动**：`ai_cache` 按 `content_hash` 跨书共享，删书时保持原状，`sentence_cards.ai_analysis_id` 已经是 `ON DELETE SET NULL`，自然无悬挂。
5. **磁盘资源跟在 DB 之后**：先在事务内完成 DB 删除，commit 之后再 `shutil.rmtree(..., ignore_errors=True)` 删 EPUB asset 目录。文件清理失败不回滚 DB。

### §25.3 UI

Books 列表表 (`/books`) 增加 `Actions` 列，每行一个 Delete 表单：

```html
<form method="post" action="/books/{book_id}/delete" class="inline">
  <button class="danger"
          onclick="return confirm('Delete this book and all related sentence cards? Word cards that also appear in other books will be kept and re-anchored.')">
    Delete
  </button>
</form>
```

- 仅在列表页提供 Delete，详情页 `/books/{book_id}` **不**加二级入口，避免误点。
- 删除成功后 `302 → /books`；book 不存在返回 404 错误页。

### §25.4 后端路由

```python
@web_app.post("/books/{book_id}/delete")
def delete_book(book_id: int) -> Any:
    db = db_factory()
    result = _delete_book(db, book_id)
    if result is None:
        return _error_page("Book not found", status_code=404)
    _purge_book_assets_dir(db, book_id)  # commit 之后，错误吞掉
    return _redirect("/books")
```

返回值 `result` 暴露统计信息用于日志：`sentence_cards_deleted`、`word_cards_reanchored`、`word_cards_deleted`、`review_logs_deleted`。

### §25.5 删除流程（单事务）

外键 `word_cards.first_sentence_id ON DELETE RESTRICT` 决定了不能直接 `DELETE FROM books`，必须先处理词卡。流程严格按下列顺序：

1. **确认存在**：`SELECT id FROM books WHERE id = ?`，不存在直接返回。
2. **删句卡复习日志**：

   ```sql
   DELETE FROM review_logs
   WHERE card_type = 'sentence'
     AND card_id IN (
       SELECT sc.id FROM sentence_cards sc
       JOIN sentences s ON s.id = sc.sentence_id
       WHERE s.book_id = ?);
   ```

   `sentence_cards / sentence_card_tags / sentence_card_errors` 不需要显式删，会随 `sentences` → `sentence_cards` 的 cascade 自动消失。

3. **查出该书锚定的所有词卡**：

   ```sql
   SELECT wc.id, wc.lemma, wc.surface_form, wc.lexical_type
   FROM word_cards wc
   JOIN sentences s ON s.id = wc.first_sentence_id
   WHERE s.book_id = ?;
   ```

4. **尝试 re-anchor**（在 Python 里逐张做，不在 SQL 里用 `instr` 模糊匹配）：
   - 拉出**其他书**的候选句子集合（懒加载，按需 `SELECT id, text FROM sentences WHERE book_id != ?`）。
   - 匹配规则：
     - `lexical_type='word'`：在候选句子上做 token 切分，命中 `surface_form` 或 `lemma`（大小写不敏感，词边界严格），返回第一个匹配的 `sentence_id`。
     - `lexical_type='phrase' / 'collocation'`：把候选句子和 `surface_form` 各自 `re.sub(r'\s+', ' ', s.strip().lower())` 规范化后做包含匹配。
   - 命中：`UPDATE word_cards SET first_sentence_id = ? WHERE id = ?`，归入"保留集合"。
   - 未命中：归入"待删除集合"。

   > 注：不使用 `instr(lower(text), lemma)`，因为 `cat` 会误中 `education`、`concatenate`；短语也需要规范化空白后做包含匹配。

5. **仅对"待删除集合"删 `review_logs`**：

   ```sql
   DELETE FROM review_logs
   WHERE card_type = 'word'
     AND card_id IN (...待删除 word_card_ids...);
   ```

   保留集合的 `review_logs` 一律不动。

6. **删"待删除集合"的词卡**：

   ```sql
   DELETE FROM word_cards WHERE id IN (...);
   ```

   `word_card_tags / word_card_errors` 随 `word_cards` cascade。

7. **删 book**：

   ```sql
   DELETE FROM books WHERE id = ?;
   ```

   `chapters / paragraphs / sentences / book_assets / chapter_blocks` 全部走 cascade。

8. **commit**。

9. **清理磁盘**（事务外）：

   ```python
   shutil.rmtree(data_dir / "assets" / "books" / str(book_id), ignore_errors=True)
   ```

   失败仅记录日志，不回滚。

### §25.6 不变量

- `ai_cache` 行数前后不变。
- 其他书的 `sentences / sentence_cards / word_cards / review_logs` 不受影响。
- 可迁移词卡删书前后 `ef / interval_days / repetitions / review_count / due_at / archived_at / user_note / current_meaning` 完全一致，仅 `first_sentence_id` 变化。
- 可迁移词卡对应的 `review_logs` 一行不少。
- 待删除词卡的 `review_logs` 全部清空，其他书的同类 `review_logs` 不受影响。

### §25.7 测试要求（`tests/web/test_fastapi_app.py` 等）

外键约束依赖 `PRAGMA foreign_keys = ON`，测试必须走真实 `db_factory()`，不允许 mock DB。

必须覆盖：

1. **404**：删不存在的 book 返回 404。
2. **UI**：Books 列表渲染 `Delete` 按钮和 `POST /books/{id}/delete` 表单；删除后 302 到 `/books`。
3. **TXT 完整链**：删 TXT book 后，`books / chapters / paragraphs / sentences / sentence_cards / sentence_card_tags / sentence_card_errors` 涉及该书的行清零。
4. **EPUB 资源**：删 EPUB book 后，`book_assets / chapter_blocks` 清零；`data/assets/books/{book_id}/` 目录被删；目录不存在或权限错时 DB 已提交不回滚。
5. **review_logs 隔离**：删 book A 不影响 book B 的句卡/词卡 `review_logs`。
6. **ai_cache 保留**：删 book 前后 `SELECT COUNT(*) FROM ai_cache` 不变。
7. **多书隔离**：两本书各有句卡词卡，删其一不影响另一本任何表的数据。
8. **词卡 re-anchor 成功**：词卡 anchor 在 book A，lemma 在 book B 中以 surface 形式出现 → 删 A 后词卡仍在，`first_sentence_id` 指向 B 的句子；`review_logs` 一行不少；SM-2 字段不变。
9. **词卡 re-anchor 失败 → 删除**：词卡 anchor 在 book A，其他书无此 lemma → 删 A 后词卡和它的 `review_logs` 全部清空，但其他书的 `review_logs` 不受影响。
10. **短语 re-anchor**：`lexical_type='phrase'` 的卡，其他书句子中以不同空白形式出现同一短语 → 能命中并迁移。
11. **词边界严格性**：`lemma='cat'`，其他书只出现 `education` / `concatenate` → 不命中，按未命中处理。

### §25.8 排除项

- 不做"软删除/回收站"。删除就是物理删除。
- 不导出书的备份。用户应在删除前自行 `cp data/reading_trainer.db` 或走现有 `data/reading_trainer.before-*.db` 备份机制。
- 不引入新迁移文件，不改任何 schema。本节只新增路由、删除流程函数、测试和模板片段。
- 不在详情页 `/books/{id}` 加 Delete 入口（一处入口足够，避免误操作面）。

---

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

## 评审清单

请对以下小节标 `yes` / `no` / 改：

- [x] §0 范围
- [x] §1 数据模型
- [x] §2 错误标签枚举
- [x] §3 词汇卡类型
- [x] §4 跨书去重
- [x] §5 AI 缓存失效
- [x] §6 EPUB 重导幂等
- [x] §7 SM-2 参数与队列预算
- [x] §8 相似提醒分层 + spaCy 模型选择
- [x] §9 AI JSON Schema
- [x] §10 Prompt 版本管理
- [x] §11 画像生成时机
- [x] §12 技术栈与目录
- [x] §13 开工顺序
- [x] §14 阅读交互：选中即操作（§14.7 Clear→Dismiss 重命名；§14.8 跨句批量取消标记）
- [x] §15 用户译文驱动 AI 诊断
- [x] §16 AI Provider 配置（DeepSeek 默认）
- [x] §17 阅读视图排版
- [x] §18 端到端动线与诊断面板
- [x] §19 词卡悬浮提示与备注编辑
- [x] §20 浮层状态机修复与词卡详情入口统一
- [x] §21 词汇 AI 分析面板（基础版）
- [x] §22 词汇 AI 分析面板改进：原文高亮、错因展开、why_this_word、用户笔记区
- [x] §23 Cards 页与 Review Queue 信息增强：Notes/AI Meaning/Source 链接、复习答案 Reveal
- [x] §24 Cards Notes 内联编辑、Review Reveal AI 含义、EPUB 导入接入
- [x] §25 删除导入材料（彻底删除 + 词卡 re-anchor）
