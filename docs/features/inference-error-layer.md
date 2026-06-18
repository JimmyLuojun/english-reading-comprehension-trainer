# Inference Error Layer — Executable Plan

Status: implemented (decision accepted in `../decisions/2026-06-18-inference-error-layer.md`)

Add a fourth error layer `inference` with two codes, `I01` and `I02`, to close the comprehension-level gap in the closed error taxonomy. This is the smallest change that lets the AI diagnose "understood every word and grammar point, but missed the author's meaning."

## The two new codes

| code | name (zh) | layer | what it tags |
|------|-----------|-------|--------------|
| `I01` | 隐含关系推断失败 | `inference` | A cause / contrast / concession / condition relation across clauses or sentences carries **no explicit connective** and must be inferred. Reader treats the parts as unrelated, or infers the wrong relation. |
| `I02` | 言外之意 / 立场推断失败 | `inference` | Implicature and authorial stance. Hedging / evaluative / ironic signals (e.g. `so-called`, `may`, `in theory`, `some`, `fails to`) read as a neutral or opposite assertion. |

Worked examples for the prompt few-shots:

- `I01` — *"The committee approved the new policy. Three members resigned the following week."* No connective, but the resignations are an implied protest **caused by** the approval. Diagnose `I01` when the translation keeps the two facts unrelated.
- `I02` — *"The minister's so-called reforms may, in theory, address some of these concerns."* `so-called` + `may` + `in theory` + `some` signal the author's doubt. Diagnose `I02` when the translation reads it as neutral or approving.

## Files to change

Source of truth flows: `db_models` → migration (DB) + JSON schema enum (auto) + prompts (manual) → tests + docs.

### 1. `english-reading-trainer/app/db_models.py`

- Add `INFERENCE = "inference"` to the `ErrorLayer` enum.
- Append two entries to `ERROR_TYPES` after the discourse block:
  - `{"code": "I01", "name": "隐含关系推断失败", "layer": ErrorLayer.INFERENCE}`
  - `{"code": "I02", "name": "言外之意 / 立场推断失败", "layer": ErrorLayer.INFERENCE}`
- `VALID_ERROR_CODES` derives from `ERROR_TYPES`; no manual edit.

### 2. New migration `english-reading-trainer/migrations/009_inference_error_layer.sql`

The `error_types.layer` column has `CHECK(layer IN ('grammar','lexical','discourse'))`. SQLite cannot alter a CHECK constraint in place, so rebuild the table:

1. Create `error_types_new` identical to `error_types` but with `CHECK(layer IN ('grammar','lexical','discourse','inference'))`.
2. `INSERT INTO error_types_new SELECT * FROM error_types;`
3. Drop `error_types`, rename `error_types_new` to `error_types`.
4. Recreate any index/foreign-key references that the rebuild dropped (check `001_initial_schema.sql` for the original definition and the `sentence_card_errors` / `word_card_errors` FKs to `error_types(id)`).
5. `INSERT OR IGNORE INTO error_types (code, name, layer) VALUES ('I01', '隐含关系推断失败', 'inference'), ('I02', '言外之意 / 立场推断失败', 'inference');`

Keep the migration idempotent / safe to re-run. Verify the FK targets in `sentence_card_errors` and `word_card_errors` still resolve after the rebuild (preserve `error_types.id` values by selecting all columns including `id`).

### 3. JSON schema — `english-reading-trainer/app/ai/ai_json_schemas.py`

No change. `_ERROR_CODES = sorted(VALID_ERROR_CODES)` picks up I01/I02 automatically, and all `enum` references derive from it.

### 4. Prompts (immutable — create new versions, do not edit v2)

- Copy `prompts/sentence_analysis_diagnose.v2.md` → `sentence_analysis_diagnose.v3.md`. Set frontmatter `version: v3` and a `reason` mentioning the inference layer. Add an "Inference layer" block to the Closed Error Code List:
  ```
  Inference layer:
  - I01 隐含关系推断失败
  - I02 言外之意 / 立场推断失败
  ```
  Add a short instruction that inference codes apply when the words and grammar are correctly decoded but an implied relation, implicature, or authorial stance is missed. Optionally add an `I01` or `I02` few-shot using the worked examples above.
- Copy `prompts/sentence_analysis_predict.v2.md` → `sentence_analysis_predict.v3.md` with the same inference-layer addition.
- **Do not** change `word_analysis.v5.md`. The inference layer is sentence-level; a single word/phrase cannot carry an implicature diagnosis.
- `prompt_version_registry.sync_prompt_versions` activates the newest version per name automatically once the v3 files exist; no code change. Old v2-cached analyses become stale and re-run on next request (accepted).

### 5. Reader panel label map — `english-reading-trainer/app/web/views/reader_script.py`

The error-code label object (around the `X00: "X00 其他"` entry) is display-only. Add:
```
I01: "I01 隐含关系推断失败",
I02: "I02 言外之意 / 立场推断失败",
```

### 6. Architecture doc — `docs/architecture/data-model.md` §2

Add a new subsection `### 2.4 推理层 inference` listing I01/I02 with one-line descriptions, before the existing fallback subsection. Keep the "closed enumeration" principle text. Renumber the fallback subsection if needed and note that `X00` is currently documented but not seeded.

### 7. Generated schema — `docs/state/schema.sql`

Regenerate from the real SQLite schema after running migration 009 (the `CHECK` constraint text changes). Do not hand-edit.

## Tests (no untested merge)

- `tests/test_db_models.py`:
  - `test_error_types_has_18_entries` → 20.
  - Add `test_inference_layer_has_2_codes`.
  - `test_error_layer_values` expected set → add `"inference"`.
  - Verify I01/I02 present and codes still unique.
- `tests/test_prompts.py`:
  - The diagnose/predict prompt code-coverage assertions (currently require G/L/D codes present) — add an inference-codes-present assertion for the v3 prompts. The `codes - VALID_ERROR_CODES` invalid-code checks pass automatically once I01/I02 are in the enum.
  - `test_word_prompt_covers_lexical_layer` stays as-is (word prompt unchanged).
- Migration: add a **real SQLite integration test** (not mocked, per project rule) that applies migrations through 009 and asserts:
  - `error_types` contains I01/I02 with layer `inference`.
  - The relaxed `CHECK` accepts an `inference` row and still rejects an unknown layer.
  - Existing `sentence_card_errors` / `word_card_errors` FK rows survive the table rebuild.
- Mirror any other test that hard-codes the 18-code count or the three-layer set.

## Verification

- `english-reading-trainer/.venv/bin/python -m pytest tests/` (full suite).
- `english-reading-trainer/.venv/bin/python -m ruff check app/web` if `reader_script.py` changed.
- Confirm `docs/state/schema.sql` was regenerated from real SQLite, and update `STATUS.md` with the new layer and any in-flight notes.

## Explicitly out of scope (deferred)

- Macro-structure code (paragraph-level argument: claim → evidence → counter → conclusion).
- Negation / comparison / quantifier scope code.

Add these only after reviewing real usage data, and batch them into a single prompt-version bump.
