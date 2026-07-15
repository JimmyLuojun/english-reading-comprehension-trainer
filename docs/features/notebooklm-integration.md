# NotebookLM 协同学习方案

> **状态：待实践验证（2026-07-13）。**
> 本文记录英语阅读训练系统与 NotebookLM 的职责分工、推荐闭环和后续实现线索。当前不实施 NotebookLM API 集成，先用手动上传验证学习收益。

## 1. 核心结论

把本项目当作**精读、诊断和长期记忆引擎**，把 NotebookLM 当作**跨章节理解、苏格拉底口试、口语复述与迁移训练教练**。

两者不应重复建设卡片、复习进度或长期知识库：

| 系统 | 唯一职责 |
|---|---|
| 英语阅读训练项目 | 精读、翻译、拆结构、错误诊断、词句卡、SM-2、长期学习记录 |
| NotebookLM | 跨段落/章节整合、引用核查、英文口试、概念迁移、音频讨论 |
| Obsidian | 已内化的阅读方法、个人错误模型和长期知识；不保存大量临时 AI 输出 |

NotebookLM 是项目的临时推理工作台，不是新的资料中枢。项目 SQLite 仍是训练事实源；经过本人验证、能用自己的话表达的长期知识才进入 Obsidian。

## 2. 当前学习数据给出的线索

以下是 2026-07-13 对本地 `reading_trainer.db` 的一次性快照，后续会自然变化：

- 234 张句卡、236 张词卡，其中 426 张仍活跃。
- 132 次复习中，128 次是词卡，句卡只有 4 次。
- 词卡复习通过率约 35.2%。
- 已有 82 条 sentence takeaway、123 次翻译和 137 次结构练习。
- learner profile snapshot 为 0。
- 高频薄弱点集中在：语境义项、习语/固定短语、省略/替代、搭配、学术词汇、后置定语、非谓语、指代和言外之意。

因此当前瓶颈不是缺少材料或 AI 解释，而是：

1. 句卡主动提取不足；
2. 已积累的错例尚未形成稳定的跨章节能力画像；
3. 阅读理解尚需从“逐句看懂”迁移到“闭卷复述、解释论证、迁移应用”。

NotebookLM 最有价值的用途是补足这三点，而不是继续扩充卡片数量。

## 3. 需要避免的负面效果

### 3.1 阅读前先看摘要

这容易形成“看懂了”的熟悉感，同时绕过最需要训练的句法解析、指代追踪和推理过程。推荐顺序始终是：先独立阅读和产出，再用 NotebookLM 核查。

### 3.2 建立第二套卡片与复习进度

NotebookLM 可以生成 Flashcards 和 Quizzes，但其进度不是本项目的 SM-2 调度。如果两边都保存词句卡，会形成重复卡片、两套复习计划和不完整的学习证据。

NotebookLM Quiz 只用于即时检索练习，尤其是篇章关系、指代、推理和作者立场。真正答错且值得长期复习的内容，才回流本项目成为 takeaway 或卡片。

### 3.3 把所有书放进一个 notebook

NotebookLM 的 notebook 相互独立，不能跨 notebook 访问。单个 notebook 放入过多无关书籍也会稀释提问上下文。推荐“一本当前在读书一个 Reading Lab”，另建一个只放近期学习证据的 Weekly Reading Lab。

### 3.4 被动收听 Audio Overview

单纯听属于再认，不能替代主动提取。Audio Overview 应配合以下至少一种行为：

- 播放前预测将讨论的论点；
- 每个主题后暂停并用英文复述；
- 使用英文 Interactive Mode 追问；
- 选择 Critique 或 Debate 后口头反驳其中一方。

### 3.5 把 NotebookLM 输出直接当作长期知识

NotebookLM 的回答、笔记和生成物都可能出错，也不应成为项目事实源。只有经过原文引用核查、本人重新表达并确认有长期价值的结论，才进入 Obsidian 的 Atom 或 Molecule。

## 4. 最小可行方案

先建立一个 notebook：

```text
当前在读书名 — Reading Lab
```

放入三类来源：

1. 当前原书：EPUB、PDF、Markdown、TXT 或网页；
2. 项目导出的 takeaway；
3. 每章一次闭卷英文复述，可以是文字或录音。

项目已有 takeaway 导出工具：

```bash
cd english-reading-trainer
.venv/bin/python scripts/export_takeaways.py \
  --output exports/2026-07-13_阅读takeaway.md
```

导出物属于项目派生资产，继续放在项目 `exports/` 下；不复制到 Obsidian。后续如增加专用导出器，建议放入 `exports/notebooklm/`，文件使用 `YYYY-MM-DD_主题.md` 命名。

## 5. 每章学习闭环

### 5.1 独立精读

在本项目中完成原文阅读、必要的翻译、结构拆解、词句卡和 takeaway。此时不向 NotebookLM 索要章节摘要。

### 5.2 闭卷英文复述

关闭原文，用英文写或录制约两分钟，至少回答：

- 本章核心主张是什么？
- 论证链、因果链或事件链如何展开？
- 哪两个细节最能支持核心主张？
- 作者的态度或暗含结论是什么？
- 哪个地方仍然解释不清？

### 5.3 NotebookLM 口试与引用核查

使用以下固定提示词：

```text
Act as my English reading examiner.

Ask only one question at a time and wait for my answer.
Do not summarize the chapter for me before I attempt an answer.

Test:
1. the main claim,
2. the argument or causal chain,
3. pronoun and omitted-element resolution,
4. the author's implied stance,
5. transfer to a new situation.

Prioritize my known weaknesses:
word sense in context, idioms, collocations, ellipsis,
non-finite clauses, reference resolution, and implicature.

After each answer:
- grade it as correct, partial, or incorrect;
- identify the exact reasoning step I missed;
- cite the supporting passage;
- ask me to repair the answer in English.
```

### 5.4 受控回流

NotebookLM 生成的内容不直接进入卡片。只有满足以下条件的内容才回流：

- 闭卷回答错误或只能部分回答；
- 能指出具体缺失的推理步骤；
- 已通过 NotebookLM 引用回到原文核查；
- 值得未来再次主动提取。

回流时优先补写现有 sentence takeaway；只有确实需要长期间隔复习时才新增卡片。

## 6. 每周训练闭环

每周建立或更新一个 `Weekly Reading Lab`，只放最近七天的学习证据，而不是整套书库。让 NotebookLM 完成以下任务：

1. 从真实错例中找重复出现的错误模式；
2. 区分“知识不知道”和“阅读过程没有执行”；
3. 从原始材料中选择三组相似但容易混淆的新句子；
4. 生成只考篇章关系、指代、推理和作者立场的高难度 Quiz；
5. 生成英文 Debate/Critique Audio，随后进行口头反驳；
6. 最后生成 Mind Map，再关闭画面凭记忆重画。

建议的每周诊断提示词：

```text
Analyze only the learning evidence from this week.

1. Identify the three most repeated reading failures.
2. For each failure, distinguish a knowledge gap from a process failure.
3. Cite at least two concrete cases from my evidence.
4. Select new passages from the source that test the same skill without
   repeating the original wording.
5. Ask me to solve them before showing any explanation.
6. End with one behavior rule I should apply during next week's reading.
```

## 7. 推荐的后续项目功能

最值得新增的不是完整 NotebookLM API 集成，而是一个**每周学习证据包导出器**。建议未来实现：

```text
english-reading-trainer/exports/notebooklm/
  2026-07-13_每周学习证据.md
```

证据包应包含：

- 原句、书名、章节和稳定 sentence ID；
- 用户首次翻译与结构尝试；
- AI 纠正和对应错误代码；
- takeaway；
- 本周 review outcome、反复失败项和掌握状态；
- 按书、章节和错误类型分组的统计；
- 必要的原文上下文，不导出整份数据库。

实现时应新增对应 Python 单元测试，并保持 Markdown 输出稳定、可复现。第一阶段先手动上传文件验证四周；只有确认确实提高了闭卷复述、迁移和复习完成率，才考虑 Google Drive 同步或 NotebookLM Enterprise API。

## 8. 成效判断

连续实践四周后，用以下指标判断是否值得继续：

- 每周句卡实际复习次数是否明显提高；
- 同一错误代码的复发率是否下降；
- 不看原文能否更完整地复述主张与论证链；
- 对新段落的指代、隐含立场和推理题正确率是否提高；
- NotebookLM 产生的内容中，真正需要回流为长期卡片的比例是否足够低；
- 每周流程是否能在可接受时间内完成，而没有变成新的资料整理负担。

如果只是生成了更多摘要、音频和卡片，却没有改善上述指标，应停止扩展集成。

## 9. NotebookLM 能力与限制参考

- [NotebookLM 支持的来源类型](https://support.google.com/notebooklm/answer/16215270?hl=en-5)
- [Notebook 的独立性与使用方式](https://support.google.com/notebooklm/answer/16206563?hl=en)
- [当前使用限额](https://support.google.com/notebooklm/answer/16269187?hl=en)
- [基于来源引用的 Chat](https://support.google.com/notebooklm/answer/16179559?hl=en)
- [Flashcards 和 Quizzes](https://support.google.com/notebooklm/answer/16958963?hl=en-GB)
- [Audio Overview 与英文互动模式](https://support.google.com/notebooklm/answer/16212820?hl=en)
- [Mind Maps](https://support.google.com/notebooklm/answer/16212283?hl=en)
- [Notes 与 Docs/Sheets 导出限制](https://support.google.com/notebooklm/answer/16262519?hl=en)
- [NotebookLM Enterprise 来源 API（Preview）](https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks-sources)
