---
name: paragraph_logic_lens
version: v1
reason: Initial paragraph-level argument analysis for Logic Reading Lens Feature 2.
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

Sentence list with stable ids:

{{ sentence_lines }}

Nearby context:

{{ context }}

Return exactly this JSON shape:

{
  "paragraph_main_claim": "string",
  "argument_flow": [
    {
      "sentence_id": 123,
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
