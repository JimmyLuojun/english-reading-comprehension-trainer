# 数据模型与核心实体

本文件保存原 `docs/design.md` 中的数据模型、错误枚举、词卡类型和跨书去重设计。当前真实 SQLite schema 以 `docs/state/schema.sql` 为准。

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
---

## 3. 词汇卡的类型字段

`word_cards.lexical_type ∈ { word, phrase, collocation }`

- `word`：单词。如 `mitigate`。
- `phrase`：固定短语 / 习语。如 `give rise to`、`no sooner ... than`。
- `collocation`：高频搭配。如 `draw a conclusion`、`heavy rain`。

第一版统一存在 `word_cards` 表，不拆表。`lemma` 字段对 phrase / collocation 存归一化后的"提示形"（小写、去标点、占位符 `...` 代表可变成分）。

`[已确认 2026-06-14]`

---
---

## 4. 同句跨书去重策略

**默认**：基于 `text_hash` 去重句子内容，但保留多个出处。

- `sentences` 表按出处插入（同一文本可有多行，对应不同 `book_id`）。
- `sentence_cards` 通过 `sentence_id` 关联其中**一个**出处（用户首次标记的那次）。
- 但卡片上展示一个"也出现在"列表，通过 `text_hash` 反查其它出处。

**理由**：用户语境中卡点产生于"读到这本书的这段"，强行合并会丢上下文；但完全不去重会让"相似提醒"误报为新句子。这是折中。

`[已确认 2026-06-14]`

---
