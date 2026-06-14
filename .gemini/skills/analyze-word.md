---
name: analyze-word
description: Analyze a word, phrase, or collocation from the reading trainer. Fetches context from DB, performs lexical analysis, and saves the result.
trigger: /analyze-word
args:
  - name: sentence_id
    description: Sentence ID containing the word
    required: true
  - name: surface_form
    description: The word or phrase as it appears in the sentence
    required: true
---

# Word Analysis Skill (Gemini CLI)

When `/analyze-word <sentence_id> "<surface_form>"` is invoked:

## Step 1 — Get the rendered prompt

```bash
cd english-reading-trainer && python -m app.ai.context_builder word <sentence_id> "<surface_form>"
```

## Step 2 — Analyze

Produce a JSON object:

```json
{
  "lemma": "<base form, lowercase>",
  "lexical_type": "<word|phrase|collocation>",
  "pos": "<noun|verb|adjective|adverb|preposition|conjunction|phrase|other>",
  "meaning_in_context": "<meaning as used in this sentence>",
  "common_collocations": ["<3–5 patterns>"],
  "near_synonyms": ["<2–4, or []>"],
  "confusable_with": ["<1–3, or []>"],
  "morphology": {"root": "<root or ''>", "family": ["<related words or []>"]},
  "predicted_error_types": ["<1–2 codes from: G05 G06 L01 L02 L03 L04 L05 L06 D02 D03>"],
  "confidence": 0.9
}
```

Rules: raw JSON only, no fences. `meaning_in_context` must reflect this sentence's sense.

## Step 3 — Save

```bash
cd english-reading-trainer && python - <<'PYEOF'
import sys, os
from app.db_connection import DatabaseConnection
from app.ai.analysis_saver import save_word_analysis

raw_json = """<INSERT_JSON_HERE>"""
db = DatabaseConnection(os.environ.get("TRAINER_DB", "data/reading_trainer.db"))
db.apply_migrations("migrations/")
result = save_word_analysis(db, <sentence_id>, "<surface_form>", raw_json, model="gemini-2.0-flash")
print(f"Saved: cache_id={result.cache_id} card_id={result.card_id} valid={result.is_valid}")
PYEOF
```

## Step 4 — Summary

Report: lemma, lexical_type, meaning_in_context, confusable_with, predicted_error_types, card status.
