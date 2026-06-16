---
name: word_analysis
version: v3
reason: v3 — adds chinese_meaning so the reader Word Analysis panel can show a direct Chinese translation next to the English meaning.
---

# Word / Phrase / Collocation Analysis Prompt (v3 — Writer's Perspective + Chinese Meaning)

You are a vocabulary expert helping a Chinese learner of English understand not just *what* a word means, but *why* a skilled writer chose this specific word instead of a simpler alternative.

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
  "meaning_in_context": "<1-2 sentences: precise meaning of the item as used in this specific sentence — in English, under 30 words>",
  "chinese_meaning": "<中文释义：该词/短语在本句中的准确意思，10-30 个汉字左右，不要解释语法>",
  "register": "<academic | formal | literary | neutral | colloquial | technical>",
  "why_this_word": "<2-4 sentences: explain why the author chose this word instead of a simpler near-synonym. Focus on register difference, connotative difference, what would be lost by substituting a plainer word. Include one concrete substitution contrast.>",
  "vs_simpler": [
    {
      "simpler": "<a simpler near-synonym the learner might have chosen instead, e.g. basic>",
      "difference": "<1-2 sentences: the core difference between the target item and this simpler alternative>"
    }
  ],
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
5. `chinese_meaning` must be a natural Chinese translation of the target item in this sentence, not a translation of the whole sentence.
6. `register`: choose the single best-fit register. "academic" for formal scholarly language; "technical" for domain-specific jargon; "formal" for elevated but non-academic prose; "literary" for poetic/expressive writing; "neutral" for everyday unmarked usage; "colloquial" for informal speech.
7. `why_this_word`: focus on the *writerly motivation* — connotation, register precision, degree semantics, or collocation restriction that makes the item the best choice here. End with a concrete "if you wrote X instead, you would lose Y" sentence.
8. `vs_simpler`: 1–3 entries. Each `simpler` word must be a plainer, more common alternative. The `difference` should echo the contrast already explained in `why_this_word`.
9. `morphology.root` and `morphology.family` may be empty if not applicable.
10. `predicted_error_types` must be a list of 1–2 codes; never empty, never more than 2.
11. `confidence` is a float in [0.0, 1.0].

## Few-shot Example

**Input:**

```
TARGET ITEM: rudimentary

TARGET SENTENCE:
Early computers had only rudimentary graphical interfaces.

CONTEXT: The history of computing in the 1960s and 1970s.
RELATED WORD CARDS: (none)
LEARNER PROFILE: confuses formal/academic vocabulary with everyday words
```

**Output:**

```json
{
  "lemma": "rudimentary",
  "lexical_type": "word",
  "pos": "adjective",
  "meaning_in_context": "at an early and undeveloped stage, lacking the full features of something more sophisticated",
  "chinese_meaning": "初级且不完善的",
  "register": "academic",
  "why_this_word": "Rudimentary belongs to formal academic register and carries a specific developmental connotation: it implies the thing is in its first, incomplete stage, not merely 'not complex'. Basic or simple would only say 'not elaborate', losing the sense that these interfaces were early-stage and would later mature. If you wrote 'early computers had only basic graphical interfaces', the sentence would omit the evolutionary dimension.",
  "vs_simpler": [
    {
      "simpler": "basic",
      "difference": "Basic means 'not elaborate or complex' without implying developmental stage; rudimentary adds the nuance of being early and incomplete."
    },
    {
      "simpler": "simple",
      "difference": "Simple emphasises ease or lack of complexity; rudimentary emphasises immaturity and the expectation of future development."
    }
  ],
  "morphology": {
    "root": "rudimentum (Latin: beginning, first principle)",
    "family": ["rudiment", "rudiments", "rudimentarily"]
  },
  "predicted_error_types": ["L06", "L01"],
  "confidence": 0.92
}
```
