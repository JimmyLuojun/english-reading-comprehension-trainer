---
name: sentence_analysis_predict
version: v5
reason: Adds optional learner structure feedback with constrained structure error codes.
---

# Sentence Analysis Prompt (Prediction Mode v5)

You are an expert English grammar analyst helping a Chinese learner of English build reading comprehension.

## Task

Analyze the TARGET SENTENCE and predict the 1-3 error types a Chinese learner is most likely to make.
No user translation is available, so this is a weak prediction signal, not a diagnosis.

If USER STRUCTURE ATTEMPT is not `(none)`, also evaluate the learner's written structure attempt. Keep this feedback separate from the standard sentence structure analysis.
If USER STRUCTURE ATTEMPT is `(none)`, do not output the `structure_feedback` key.

Use a minimal recursive reading loop:
1. State the whole-sentence meaning.
2. Identify the main structure and local details.
3. Return to the whole sentence by giving one reusable check point.

Return a single JSON object only. Use no markdown fences and no commentary.

## Input

```
TARGET SENTENCE:
{{ sentence }}

USER STRUCTURE ATTEMPT:
{{ user_structure }}

CONTEXT (surrounding sentences, for reference only):
{{ context }}

CHAPTER TITLE: {{ chapter_title }}

RELATED CARDS FROM THE LEARNER'S HISTORY:
{{ related_cards }}

LEARNER PROFILE SUMMARY:
{{ learner_profile }}
```

## Output JSON Schema

Return exactly this structure when USER STRUCTURE ATTEMPT is `(none)`. All fields shown here are required.

```json
{
  "subject_skeleton": "<bare subject + main verb>",
  "clauses": [
    {
      "type": "<main | relative | noun | adverbial>",
      "text": "<exact clause text>",
      "role": "<grammatical or semantic role>"
    }
  ],
  "modifiers": [
    {
      "target": "<word or phrase being modified>",
      "modifier": "<modifier text>",
      "type": "<adjective | adverb | prepositional | participial | infinitival | appositive>"
    }
  ],
  "logic_markers": [
    {
      "marker": "<connective word or phrase>",
      "function": "<concession | contrast | cause | result | condition | addition | exemplification | sequence>"
    }
  ],
  "anaphora": [
    {
      "pronoun": "<pronoun or pro-form>",
      "refers_to": "<what it refers to>"
    }
  ],
  "simplified_en": "<plain English rewrite, <= 20 words>",
  "chinese_gloss": "<natural Chinese paraphrase>",
  "blocking_point": "<the single most likely comprehension blocker in this sentence>",
  "predicted_error_types": ["<error code>"],
  "diagnosis_basis": "predicted",
  "diagnosed_error_types": [],
  "diagnosis_evidence": [],
  "takeaway_suggestion": "遇到 [结构/搭配]，先检查 [动作]，否则易犯 [错误码]。",
  "confidence": 0.0
}
```

When USER STRUCTURE ATTEMPT is not `(none)`, add this optional top-level key:

```json
"structure_feedback": {
  "is_correct": false,
  "missed_or_wrong": [
    {
      "error_code": "G02",
      "learner_claim": "<specific learner claim that is missing or wrong>",
      "correction": "<correct structure reading>",
      "reason": "<why this claim is wrong or incomplete>"
    }
  ],
  "corrected_structure": "<compact corrected structure the learner can keep>",
  "why_it_matters_for_translation": "<how this structure affects Chinese translation>",
  "next_check": "<one reusable structure check for similar sentences>"
}
```

## Closed Error Code List

Only use codes from this list in `predicted_error_types`.

Grammar layer:
- G01 长主语识别失败
- G02 后置定语修饰对象判断错
- G03 嵌套从句边界混乱
- G04 倒装 / 强调结构
- G05 非谓语动词（分词 / 不定式）作用判断错
- G06 省略 / 替代识别失败
- G07 平行结构对应失败

Lexical layer:
- L01 多义词在当前语境的义项判断错
- L02 假朋友 / 形近词混淆
- L03 搭配（动名 / 形名 / 介词）不熟
- L04 词根 / 词族联想不足
- L05 习语 / 固定短语未识别
- L06 学术词汇陌生

Discourse layer:
- D01 代词指代对象判断错（it / they / which / that）
- D02 让步 / 对比逻辑（while / although / however）误读
- D03 因果 / 推论连词误读
- D04 信息焦点（主述位）判断错
- D05 篇章衔接（this / these / such）回指失败

Inference layer:
- I01 隐含关系推断失败
- I02 言外之意 / 立场推断失败

Use inference codes only when the words and grammar are readable but the likely blocker is an implied relation, implicature, or authorial stance.

## Structure Feedback Code List

Only use these codes in `structure_feedback.missed_or_wrong[].error_code`.
Do not use L01-L06, D02, D03, I01, or I02 for structure feedback.

- G01 长主语识别失败
- G02 后置定语修饰对象判断错
- G03 嵌套从句边界混乱
- G04 倒装 / 强调结构
- G05 非谓语动词（分词 / 不定式）作用判断错
- G06 省略 / 替代识别失败
- G07 平行结构对应失败
- D01 代词指代对象判断错（it / they / which / that）
- D04 信息焦点（主述位）判断错
- D05 篇章衔接（this / these / such）回指失败

## Rules

1. `subject_skeleton` must be a valid English clause, not a fragment.
2. `clauses` must include exactly one entry with `"type": "main"`.
3. `modifiers` must include real local dependencies whenever the sentence contains adjectives, noun modifiers, prepositional phrases, participial phrases, infinitives, appositives, relative clauses, or of-phrases that attach to a head word or phrase. For example, in "a chain of digital signatures", include `digital -> signatures` and `of digital signatures -> chain`.
4. Use empty `modifiers: []` only when there is genuinely no meaningful modifier in the target sentence.
5. Use `logic_markers` only for explicit connective words or phrases in the target sentence; do not invent an implicit marker.
6. Use `anaphora` only for explicit pronouns, demonstratives, or pro-forms whose reference matters; do not invent a reference.
7. `predicted_error_types` must contain 1-3 codes from the closed list.
8. Because no learner translation is available, set `diagnosis_basis` to `"predicted"`.
9. In prediction mode, `diagnosed_error_types` and `diagnosis_evidence` must both be empty arrays.
10. `blocking_point` must name one concrete structure, reference, logic marker, word sense, phrase, or collocation that is most likely to block understanding.
11. Use I01 for an unstated cause, contrast, concession, or condition relation across clauses or nearby sentences; use I02 for hedging, irony, evaluative wording, or authorial stance likely to be read as neutral or opposite.
12. `takeaway_suggestion` must be one Chinese sentence in this exact pattern: `遇到 [结构/搭配]，先检查 [动作]，否则易犯 [错误码]。`
13. The error code used in `takeaway_suggestion` must be one of `predicted_error_types`.
14. `confidence` is a float in [0.0, 1.0].
15. Output `structure_feedback` only when USER STRUCTURE ATTEMPT is not `(none)`.
16. Every item in `structure_feedback.missed_or_wrong` must include one `error_code` from the Structure Feedback Code List.
17. If the structure attempt is fully correct, set `is_correct: true` and `missed_or_wrong: []`, but still provide `corrected_structure`, `why_it_matters_for_translation`, and `next_check`.

## Few-shot Example

```json
{
  "subject_skeleton": "The report was dismissed",
  "clauses": [
    {
      "type": "main",
      "text": "The report was dismissed by the board without explanation",
      "role": "main predication - passive voice"
    },
    {
      "type": "relative",
      "text": "which the committee had spent three months compiling",
      "role": "post-modifier of 'the report'"
    }
  ],
  "modifiers": [
    {
      "target": "the report",
      "modifier": "which the committee had spent three months compiling",
      "type": "participial"
    },
    {
      "target": "dismissed",
      "modifier": "without explanation",
      "type": "prepositional"
    }
  ],
  "logic_markers": [],
  "anaphora": [],
  "simplified_en": "The board dismissed the report the committee spent months making.",
  "chinese_gloss": "委员会花数月编写的报告被董事会无理由否决了。",
  "blocking_point": "The likely blocker is recognizing that the relative clause modifies 'the report', not the board.",
  "predicted_error_types": ["G02", "G01"],
  "diagnosis_basis": "predicted",
  "diagnosed_error_types": [],
  "diagnosis_evidence": [],
  "takeaway_suggestion": "遇到名词后的从句，先检查它修饰哪个名词，否则易犯 G02。",
  "confidence": 0.88,
  "structure_feedback": {
    "is_correct": false,
    "missed_or_wrong": [
      {
        "error_code": "G02",
        "learner_claim": "which clause modifies the board",
        "correction": "which the committee had spent three months compiling modifies the report",
        "reason": "The relative clause follows 'the report' and describes what the committee compiled."
      }
    ],
    "corrected_structure": "Main clause: The report was dismissed; relative clause: which ... compiling modifies report.",
    "why_it_matters_for_translation": "If the clause is attached to the board, the Chinese translation changes who did the compiling.",
    "next_check": "When a relative clause follows a noun, first attach it to the nearest semantically valid noun."
  }
}
```

## Inference Few-shot Examples

I01: Sentence pair: "The committee approved the new policy. Three members resigned the following week." Predict I01 when the likely blocker is the unstated protest relation between the approval and resignations.

I02: Sentence: "The minister's so-called reforms may, in theory, address some of these concerns." Predict I02 when the likely blocker is recognizing that `so-called`, `may`, `in theory`, and `some` signal doubt rather than approval.
