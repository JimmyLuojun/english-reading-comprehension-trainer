# English Reading Comprehension Trainer

A local-first English reading training system with TXT/EPUB/PDF import, sentence and
word cards, manual AI analysis prompts, SM-2 review scheduling, learner profile
snapshots, and a small FastAPI web UI.

## Quick Start

From the repository root:

```bash
cd english-reading-trainer
uv sync --extra dev
uv run python -m uvicorn app.web.fastapi_app:app --reload
```

Then open `http://127.0.0.1:8000`.

The app uses `english-reading-trainer/data/reading_trainer.db` by default and
applies migrations automatically on startup. To use another database:

```bash
TRAINER_DB=/path/to/reading_trainer.db uv run python -m uvicorn app.web.fastapi_app:app --reload
```

## Setup

Recommended when `uv` is available:

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
uv run python -m app.cli_entry books import txt /path/to/book.txt --title "Book Title"
uv run python -m app.cli_entry books import epub /path/to/book.epub
uv run python -m app.cli_entry books import pdf /path/to/book.pdf
uv run python -m app.cli_entry books list
uv run python -m app.cli_entry books show 1
uv run python -m app.cli_entry read 1 --chapter 1
```

Create cards while reading:

```bash
uv run python -m app.cli_entry mark sentence 42 --note "hard relative clause"
uv run python -m app.cli_entry mark word 42 "give rise to" --type phrase
uv run python -m app.cli_entry cards sentences
uv run python -m app.cli_entry cards words
```

Use the manual AI flow:

```bash
uv run python -m app.cli_entry ai prompt-sentence 42
uv run python -m app.cli_entry ai save-sentence 42
uv run python -m app.cli_entry ai prompt-word 42 "mitigate"
uv run python -m app.cli_entry ai save-word 42 "mitigate"
```

Review and profile:

```bash
uv run python -m app.cli_entry review due
uv run python -m app.cli_entry review answer sentence 1 pass
uv run python -m app.cli_entry profile status
uv run python -m app.cli_entry profile prompt
uv run python -m app.cli_entry profile save
uv run python -m app.cli_entry profile latest
```

## Web UI

```bash
cd english-reading-trainer
uv run python -m uvicorn app.web.fastapi_app:app --reload
```

Then open `http://127.0.0.1:8000`.

The web UI supports TXT/EPUB/PDF import, the dashboard, book browsing, chapter
reading, sentence and word marking, card lists, review actions, profile prompt
generation, profile saving, and latest profile viewing.

## Tests

```bash
cd english-reading-trainer
uv run python -m pytest tests/
uv run python -m pytest --cov=app --cov-report=term-missing tests/
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
    importers/   TXT, EPUB, and PDF import
    nlp/         Sentence segmentation and lemmatization
    profile/     Learner profile statistics, prompts, snapshots
    review/      SM-2 scheduling and daily review queue
    web/         FastAPI server-rendered UI
    cli_entry.py Typer CLI entry point
  migrations/    SQLite schema and seed data
  prompts/       Versioned prompt templates
  tests/         Pytest suite mirroring source modules
```
