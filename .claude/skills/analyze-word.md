---
name: analyze-word
description: Analyze a word, phrase, or collocation from the reading trainer. Fetches sentence context from DB, performs lexical analysis, and saves the result — no API key needed.
trigger: /analyze-word
args:
  - name: sentence_id
    description: The sentence ID containing the word (from 'trainer read')
    required: true
  - name: surface_form
    description: The word or phrase exactly as it appears in the sentence
    required: true
---

# Word / Phrase Analysis Skill

When `/analyze-word <sentence_id> "<surface_form>"` is invoked, execute these steps.

## Step 1 — Fetch the rendered prompt from DB

```bash
cd english-reading-trainer && python -m app.ai.context_builder word {{ sentence_id }} "{{ surface_form }}"
```

This prints the fully rendered word-analysis prompt with the sentence, context, related cards, and learner profile already filled in.

## Step 2 — Perform the analysis

Using the information from Step 1, produce a JSON object matching the schema below.
Output the JSON directly — no markdown fences, no commentary.

```json
{
  "lemma": "<base/citation form: lowercase, uninflected; use '...' for variable slots in phrases>",
  "lexical_type": "<word|phrase|collocation>",
  "pos": "<noun|verb|adjective|adverb|preposition|conjunction|phrase|other>",
  "meaning_in_context": "<precise meaning as used in this specific sentence>",
  "common_collocations": ["<3–5 typical patterns>"],
  "near_synonyms": ["<2–4 near-synonyms, or []>"],
  "confusable_with": ["<1–3 commonly confused words, or []>"],
  "morphology": {
    "root": "<Latin/Greek root if applicable, else ''>",
    "family": ["<2–5 related words, or []>"]
  },
  "predicted_error_types": ["<1–2 codes from the list below>"],
  "confidence": 0.0
}
```

**Constraints:**
- `lexical_type`: exactly one of `word`, `phrase`, `collocation`
- `predicted_error_types`: 1–2 codes from this closed list only:
  G05 G06 L01 L02 L03 L04 L05 L06 D02 D03
- `confidence`: float in [0.0, 1.0]
- `meaning_in_context` must reflect the sense used **in this sentence**, not a dictionary default

## Step 3 — Save the result to DB

```bash
cd english-reading-trainer && python - <<'PYEOF'
import sys, os
from app.db_connection import DatabaseConnection
from app.ai.analysis_saver import save_word_analysis

raw_json = """<INSERT_JSON_HERE>"""
sentence_id  = {{ sentence_id }}
surface_form = "{{ surface_form }}"

db = DatabaseConnection(os.environ.get("TRAINER_DB", "data/reading_trainer.db"))
db.apply_migrations("migrations/")

result = save_word_analysis(db, sentence_id, surface_form, raw_json, model="claude-opus-4-7")
print(f"cache_id={result.cache_id}  card_id={result.card_id}  valid={result.is_valid}")
if result.error:
    print(f"Error: {result.error[:300]}", file=sys.stderr)
PYEOF
```

Replace `<INSERT_JSON_HERE>` with the JSON from Step 2.

## Step 4 — Report to the user

```
Word [{{ surface_form }}] analyzed and saved.

Lemma            : <lemma>
Type             : <lexical_type>
POS              : <pos>
Meaning here     : <meaning_in_context>
Collocations     : <common_collocations joined by " | ">
Confusable with  : <confusable_with joined by ", " or "(none)">
Error types      : <predicted_error_types with names>
Card             : <created|updated> (id=<card_id>)
```

## Error handling

- Sentence not found → report error from Step 1
- JSON validation fails → show error, ask user to fix
- surface_form is empty → remind user to quote multi-word phrases: `/analyze-word 42 "give rise to"`
