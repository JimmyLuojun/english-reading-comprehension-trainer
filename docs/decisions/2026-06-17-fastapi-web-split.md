# ADR: Split FastAPI Web UI by Routes, Queries, and Views

Date: 2026-06-17

Status: Accepted

## Context

`app/web/fastapi_app.py` had grown into a large mixed-responsibility module containing app setup, routes, SQL queries, HTML/CSS/JS rendering, upload handling, and business workflow logic. This made feature work risky because unrelated concerns had to be edited in the same file.

## Decision

Keep `app/web/fastapi_app.py` as a thin app factory and route registration entry point. Move feature endpoints into `app/web/routers/`, database access into `app/web/queries/`, presentation helpers into `app/web/views/`, and shared HTTP/config/model helpers into focused web modules.

`create_app(db_factory=None)` remains stable for existing tests and external callers.

## Rationale

This is the lowest-risk split for the current server-rendered FastAPI app. It reduces file size and clarifies ownership without introducing a frontend framework, template migration, authentication system, or productization work before the project needs it.

## Consequences

- Route modules stay responsible for HTTP concerns: request parameters, responses, redirects, and status codes.
- Query modules own SQL and database persistence behavior.
- View modules own HTML/CSS/JS string rendering until a future template/static asset migration is justified.
- Future complex business workflows should move into `app/web/services/` instead of accumulating in routers.

## Revisit When

- Route handlers begin coordinating multiple query modules and business rules.
- HTML/JS/CSS string helpers become hard to test or review.
- The project enters a productization phase that justifies template/static asset or frontend tooling changes.
