# Contextual word senses across books

Status: implemented (2026-07-25)

## Goal

When an analyzed expression appears in another Library Item, expose the saved
meanings without assuming that any one meaning applies. A new analysis checks
the current context, recommends reuse or creation, and preserves every distinct
meaning under one review card.

## Behavior

- Exact normalized surface-form matches may receive a dotted cross-book marker.
  Its label says that saved meanings exist elsewhere and remain unverified here.
- AI word analysis always targets the selected `word_card_sources` occurrence,
  not `word_cards.first_sentence_id`.
- The prompt receives stable saved sense IDs and returns a structured
  `sense_resolution` recommendation: `same`, `new`, or `uncertain`.
- The active word prompt is v7. Historical v6 is immutable; v7 retains its JSON
  contract and adds clearer JSON-only and ambiguous-`coating` guidance.
- The contextual analysis is saved for the exact source occurrence.
- Clicking a dotted marker registers its exact DOM range and converts it into
  a saved-source marker. Repeated copies of the same word in one sentence keep
  separate source IDs and Unicode code-point offsets, including after reload.
- With existing senses, the learner confirms reuse or creation before a stable
  assignment is made.
- Clicking an analyzed occurrence shows the meaning used there, its contextual
  explanation, every other saved meaning, representative examples, and sense
  assignment controls.
- Review scheduling remains one-per-lemma for this version.

## Matching boundary

The first version uses exact case-insensitive surface-form matching with strict
word/phrase boundaries. It does not infer morphology, synonyms, or semantic
identity before analysis.

## Data

- `word_cards`: lemma-level review/mastery unit.
- `word_senses`: stable canonical meanings.
- `word_card_sources`: occurrence, assigned sense, contextual analysis, and
  resolution metadata.
- `ai_cache`: validated contextual response artifacts, not sense identity.

See
[`2026-07-25-word-senses-and-occurrence-analysis.md`](../decisions/2026-07-25-word-senses-and-occurrence-analysis.md).
