---
name: analyze-sentence
description: Analyze a difficult English sentence from the reading trainer. Fetches sentence + context from DB, performs structural analysis, and saves the result.
trigger: /analyze-sentence
args:
  - name: sentence_id
    description: The sentence ID shown in brackets in 'trainer read' output
    required: true
---

# Sentence Analysis Skill (Gemini CLI)

When `/analyze-sentence <sentence_id>` is invoked:

## Step 1 — Get the rendered prompt

Run in the project directory:

```bash
cd english-reading-trainer && python -m app.ai.context_builder sentence <sentence_id>
```

## Step 2 — Analyze

Read the prompt output and produce a JSON object with this exact structure:

```json
{
  "subject_skeleton": "<bare subject + main verb>",
  "clauses": [
    {"type": "main", "text": "<text>", "role": "<role>"}
  ],
  "modifiers": [{"target": "<word>", "modifier": "<text>", "type": "<type>"}],
  "logic_markers": [{"marker": "<word>", "function": "<function>"}],
  "anaphora": [{"pronoun": "<pronoun>", "refers_to": "<antecedent>"}],
  "simplified_en": "<plain English ≤ 20 words>",
  "chinese_gloss": "<Chinese paraphrase>",
  "predicted_error_types": ["<1–3 codes: G01–G07 L01–L06 D01–D05>"],
  "confidence": 0.9
}
```

Rules:
- `clauses` must include exactly one `"type": "main"` entry
- `predicted_error_types`: 1–3 codes from G01 G02 G03 G04 G05 G06 G07 L01 L02 L03 L04 L05 L06 D01 D02 D03 D04 D05
- Output raw JSON only — no markdown fences

## Step 3 — Save

```bash
cd english-reading-trainer && python - <<'PYEOF'
import sys, os
from app.db_connection import DatabaseConnection
from app.ai.analysis_saver import save_sentence_analysis

raw_json = """<INSERT_JSON_HERE>"""
db = DatabaseConnection(os.environ.get("TRAINER_DB", "data/reading_trainer.db"))
db.apply_migrations("migrations/")
result = save_sentence_analysis(db, <sentence_id>, raw_json, model="gemini-2.0-flash")
print(f"Saved: cache_id={result.cache_id} card_id={result.card_id} valid={result.is_valid}")
PYEOF
```

## Step 4 — Summary

Report: subject_skeleton, simplified_en, chinese_gloss, predicted_error_types, card status.
