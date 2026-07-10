# Local Data And Service Hardening

Date: 2026-07-10

## Context

The trainer is a local, single-user FastAPI application, but it mutates a
long-lived SQLite database, imports arbitrary URLs, and contains a substantial
reader interaction script. The former startup model could partially apply a
migration, the service accepted unprotected loopback requests, and the Reader
embedded its complete script in every HTML response.

## Decision

- Use SQLite online backups before pending migrations and destructive book
  deletes. Restore only through an explicit CLI confirmation after verifying
  the backup's SQLite integrity.
- Execute each migration in one `BEGIN IMMEDIATE` transaction and record a
  SHA-256 checksum in `schema_migrations`. Existing migration contents are
  therefore immutable after first application.
- Keep the product local-only: the launcher binds to `127.0.0.1`, prints a
  per-process tokenized URL, and middleware accepts that token through a strict
  local cookie or `X-Trainer-Token`. Same-origin checks reject cross-origin
  state changes. This is not OAuth or a multi-user security boundary.
- Validate each URL-import redirect before contacting it, resolve DNS before
  connecting, and reject non-global addresses. This is a practical SSRF guard;
  it does not claim to pin DNS through the full TCP/TLS connection lifecycle.
- Initialize the default database in FastAPI lifespan, add bounded LLM client
  retries/timeouts, use real database integrity health checks, and write
  request-scoped rotating local logs.
- Serve the Reader browser code as `/static/reader.js`. The Python loader stays
  only for source-level script contract tests, so there is one runtime asset.

## Consequences

Recovery is now an intentional operator workflow rather than copying a live
database file. Startup fails safely on tampered migrations or integrity errors.
The normal launcher URL is required for browser access, while local scripts can
use the header token. CI installs Chromium and exercises the Reader browser
tests; packaging includes the static JavaScript asset.
