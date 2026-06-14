"""
English sentence segmentation using pysbd.

Provides character-offset-aware segmentation so importers can store
char_offset_start / char_offset_end for each sentence in the DB.
"""

from dataclasses import dataclass

import pysbd

# Module-level singleton — pysbd.Segmenter is thread-safe after init.
_segmenter: pysbd.Segmenter | None = None


def _get_segmenter() -> pysbd.Segmenter:
    global _segmenter
    if _segmenter is None:
        _segmenter = pysbd.Segmenter(language="en", clean=False)
    return _segmenter


@dataclass(frozen=True)
class SegmentedSentence:
    text: str          # stripped sentence text
    char_start: int    # byte offset in the original paragraph text
    char_end: int      # exclusive end offset (points past the raw token incl. trailing space)


def segment_sentences(text: str) -> list[SegmentedSentence]:
    """
    Split *text* into sentences and return each with its character offsets.

    Offsets are relative to the *text* argument, not the full document.
    Empty or whitespace-only input returns [].
    """
    if not text or not text.strip():
        return []

    segmenter = _get_segmenter()
    raw_tokens: list[str] = segmenter.segment(text)

    results: list[SegmentedSentence] = []
    cursor = 0

    for raw in raw_tokens:
        if not raw or not raw.strip():
            # Advance cursor past whitespace-only token
            pos = text.find(raw, cursor)
            if pos != -1:
                cursor = pos + len(raw)
            continue

        pos = text.find(raw, cursor)
        if pos == -1:
            # pysbd occasionally strips leading whitespace; try stripped form
            stripped = raw.lstrip()
            pos = text.find(stripped, cursor)
            if pos == -1:
                continue
            raw = stripped

        sentence_text = raw.strip()
        if sentence_text:
            results.append(SegmentedSentence(
                text=sentence_text,
                char_start=pos,
                char_end=pos + len(raw),
            ))
        cursor = pos + len(raw)

    return results


def normalize_for_hash(text: str) -> str:
    """
    Canonical form used to compute text_hash for cross-book deduplication.
    Lowercases and collapses all internal whitespace.
    """
    return " ".join(text.lower().split())
