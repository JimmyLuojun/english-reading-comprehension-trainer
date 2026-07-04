---
name: paragraph_logic_lens
version: v4
reason: Add optional connector_function metadata so paragraph movement can be explained without splitting transition into many primary roles.
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
- transition: a pure signpost that introduces, previews, links, or shifts
  sections without adding substantive proof by itself.
- unclear: use only when the sentence role cannot be determined from this
  paragraph and nearby context.

If a sentence could fit more than one role, choose the most specific role based
on its function in this paragraph. Do not label a sentence as evidence merely
because it contains information; it must support a claim.

Primary role rule:

- `role` = what the sentence contributes to the argument.
- `connector_function` = how the sentence connects to nearby sentences.

Do not split transition into many primary roles. Use role `transition` only for
pure signpost sentences. If a sentence makes a claim, gives evidence, provides
an example, grants a concession, or draws a conclusion, keep that primary role
even when it contains a connector such as "however", "for example", or
"therefore".

Optional connector_function guide for `argument_flow[]`:

Include `connector_function` only when it helps the learner understand paragraph
movement. Omit it when no useful connector function is present.

- addition: adds another parallel point.
- contrast: marks difference, opposition, or a turn.
- cause: gives a cause, reason, or basis.
- result: gives a consequence, result, or inference signal.
- example: introduces an illustration.
- concession: admits a point while preserving the main direction.
- sequence: orders steps or stages.
- clarification: restates, defines, or explains more precisely.
- summary: condenses or wraps up earlier material.
- topic_shift: moves to a different aspect or issue.
- emphasis: highlights importance or priority.
- condition: states an if/unless/provided-that condition.
- purpose: states an aim or intended effect.

Paragraph to analyze:

{{ paragraph }}

Sentence list with stable ids and original sentence text:

{{ sentence_lines }}

Nearby context:

{{ context }}

For each `argument_flow` item:

- Keep `sentence_id` as the stable internal id from the sentence list.
- Set `sentence_text` to the exact original English sentence text for that id.
- Set `role` based on the sentence's argumentative job, not merely on connector
  words.
- Add `connector_function` only when the connection itself is useful for a
  learner to notice.
- In explanations for learners, refer to the original sentence text, not only
  the id.

Return exactly this JSON shape:

{
  "paragraph_main_claim": "string",
  "argument_flow": [
    {
      "sentence_id": 123,
      "sentence_text": "Original English sentence text.",
      "role": "claim",
      "connector_function": "contrast",
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
