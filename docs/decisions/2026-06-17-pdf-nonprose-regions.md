# ADR: PDF Math and Code Regions Render as Figures

Date: 2026-06-17

Status: Accepted

## Context

Some PDF content is extractable text but is not useful prose for the reading
trainer. The Bitcoin whitepaper's calculations section includes display math
and C code. A normal word-order extractor linearizes those 2D layouts into
garbled sentences and pollutes sentence segmentation, AI analysis, and review
card workflows.

## Decision

PDF import detects non-prose text clusters, including monospace code blocks and
math-like lines with symbol fonts, high operator density, or strong font-size
variance. These regions are routed through the same figure-rendering path used
for vector diagrams:

- render the region to PNG through `pdfplumber`/`pypdfium2`;
- store it as `book_assets` and `chapter_blocks(kind='figure')`;
- exclude words inside the region from normal sentence extraction.

## Rationale

The project is an English reading-comprehension trainer. Mathematical formulas
and code blocks should remain visible for comprehension context, but they should
not become sentence cards or AI-analysis input. Rendering them preserves layout
without OCR, PDF viewer integration, or a separate code/math parser.

## Consequences

- Surrounding English prose remains selectable and trainable.
- Math and code are visible but not selectable as text in Phase 2B.
- A later code-specific path may emit `TextBlock(kind='pre')` if selectable code
  becomes valuable, but image-first is the lower-risk default.
