# Project Invariants

These rules describe behavior that should not change accidentally. Each implementation change that touches one of these areas should either preserve the invariant with tests or update this file and the corresponding ADR/feature design.

## Documentation

- `AGENTS.md` is the operating contract for AI agents.
- `STATUS.md` is the project working-memory checkpoint and should stay short.
- `docs/design.md` is the architecture map and index, not the place for long feature execution plans.
- Detailed evolving feature plans live in `docs/features/`.
- Non-trivial "why" decisions live in `docs/decisions/`.
- `docs/state/schema.sql` reflects the real current SQLite schema and must be regenerated after schema migrations.

## Data Model

- The current implemented source formats are `txt` and `epub`; `pdf` remains planned until a migration expands `books.source_format`.
- Schema migrations and SQL schema changes must be tested with real SQLite, not mocks.
- `sentences.id` is the stable anchor for reader selection, sentence cards, word card source links, AI analysis context, and review navigation.
- `word_cards.lemma` remains globally unique for the current card model.

## Cards And Review

- `word_cards.user_note` is the only source for user-authored Notes / Your note UI.
- AI meaning or `current_meaning` must not be displayed as user-authored notes.
- Review logs preserve SM-2 state transitions and should not be deleted unless their owning card is truly deleted.

## Book Deletion

- Sentence cards belong to the deleted book and are removed with that book.
- Word cards should be re-anchored to matching sentences in other books when possible.
- Re-anchorable word cards keep SM-2 state and review logs.
- Only word cards that cannot be re-anchored are deleted with their own review logs.

## Reader

- Reader mark/unmark/save/analyze actions should preserve the current reading position.
- AI analysis is an overlay drawer and should not change the reader text layout.
- Source links from Cards and Review should jump to the card's source sentence when an anchor exists.
