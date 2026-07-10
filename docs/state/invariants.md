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

- The current implemented `books.source_format` values are `txt`, `md`, `epub`, and `pdf`; URL import intentionally stores extracted web text as `txt` until a future source metadata migration exists.
- Schema migrations and SQL schema changes must be tested with real SQLite, not mocks.
- Applied migration files are immutable: their recorded SHA-256 checksums must match on every later startup.
- Pending migrations run in one SQLite transaction, with a recoverable online backup created first; a failed migration must leave neither schema changes nor a migration record behind.
- Backup restore requires the web service to be stopped and an explicit CLI `--yes`; restored databases must pass SQLite integrity checks before replacing the live file.
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
- Reader interaction code is served from `/static/reader.js`; `reader_script._selection_script()` is test-only asset loading, not a second source of browser behavior.

## Local Service And Imports

- The supported web deployment is loopback-only, single-user access. The launcher issues a per-process token; requests need the token header or the strict local cookie created from the tokenized launcher URL.
- State-changing browser requests must originate from the same local origin; cross-origin `Origin` or `Referer` values are rejected.
- URL imports may follow only validated `http`/`https` redirects. Every resolved target host must have globally routable DNS addresses; loopback, private, link-local, multicast, reserved, and unspecified addresses are rejected.
