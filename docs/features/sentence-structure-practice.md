# 句子结构练习与 AI 结构纠错

本文件是「在句子浮层写语法结构 → AI 评估纠正」功能的实现交接说明，供 Codex 执行。
核心闭环：**写结构 → 保存草稿 → AI 检查结构 → 右侧面板显示纠正结果**，复用现有句子分析链路，不另造学习系统。

> 状态：方案已评审、已对照真实代码核实，尚未实现。本文件聚焦最易踩的工程坑（双 prompt + 版本耦合），并给出完整改动清单与验收标准。

## §S1 功能行为

1. 句子浮层新增 `Write structure / 写结构` 按钮，位置在 `Write translation` 与 `AI analysis` 之间，仅在完整选中一句时显示。
2. 点击打开一个类似翻译编辑器的 textarea，单一自由输入框，placeholder 引导：
   ```text
   主干：
   从句：
   修饰成分：
   指代/逻辑：
   ```
3. 两个动作：
   - `Save only`：只保存结构草稿，不触发分析。
   - `Save and AI check`：保存结构并调用句子分析，进入现有右侧 AI Analysis 面板。
4. 新打开/恢复 analysis 仍从面板顶部开始；`Back to previous analysis` 仍保留上一层滚动位置（沿用 [reader-analysis-panel.md](reader-analysis-panel.md) 的现有行为，不改动）。

## §S2 数据模型

新增迁移 `migrations/010_sentence_user_structure.sql`，照搬 `004_sentence_user_translation.sql` 的形态：

```sql
ALTER TABLE sentence_cards ADD COLUMN user_structure TEXT;
ALTER TABLE sentence_cards ADD COLUMN structure_created_at TEXT;
```

- `app/db_models.py` 的 `SentenceCard` dataclass 补 `user_structure: Optional[str] = None`（紧挨 `user_translation`，约 `:231`）。
- 迁移必须用**真实 SQLite 集成测试**验证（不可 mock，AGENTS.md 硬性要求）。
- **不要**复用 `user_note`（那是 takeaway 存储列，会被 Review 当成复盘结论）。
- **不要**把结构错误写进 `sentence_card_errors`（该表喂给 `similar_card_finder` 的 "Similar past mistake" 与 SM-2，会把"结构练习错误"误当"翻译诊断错误"）。

## §S3 关键工程坑：版本号是两套 prompt 共用的单一全局常量

句子分析有两套 prompt，由 `llm_sentence_analyzer._prompt_name_for_translation`（`:144`）二选一：

| 条件 | 走的 prompt |
|---|---|
| 有翻译 | `sentence_analysis_diagnose` |
| 无翻译 | `sentence_analysis_predict` |

"只写结构、不写翻译"是合法用法，那种情况走的是 **predict**。但 `analyze_sentence` 对两套 prompt 用的是**同一个** `prompt_version`（`llm_sentence_analyzer.py:32` 仅一个 `_PROMPT_VERSION = "v4"`），再由 `_load_prompt(name, version)`（`:137`）拼成 `{name}.{version}.md`。

由此推出三条**硬约束**（不照做就崩，不是建议）：

1. **版本号一改全改**：`_PROMPT_VERSION` 升到 `"v5"` 后，`_load_prompt` 会同时找 `sentence_analysis_diagnose.v5.md` 和 `sentence_analysis_predict.v5.md`。少建一个，走到那条路径就 `FileNotFoundError`。
2. **schema 必须出 v5 分支**：`ai_json_schemas.py` 顶层是 `additionalProperties: False`（`:35`）。LLM 多吐一个 `structure_feedback` 键而 schema 未声明 → 校验直接失败。所以必须新增 schema 常量，不能复用 V2。
3. **运行版本与落库版本必须同步**：分析**运行时**用 `_PROMPT_VERSION`；落库 metadata 用 `_active_sentence_prompt_version`（读 `prompt_versions` 表 active 版本，`web/queries/analysis.py`）。两者不一致 → stale 检测错乱。两处都要落到 v5。

## §S4 完整改动清单（按依赖顺序）

### ① 成对新建 v5 prompt（缺一即崩）

`prompts/sentence_analysis_diagnose.v5.md`、`prompts/sentence_analysis_predict.v5.md`，各基于对应 v4 复制后：

- frontmatter 的 `version:` 字段写 `v5`，与文件名一致——`prompt_version_registry._parse_prompt_file` 不一致会报 `ValueError`。
- 新增模板变量占位 `{{ user_structure }}`。
- 加指令：**仅当 `user_structure` 非 `(none)` 时**才输出 `structure_feedback` 块；为空时**禁止**输出该键。
- predict 版同样接 `user_structure`（这正是"只写结构不写翻译"的路径）。
- 保留现有 `subject_skeleton / clauses / modifiers / anaphora` 作为 AI 标准结构分析，`structure_feedback` 单独表示"你写的结构哪里错"。

`structure_feedback` 形态：

```json
"structure_feedback": {
  "is_correct": false,
  "missed_or_wrong": [
    { "learner_claim": "...", "correction": "...", "reason": "..." }
  ],
  "corrected_structure": "...",
  "why_it_matters_for_translation": "...",
  "next_check": "..."
}
```

### ② schema 出 v5 分支

`app/ai/ai_json_schemas.py`：新增 `SENTENCE_ANALYSIS_SCHEMA_V3`（命名可酌），在 V2 基础上把 `structure_feedback` 加进 `properties`，**不**加进顶层 `required`（保证没写结构时响应仍合法）；其内层对象同样 `additionalProperties: False`。

`app/ai/llm_sentence_analyzer.py:150` 选择器扩展：

```python
def _sentence_analysis_schema(prompt_version: str) -> dict:
    if prompt_version == "v1":
        return SENTENCE_ANALYSIS_SCHEMA
    if prompt_version == "v5":
        return SENTENCE_ANALYSIS_SCHEMA_V3
    return SENTENCE_ANALYSIS_SCHEMA_V2
```

### ③ 升版本常量 + 串 `user_structure`

`app/ai/llm_sentence_analyzer.py`：
- `_PROMPT_VERSION` 改 `"v5"`（`:32`）。
- `analyze_sentence` 加形参 `user_structure: str | None = None`，清洗（仿 `_clean_optional_translation`）后：
  - 并入 `_render` vars：`"user_structure": cleaned_structure or "(none)"`（`:92`）。
  - **仅非空时**并入 cache key（见 ④）。
- `_prompt_name_for_translation` **不改**——v5 两套文件就绪后，无论走哪条都具备 `structure_feedback` 能力。

### ④ cache key 向后兼容

`app/ai/ai_response_cache.py:39` `compute_content_hash` 加 `user_structure: str | None = None`，**仅当非空时**追加 `"|" + normalize_for_hash(user_structure)`；为空则一字节不加，保证历史条目 hash 不变、不被全量打 stale。

> 设计依据：现 hash 为 `normalize(sentence)|context|normalize(translation)`。直接无条件追加段会改变所有空结构旧条目的 hash。

### ⑤ 落库版本对齐

确认 `prompt_version_registry.sync_prompt_versions` 启动扫到两个 v5 文件并标 active（按最高版本号置 active，本就如此），使 `_active_sentence_prompt_version` 返回 `v5`，与 `_PROMPT_VERSION` 一致。逻辑不改，测试需断言两套 prompt 的 active 版本都是 v5。

### ⑥ 串联与 UI

- 保存：`app/cards/sentence_card_service.py` 新增 `save_sentence_structure`（仿 `save_sentence_translation`），写 `user_structure` + `structure_created_at`。
- 接口：`app/web/routers/analysis.py` 接 `user_structure` 表单字段；`app/web/services/analysis.py` 的 `analyze_sentence_for_reader` 透传（仿 `user_translation`：保存草稿 → fetch → 传入 `analyze_sentence`）。
- UI：`app/web/views/reader.py`（按钮 + 隐藏字段 + 编辑器）、`app/web/views/reader_script.py`（提交、面板渲染两个新区块）。
  - 右侧面板加 `我的结构 / Your structure attempt`（显示并可编辑已保存结构）与 `结构反馈 / Structure feedback`（AI 评估纠正）。
  - 现有 `句子结构 / Structure` 区块继续显示 AI 标准结构，不混在一起。
- `Save only` 后旧分析转 stale 属预期——沿用翻译编辑的现有 stale 语义（commit `27f5356`），无需新机制。

## §S5 必须补的测试（防"只改一套"回归）

- `tests/ai/test_llm_sentence_analyzer.py`
  - 断言 `_load_prompt` 对 `..._predict, "v5"` 与 `..._diagnose, "v5"` **都能加载**（缺一即 fail）——封死本坑的核心回归。
  - 写结构 + 无翻译 → 命中 predict → 返回含 `structure_feedback`（mock LLM）。
  - 写结构 + 有翻译 → 命中 diagnose → 含 `structure_feedback`。
  - 无结构 → 两套路径响应都**不含** `structure_feedback` 且通过校验。
- `tests/ai/test_ai_response_cache.py`：`user_structure` 空时 hash == 旧 hash；非空时 hash 改变。
- `tests/ai/test_ai_json_schemas.py`：v5 schema 接受带/不带 `structure_feedback` 两种响应；带未声明字段仍被 `additionalProperties: False` 拒绝。
- `tests/ai/test_prompt_version_registry.py`：sync 后两个 prompt 名的 active 版本均为 `v5`。
- `migrations` 010 真实 SQLite 集成测试。
- 镜像测试：service / router / sentence_card_service 各自补对应用例。

执行命令（AGENTS.md 强制用项目 venv）：

```bash
english-reading-trainer/.venv/bin/python -m pytest tests/
english-reading-trainer/.venv/bin/python -m ruff check app/web
```

## §S6 验收标准（四条缺一不可）

1. diagnose 和 predict 两套 v5 prompt **同时存在**且 frontmatter `version: v5`。
2. schema 选择器对 `"v5"` 返回带**可选** `structure_feedback` 的新常量。
3. `_PROMPT_VERSION` 与 DB active 版本**都为 v5**。
4. **空结构不改 cache hash**（历史分析不被全量打 stale）。

---

# 递归增益设计：让结构练习随时间复利

> 上面 §S1–S6 交付的是**一次闭环**（写结构 → AI 纠正 → 看反馈）。
> 单独看它是个好工具，但**不会递归**：`structure_feedback` 若只存自由文本，喂不进聚合、喂不进复习、也回答不了"我反复栽在哪类结构"。下一句不会因为上一句变得更聪明。
> 本部分把"一次闭环"升级成"会自我增益的引擎"。**Phase A 随 v1 一起做**（成本极低、是后续一切的前提），B/C/D 是同一批数据解锁的分期路线。

## §S7 递归的"关节"：复用现有 error-code 闭合枚举，不另造分类

核心判断（已对照真实代码）：**不要为结构练习发明第二套错误分类。** `app/db_models.py:75` 的 `ERROR_TYPES` 闭合枚举本身就是一套结构技能表：

| code | 名称 | 对应结构技能 |
|---|---|---|
| G01 | 长主语识别失败 | 主干切分 |
| G02 | 后置定语修饰对象判断错 | 后置修饰挂靠 |
| G03 | 嵌套从句边界混乱 | 从句边界 |
| G04 | 倒装 / 强调结构 | 语序/前置 |
| G05 | 非谓语动词作用判断错 | 分词/不定式功能 |
| G06 | 省略 / 替代识别失败 | 省略/替代 |
| G07 | 平行结构对应失败 | 平行结构 |
| D01 | 代词指代对象判断错 | 指代消解 |
| D04 | 信息焦点（主述位）判断错 | 主述位 |
| D05 | 篇章衔接回指失败 | 回指 |

让 `structure_feedback` 的每条 `missed_or_wrong` 带一个 **`error_code`（取上表这个结构子集）**，结构练习就和现有的诊断画像、`similar_card_finder`、能力画像**说同一种语言**——这一个字段，就是把"一次闭环"变成"递归引擎"的关节。`L*`（词汇）和 `I*`（推理）层不属于结构反馈，schema 枚举要收窄到结构子集。

### Phase A —— 随 v1 一起做（零迁移、不碰 `similar_card_finder`）

只在 §S4 已经新增的 `structure_feedback` 块里加一个受约束字段，**不新增表、不新增迁移**：

```json
"structure_feedback": {
  "is_correct": false,
  "missed_or_wrong": [
    {
      "error_code": "G02",
      "learner_claim": "...",
      "correction": "...",
      "reason": "..."
    }
  ],
  "corrected_structure": "...",
  "why_it_matters_for_translation": "...",
  "next_check": "..."
}
```

改动落点（在 §S4 基础上增量）：

1. `app/ai/ai_json_schemas.py`：在 §S4-② 的 `SENTENCE_ANALYSIS_SCHEMA_V3` 里，给 `missed_or_wrong` 的 item 加 `error_code`，`enum` 引用一个**新派生常量** `STRUCTURE_SKILL_CODES`（= G01–G07 + D01/D04/D05 的子集，从 `ERROR_TYPES` 派生，**不要**手抄字符串，复用 `_ERROR_CODES` 的派生方式见 `:123`）。item 内 `additionalProperties: False`，`error_code` 列入 item 的 `required`（块本身仍整体可选）。
2. v5 两套 prompt：指令里要求"每条 `missed_or_wrong` 必须从给定结构 code 列表里选一个 `error_code`"，并把列表连同中文名一起写进 prompt（让模型选得准）。
3. 测试：`tests/ai/test_ai_json_schemas.py` 断言 `missed_or_wrong` 缺 `error_code` 被拒、`error_code` 取 `L01`/`I01` 这种非结构子集被拒。

**为什么 Phase A 必须现在做**：历史数据从第一天起就带标签。等将来建 Phase B/D 的聚合时，几个月的练习记录直接能用；否则得回溯重跑 AI 补标签，又贵又不准。这是唯一一个"现在不做、以后很贵"的点。

## §S8 隔离边界：为什么递归也**仍然不**写 `sentence_card_errors`

`find_similar_sentence_mistakes`（`app/cards/similar_card_finder.py:115`）硬门槛是 `diagnosis_basis == "user_translation"` + `confidence ≥ 0.75` + 读 `sentence_card_errors`，其 docstring 明确"只用翻译诊断数据，不引入第二套自由文本错误分类"。结构练习错误若混进去，会被"过往相似错误"和 SM-2 当成翻译诊断错误。

所以递归走**并行 lane**，而非塞进同一张表：

- 结构错误的 `error_code` 先只活在 `ai_cache.response_json` 的 `structure_feedback` 里（与 `takeaway_suggestion` 同一存法）。
- 聚合/画像通过**扫描 JSON** 得到（见 Phase B/D），不经过 `sentence_card_errors`，因此 `similar_card_finder` 与 SM-2 的语义零改动。
- 关节是**共享 code 枚举**，不是共享存储表。这样"结构练习发现的 G02 弱点"和"翻译诊断发现的 G02 弱点"能在画像层合并，但在"相似错误推荐"里互不污染。

## §S9 Phase B —— 结构弱点画像（聚合）

目标：把散落在各 `structure_feedback` 里的 `error_code` 汇成"你的结构盲点分布"。

- **先用扫描实现，不急着建表**：新增 `app/web/queries`（或 `scripts`）里一个聚合函数，遍历有 `structure_feedback` 的 sentence_cards，统计每个 `error_code` 的出现次数、最近一次、关联句子。单用户数据量下扫描足够。
- 升级到表（可选，仅当扫描变慢或要支撑 Phase C 实时查询）：并行表 `sentence_structure_errors(card_id, error_type_id, source='structure', created_at)`，在 AI 返回 `structure_feedback` 时由 `save` 路径写入。**真实 SQLite 集成测试**（AGENTS.md 硬性要求）。仍**不**进 `similar_card_finder` 查询。
- 产出：Profile 页加一块"结构盲点 Top-N"，复用现有能力画像的展示位，不另造页面。

## §S10 Phase C —— 预测式前置 + 间隔重练（递归的真正回报）

有了弱点画像，系统在你**动笔前**就能用它：

1. **预测式高亮（复用已有分析，不引新 NLP）**：reader 里，对**已有标准结构分析**（`subject_skeleton/clauses/modifiers` 或已落库的 `predicted_error_types`）命中你 Top-N 弱 code 的句子打标，提示"这句正好练你的弱项 G02，要不要写结构？"。对未分析句子做实时结构探测要 AI/spaCy，**留到以后**，先吃免费的已分析数据。
2. **结构 drill 队列**：按弱 code 拉取相关 sentence cards，让你在**新句子**上重写结构——考迁移，不是背旧句。这是在现有 SM-2「调度卡片」之上加一层「按技能 code 选料」，**不要**改 SM-2 内核，只做选择层。间隔随该 code 的正确率拉长。

> 注意范围：Phase C 是体验层，依赖 B 的画像。先确认 A/B 有真实数据再做，避免空画像驱动空队列。

## §S11 Phase D —— 元分析导出（人在环上的递归层）

镜像现有 `/export-takeaways`：新增 `scripts/export_structure_attempts.py`，导出"原句 + 我写的结构 + AI 纠正 + `error_code`"，并按 code 聚合，附一段分析 prompt（仿 `.claude/skills/export-takeaways.md` 第二步），让外部 AI 给出"你前三大结构失败模式 + 可迁移检查清单"。`next_check` / `why_it_matters_for_translation` 字段沉淀下来，就是真正能带进冷读的"遇到[结构]先查[动作]"清单。新增对应 Codex/Gemini skill 入口。

## §S12 分期与验收

| 阶段 | 范围 | 何时做 | 关键验收 |
|---|---|---|---|
| A | `structure_feedback.missed_or_wrong[].error_code`（结构子集枚举） | **随 v1** | schema 拒绝缺 code / 非结构 code；prompt 稳定产出合法 code |
| B | 结构弱点画像（先扫描，可选并行表） | 有真实练习数据后 | 画像计数与 `structure_feedback` 实际 code 一致；不经过 `sentence_card_errors` |
| C | 预测式高亮 + 结构 drill 队列 | B 落地后 | 高亮命中弱 code；drill 按 code 选新句；SM-2 内核未改 |
| D | `export_structure_attempts.py` + skill 入口 | 任意（独立） | 导出按 code 聚合；与 `export_takeaways` 同形 |

**贯穿约束**：递归全程复用 `ERROR_TYPES` 闭合枚举做关节，结构错误**永不**写进 `sentence_card_errors`（保 `similar_card_finder` 语义），所有迁移走真实 SQLite 集成测试，每个新函数同步加测试。

---

# 使用指南：怎么用才发挥更大作用

> 给自己看的，不是给 Codex 的。Phase A 上线后按此用。

## 核心动线：难句先写结构、再写译文

碰到读不顺的长句，别急着翻译。先点「写结构 / Write structure」→「Save and AI check」，确认你真把骨架看对了，再去写译文。

这一步把"读不懂"拆成两件独立的事：

- **没看清结构** → 结构练习负责
- **结构清楚了但词义/逻辑没懂** → 译文诊断负责

两个工具串起来，定位精度比只用译文诊断高得多。

## 结构写具体，别写笼统

AI 只能纠正你**明确写出来的判断**。

- 没法纠的写法："这是个复合句"
- 有价值的写法："`which` 修饰的是 the report，不是 the committee；分词短语 `taken seriously` 作后置定语修饰 the issue"

你写得越像在"下判断"，`missed_or_wrong` 里的反馈越具体，`error_code` 也才打得准。

## 把 `next_check` 当成手攒的清单

B/D 还没自动聚合前，自己留意 `next_check` 和 `why_it_matters_for_translation` 反复出现的那几条——多半就是你的结构盲点。同一类句型再栽两三次，就是该专门刷它的信号。

## 持续用，哪怕暂时看不到聚合

Phase A 的复利来自**坚持喂数据**。你练得越多、`error_code` 打得越全，将来 Phase B（弱点画像）一上线，画像越准、越快有用。三天打鱼，等于 B 上线时还是空画像。
