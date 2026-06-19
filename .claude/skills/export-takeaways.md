---
name: export-takeaways
description: Export all user-written takeaways (with sentence context and AI suggestions) from the reading trainer database, then display them ready for AI pattern analysis.
trigger: /export-takeaways
args:
  - name: format
    description: Output format — "text" (default, paste-ready) or "json" (structured)
    required: false
---

# Export Takeaways Skill

When `/export-takeaways [format]` is invoked, run the export script and display the results.

## Step 1 — Run the export script

```bash
cd english-reading-trainer && .venv/bin/python scripts/export_takeaways.py --format {{ format | default: "text" }}
```

## Step 2 — Report to the user

Display the full output verbatim so the user can copy and paste it into any AI for analysis.

Then append this ready-to-use analysis prompt:

```
---
AI分析prompt模板（复制上方内容 + 以下prompt一起发给Claude/ChatGPT）：

以下是我的英语阅读理解练习takeaway记录，格式包含：原句、我的takeaway、AI建议（如有）。

请帮我：
1. 找出我反复犯的错误模式（不同句子但同类问题反复出现）
2. 找出描述不够精确的takeaway（太宽泛，或无法转化为具体检查动作）
3. 找出明显遗漏的错误维度（句子有明显陷阱，但我的takeaway没提到）
4. 对比"我的takeaway"和"AI建议"，找出我系统性忽略的角度
5. 给出3-5条可迁移的"阅读检查清单条目"，格式：遇到[结构]时，先检查[什么]
```

## Error handling

- Script not found → remind user to run from `english-reading-trainer/` directory
- Database not found → `TRAINER_DB` env var or default `data/reading_trainer.db`
- No takeaways → inform user they need to write and save takeaways in the reader first
