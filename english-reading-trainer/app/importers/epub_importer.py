"""
EPUB file importer: reads an EPUB book and inserts the full
Book → Chapter → Paragraph → Sentence hierarchy into the database.

Processing pipeline:
  1. Read EPUB with ebooklib; extract metadata (title, author).
  2. Build a TOC map (href → chapter title) for naming chapters.
  3. Walk spine items in reading order; skip navigation documents.
  4. For each content item: parse HTML with BeautifulSoup,
     extract <p> text blocks as paragraphs, segment with pysbd.
  5. Insert all rows in a single transaction.

Chapter title resolution (priority):
  1. TOC entry matching the item's href
  2. First <h1> / <h2> / <h3> in the item's HTML
  3. Item filename (stem)
  4. "Chapter N" fallback
"""

import hashlib
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from ebooklib import ITEM_DOCUMENT, ITEM_NAVIGATION, epub

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.importers.txt_importer import DuplicateBookError, ImportResult
from app.nlp.sentence_segmenter import normalize_for_hash, segment_sentences

# Suppress ebooklib's noisy lxml XML-parsed-as-HTML warning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")

# Tags whose text content becomes paragraph candidates
_BLOCK_TAGS = {"p", "div", "blockquote", "li"}

# Tags that are always headings
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Minimum character length for a block to count as a paragraph
_MIN_PARA_LEN = 20


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_epub(
    db: DatabaseConnection,
    file_path: str | Path,
    title: str | None = None,
    author: str | None = None,
    language: str = "en",
) -> ImportResult:
    """
    Parse *file_path* (EPUB) and insert the full hierarchy into the DB.

    If *title* / *author* are None, values are extracted from EPUB metadata.

    Raises:
        FileNotFoundError: if the file does not exist.
        DuplicateBookError: if file_hash already exists in books table.
        ValueError: if the EPUB contains no usable text.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    raw_bytes = file_path.read_bytes()
    file_hash = _sha256(raw_bytes)

    book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

    resolved_title  = title  or _extract_metadata(book, "title")  or file_path.stem
    resolved_author = author or _extract_metadata(book, "creator") or ""

    toc_map = _build_toc_map(book)
    chapters_raw = _extract_chapters(book, toc_map)

    if not chapters_raw:
        raise ValueError(f"EPUB contains no usable text: {file_path}")

    return _insert(
        db, resolved_title, resolved_author, language,
        file_hash, SourceFormat.EPUB, chapters_raw,
    )


# ---------------------------------------------------------------------------
# EPUB parsing helpers
# ---------------------------------------------------------------------------

def _extract_metadata(book: epub.EpubBook, field: str) -> str:
    """Return the first value for a Dublin Core metadata field, or ''."""
    values = book.get_metadata("DC", field)
    if values:
        val = values[0]
        # ebooklib returns (value, attributes_dict) tuples
        return (val[0] if isinstance(val, tuple) else val).strip()
    return ""


def _build_toc_map(book: epub.EpubBook) -> dict[str, str]:
    """
    Return a dict mapping bare filename (without fragment) → chapter title
    extracted from the EPUB TOC tree.
    """
    result: dict[str, str] = {}

    def _walk(items) -> None:
        for item in items:
            if isinstance(item, epub.Link):
                href, _ = urldefrag(item.href)
                bare = href.split("/")[-1]  # strip directory prefix
                if bare and item.title:
                    result[bare] = item.title.strip()
            elif isinstance(item, tuple) and len(item) == 2:
                section, children = item
                if isinstance(section, epub.Section) and section.title:
                    href, _ = urldefrag(section.href or "")
                    bare = href.split("/")[-1]
                    if bare:
                        result[bare] = section.title.strip()
                _walk(children)
            elif isinstance(item, (list, tuple)):
                _walk(item)

    _walk(book.toc)
    return result


def _extract_chapters(
    book: epub.EpubBook,
    toc_map: dict[str, str],
) -> list[dict]:
    """
    Walk spine in reading order; return list of
    {"title": str, "paragraphs": [str, ...]} dicts.
    Skips navigation documents and items with no usable text.
    """
    chapters: list[dict] = []
    ch_idx = 0

    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        if item.get_type() == ITEM_NAVIGATION:
            continue
        if item.get_type() != ITEM_DOCUMENT:
            continue

        html_bytes = item.get_body_content() or item.get_content()
        if not html_bytes:
            continue

        soup = BeautifulSoup(html_bytes, "lxml")

        # Determine chapter title
        bare_name = Path(item.file_name).name
        title = (
            toc_map.get(bare_name)
            or toc_map.get(item.file_name)
            or _heading_from_soup(soup)
            or Path(item.file_name).stem
        )

        paragraphs = _extract_paragraphs(soup)
        if not paragraphs:
            continue

        ch_idx += 1
        chapters.append({"title": title, "paragraphs": paragraphs})

    return chapters


def _heading_from_soup(soup: BeautifulSoup) -> str:
    """Return the text of the first heading tag found, or ''."""
    for tag in _HEADING_TAGS:
        el = soup.find(tag)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    """
    Extract non-empty text blocks from the HTML.

    Strategy:
    - Prefer explicit <p> tags.
    - If none exist, fall back to any block-level element with enough text.
    - Always strip heading tags (h1-h6) — they become the chapter title, not body.
    - Filter blocks shorter than _MIN_PARA_LEN characters.
    """
    # Remove script, style, nav, aside
    for tag in soup.find_all(["script", "style", "nav", "aside", "head"]):
        tag.decompose()

    p_tags = soup.find_all("p")
    candidates = p_tags if p_tags else soup.find_all(_BLOCK_TAGS)

    paragraphs: list[str] = []
    for el in candidates:
        # Skip heading-like <p> elements (very short, ALL CAPS)
        if el.name in _HEADING_TAGS:
            continue
        text = el.get_text(" ", strip=True)
        text = _clean_text(text)
        if len(text) >= _MIN_PARA_LEN:
            paragraphs.append(text)

    return paragraphs


def _clean_text(text: str) -> str:
    """Normalise whitespace in extracted HTML text."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_hash(sentence_text: str) -> str:
    return _sha256(normalize_for_hash(sentence_text).encode("utf-8"))


# ---------------------------------------------------------------------------
# DB insertion  (mirrors txt_importer._insert but uses pre-split paragraphs)
# ---------------------------------------------------------------------------

def _insert(
    db: DatabaseConnection,
    title: str,
    author: str,
    language: str,
    file_hash: str,
    source_format: SourceFormat,
    chapters_raw: list[dict],
) -> ImportResult:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    chapter_count = paragraph_count = sentence_count = 0
    global_sentence_idx = 0

    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if existing:
            raise DuplicateBookError(
                f"A book with file_hash={file_hash!r} already exists "
                f"(id={existing['id']})"
            )

        book_id: int = conn.execute(
            """INSERT INTO books
               (title, author, language, source_format, file_hash, imported_at,
                total_chapters, total_sentences)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
            (title, author, language, source_format.value, file_hash, now),
        ).lastrowid

        for ch_idx, ch in enumerate(chapters_raw, start=1):
            ch_sentence_start = global_sentence_idx

            chapter_id: int = conn.execute(
                """INSERT INTO chapters
                   (book_id, idx, title, sentence_start, sentence_end)
                   VALUES (?, ?, ?, ?, ?)""",
                (book_id, ch_idx, ch["title"],
                 ch_sentence_start, ch_sentence_start),
            ).lastrowid
            chapter_count += 1

            for par_idx, para_text in enumerate(ch["paragraphs"], start=1):
                par_start = global_sentence_idx

                paragraph_id: int = conn.execute(
                    """INSERT INTO paragraphs
                       (chapter_id, idx, sentence_start, sentence_end)
                       VALUES (?, ?, ?, ?)""",
                    (chapter_id, par_idx, par_start, par_start),
                ).lastrowid
                paragraph_count += 1

                for sent in segment_sentences(para_text):
                    conn.execute(
                        """INSERT INTO sentences
                           (book_id, chapter_id, paragraph_id, idx,
                            text, text_hash,
                            char_offset_start, char_offset_end)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (book_id, chapter_id, paragraph_id,
                         global_sentence_idx,
                         sent.text, _text_hash(sent.text),
                         sent.char_start, sent.char_end),
                    )
                    global_sentence_idx += 1
                    sentence_count += 1

                conn.execute(
                    "UPDATE paragraphs SET sentence_end = ? WHERE id = ?",
                    (global_sentence_idx, paragraph_id),
                )

            conn.execute(
                "UPDATE chapters SET sentence_end = ? WHERE id = ?",
                (global_sentence_idx, chapter_id),
            )

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
