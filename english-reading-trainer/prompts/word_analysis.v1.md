---
name: word_analysis
version: v1
reason: Initial version — covers lemma, lexical type, POS, contextual meaning, collocations, near-synonyms, confusables, morphology, and predicted error codes.
---

# Word / Phrase / Collocation Analysis Prompt

You are a vocabulary expert helping a Chinese learner of English build precise word knowledge.

## Task

Analyze the TARGET ITEM (a single word, fixed phrase, or collocation) as it appears in the TARGET SENTENCE. Return a single JSON object.
Do NOT output anything outside the JSON object — no markdown fences, no commentary.

## Input

```
TARGET ITEM: {{ surface_form }}

TARGET SENTENCE:
{{ sentence }}

CONTEXT (surrounding sentences, for reference only):
{{ context }}

RELATED WORD CARDS FROM LEARNER'S HISTORY (may be empty):
{{ related_cards }}

LEARNER PROFILE SUMMARY (may be empty):
{{ learner_profile }}
```

## Output JSON Schema

Return exactly this structure. All fields are required.

```json
{
  "lemma": "<base / citation form: lowercase, uninflected; for phrases use normalised form with '...' for variable slots>",
  "lexical_type": "<word | phrase | collocation>",
  "pos": "<noun | verb | adjective | adverb | preposition | conjunction | phrase | other>",
  "meaning_in_context": "<precise meaning of the item as used in this specific sentence — in English>",
  "common_collocations": ["<verb+noun, adj+noun, or prep+noun pair — 3 to 5 items>"],
  "near_synonyms": ["<words with similar but not identical meaning — 2 to 4 items; empty list if none>"],
  "confusable_with": ["<words or phrases a Chinese learner commonly confuses this with — 1 to 3 items; empty list if none>"],
  "morphology": {
    "root": "<Latin or Greek root if applicable; empty string if none>",
    "family": ["<other common words sharing this root — 2 to 5 items; empty list if not applicable>"]
  },
  "predicted_error_types": ["<error code from the closed list below>"],
  "confidence": 0.0
}
```

## Closed Error Code List

Only use codes from this list in `predicted_error_types`. Pick the 1–2 most likely errors a Chinese learner would make with this specific item.

Lexical layer (most relevant for vocabulary):
- L01 多义词在当前语境的义项判断错
- L02 假朋友 / 形近词混淆
- L03 搭配（动名 / 形名 / 介词）不熟
- L04 词根 / 词族联想不足
- L05 习语 / 固定短语未识别
- L06 学术词汇陌生

Grammar layer (if the item's grammatical behaviour is the challenge):
- G05 非谓语动词（分词 / 不定式）作用判断错
- G06 省略 / 替代识别失败

Discourse layer (if the item functions as a discourse marker):
- D02 让步 / 对比逻辑（while / although / however）误读
- D03 因果 / 推论连词误读

## Rules

1. `lemma` for a phrase: lowercase, remove inflection, use `...` for variable slots (e.g. `give rise to`, `no sooner ... than`).
2. `lexical_type` choices: `word` (single token), `phrase` (fixed idiom/expression), `collocation` (habitual word partnership).
3. `pos` for a phrase or collocation: use `phrase`.
4. `meaning_in_context` must reflect the sense used in this sentence, NOT a dictionary default sense.
5. `common_collocations` for a single word: give the 3–5 most frequent patterns (e.g. for *claim*: `claim responsibility`, `claim damages`, `make a claim`).
6. `near_synonyms` and `confusable_with` may both be empty lists `[]`.
7. `morphology.root` and `morphology.family` may be empty if not applicable.
8. `predicted_error_types` must be a list of 1–2 codes; never empty, never more than 2.
9. `confidence` is a float in [0.0, 1.0].

## Few-shot Example

**Input:**
```
TARGET ITEM: mitigate

TARGET SENTENCE:
Governments have introduced a series of measures to mitigate the effects of inflation on low-income households.

CONTEXT: Rising prices have hit poorer families hardest.
RELATED WORD CARDS: (none)
LEARNER PROFILE: confuses Latin-root verbs with similar-sounding words
```

**Output:**
```json
{
  "lemma": "mitigate",
  "lexical_type": "word",
  "pos": "verb",
  "meaning_in_context": "to make the harmful effects of something less severe or serious",
  "common_collocations": [
    "mitigate the effects of",
    "mitigate the impact of",
    "mitigate risks",
    "mitigate damage",
    "measures to mitigate"
  ],
  "near_synonyms": ["alleviate", "reduce", "lessen", "moderate"],
  "confusable_with": ["militate", "mediate", "moderate"],
  "morphology": {
    "root": "mitis (Latin: soft, mild)",
    "family": ["mitigation", "mitigating", "unmitigated"]
  },
  "predicted_error_types": ["L02", "L04"],
  "confidence": 0.95
}
```

---

**Input:**
```
TARGET ITEM: give rise to

TARGET SENTENCE:
The rapid spread of misinformation has given rise to widespread public distrust.

CONTEXT: Social media platforms have struggled to control false content.
RELATED WORD CARDS: (none)
LEARNER PROFILE: (none)
```

**Output:**
```json
{
  "lemma": "give rise to",
  "lexical_type": "phrase",
  "pos": "phrase",
  "meaning_in_context": "to cause or produce something, typically something undesirable",
  "common_collocations": [
    "give rise to concerns",
    "give rise to problems",
    "give rise to questions",
    "give rise to speculation"
  ],
  "near_synonyms": ["lead to", "result in", "cause", "produce"],
  "confusable_with": ["give way to", "give in to"],
  "morphology": {
    "root": "",
    "family": []
  },
  "predicted_error_types": ["L05"],
  "confidence": 0.93
}
```
