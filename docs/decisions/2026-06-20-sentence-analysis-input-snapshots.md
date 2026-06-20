# Sentence Analysis Input Snapshots

Date: 2026-06-20

## Status

Accepted

## Context

Reader sentence analysis can become stale when the learner edits their translation
or structure attempt after an AI analysis has been generated. The panel must show
what the analysis actually evaluated without making the current editable
translation/structure ambiguous.

`is_stale` is not enough to decide whether to show old input because it also
turns true when only the prompt version changes. Showing a read-only "old input"
box in that case would add noise even though the learner's text has not changed.

## Decision

Store the sentence-analysis input snapshot on the `ai_cache` row:

- `ai_cache.input_translation`
- `ai_cache.input_structure`

Both columns are nullable. Historical cache rows and word-analysis rows keep
`NULL`.

Reader sentence payloads expose these values as `analyzed_translation` and
`analyzed_structure`. The UI shows a read-only "Initial ... analyzed" snapshot
only when the snapshot is non-empty and textually differs from the current
editable field. `is_stale` remains a "this analysis may need refresh" signal, not
a snapshot-display switch.

`Save translation`, `Save structure`, and `Reanalyze` continue to operate only on
the current editable fields.

## Consequences

- Learners can compare the original mistaken translation/structure with their
  corrected current version.
- Existing cache invalidation remains unchanged because `content_hash` already
  encodes translation and structure inputs.
- `ai_cache` gains two sentence-specific columns, a small layering tradeoff that
  avoids a new snapshot table and naturally binds the snapshot to `ai_analysis_id`.
