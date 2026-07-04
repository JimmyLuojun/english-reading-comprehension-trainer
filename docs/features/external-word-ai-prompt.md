# External Word AI Prompt / 外部 AI 词汇分析提示词

Status: implemented on 2026-07-04.

This feature lets the reader select an unfamiliar word, phrase, or collocation
in the original article, copy a high-quality external AI prompt immediately, use
a stronger web AI for fast analysis, and optionally paste the validated result
back into the app.

Implemented scope:

- Reader selection toolbar uses the grouped layout:
  `Word | Phrase | Collocation` plus `Copy prompt` and `AI analysis`.
- Fresh selections can copy an external prompt without creating a word card.
- Existing Word Analysis panels have `Copy prompt`.
- External replies can be pasted back for either a fresh selection or an
  existing card.
- Paste-back extracts the last fenced JSON block, validates it against the
  active `word_analysis` schema, saves a valid `external-ai` cache entry, and
  opens the normal Word Analysis panel.
- Fresh selection paste-back preserves exact `word_card_sources` offsets; if
  the external JSON normalizes the lemma, the selected card/source is still the
  card updated by the analysis.

## Goal

The fastest target workflow is:

```text
select a stranger word
  -> Copy prompt
  -> paste into external web AI
  -> optionally paste JSON back into the app
  -> app validates and saves as a normal word analysis
```

The user must not need to run internal `AI analysis` first. The user must not
need to create a saved word card before copying the external prompt.

The same feature should also work from an existing Word Analysis panel, so a
saved word/phrase/collocation can be re-analyzed by a stronger external model.

## What To Avoid

- Do not force internal `AI analysis` before external prompt copy.
- Do not force card creation before prompt copy.
- Do not identify the selection only by surface text; repeated words in one
  sentence need exact offsets.
- Do not create separate backend systems for word, phrase, and collocation.
  Use one word-analysis path with `lexical_type`.
- Do not auto-save external AI output. Save only after extracting JSON and
  validating it against the word-analysis schema.
- Do not make the floating toolbar a long row of equal buttons. It should feel
  compact, predictable, and easy to scan.

## UX Design

Use a grouped floating toolbar, not a flat five-button row.

Recommended desktop layout:

```text
[ Word | Phrase | Collocation ]   [ Copy prompt ] [ AI analysis ]
```

The first group is a segmented lexical-type selector. The active segment shows
the default type for the current selection, and clicking a segment keeps the
toolbar open so the learner can choose `Copy prompt` or `AI analysis` next.

Button meaning:

- `Word`: use `word` as the target type.
- `Phrase`: use `phrase` as the target type.
- `Collocation`: use `collocation` as the target type.
- `Copy prompt`: copy the external AI prompt for the current selection and
  selected target type.
- `AI analysis`: save the current selection with the selected target type and
  run the internal model.

Default selection:

- One token defaults to `word`.
- Multiple tokens default to `phrase`.
- The active segment is the current target type. Clicking a segment is only a
  type choice; it should show short feedback such as `Using phrase` and must
  not dismiss the toolbar.

Visual behavior:

- Keep the toolbar compact and grouped.
- Use a light surface, subtle shadow, and stable 8px radius.
- Keep controls around 36px high with predictable spacing.
- Show the selected lexical type with a quiet accent.
- Make `Copy prompt` slightly more prominent than `AI analysis`, because the
  external-first path is the desired fast workflow.
- Place the toolbar near the selection, but never over the selected text.
- Flip above/below based on available space.
- Avoid overlapping the right analysis panel.
- `Esc` or outside click dismisses the toolbar.
- After copying, show short in-toolbar feedback such as `Copied`, then dismiss
  or return to the normal state after about one second.

Mobile/narrow fallback:

```text
Word | Phrase | Collocation
Copy prompt | AI analysis
```

The toolbar may wrap into two compact rows, but each row should keep stable
dimensions so the selection action does not jump.

## Reader Flows

### Fresh Stranger Word

1. User selects unfamiliar text in the article.
2. Reader captures:
   - `sentence_id`
   - `surface_form`
   - `lexical_type`
   - `start_offset`
   - `end_offset`
3. User clicks `Copy prompt`.
4. The app calls the selection prompt endpoint and copies the returned prompt.
5. The right panel opens in temporary external-word mode:

```text
External Word Analysis
Prompt copied. Paste external result here.
```

6. User pastes the external AI reply.
7. User clicks `Save analysis`.
8. Backend extracts the final fenced JSON block, validates it, creates/updates
   the word card, saves the analysis as `external-ai`, and opens the normal Word
   Analysis panel.

### Existing Word Analysis Panel

1. User opens a saved Word Analysis panel.
2. User clicks `Copy prompt`.
3. The app calls the existing-card prompt endpoint and copies the returned
   prompt.
4. User may paste the external AI result back.
5. Backend validates and updates the existing word card analysis.

## Backend API

### Selection Prompt

Use this when the selection does not need to be saved before prompt copy.

```text
POST /analysis/selection/word-external-prompt
```

Request:

```json
{
  "sentence_id": 123,
  "surface_form": "evidenced",
  "lexical_type": "word",
  "start_offset": 45,
  "end_offset": 54
}
```

Response:

```json
{
  "ok": true,
  "prompt": "paste-ready prompt text",
  "sentence_id": 123,
  "surface_form": "evidenced",
  "lexical_type": "word",
  "start_offset": 45,
  "end_offset": 54
}
```

Rules:

- `lexical_type` must be `word`, `phrase`, or `collocation`.
- `surface_form` must be non-empty.
- `start_offset` and `end_offset` must point to the selected occurrence in the
  sentence.
- The endpoint does not write to the database.

### Existing Card Prompt

Use this from the Word Analysis panel.

```text
GET /analysis/word/{card_id}/external-prompt
```

Response shape can match the selection prompt response, but the source fields
come from the saved card.

Implemented response:

```json
{
  "ok": true,
  "card_id": 456,
  "sentence_id": 123,
  "surface_form": "evidenced",
  "lexical_type": "word",
  "prompt": "paste-ready prompt text"
}
```

Rules:

- The card must exist and not be archived.
- Prefer the primary source occurrence when available.
- Include source sentence and local context so the external model analyzes the
  word in its real reading context.

### Selection Paste-Back

Use this when a fresh selection has no card yet.

```text
POST /analysis/selection/word-external
```

Request:

```json
{
  "sentence_id": 123,
  "surface_form": "evidenced",
  "lexical_type": "word",
  "start_offset": 45,
  "end_offset": 54,
  "external_result": "full external AI reply ending with a ```json block```"
}
```

Behavior:

- Extract the final fenced `json` block.
- Validate against the active word-analysis schema.
- Create or update the word card.
- Record the exact source occurrence with offsets.
- Save the analysis with model `external-ai`.
- Return the normal Word Analysis panel payload.
- The implemented payload also includes `word_card` and `source` so the Reader
  can refresh the exact source highlight without a page reload.

### Existing Card Paste-Back

Use this from the Word Analysis panel for an already saved card.

```text
POST /analysis/word/{card_id}/external
```

Behavior:

- Extract and validate the final JSON block.
- Save the analysis to the existing card as `external-ai`.
- Return the normal Word Analysis panel payload.
- The implemented payload also includes `word_card` so Reader glossary state can
  refresh immediately.

## Prompt Construction

Reuse the existing word-analysis prompt machinery instead of building prompt
text in JavaScript.

The external wrapper should include:

- selected surface text;
- lexical type;
- source sentence;
- nearby context;
- learner note if a saved card already has one;
- learner profile when available;
- the active `word_analysis.v5` JSON contract.

For external web AI, the wrapper should allow a human-readable explanation first
but require the final machine-readable result as the last fenced JSON block:

````text
1. First explain the word/phrase/collocation for a Chinese native speaker.
2. Then output exactly one final ```json code block``` that matches the project
   JSON contract.
3. The app reads only the last JSON block.
````

This mirrors the sentence and paragraph external-AI loops and keeps save-back
validation deterministic.

## Backend Implementation Notes

Add service helpers in the web analysis service layer:

```python
build_external_word_prompt_for_selection(...)
build_external_word_prompt_for_card(...)
save_external_word_analysis_for_selection(...)
save_external_word_analysis_for_card(...)
```

The selection prompt builder should fetch the sentence, validate the offsets,
compute nearby context, then render the active word prompt.

The save-back path should reuse existing word-analysis validation and saving
logic where possible. If the existing saver cannot preserve offsets, add a thin
web service wrapper that creates the source occurrence after the card is
created/updated.

No schema migration is expected for the first implementation because
`word_card_sources` already stores exact `start_offset`, `end_offset`, and
`selected_text`.

## Frontend Implementation Notes

Reader script state should track a selection snapshot:

```json
{
  "sentenceId": "123",
  "surfaceForm": "evidenced",
  "lexicalType": "word",
  "startOffset": 45,
  "endOffset": 54
}
```

Toolbar behavior:

- On selection, infer default lexical type.
- Render the grouped toolbar.
- Segment changes update the active lexical type without changing the selected
  text.
- `Copy prompt` calls `/analysis/selection/word-external-prompt`, copies the
  prompt, and opens external-word panel mode.
- `AI analysis` runs the internal word-analysis path with the selected lexical
  type.

Panel behavior:

- Add `Copy prompt` to the Word Analysis panel header controls.
- Reuse the existing external-result textarea, but bind it to a word selection
  or word card instead of a sentence/paragraph.
- Save dispatch must know whether the active external result belongs to:
  - sentence;
  - paragraph;
  - word selection;
  - existing word card.

## Tests

Add focused tests before or alongside implementation:

- Service tests:
  - selection prompt accepts valid offsets;
  - invalid lexical type rejected;
  - offset mismatch rejected;
  - existing-card prompt uses the primary source;
  - paste-back validates JSON and saves `external-ai`.
- Router tests:
  - new prompt endpoints return prompt text;
  - paste-back endpoints return normal Word Analysis payload;
  - invalid payloads return 400.
- Reader script tests:
  - grouped toolbar contract exists;
  - single token defaults to `word`;
  - multi-token defaults to `phrase`;
  - lexical type segment controls keep the toolbar open and update the prompt
    payload;
  - `Copy prompt` opens external-word panel mode;
  - Word Analysis panel contains `Copy prompt`.
- Golden fixture:
  - update `tests/fixtures/reader_selection_script.js`.
- Full verification:
  - `english-reading-trainer/.venv/bin/python -m pytest tests/`
  - `english-reading-trainer/.venv/bin/python -m ruff check app/web`
  - `node --check tests/fixtures/reader_selection_script.js`

## Recommended Implementation Order

1. Backend selection prompt endpoint with no DB writes.
2. Existing-card prompt endpoint.
3. Grouped reader toolbar UI and `Copy prompt` copy behavior.
4. Word Analysis panel `Copy prompt`.
5. Selection paste-back endpoint.
6. Existing-card paste-back endpoint.
7. External-word panel mode and save dispatch.
8. Full tests and docs/status update.

If implementation needs to be split, ship steps 1-4 first. They provide the
main speed gain: select unfamiliar text, copy prompt, and use external web AI
without waiting for internal analysis.
