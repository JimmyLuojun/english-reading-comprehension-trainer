# Repeated analyzed vocabulary indicator

Status: superseded by
[`contextual-word-senses.md`](contextual-word-senses.md) (2026-07-25)

## Goal

When a learner meets the same saved expression again elsewhere in a book, the
Reader should reveal that a valid AI analysis already exists before the learner
selects the expression.

## Original 2026-07-18 behavior

- An exact saved source occurrence keeps the existing lexical-type highlight
  and solid underline.
- An unrecorded repeat of the same surface form receives a thin dotted
  underline only when the card has a valid AI analysis.
- Word, phrase, and collocation markers retain their existing green, purple,
  and orange lexical-type colors.
- Hover text says `Analyzed earlier in this book — click to view`.
- Single-clicking or double-clicking the dotted repeat loads the saved analysis
  with `GET /analysis/word/{card_id}`. The inferred occurrence does not expose
  card removal controls and does not create a new source occurrence.
- Matching is case-insensitive, respects whole-word/whole-phrase boundaries,
  gives longer expressions priority, and is limited to cards sourced from the
  current book. It does not infer morphology, synonyms, or cross-book identity.
- Repeats are rendered as dormant spans for saved-but-not-yet-analyzed cards.
  When analysis finishes on the current page, JavaScript activates those spans
  immediately without a reload.

The implementation reuses `word_cards.ai_analysis_id`, validity-aware
`ai_cache` joins, and existing `word_card_sources`; no schema migration is
required.

## Superseded scope

The original same-book, read-only marker was the precursor to the implemented
contextual-sense model. The current Reader can show the marker across books,
register the clicked occurrence, analyze its exact sentence, and preserve or
create stable meanings under one lemma-level review card. The marker still
means only “saved meanings exist”; it never confirms that a prior meaning fits
the new sentence.
