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

---

## 1. 数据模型（SQLite）

### 1.1 表清单

```text
books
chapters
paragraphs
sentences

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
chapters(id, book_id, idx, title, sentence_start, sentence_end)
paragraphs(id, chapter_id, idx, sentence_start, sentence_end)
sentences(id, book_id, chapter_id, paragraph_id, idx,
          text, text_hash, char_offset_start, char_offset_end)

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

- `text_hash` 用 SHA256(normalized_text)；用于跨书去重（见 §4）。
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

**默认：按 ********`file_hash`******** 识别同一本书，更新元数据与章节结构，但不动卡片和复习记录。**

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

### 7.4 mastery_state 派生规则

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

