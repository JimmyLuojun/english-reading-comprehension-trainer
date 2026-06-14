"""
TXT file importer: reads a plain-text English book and inserts the full
Book → Chapter → Paragraph → Sentence hierarchy into the database.

Chapter detection heuristics (in priority order):
  1. Lines matching common heading patterns (Chapter N, PART I, etc.)
  2. Short ALL-CAPS lines (≤ 60 chars) preceded by a blank line
  3. Fallback: entire file treated as one chapter named "Chapter 1"

Paragraphs are blocks of text separated by one or more blank lines.
Sentences are produced by sentence_segmenter.segment_sentences().
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import chardet

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.nlp.sentence_segmenter import normalize_for_hash, segment_sentences

# ---------------------------------------------------------------------------
# Heading detection patterns (case-insensitive)
# ---------------------------------------------------------------------------

_HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(r"^chapter\s+(\w+)", re.IGNORECASE),
    re.compile(r"^part\s+(\w+)", re.IGNORECASE),
    re.compile(r"^section\s+(\w+)", re.IGNORECASE),
    re.compile(r"^epilogue\b", re.IGNORECASE),
    re.compile(r"^prologue\b", re.IGNORECASE),
    re.compile(r"^introduction\b", re.IGNORECASE),
    re.compile(r"^conclusion\b", re.IGNORECASE),
    re.compile(r"^\d+\.\s+\S"),           # "1. Title"
    re.compile(r"^[IVX]{1,5}\.\s+\S"),   # "IV. The Storm"
]

_MAX_ALLCAPS_HEADING_LEN = 60


@dataclass
class ImportResult:
    book_id: int
    chapter_count: int
    paragraph_count: int
    sentence_count: int


class DuplicateBookError(Exception):
    """Raised when a file with the same SHA-256 hash already exists in the DB."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_txt(
    db: DatabaseConnection,
    file_path: str | Path,
    title: str,
    author: str = "",
    language: str = "en",
) -> ImportResult:
    """
    Parse *file_path* (TXT) and insert the full hierarchy into the DB.

    Raises:
        FileNotFoundError: if the file does not exist.
        DuplicateBookError: if file_hash is already in the books table.
        ValueError: if the file contains no usable text.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    raw_bytes = file_path.read_bytes()
    file_hash = _sha256(raw_bytes)
    text = _decode(raw_bytes)

    if not text.strip():
        raise ValueError(f"File contains no usable text: {file_path}")

    chapters_raw = _split_chapters(text)
    return _insert(db, title, author, language, file_hash, chapters_raw)


# ---------------------------------------------------------------------------
# Text parsing helpers
# ---------------------------------------------------------------------------

def _decode(raw: bytes) -> str:
    """Decode bytes to str; tries UTF-8 first, then chardet detection."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "latin-1"
        return raw.decode(encoding, errors="replace")


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    for pat in _HEADING_PATTERNS:
        if pat.match(stripped):
            return True
    # ALL-CAPS short line (e.g. "THE STORM")
    if (stripped == stripped.upper()
            and len(stripped) <= _MAX_ALLCAPS_HEADING_LEN
            and len(stripped) >= 2
            and stripped.replace(" ", "").isalpha()):
        return True
    return False


def _split_chapters(text: str) -> list[dict]:
    """
    Return a list of dicts:  {"title": str, "body": str}
    where body is the raw text of the chapter (without the heading line).
    """
    lines = text.splitlines(keepends=True)
    chapters: list[dict] = []
    current_title = "Chapter 1"
    current_lines: list[str] = []
    found_any_heading = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if _is_heading(stripped):
            # Save previous chapter if it has content
            body = "".join(current_lines).strip()
            if body:
                chapters.append({"title": current_title, "body": body})
            elif not found_any_heading and current_lines:
                # Text before first heading: treat as a preamble chapter
                chapters.append({"title": "Preamble", "body": "".join(current_lines).strip()})
            current_title = stripped
            current_lines = []
            found_any_heading = True
        else:
            current_lines.append(line)

    # Flush last chapter
    body = "".join(current_lines).strip()
    if body:
        chapters.append({"title": current_title, "body": body})

    if not chapters:
        # Entire file had no parseable text
        return []

    # If no headings were found, we have exactly one element with title "Chapter 1"
    return chapters


def _split_paragraphs(body: str) -> list[str]:
    """Split chapter body into non-empty paragraphs on blank lines."""
    blocks = re.split(r"\n{2,}", body)
    return [b.strip() for b in blocks if b.strip()]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_hash(sentence_text: str) -> str:
    return _sha256(normalize_for_hash(sentence_text).encode("utf-8"))


# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------

def _insert(
    db: DatabaseConnection,
    title: str,
    author: str,
    language: str,
    file_hash: str,
    chapters_raw: list[dict],
) -> ImportResult:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    chapter_count = 0
    paragraph_count = 0
    sentence_count = 0
    global_sentence_idx = 0  # monotonic sentence index across the whole book

    with db.get_connection() as conn:
        # Check for duplicate
        existing = conn.execute(
            "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if existing:
            raise DuplicateBookError(
                f"A book with file_hash={file_hash!r} already exists (id={existing['id']})"
            )

        # Insert book (total_* updated at the end)
        book_id: int = conn.execute(
            """INSERT INTO books
               (title, author, language, source_format, file_hash, imported_at,
                total_chapters, total_sentences)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
            (title, author, language, SourceFormat.TXT.value, file_hash, now),
        ).lastrowid

        chapter_sentence_start = 0

        for ch_idx, ch in enumerate(chapters_raw, start=1):
            ch_sentence_start = global_sentence_idx
            paragraphs = _split_paragraphs(ch["body"])
            par_sentence_start = global_sentence_idx

            chapter_id: int = conn.execute(
                """INSERT INTO chapters
                   (book_id, idx, title, sentence_start, sentence_end)
                   VALUES (?, ?, ?, ?, ?)""",
                (book_id, ch_idx, ch["title"],
                 ch_sentence_start, ch_sentence_start),  # end updated below
            ).lastrowid
            chapter_count += 1

            for par_idx, para_text in enumerate(paragraphs, start=1):
                par_start = global_sentence_idx

                paragraph_id: int = conn.execute(
                    """INSERT INTO paragraphs
                       (chapter_id, idx, sentence_start, sentence_end)
                       VALUES (?, ?, ?, ?)""",
                    (chapter_id, par_idx, par_start, par_start),
                ).lastrowid
                paragraph_count += 1

                sentences = segment_sentences(para_text)
                for sent in sentences:
                    conn.execute(
                        """INSERT INTO sentences
                           (book_id, chapter_id, paragraph_id, idx,
                            text, text_hash,
                            char_offset_start, char_offset_end)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (book_id, chapter_id, paragraph_id,
                         global_sentence_idx,
                         sent.text,
                         _text_hash(sent.text),
                         sent.char_start,
                         sent.char_end),
                    )
                    global_sentence_idx += 1
                    sentence_count += 1

                # Update paragraph.sentence_end
                conn.execute(
                    "UPDATE paragraphs SET sentence_end = ? WHERE id = ?",
                    (global_sentence_idx, paragraph_id),
                )

            # Update chapter.sentence_end
            conn.execute(
                "UPDATE chapters SET sentence_end = ? WHERE id = ?",
                (global_sentence_idx, chapter_id),
            )

        # Update book totals
        conn.execute(
            "UPDATE books SET total_chapters = ?, total_sentences = ? WHERE id = ?",
            (chapter_count, sentence_count, book_id),
        )

    return ImportResult(
        book_id=book_id,
        chapter_count=chapter_count,
        paragraph_count=paragraph_count,
        sentence_count=sentence_count,
    )
