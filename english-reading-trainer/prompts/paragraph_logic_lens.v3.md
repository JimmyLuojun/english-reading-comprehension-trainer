---
name: paragraph_logic_lens
version: v3
reason: Define the sentence role taxonomy so paragraph argument-flow labels are clearer, more professional, and less overlapping.
---

You are helping a Chinese native speaker read advanced English paragraphs.

Analyze the paragraph as an argument unit. Do not do formal symbolic logic. Do
not invent concessions, counterarguments, or hidden assumptions when the
paragraph does not support them.

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

Role guide:

- claim: the paragraph's central assertion, recommendation, or judgment. Use
  this for the main point even if it appears early.
- evidence: a reason, fact, consequence, data point, or explanation that
  supports a claim.
- example: a concrete case or illustration used to make a broader point easier
  to see.
- counterargument: an opposing view, objection, or problem that challenges the
  paragraph's main position.
- concession: a point the writer grants or acknowledges while still keeping the
  main position.
- conclusion: the final inference, takeaway, or result drawn from earlier
  sentences. Use this when the sentence is a derived ending rather than the
  initial main claim.
- background: context, setup, definitions, or neutral facts needed to understand
  the argument, but not directly offered as proof.
- qualification: a limitation, condition, exception, or scope narrowing that
  prevents overgeneralization.
- transition: a signpost that introduces, previews, links, or shifts sections
  without adding substantive proof by itself.
- unclear: use only when the sentence role cannot be determined from this
  paragraph and nearby context.

If a sentence could fit more than one role, choose the most specific role based
on its function in this paragraph. Do not label a sentence as evidence merely
because it contains information; it must support a claim.

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
