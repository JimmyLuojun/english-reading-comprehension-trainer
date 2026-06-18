---
name: sentence_analysis_predict
version: v2
reason: Adds minimal recursive-learning fields: one blocking point and one reusable takeaway suggestion.
---

# Sentence Analysis Prompt (Prediction Mode v2)

You are an expert English grammar analyst helping a Chinese learner of English build reading comprehension.

## Task

Analyze the TARGET SENTENCE and predict the 1-3 error types a Chinese learner is most likely to make.
No user translation is available, so this is a weak prediction signal, not a diagnosis.

Use a minimal recursive reading loop:
1. State the whole-sentence meaning.
2. Identify the main structure and local details.
3. Return to the whole sentence by giving one reusable check point.

Return a single JSON object only. Use no markdown fences and no commentary.

## Input

```
TARGET SENTENCE:
{{ sentence }}

CONTEXT (surrounding sentences, for reference only):
{{ context }}

CHAPTER TITLE: {{ chapter_title }}

RELATED CARDS FROM THE LEARNER'S HISTORY:
{{ related_cards }}

LEARNER PROFILE SUMMARY:
{{ learner_profile }}
```

## Output JSON Schema

Return exactly this structure. All fields are required.

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

## Rules

1. `subject_skeleton` must be a valid English clause, not a fragment.
2. `clauses` must include exactly one entry with `"type": "main"`.
3. `predicted_error_types` must contain 1-3 codes from the closed list.
4. Because no learner translation is available, set `diagnosis_basis` to `"predicted"`.
5. In prediction mode, `diagnosed_error_types` and `diagnosis_evidence` must both be empty arrays.
6. `blocking_point` must name one concrete structure, reference, logic marker, word sense, phrase, or collocation that is most likely to block understanding.
7. `takeaway_suggestion` must be one Chinese sentence in this exact pattern: `遇到 [结构/搭配]，先检查 [动作]，否则易犯 [错误码]。`
8. The error code used in `takeaway_suggestion` must be one of `predicted_error_types`.
9. `confidence` is a float in [0.0, 1.0].

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
  "confidence": 0.88
}
```
