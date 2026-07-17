# ADR: Library Item compatibility layer

Date: 2026-07-17
Status: Accepted

## Context

The reader now imports books, articles, excerpts, pasted paragraphs, Markdown, PDF, EPUB, and URL content. The physical schema and many downstream relationships use `books.id` / `book_id`, while the product needs semantic content types, provenance, organization status, and item tags.

## Decision

Treat Library Item as the product/UI concept and keep `books` as the physical compatibility table. Add constrained `content_kind`, nullable `import_method`, `source_uri`, and manual `library_status` fields to `books`; add `book_tags` for item-level tags. Preserve `book_id`, `/books` routes, assets, cards, annotations, and Reader localStorage keys.

Existing rows are `unclassified`; their unknown historical import method is not inferred. Import format, import channel, and semantic content kind remain independent. Collections and server-side reading progress are separate future decisions.

## Consequences

- Existing IDs and foreign keys remain stable, so no card/progress relinking is required.
- UI terminology can vary by content kind while the hierarchy remains unchanged.
- Internal names such as `books` and `chapters` remain visible to developers until a later, separately justified migration.
- Any future table rename must include routes, asset paths, CLI, tests, and localStorage compatibility rather than being treated as a cosmetic refactor.
