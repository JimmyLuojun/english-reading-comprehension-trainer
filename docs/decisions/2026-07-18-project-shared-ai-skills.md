# Project-shared AI skills

- Status: Accepted
- Date: 2026-07-18

## Context

Codex CLI, Kimi Code CLI, and Antigravity all need the same word and sentence
analysis workflows in this repository. Existing `.codex/skills`,
`.claude/skills`, and `.gemini/skills` copies have drifted: they duplicate JSON
schemas, use different model labels, and bypass the application's supported
save commands.

## Decision

- Store portable project workflows once under `.agents/skills/<name>/SKILL.md`.
- Keep only `name` and `description` in skill frontmatter so all three tools can
  read the same files.
- Treat `AGENTS.md` as the project instruction source. Antigravity uses the thin
  `.agents/rules/project-standards.md` adapter, configured as Always On.
- Treat `app.cli_entry ai prompt-*` output as the current prompt/schema source.
- Save responses through `app.cli_entry ai save-* --input-file`; skills never
  write directly to SQLite, embed JSON in executable code, or hardcode a model.
- Keep existing tool-specific skill files temporarily. Remove them only after
  all three tools pass manual discovery and end-to-end acceptance checks.

## Consequences

Prompt/schema upgrades happen in the application and are immediately consumed
by every tool. A small static contract test prevents portable skills from
reintroducing tool-specific metadata or unsafe save paths. Antigravity still
requires a one-time workspace UI setting to make its rule Always On.

Global installation, cross-project synchronization, Antigravity workflows, and
tool-specific wrappers remain out of scope.
