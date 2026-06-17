# ADR: PDF Import Uses Normalized Text, Not a PDF Viewer

Date: 2026-06-17

Status: Accepted for planned PDF import

## Context

The reader, AI analysis, card creation, review queue, and source navigation all depend on sentence-backed DOM spans and stable `sentence_id` anchors. A PDF viewer would preserve page visuals but would not naturally produce the same sentence/card/review anchors.

## Decision

PDF import will normalize extractable PDF text into the existing `books / chapters / paragraphs / sentences / chapter_blocks` model. The reader will continue to use `/read/{book_id}` and `sentence_id` spans. Phase 1 will not embed a PDF viewer as the main reading surface and will not attempt OCR.

## Rationale

This keeps PDF support compatible with the existing learning workflow: sentence selection, word/phrase/collocation marking, AI analysis, Cards, Review, and source links. It also isolates PDF-specific cleanup in the importer instead of spreading PDF special cases through the reader JavaScript and review/card flows.

## Consequences

- PDF visual layout will not be reproduced 1:1 in Phase 1.
- Scanned PDFs or PDFs without extractable text fail with a clear error.
- The schema must later expand `books.source_format` to include `pdf`.
- Migration tests must use real SQLite and prove existing TXT/EPUB rows survive the CHECK-constraint rebuild.

## Revisit When

- OCR becomes a required feature.
- Users need page-faithful visual comparison more than selectable training text.
- The importer needs shared insertion behavior beyond direct reuse of EPUB importer `_insert()`.
