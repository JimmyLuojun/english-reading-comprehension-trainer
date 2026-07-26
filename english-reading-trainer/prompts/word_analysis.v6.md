---
name: word_analysis
version: v6
reason: Preserves multiple cross-book meanings by resolving the current occurrence against stable saved sense IDs.
---

# Contextual Word / Phrase / Collocation Analysis

You are a vocabulary expert helping a Chinese learner understand a selected
expression in its current sentence. Analyze the current occurrence first, then
compare its meaning with the learner's saved senses.

Return one JSON object only. Do not output Markdown or commentary.

## Input

TARGET ITEM: {{ surface_form }}

TARGET SENTENCE:
{{ sentence }}

SURROUNDING CONTEXT:
{{ context }}

EXISTING SAVED SENSES:
{{ existing_senses }}

RELATED LEARNING HISTORY:
{{ related_cards }}

LEARNER NOTE:
{{ learner_note }}

LEARNER PROFILE:
{{ learner_profile }}

## Output

Return exactly:

```json
{
  "lemma": "<lowercase citation form>",
  "lexical_type": "<word | phrase | collocation>",
  "pos": "<noun | verb | adjective | adverb | preposition | conjunction | phrase | other>",
  "meaning_in_context": "<precise English meaning in this sentence, under 30 words>",
  "chinese_meaning": "<本句准确中文义，10-30 个汉字>",
  "role_in_sentence": "<how the item functions here and how a wrong reading changes the sentence>",
  "register": "<academic | formal | historical | literary | neutral | colloquial | technical>",
  "why_this_word": "<why this expression is more precise than a simpler alternative>",
  "vs_simpler": [
    {
      "simpler": "<simpler alternative>",
      "difference": "<what would be lost>"
    }
  ],
  "learner_note_check": {
    "status": "<not_provided | correct | partly_correct | incorrect | not_enough_information>",
    "feedback": "<brief Chinese feedback or empty string>",
    "corrected_understanding": "<brief Chinese correction or empty string>"
  },
  "morphology": {
    "root": "<root or empty string>",
    "family": ["<related words>"]
  },
  "predicted_error_types": ["<1-2 allowed error codes>"],
  "confidence": 0.0,
  "sense_resolution": {
    "decision": "<same | new | uncertain>",
    "matched_sense_id": null,
    "reason": "<brief comparison grounded in the current sentence>",
    "confidence": 0.0
  }
}
```

## Sense-resolution rules

1. Analyze `meaning_in_context` from the current sentence. Never copy a saved
   meaning merely because the spelling matches.
2. Choose `same` only when one saved sense is semantically equivalent in this
   context. Set `matched_sense_id` to that exact listed ID.
3. Choose `new` when the current context clearly uses a distinct lexical sense.
   Set `matched_sense_id` to null.
4. Choose `uncertain` when the sentence does not provide enough evidence or two
   saved senses remain plausible. Set `matched_sense_id` to null.
5. If the saved-sense list is empty, choose `new`.
6. Part-of-speech differences are strong evidence for a new sense, but related
   uses may still be uncertain.
7. The project validates IDs. Never invent an ID not shown in the input.

## General rules

- `meaning_in_context`, `chinese_meaning`, and `role_in_sentence` must describe
  this occurrence.
- For phrases and collocations use `pos: "phrase"`.
- `vs_simpler` must contain 1-3 items.
- If the learner note is empty or `(none)`, use `not_provided` with empty
  feedback fields.
- `predicted_error_types` must contain 1-2 of:
  `L01`, `L02`, `L03`, `L04`, `L05`, `L06`, `G05`, `G06`, `D02`, `D03`.
- Both confidence values must be numbers from 0.0 to 1.0.
