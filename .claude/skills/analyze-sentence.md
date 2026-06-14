---
name: analyze-sentence
description: Analyze a difficult English sentence from the reading trainer. Fetches sentence + context from DB, performs structural analysis, and saves the result — no API key needed.
trigger: /analyze-sentence
args:
  - name: sentence_id
    description: The sentence ID shown in brackets in 'trainer read' output
    required: true
---

# Sentence Analysis Skill

When `/analyze-sentence <sentence_id>` is invoked, execute these steps in order.

## Step 1 — Fetch the rendered prompt from DB

```bash
cd english-reading-trainer && python -m app.ai.context_builder sentence {{ sentence_id }}
```

This prints the fully rendered analysis prompt with the sentence, surrounding context, chapter title, related cards, and learner profile already filled in. Read it carefully before proceeding.

## Step 2 — Perform the analysis

Using the information from Step 1, produce a JSON object matching the schema below.
Output the JSON directly — no markdown fences, no commentary, no extra text.

```json
{
  "subject_skeleton": "<bare subject + main verb, stripped of all modifiers>",
  "clauses": [
    {"type": "main", "text": "<clause text>", "role": "<grammatical role>"}
  ],
  "modifiers": [
    {"target": "<modified word>", "modifier": "<modifier text>", "type": "<adjective|adverb|prepositional|participial|infinitival|appositive>"}
  ],
  "logic_markers": [
    {"marker": "<connective>", "function": "<concession|contrast|cause|result|condition|addition|exemplification|sequence>"}
  ],
  "anaphora": [
    {"pronoun": "<pronoun or pro-form>", "refers_to": "<antecedent>"}
  ],
  "simplified_en": "<plain English rewrite in ≤ 20 words>",
  "chinese_gloss": "<natural Chinese paraphrase>",
  "predicted_error_types": ["<1–3 codes from the list below>"],
  "confidence": 0.0
}
```

**Constraints:**
- `clauses` must contain exactly one entry with `"type": "main"` — never omit it
- `predicted_error_types`: 1–3 codes, chosen from this closed list only:
  G01 G02 G03 G04 G05 G06 G07 L01 L02 L03 L04 L05 L06 D01 D02 D03 D04 D05
- `confidence`: float in [0.0, 1.0]
- `modifiers`, `logic_markers`, `anaphora` may be `[]`

## Step 3 — Save the result to DB

Write the JSON to a temp file, then call the save command:

```bash
cd english-reading-trainer && python - <<'PYEOF'
import json, sys, os
from app.db_connection import DatabaseConnection
from app.ai.analysis_saver import save_sentence_analysis

raw_json = """<INSERT_JSON_HERE>"""
sentence_id = {{ sentence_id }}

db = DatabaseConnection(os.environ.get("TRAINER_DB", "data/reading_trainer.db"))
db.apply_migrations("migrations/")

result = save_sentence_analysis(db, sentence_id, raw_json, model="claude-opus-4-7")
print(f"cache_id={result.cache_id}  card_id={result.card_id}  valid={result.is_valid}")
if result.error:
    print(f"Error: {result.error[:300]}", file=sys.stderr)
PYEOF
```

Replace `<INSERT_JSON_HERE>` with the JSON from Step 2.

## Step 4 — Report to the user

Show a concise summary:

```
Sentence [{{ sentence_id }}] analyzed and saved.

Subject skeleton : <subject_skeleton>
Simplified       : <simplified_en>
Chinese gloss    : <chinese_gloss>
Error types      : <predicted_error_types with names>
Confidence       : <confidence>
Card             : <created|updated> (id=<card_id>)
```

## Error handling

- Sentence not found → report the error from Step 1, exit
- JSON validation fails in Step 3 → show the error, ask user to check the JSON
- DB not found → remind user to run `trainer books import` first or set `TRAINER_DB`
