# English Reading Comprehension Trainer

A local-first English reading training system with TXT/Markdown/EPUB/PDF/URL import,
sentence and word cards, manual AI analysis prompts, SM-2 review scheduling, learner
profile snapshots, and a small FastAPI web UI.

## Quick Start

From the repository root:

```bash
cd english-reading-trainer
.venv/bin/python -m app.web.launcher --port 8001
```

Open the tokenized loopback URL printed by the launcher. The browser receives a
strict local cookie after the first request; API automation can instead send the
same token in `X-Trainer-Token`. The service intentionally binds only to
`127.0.0.1` and is not a multi-user or network-facing deployment.

### Restarting without losing the Reader

By default, the launcher generates a fresh local access token for each launch.
For local development with `--reload`, or when manually stopping and restarting
the server, set a stable token before launching:

```bash
cd english-reading-trainer
export TRAINER_REQUEST_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
.venv/bin/python -m app.web.launcher --port 8001 --reload
```

Keep the same `TRAINER_REQUEST_TOKEN` value for later restarts (including a new
terminal session). Open the printed URL once to establish the browser cookie;
then a hard reload of a Reader page keeps access and restores its saved chapter
and reading position. An explicit token can also be supplied with
`--access-token`, but the environment variable avoids placing it in shell
history.

The app uses `english-reading-trainer/data/reading_trainer.db` by default and
applies migrations automatically on startup. To use another database:

```bash
TRAINER_DB=/path/to/reading_trainer.db .venv/bin/python -m app.web.launcher --port 8001
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
.venv/bin/python -m app.web.launcher --port 8001
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
TRAINER_LLM_TIMEOUT_SECONDS=45
TRAINER_LLM_MAX_RETRIES=1
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
.venv/bin/python -m app.web.launcher --port 8001
```

Open the tokenized URL printed by the launcher. Keep the service on the local
machine; the launcher deliberately does not expose it on a LAN interface.
For restart-safe local development, follow the stable-token instructions in
[Restarting without losing the Reader](#restarting-without-losing-the-reader).

The web UI supports TXT/Markdown/EPUB/PDF file import, URL import for
HTML/plain-text pages, the dashboard, book browsing, chapter reading, sentence
and word marking, card lists, review actions, profile prompt generation, profile
saving, and latest profile viewing.

## NotebookLM Companion Workflow

NotebookLM can complement the trainer as a source-grounded oral examiner and
cross-chapter synthesis tool. The trainer remains the system of record for close
reading, error diagnosis, sentence/word cards, and SM-2 review; NotebookLM should
not create a second long-term card system or replace independent reading.

The recommended first experiment is one Reading Lab notebook for the current
book, containing the original source, exported takeaways, and a closed-book
English recall after each chapter. Only errors confirmed against source citations
should flow back into the trainer. See the full workflow, prompt templates,
weekly evidence-pack proposal, and four-week success criteria in
[NotebookLM 协同学习方案](docs/features/notebooklm-integration.md).

## Mobile Reading and App Roadmap

The recommended path to Mac/iPhone continuity is deliberately incremental:
first move Reader progress from browser-only localStorage into the existing
SQLite system of record and expose the loopback service through private
Tailscale HTTPS; then make the current Reader an installable Web App. A native
SwiftUI plus CloudKit/cloud-backend build is reserved for a later, explicitly
validated need to read offline while the Mac is asleep or powered off. See the
complete scope, conflict rules, security boundary, sleep/lock behavior, decision
gates, and acceptance criteria in
[Mac 与 iPhone 三阶段移动阅读/App 化路线](docs/features/mobile-app-roadmap.md).

## Database Recovery

Migrations and destructive book deletes create SQLite backups in `data/backups/`.
Run recovery commands while the web server is stopped:

```bash
cd english-reading-trainer
.venv/bin/python -m app.cli_entry db backup
.venv/bin/python -m app.cli_entry db integrity
.venv/bin/python -m app.cli_entry db restore data/backups/reading_trainer.manual-*.db --yes
```

## Tests

```bash
cd english-reading-trainer
.venv/bin/python -m pytest tests/
make verify
```

`make verify` runs Ruff, branch coverage, per-module coverage gates, schema drift
checks, and Playwright reader interaction tests. For a new development setup,
install browser dependencies with `uv sync --extra dev --extra browser`.

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
