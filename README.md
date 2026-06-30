# English Reading Comprehension Trainer

A local-first English reading training system with TXT/Markdown/EPUB/PDF/URL import,
sentence and word cards, manual AI analysis prompts, SM-2 review scheduling, learner
profile snapshots, and a small FastAPI web UI.

## Quick Start

From the repository root:

```bash
cd english-reading-trainer
.venv/bin/python -m uvicorn app.web.fastapi_app:app --host 127.0.0.1 --port 8001 --reload
```
Then open `http://127.0.0.1:8001`.

The app uses `english-reading-trainer/data/reading_trainer.db` by default and
applies migrations automatically on startup. To use another database:

```bash
TRAINER_DB=/path/to/reading_trainer.db .venv/bin/python -m uvicorn app.web.fastapi_app:app --host 127.0.0.1 --port 8001 --reload
```

If `.venv` does not exist yet, run the setup step below first. Prefer the
project virtual environment for normal development so commands keep using the
same interpreter and do not trigger an extra `uv run` sync/build.

## Setup

Recommended when `uv` is available and PyPI access is working:

```bash
cd english-reading-trainer
uv sync --extra dev
```

Alternatively, use a standard virtual environment:

```bash
cd english-reading-trainer
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

The default SQLite database is `english-reading-trainer/data/reading_trainer.db`.
Set `TRAINER_DB=/path/to/reading_trainer.db` to use a different database.
Migrations are applied automatically by the CLI and web app.

If `uv run` fails while fetching `setuptools` or another build dependency, use
the existing virtual environment directly:

```bash
cd english-reading-trainer
.venv/bin/python -m uvicorn app.web.fastapi_app:app --host 127.0.0.1 --port 8001 --reload
```

In shared handoff setups, logs may show the physical path under
`/Users/Shared/ai-handoff/...` even when you enter the project through a
`~/Documents/...` symlink. That path difference is expected.

## AI Provider

DeepSeek is the default OpenAI-compatible provider. Put your API key in a local
file that is not committed:

```bash
cd english-reading-trainer
cp .env.example .env
```

Then edit `english-reading-trainer/.env`:

```text
OPENAI_API_KEY=sk-your-real-deepseek-api-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
TRAINER_MODEL=deepseek-v4-flash
TRAINER_SENTENCE_MODEL=deepseek-v4-pro
TRAINER_PRO_MODEL=deepseek-v4-pro
```

The code also accepts real environment variables with the same names; exported
environment variables take priority over `.env` values.

## CLI Workflow

Run commands from `english-reading-trainer/`:

```bash
.venv/bin/python -m app.cli_entry books import txt /path/to/book.txt --title "Book Title"
.venv/bin/python -m app.cli_entry books import md /path/to/notes.md --title "Notes"
.venv/bin/python -m app.cli_entry books import epub /path/to/book.epub
.venv/bin/python -m app.cli_entry books import pdf /path/to/book.pdf
.venv/bin/python -m app.cli_entry books list
.venv/bin/python -m app.cli_entry books show 1
.venv/bin/python -m app.cli_entry read 1 --chapter 1
```

Create cards while reading:

```bash
.venv/bin/python -m app.cli_entry mark sentence 42 --note "hard relative clause"
.venv/bin/python -m app.cli_entry mark word 42 "give rise to" --type phrase
.venv/bin/python -m app.cli_entry cards sentences
.venv/bin/python -m app.cli_entry cards words
```

Use the manual AI flow:

```bash
.venv/bin/python -m app.cli_entry ai prompt-sentence 42
.venv/bin/python -m app.cli_entry ai save-sentence 42
.venv/bin/python -m app.cli_entry ai prompt-word 42 "mitigate"
.venv/bin/python -m app.cli_entry ai save-word 42 "mitigate"
```

Review and profile:

```bash
.venv/bin/python -m app.cli_entry review due
.venv/bin/python -m app.cli_entry review answer sentence 1 pass
.venv/bin/python -m app.cli_entry profile status
.venv/bin/python -m app.cli_entry profile prompt
.venv/bin/python -m app.cli_entry profile save
.venv/bin/python -m app.cli_entry profile latest
```

## Web UI

```bash
cd english-reading-trainer
.venv/bin/python -m uvicorn app.web.fastapi_app:app --host 127.0.0.1 --port 8001 --reload
```

Then open `http://127.0.0.1:8001`.

The web UI supports TXT/Markdown/EPUB/PDF file import, URL import for
HTML/plain-text pages, the dashboard, book browsing, chapter reading, sentence
and word marking, card lists, review actions, profile prompt generation, profile
saving, and latest profile viewing.

## Tests

```bash
cd english-reading-trainer
.venv/bin/python -m pytest tests/
.venv/bin/python -m pytest --cov=app --cov-report=term-missing tests/
```

Project coverage policy is configured in `pyproject.toml`: total line coverage
must stay at or above 90%, and the key modules `sm2_scheduler`,
`ai_response_cache`, and `json_output_validator` are expected to stay at 100%.

## Project Layout

```text
english-reading-trainer/
  app/
    ai/          Manual AI prompts, JSON validation, response cache, savers
    cards/       Sentence cards, word cards, similar-card lookup
    importers/   TXT, Markdown, EPUB, PDF, and URL import workflows
    nlp/         Sentence segmentation and lemmatization
    profile/     Learner profile statistics, prompts, snapshots
    review/      SM-2 scheduling and daily review queue
    web/         FastAPI server-rendered UI
    cli_entry.py Typer CLI entry point
  migrations/    SQLite schema and seed data
  prompts/       Versioned prompt templates
  tests/         Pytest suite mirroring source modules
```
