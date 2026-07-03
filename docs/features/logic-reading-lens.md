# Logic Reading Lens / 文章逻辑视角

Status: implemented.

This feature is split into two deployable parts. Feature 1 adds sentence-level
argument role metadata to the existing sentence analysis. Feature 2 adds an
explicit paragraph selection workflow and paragraph-level argument analysis.

Implemented state:

- Feature 1 is live in sentence analysis prompt/schema v7 and the Reader panel.
- Feature 2 is live in the Reader: click a normal paragraph, press bare `p`,
  use the separate paragraph toolbar, then run or copy paragraph argument
  analysis.
- Paragraph analysis uses `paragraph_logic_lens.v3`, validates against
  `PARAGRAPH_LOGIC_LENS_SCHEMA`, caches in `ai_cache`, and is not attached to
  sentence cards, Review, or `sentence_card_errors`.
- `paragraph_logic_lens.v3` keeps original sentence text beside stable internal
  ids and defines the role taxonomy for claim/evidence/example/counterargument/
  concession/conclusion/background/qualification/transition/unclear.

The boundary is intentional:

- Sentence analysis answers: what job is this sentence doing?
- Paragraph analysis answers: how does this whole paragraph argue?

This should not become formal logic-rules practice. Truth tables, predicate
logic, natural deduction, and symbolic proof drills stay in the separate
`Logic_Rules_Methods_Practice` project.

## Existing Coverage

The current sentence analysis already covers much of a light "logic lens":

- `logic_markers` identifies explicit connectors.
- `I01` tags missed implied relations such as unstated cause, contrast,
  concession, or condition.
- `I02` tags missed stance, hedging, implicature, or evaluative tone.
- `blocking_point` identifies the main comprehension blocker.
- `takeaway_suggestion` gives a reusable reading check.

Because these fields already exist, do not add a separate sentence-level
`Analyze logic` button. It would duplicate the normal sentence analysis path
and double API cost without adding enough value.

## Non-goals

- Do not add a formal logic parser.
- Do not add truth-table, predicate-logic, syllogism, or proof UI.
- Do not create a second error taxonomy.
- Do not auto-analyze every paragraph or every sentence.
- Do not create a second Review system for paragraph analysis.
- Do not write paragraph-role signals into `sentence_card_errors`.

---

## Feature 1: Sentence Argument Role

Goal: extend the existing sentence analysis so the Reader can show what role
the sentence plays in the local argument.

This is lightweight metadata, not a new analysis mode.

### User Value

Advanced reading mistakes often come from misidentifying the job of a sentence:

- treating evidence as the author's main claim;
- treating a concession as agreement;
- missing that a sentence qualifies or limits the previous point;
- reading background as conclusion;
- failing to notice a transition before the argument turns.

The useful habit is:

```text
Before translating deeply, ask whether this sentence is making, supporting,
limiting, opposing, or concluding a point.
```

### Output Fields

Add these fields to the existing sentence analysis JSON:

```json
{
  "argument_role": "evidence",
  "argument_role_reason": "This sentence gives a concrete result supporting the previous claim.",
  "argument_role_check": "Do not treat supporting evidence as the author's final conclusion."
}
```

`argument_role` enum:

```text
claim
evidence
example
counterargument
concession
conclusion
background
qualification
transition
unclear
```

Use `unclear` when the sentence role cannot be determined from the sentence and
available local context. Do not force a confident label.

### Implementation Plan

No database migration is needed. The fields live in `ai_cache.response_json`
with the rest of sentence analysis.

1. Create immutable prompt files:
   - `english-reading-trainer/prompts/sentence_analysis_predict.v7.md`
   - `english-reading-trainer/prompts/sentence_analysis_diagnose.v7.md`
2. In both v7 prompts:
   - add `argument_role`, `argument_role_reason`, and `argument_role_check`;
   - require the enum above;
   - instruct the model to use paragraph/local context when available;
   - instruct the model to use `unclear` rather than guessing.
3. Add a new sentence schema constant in
   `english-reading-trainer/app/ai/ai_json_schemas.py` based on the current v6
   schema and requiring the three new fields.
4. Update `english-reading-trainer/app/ai/llm_sentence_analyzer.py`:
   - bump `_PROMPT_VERSION` from `v6` to `v7`;
   - map `prompt_version == "v7"` to the new schema;
   - keep older schema mappings intact.
5. Pass local paragraph context into sentence analysis where practical:
   - `analyze_sentence()` already accepts `context`;
   - update the Reader service/query path so a sentence analysis can receive
     the target paragraph text or nearby sentences;
   - because context is part of the cache hash, the v7 prompt bump should be
     treated as a normal cache-version boundary.
6. Render the fields in the existing right analysis panel:
   - place the role near `blocking_point`;
   - show the role as a compact label;
   - show `argument_role_reason` and `argument_role_check` as normal analysis
     text, not decorative-only metadata.
7. Include the three fields in the panel copy/export helper.

### UI Copy

Suggested labels:

```text
Argument role
Why this role
Reading check
```

Example display:

```text
Argument role: evidence
Why this role: It gives survey results supporting the previous claim.
Reading check: Do not mistake supporting data for the author's final conclusion.
```

### Tests

- Prompt tests:
  - both `sentence_analysis_predict.v7.md` and
    `sentence_analysis_diagnose.v7.md` load;
  - frontmatter versions match file names;
  - both prompts contain the role enum and the three field names.
- Schema tests:
  - v7 accepts valid role output;
  - invalid role values are rejected;
  - missing `argument_role_reason` or `argument_role_check` is rejected;
  - old v6-compatible outputs remain valid only under the v6 schema.
- Analyzer tests:
  - `_sentence_analysis_schema("v7")` returns the new schema;
  - mocked prediction and diagnosis calls return the role fields.
- Reader tests:
  - panel renders role, reason, and check;
  - copy helper includes role, reason, and check.
- Web lint:
  - run `english-reading-trainer/.venv/bin/python -m ruff check english-reading-trainer/app/web`.
- Full suite:
  - run `english-reading-trainer/.venv/bin/python -m pytest english-reading-trainer/tests/`.

### Acceptance Criteria

- Sentence analysis v7 has the three new fields in both prediction and
  diagnosis modes.
- The fields are validated by schema, not accepted as arbitrary extras.
- Reader shows the role plus reason and check.
- No new DB migration is introduced.
- No new Review or card behavior is introduced.

---

## Feature 2: Paragraph Selection And Paragraph Logic Lens

Goal: let the user select a whole paragraph with a keyboard action, then run a
paragraph-level argument analysis from a separate paragraph flying layer.

This is the real "Logic Lens" mode. It is paragraph-level and user-triggered.

### Interaction

1. User clicks inside a reader paragraph.
2. Reader stores that paragraph as the active paragraph.
3. User presses bare `p`.
4. The paragraph gets a highlighted background.
5. A new paragraph flying layer appears near the paragraph.
6. The flying layer offers MVP buttons:
   - `Analyze argument`
   - `Copy prompt`
   - `Dismiss`
7. `Analyze argument` opens the existing right-side analysis panel shell in
   paragraph mode.

The paragraph flying layer must be separate from the sentence selection toolbar.
Use a new DOM element such as `#paragraph-toolbar`; do not overload
`#selection-toolbar`.

The right-side drawer can reuse the existing `#analysis-panel` shell, but it
must render a distinct paragraph mode so sentence analysis state does not leak
into paragraph analysis.

### Paragraph Output Schema

Add a new paragraph logic schema, separate from sentence analysis:

```json
{
  "paragraph_main_claim": "The author argues that the policy failed because it ignored local incentives.",
  "argument_flow": [
    {
      "sentence_id": 123,
      "sentence_text": "The policy was introduced to solve the shortage.",
      "role": "background",
      "reason": "This sentence establishes the policy context."
    },
    {
      "sentence_id": 124,
      "sentence_text": "Yet it failed because local incentives did not change.",
      "role": "claim",
      "reason": "This sentence states the paragraph's main judgment."
    },
    {
      "sentence_id": 125,
      "sentence_text": "Local behavior therefore remained unchanged.",
      "role": "evidence",
      "reason": "This sentence provides the concrete result supporting the claim."
    }
  ],
  "evidence": [
    "The paragraph cites the policy's failure to change local behavior."
  ],
  "concession_or_counterpoint": "The paragraph briefly admits the policy had a plausible goal.",
  "hidden_assumption": "Changing formal rules is insufficient unless incentives change.",
  "author_stance": "Skeptical of the policy's effectiveness.",
  "possible_misreading": "A reader may treat the background sentence as the main claim.",
  "reading_check": "Identify which sentence states the point and which sentences merely support it.",
  "takeaway_suggestion": "遇到一段先铺背景再下判断，先找作者真正评价的那一句。"
}
```

`argument_flow[].role` should use the same enum as Feature 1:

```text
claim
evidence
example
counterargument
concession
conclusion
background
qualification
transition
unclear
```

Use nullable or empty-string fields for `concession_or_counterpoint` and
`hidden_assumption` when they are not present. Do not invent them for every
paragraph.

### Implementation Plan

No DB migration is required for the MVP. Cache paragraph analyses by recomputing
a paragraph content hash and writing valid JSON to `ai_cache`.

1. Reader markup:
   - add `data-paragraph-id` to paragraph wrappers in
     `english-reading-trainer/app/web/views/reader.py`;
   - start with normal paragraphs (`.reader-para`);
   - list items can be a later extension unless implementation is simple.
2. Reader script:
   - track `activeParagraph` on click inside `.reader-para`;
   - on bare `p`, select/highlight the active paragraph;
   - ignore `p` when focus is in input, textarea, select, contenteditable, or
     an open editor;
   - show a new `#paragraph-toolbar`;
   - hide the sentence toolbar before showing paragraph toolbar;
   - `Dismiss` clears highlight and toolbar.
3. Styles:
   - add a stable paragraph highlight class such as `.reader-para.logic-selected`;
   - add paragraph toolbar styling separate from `.selection-toolbar`.
4. Backend query:
   - add a helper to fetch paragraph text and sentence ids by `paragraph_id`;
   - include previous/next paragraph text as context when available;
   - preserve original sentence order.
5. AI pipeline:
   - add prompt `english-reading-trainer/prompts/paragraph_logic_lens.v3.md`;
   - add a `PARAGRAPH_LOGIC_LENS_SCHEMA`;
   - add a small service such as `analyze_paragraph_logic_for_reader`;
   - use `ai_cache` with a distinct prompt version such as
     `paragraph_logic_lens.v3`;
   - do not attach paragraph analysis to `sentence_cards.ai_analysis_id`.
6. Routes:
   - `POST /analysis/paragraph/{paragraph_id}/logic` analyzes and returns the
     paragraph payload;
   - optionally add `GET /analysis/paragraph/{paragraph_id}/logic-prompt` for
     external AI copy/paste parity.
7. Right panel:
   - add paragraph mode state to the existing analysis panel shell;
   - clear sentence-specific fields when paragraph mode opens;
   - render paragraph main claim, argument flow, evidence, stance, hidden
     assumption, possible misreading, reading check, and takeaway suggestion.
8. Copy prompt:
   - the paragraph toolbar `Copy prompt` can call the optional external-prompt
     route or build from current paragraph text;
   - copied prompt must include paragraph text and nearby context, not just the
     clicked sentence.

### MVP Buttons

Start with only:

```text
Analyze argument
Copy prompt
Dismiss
```

Do not add `Find claim`, `Explain paragraph`, or `Save takeaway` in the first
PR. Those are natural follow-ups after the core flow is stable.

### Tests

- Reader view tests:
  - paragraph markup includes `data-paragraph-id`;
  - paragraph toolbar DOM exists and is separate from `#selection-toolbar`.
- Reader script tests:
  - bare `p` selects the clicked paragraph;
  - `p` is ignored in text inputs/editors;
  - paragraph selection hides sentence toolbar;
  - `Dismiss` clears highlight;
  - generated fixture stays in sync.
- Query/service tests:
  - paragraph fetch returns target text, ordered sentence ids, and local context;
  - missing paragraph returns a controlled error.
- Schema tests:
  - valid paragraph analysis passes;
  - invalid `argument_flow[].role` is rejected;
  - extra fields are rejected.
- Route tests:
  - `POST /analysis/paragraph/{id}/logic` returns payload;
  - validation failure returns a retryable AI error without saving invalid data
    as a successful analysis.
- Web lint:
  - run `english-reading-trainer/.venv/bin/python -m ruff check english-reading-trainer/app/web`.
- Full suite:
  - run `english-reading-trainer/.venv/bin/python -m pytest english-reading-trainer/tests/`.

### Acceptance Criteria

- Clicking a paragraph and pressing `p` highlights exactly that paragraph.
- Paragraph toolbar is visually and logically separate from the sentence
  selection toolbar.
- `Analyze argument` opens the right panel in paragraph mode.
- Paragraph analysis uses whole-paragraph text plus local context.
- No sentence card, Review row, or `sentence_card_errors` row is created by
  paragraph analysis.
- Paragraph analysis is cached, but not attached to sentence-card analysis.

---

## Suggested Deployment Order

Deploy in three small PRs or checkpoints:

1. Feature 1: sentence `argument_role` v7 prompt/schema/panel.
2. Feature 2A: paragraph selection UI only (`p`, highlight, toolbar, no AI).
3. Feature 2B: paragraph AI analysis backend, prompt/schema, route, and panel
   rendering.

This keeps failures easy to isolate. If Feature 1 proves useful, it improves
normal sentence analysis immediately. If Feature 2A feels awkward in the
browser, fix the interaction before spending API/prompt work on Feature 2B.
