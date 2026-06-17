# Project Status

Updated: 2026-06-17

## Current State

- The project is in the self-use stabilization phase: local FastAPI Web UI, SQLite storage, TXT/EPUB imports, AI analysis/cache, SM-2 review, cards, and EPUB media support are active.
- `app/web/fastapi_app.py` has been split into a thin app factory plus `routers/`, `queries/`, `views/`, and shared web helpers while preserving `create_app(db_factory=None)`.
- `app/web/services/` now holds the first workflow services for book deletion, TXT/EPUB import outcomes, and AI analysis/card-cache coordination.
- `docs/design.md` is now a 117-line architecture map and index instead of a continuously growing implementation log.
- Web source files and mirrored tests now align for all non-`__init__.py` files under `app/`; router tests verify route registration, while query/view/helper tests cover stable contracts.
- `python -m ruff check app/web` is part of the Web change verification contract.

## In Flight

- PDF import is designed but not implemented. Its detailed plan lives in `docs/features/pdf-import.md`.

## Next

- When PDF import starts, implement the SQLite migration, `SourceFormat.PDF`, `pdf_importer.py`, Web upload support, CLI support, and the required SQLite/importer/Web/CLI tests.
- Continue moving complex web workflows into `app/web/services/` when a route starts coordinating multiple queries or domain services.
- Keep `docs/state/schema.sql` regenerated after schema migrations.
- Keep mirrored tests in sync when adding or splitting Python source files.

## Known Issues

- The current generated schema still allows only `txt` and `epub`; `pdf` remains a planned source format until its migration lands.
- The working tree still contains a modified local database file at `english-reading-trainer/data/reading_trainer.db`.

## Recent Verification

- 2026-06-17: Full test suite after `docs/design.md` topic split passed with `1069 passed, 18 skipped`.
- 2026-06-17: Full test suite after adding `app/web/services/` passed with `1077 passed, 18 skipped`.
- 2026-06-17: Web mirror-test and static-check pass completed: source/test mirror `55/55`, `python -m ruff check app/web tests/web` passed, Web tests passed with `175 passed, 18 skipped`, and full suite passed with `1131 passed, 18 skipped`.
