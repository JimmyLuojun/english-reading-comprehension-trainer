# Inference Error Layer

Date: 2026-06-18

## Status

Accepted

## Context

The closed error-type enumeration (see `architecture/data-model.md` §2) has 18 codes across three layers: grammar (G01–G07), lexical (L01–L06), and discourse (D01–D05). This set maps cleanly onto the "syntax / lexis / local cohesion" three-way split from L2 reading research and is complete **as a single-sentence decoding taxonomy** — it covers turning text into propositions.

The product is a reading **comprehension** trainer. In reading research, comprehension = decoding × higher-order processing (Simple View of Reading; Kintsch's construction–integration). The most common advanced-reader failure is "every word and every grammar point understood, but the author's meaning missed." The current taxonomy cannot represent that failure:

- The discourse layer covers only **explicit** local cohesion (pronoun anaphora D01, connective logic D02/D03, theme/rheme D04, surface conjunction D05). It has no code for an **implied** relation that the reader must infer when no connective is present.
- There is no code for implicature or authorial stance/hedging (reading "may suggest", "so-called", evaluative tone as a neutral assertion).

Because the AI diagnosis prompt only allows codes from the closed list, the model cannot tag an inference failure that does not exist in the list. Such failures are currently forced into the nearest wrong discourse code or produce low-confidence noise, so the single most important comprehension signal is hidden. Note: `X00 其他` appears as a display label in `reader_script.py` but is **not** seeded in `db_models.ERROR_TYPES` and is **not** offered in any prompt, so it is not a working fallback today.

Adding codes is not free: the enum is the source of truth in `db_models`, the `error_types.layer` column carries a SQLite `CHECK` constraint, the codes are listed inside the diagnosis/prediction prompts, and changing a prompt requires a new immutable version that makes older cached analyses stale.

## Decision

Add one new error layer, `inference`, with exactly two codes, and defer all other taxonomy expansion:

- `I01 隐含关系推断失败` — a cross-clause or cross-sentence relation (cause / contrast / concession etc.) carries no explicit connective and must be inferred; the reader treats the parts as unrelated or infers the wrong relation.
- `I02 言外之意 / 立场推断失败` — implicature and authorial stance: hedging, evaluative or ironic tone (e.g. `so-called`, `may`, `in theory`, `fails to`) read as a neutral or opposite assertion.

Defer the other identified gaps — macro-structure (paragraph-level argument structure) and negation/comparison/quantifier scope. Do **not** add them speculatively. Once `inference` has been in use, review accumulated low-confidence and mis-tagged diagnoses to decide whether those layers are warranted, and add any approved codes in a single batch so the prompt-version/cache cost is paid once.

The new layer is sentence/discourse level. The word-analysis prompt (`word_analysis.v5`) is **not** changed: a single word or phrase cannot carry an implicature/stance diagnosis. The JSON schema enum will accept I01/I02 (it derives from `VALID_ERROR_CODES`), but the word prompt will not instruct the model to use them.

## Consequences

- The diagnosis and prediction prompts bump to new versions (`v3`); existing cached sentence analyses may appear stale and re-run on next request.
- The `error_types.layer` `CHECK` constraint must be relaxed to include `inference`, which requires a table rebuild migration.
- `ErrorLayer`, `ERROR_TYPES`, layer-count tests, and the regenerated `docs/state/schema.sql` change accordingly; `VALID_ERROR_CODES` and all JSON schema enums update automatically.
- Existing similar-mistake matching, profile generation, and review continue to work unchanged because they consume error codes generically.
- The taxonomy stays closed; the deferred layers wait for real usage data rather than speculation.

See the executable plan in `features/inference-error-layer.md`.
