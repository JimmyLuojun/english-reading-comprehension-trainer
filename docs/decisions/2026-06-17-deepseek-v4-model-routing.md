# DeepSeek V4 Model Routing

Date: 2026-06-17

## Status

Accepted

## Context

The project previously defaulted direct OpenAI-compatible LLM calls to DeepSeek
through `TRAINER_MODEL=deepseek-chat`. DeepSeek now exposes V4 model names
directly, and the reading trainer has two different accuracy/cost profiles:

- word, phrase, and collocation explanation should be inexpensive enough for
  frequent daily use;
- sentence-level AI analysis diagnoses grammar, discourse, and user translation
  errors, where accuracy is more important than minimal token cost.

The reader already has a `Reanalyze` action, so the UI can expose an explicit
high-accuracy retry without changing the database schema.

## Decision

Use `deepseek-v4-flash` as the default model for ordinary analysis through
`TRAINER_MODEL`.

Use `deepseek-v4-pro` as the default sentence-analysis model through
`TRAINER_SENTENCE_MODEL`.

Use `deepseek-v4-pro` as the explicit high-accuracy reanalysis model through
`TRAINER_PRO_MODEL`.

The reader analysis panel keeps the existing `Reanalyze` button and adds
`Reanalyze with Pro`. The Pro button posts `prefer_pro=1`; the Web analysis
service then passes `TRAINER_PRO_MODEL` into the existing analyzer call. Sentence
analysis already defaults to the Pro model, while word analysis continues to
default to Flash unless the user chooses the Pro reanalysis path.

## Consequences

- Existing cache records remain valid but are keyed by their stored model name;
  newly generated V4 results will not accidentally reuse old `deepseek-chat`
  cache rows.
- Sentence analysis costs more than word analysis by default, matching its
  higher accuracy requirement.
- Users can escalate a weak word explanation to Pro without changing `.env` or
  restarting the server.
- No schema migration is required.
