# Project Status

Updated: 2026-06-17

## Current State

- The project is in the self-use stabilization phase: local FastAPI Web UI, SQLite storage, TXT/EPUB/PDF imports, AI analysis/cache, SM-2 review, cards, and EPUB media support are active.
- `app/web/fastapi_app.py` has been split into a thin app factory plus `routers/`, `queries/`, `views/`, and shared web helpers while preserving `create_app(db_factory=None)`.
- `app/web/services/` now holds workflow services for book deletion, TXT/EPUB/PDF import outcomes, and AI analysis/card-cache coordination.
- PDF import Phase 2B is implemented through `app/importers/pdf_importer.py`: normalized selectable text plus coarse vector/image figure-region preservation and math/code non-prose region preservation as `book_assets` and `chapter_blocks(kind='figure')`; it does not introduce a PDF viewer or OCR.
- Cards 页 Word Cards 表格现在提供直接 Delete 操作，复用现有词卡软删除接口；Source/词条链接继续用于回到来源阅读位置或已保存的 Word Analysis。
- Word Cards 的 `Occ.` 现在表示不同来源位置数量，由 `word_card_sources` 表记录；旧词卡迁移时按 `first_sentence_id` 回填并重算，Cards 页提供 Sources / Find Occurrences / Set primary。
- EPUB import now treats obvious `Part ...` divider pages as non-counted sections and strips word-based `Chapter One:` style prefixes from displayed chapter labels.
- PDF import now detects page-leading `Part ...` and `Chapter ...` headings before falling back to fixed 10-page virtual chapters; detected title lines are removed from trainable prose while body text remains.
- DeepSeek API routing now defaults ordinary analysis to `deepseek-v4-flash`, sentence AI analysis to `deepseek-v4-pro`, and exposes a reader `Reanalyze with Pro` action backed by `TRAINER_PRO_MODEL`.
- Reader nested Word Analysis now passes analysis-panel block context as transient `context_text`, so words selected from explanations are analyzed in the explanation context while source links still use the original reading sentence anchor.
- Word Analysis now passes the learner's saved Word Card Note into immutable prompt `word_analysis.v4.md` as `learner_note`; AI returns a separate `learner_note_check` block that evaluates the note without overwriting My notes or the original meaning analysis.
- Reader Write translation now repositions the expanded translation editor around the target sentence after it opens, keeping the sentence visible instead of covering it.
- Reader `Save only` for sentence translations now keeps saved translations as a separate `translated` dotted-underline state without adding the sentence to Review; `Check translation` still saves analysis and reactivates the sentence card for Review; `Delete translation` clears the translation and archives the sentence card because the review reason is gone.
- `docs/design.md` is now a 117-line architecture map and index instead of a continuously growing implementation log.
- Web source files and mirrored tests now align for all non-`__init__.py` files under `app/`; router tests verify route registration, while query/view/helper tests cover stable contracts.
- `python -m ruff check app/web` is part of the Web change verification contract.

## In Flight

- No active feature branch task is marked in-flight after PDF import Phase 2A.

## Next

- Improve PDF importer quality only after real sample PDFs expose gaps: outline-based chapters, multi-column handling, better multi-figure clustering, caption extraction, or OCR should be separate scoped follow-ups.
- Continue moving complex web workflows into `app/web/services/` when a route starts coordinating multiple queries or domain services.
- Keep `docs/state/schema.sql` regenerated after schema migrations.
- Keep mirrored tests in sync when adding or splitting Python source files.

## Known Issues

- None currently recorded.

## Recent Verification

- 2026-06-17: Full test suite after `docs/design.md` topic split passed with `1069 passed, 18 skipped`.
- 2026-06-17: Full test suite after adding `app/web/services/` passed with `1077 passed, 18 skipped`.
- 2026-06-17: Web mirror-test and static-check pass completed: source/test mirror `55/55`, `python -m ruff check app/web tests/web` passed, Web tests passed with `175 passed, 18 skipped`, and full suite passed with `1131 passed, 18 skipped`.
- 2026-06-17: PDF import Phase 1 pass completed: focused PDF/DB/CLI/Web tests passed with `313 passed`, Web tests passed with `180 passed, 1 skipped`, full suite passed with `1150 passed, 1 skipped`, targeted ruff passed, source/test mirror `56/56`, and `docs/state/schema.sql` matched a clean migrated SQLite schema.
- 2026-06-17: PDF import Phase 2A vector-figure importer test passed with `9 passed`; a real Bitcoin whitepaper temp import produced `7` figure assets.
- 2026-06-17: PDF import Phase 2B non-prose region importer test passed with `10 passed`; a real Bitcoin whitepaper temp import produced `14` figure assets and no `AttackerSuccessProbability`/`#include` sentence pollution while preserving surrounding prose.
- 2026-06-17: Cards word delete UI verification passed: focused pytest `9 passed`, targeted ruff passed, and browser check on `http://127.0.0.1:8000/cards` found Actions plus 18 Delete buttons.
- 2026-06-17: Word-card source tracking pass completed: related pytest set passed, targeted ruff passed, `docs/state/schema.sql` regenerated from a migrated SQLite DB, and browser check confirmed `intangible` Occ. is now `1` with Sources page available.
- 2026-06-17: EPUB Part divider import fix completed: focused pytest `94 passed`, targeted ruff passed, and the local Rich Dad Poor Dad for Teens EPUB was reimported as `book_id=11` with `total_chapters=10`; Part pages no longer consume body chapter numbers.
- 2026-06-17: PDF heading-based chapter detection completed: `uv run python -m pytest tests/importers/test_pdf_importer.py` passed with `11 passed`, EPUB/Books regression tests passed with `94 passed`, and targeted ruff passed.
- 2026-06-17: DeepSeek V4 model routing completed: targeted AI/Web tests passed, `uv run python -m pytest tests/ -q` passed, and `uv run python -m ruff check app/web` passed.
- 2026-06-17: Analysis-panel nested word context fix completed: `.venv/bin/python -m pytest tests/web -k "analysis or explain or reader_script"` passed with `38 passed, 1 skipped, 156 deselected`; `.venv/bin/python -m pytest tests/web/routers/test_analysis.py tests/web/services/test_analysis.py tests/web/views/test_reader_script.py` passed with `16 passed`; `python -m ruff check app/web` passed.
- 2026-06-17: Word detail pending-note preservation fix completed: `.venv/bin/python -m pytest tests/web/views/test_reader_script.py tests/web/test_fastapi_app.py -k "reader_script or explain_button or panel_has_notes"` passed with `12 passed`; `python -m ruff check app/web tests/web/views/test_reader_script.py tests/web/test_reader_toolbar_state.py` passed. The Playwright toolbar-state module remains skipped in this environment.
- 2026-06-17: Full regression suite after the word-detail pending-note fix passed with `.venv/bin/python -m pytest tests/`: `1184 passed, 1 skipped`.
- 2026-06-17: Learner-note evaluation for Word Analysis completed: targeted pytest for prompt/schema/analyzer/web rendering passed with `135 passed`; AI schema/saver/analyzer tests passed with `121 passed`; targeted ruff passed; full suite passed with `.venv/bin/python -m pytest tests/`: `1190 passed, 1 skipped`.
- 2026-06-17: Prompt immutability startup fix completed: restored historical `word_analysis.v3.md`, moved learner-note evaluation to new `word_analysis.v4.md`, verified `uv run python -c "from app.web.fastapi_app import _get_db; db=_get_db(); print('ok')"` passes, targeted prompt/Web/AI tests passed with `231 passed, 131 deselected`, targeted ruff passed, and full suite passed with `.venv/bin/python -m pytest tests/`: `1195 passed, 1 skipped`.
- 2026-06-17: Reader Write translation overlay fix completed: targeted reader/script/style tests passed with `13 passed`; `python -m ruff check app/web` passed; reader page render regression passed; full suite passed with `.venv/bin/python -m pytest tests/`: `1196 passed, 1 skipped`.
- 2026-06-17: Reader translation/review state split completed: targeted cards/Web/AI query/view/FastAPI tests passed; `python -m ruff check app/web` and `python -m ruff check app/ai/context_builder.py` passed; full suite passed with `.venv/bin/python -m pytest tests/ -q`. Browser toolbar-state tests remain locally uncollected because `playwright` is not installed in this environment.
- 2026-06-17: Reader Delete translation action completed: targeted card service/FastAPI/reader view/script tests passed; `python -m ruff check app/web app/cards/sentence_card_service.py` passed; full suite passed with `.venv/bin/python -m pytest tests/ -q`.
- 2026-06-17: Reader translated-sentence double-click shortcut completed: `tests/web/views/test_reader_script.py` passed, `tests/web` passed, full `.venv/bin/python -m pytest tests/ -q` passed, and `python -m ruff check app/web tests/web/views/test_reader_script.py` passed.
