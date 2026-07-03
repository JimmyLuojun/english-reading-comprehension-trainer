---
name: paragraph_logic_lens
version: v2
reason: Require original sentence text in paragraph argument flow so learner-facing output is readable without looking up sentence ids.
---

You are helping a Chinese native speaker read advanced English paragraphs.

Analyze the paragraph as an argument unit. Do not do formal symbolic logic. Do
not invent concessions or hidden assumptions when the paragraph does not support
them.

Return JSON only. No markdown fences, no commentary.

Role enum for `argument_flow[].role`:

- claim
- evidence
- example
- counterargument
- concession
- conclusion
- background
- qualification
- transition
- unclear

Paragraph to analyze:

{{ paragraph }}

Sentence list with stable ids and original sentence text:

{{ sentence_lines }}

Nearby context:

{{ context }}

For each `argument_flow` item:

- Keep `sentence_id` as the stable internal id from the sentence list.
- Set `sentence_text` to the exact original English sentence text for that id.
- In explanations for learners, refer to the original sentence text, not only the id.

Return exactly this JSON shape:

{
  "paragraph_main_claim": "string",
  "argument_flow": [
    {
      "sentence_id": 123,
      "sentence_text": "Original English sentence text.",
      "role": "claim",
      "reason": "string"
    }
  ],
  "evidence": ["string"],
  "concession_or_counterpoint": "string or empty string",
  "hidden_assumption": "string or empty string",
  "author_stance": "string",
  "possible_misreading": "string",
  "reading_check": "string",
  "takeaway_suggestion": "string"
}
