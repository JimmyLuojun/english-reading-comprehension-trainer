# ADR: PDF Vector Figures Render Through pdfplumber

Date: 2026-06-17

Status: Accepted

## Context

Some PDFs, including the Bitcoin whitepaper, store diagrams as vector primitives
instead of embedded image files. `pdfplumber` reports these as lines, curves, and
rectangles, so a text-only PDF importer drops the visual structure even though
the diagram labels are extractable as words.

The project already depends on `pdfplumber>=0.11`, which uses `pypdfium2` for
in-process rendering.

## Decision

PDF import preserves vector figures by detecting coarse visual regions from PDF
lines, curves, rectangles, and images, rendering those regions to PNG through
`pdfplumber`/`pypdfium2`, and storing them as existing `book_assets` plus
`chapter_blocks(kind='figure')`.

Words whose bounding boxes fall inside detected figure regions are excluded from
normal sentence extraction to prevent diagram labels from appearing twice.

## Rationale

This preserves important diagrams without introducing a PDF viewer, OCR, schema
changes, or a new rendering dependency. It keeps selectable prose anchored on
`sentence_id` while using the reader's existing media-block support for figures.

PyMuPDF is not used because the existing `pdfplumber` rendering path is
sufficient and avoids adding AGPL licensing risk.

## Consequences

- Figure detection is heuristic and intentionally coarse in Phase 2A.
- Slight over-capture is acceptable; missing surrounding prose is not.
- PNG bytes are not treated as deterministic across rendering backend versions,
  so tests assert database structure and asset presence rather than exact pixels.
- OCR remains out of scope for scanned PDFs.
