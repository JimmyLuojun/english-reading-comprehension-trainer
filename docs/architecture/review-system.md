# 复习系统与能力画像

本文件保存 SM-2 复习、相似提醒和能力画像生成时机的设计。

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
---

## 11. 能力画像生成时机

**默认：每完成 20 张卡片复习 OR 距上次画像超过 7 天，自动生成一次。**

- 生成时只取近 90 天数据。
- 输出到 `learner_profile_snapshots`，保留全部历史快照。
- 在 prompt 压缩时只用**最近一次** snapshot 的 `summary_md`。

`[已确认 2026-06-14]`

---
