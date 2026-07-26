# ADR: separate lemma cards, stable senses, and occurrence analyses

Date: 2026-07-25
Status: accepted

## Context

`word_cards` is globally unique by lemma and owns the learner's SM-2 state.
It historically had one active AI analysis even when the expression appeared
more than once. Reusing that analysis across books would incorrectly treat an
identical spelling as a confirmed identical sense, while overwriting it would
lose earlier meanings and sentence-specific explanations.

## Decision

- Keep one `word_card` per normalized lemma as the review and mastery unit.
- Add `word_senses` for stable English/Chinese meanings under that card.
- Keep exact occurrences in `word_card_sources`.
- Let each source point to both its assigned stable sense and its own
  context-specific AI analysis.
- Ask the AI to recommend `same`, `new`, or `uncertain` in the normal word
  analysis response. Existing senses are passed by stable ID.
- Do not silently resolve cross-book ambiguity in the first release. The
  learner confirms reuse or creation; assignment remains editable.
- Keep legacy `word_cards.current_meaning` and `ai_analysis_id` as compatibility
  mirrors until Cards and Review migrate fully to multi-sense presentation.

## Consequences

- Multiple meanings no longer overwrite one another.
- Sentence-specific fields such as `role_in_sentence` remain tied to the
  occurrence they describe.
- SM-2 history remains one-per-lemma and is not duplicated.
- Cross-book dotted indicators mean only that saved meanings exist; they do not
  assert that a saved sense applies.
- The schema and Reader API become source-aware, and a prompt-version upgrade is
  required.
- The sense-resolution JSON contract began in word prompt v6. Its final
  instruction refinement is v7 so the already-registered v6 remains immutable.
