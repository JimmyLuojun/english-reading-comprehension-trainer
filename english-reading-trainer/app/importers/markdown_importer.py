"""Markdown importer for normalized reader-text imports."""

from __future__ import annotations

from pathlib import Path
import re

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.importers.txt_importer import (
    ImportResult,
    _decode,
    _insert,
    _sha256,
)


_ATX_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SETEXT_HEADING_RE = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_REFERENCE_DEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+\S+")
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_HORIZONTAL_RULE_RE = re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$")
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_LIST_PREFIX_RE = re.compile(r"^\s{0,3}(?:[-+*]|\d{1,4}[.)])\s+")
_TASK_MARKER_RE = re.compile(r"^\[[ xX]\]\s+")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_REFERENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_AUTOLINK_URL_RE = re.compile(r"<(?:https?|mailto):[^>]+>", re.I)
_HTML_TAG_RE = re.compile(r"</?[^>]+>")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_EMPHASIS_PATTERNS = (
    re.compile(r"(?<!\\)(\*\*\*|___)(.+?)(?<!\\)\1"),
    re.compile(r"(?<!\\)(\*\*|__)(.+?)(?<!\\)\1"),
    re.compile(r"(?<!\\)(\*|_)([^*_]+?)(?<!\\)\1"),
    re.compile(r"(?<!\\)(~~)(.+?)(?<!\\)\1"),
)
_ESCAPED_MARKDOWN_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>])")
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


def import_markdown(
    db: DatabaseConnection,
    file_path: str | Path,
    title: str,
    author: str = "",
    language: str = "en",
) -> ImportResult:
    """Read *file_path* as Markdown and import readable prose into the DB."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Markdown path is not a file: {path}")
    return import_markdown_bytes(
        db,
        path.read_bytes(),
        title=title,
        author=author,
        language=language,
    )


def import_markdown_bytes(
    db: DatabaseConnection,
    raw_bytes: bytes,
    *,
    title: str,
    author: str = "",
    language: str = "en",
) -> ImportResult:
    """
    Parse Markdown bytes and insert the standard reader hierarchy.

    The duplicate hash is based on the original Markdown bytes. Markdown syntax
    is normalized before sentence segmentation so cards do not include markup.
    """
    file_hash = _sha256(raw_bytes)
    markdown = _decode(raw_bytes)
    chapters_raw = _split_markdown_chapters(markdown)
    if not chapters_raw:
        raise ValueError("Markdown contains no usable text")
    return _insert(
        db,
        title,
        author,
        language,
        file_hash,
        chapters_raw,
        source_format=SourceFormat.MD,
    )


def _split_markdown_chapters(markdown: str) -> list[dict[str, str]]:
    """Split Markdown into chapter dictionaries using Markdown headings."""
    items = _markdown_items(markdown)
    if not items:
        return []

    chapters: list[dict[str, str]] = []
    current_title = "Chapter 1"
    current_lines: list[str] = []

    for kind, value in items:
        if kind == "heading":
            _append_markdown_chapter(chapters, current_title, current_lines)
            current_title = value
            current_lines = []
            continue
        current_lines.append(value)

    _append_markdown_chapter(chapters, current_title, current_lines)
    if chapters:
        return chapters
    return []


def _append_markdown_chapter(
    chapters: list[dict[str, str]],
    title: str,
    lines: list[str],
) -> None:
    body = "\n".join(lines).strip()
    if body:
        chapters.append({"title": title, "body": body})


def _markdown_items(markdown: str) -> list[tuple[str, str]]:
    text = _strip_front_matter(_HTML_COMMENT_RE.sub("", markdown))
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    items: list[tuple[str, str]] = []
    in_fence = False
    fence_char = ""
    index = 0

    while index < len(raw_lines):
        line = raw_lines[index]
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
                fence_char = ""
            index += 1
            continue
        if in_fence:
            index += 1
            continue

        atx_heading = _ATX_HEADING_RE.match(line)
        if atx_heading:
            heading = _clean_inline_markdown(atx_heading.group(1))
            if heading:
                items.append(("heading", heading))
            index += 1
            continue

        if (
            index + 1 < len(raw_lines)
            and line.strip()
            and _SETEXT_HEADING_RE.match(raw_lines[index + 1])
        ):
            heading = _clean_inline_markdown(line)
            if heading:
                items.append(("heading", heading))
            index += 2
            continue

        cleaned = _clean_markdown_line(line)
        if cleaned is not None:
            items.append(("text", cleaned))
        index += 1

    return _squash_blank_items(items)


def _strip_front_matter(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    delimiter = lines[0].strip()
    if delimiter not in {"---", "+++"}:
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == delimiter:
            return "\n".join(lines[index + 1 :])
    return text


def _clean_markdown_line(line: str) -> str | None:
    if not line.strip():
        return ""
    if _REFERENCE_DEF_RE.match(line) or _TABLE_SEPARATOR_RE.match(line):
        return None
    if _HORIZONTAL_RULE_RE.match(line):
        return ""

    stripped = line
    while True:
        next_line = _BLOCKQUOTE_RE.sub("", stripped)
        if next_line == stripped:
            break
        stripped = next_line
    stripped = _LIST_PREFIX_RE.sub("", stripped)
    stripped = _TASK_MARKER_RE.sub("", stripped)
    return _clean_inline_markdown(stripped)


def _clean_inline_markdown(text: str) -> str:
    cleaned = _IMAGE_RE.sub(lambda match: match.group(1), text)
    cleaned = _LINK_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _REFERENCE_LINK_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _AUTOLINK_URL_RE.sub("", cleaned)
    cleaned = _INLINE_CODE_RE.sub(lambda match: match.group(1), cleaned)
    for pattern in _EMPHASIS_PATTERNS:
        cleaned = pattern.sub(lambda match: match.group(2), cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _ESCAPED_MARKDOWN_RE.sub(lambda match: match.group(1), cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _squash_blank_items(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    squashed: list[tuple[str, str]] = []
    previous_blank = False
    for kind, value in items:
        if kind == "heading":
            while squashed and squashed[-1] == ("text", ""):
                squashed.pop()
            squashed.append((kind, value))
            previous_blank = False
            continue
        if value == "":
            if squashed and not previous_blank:
                squashed.append((kind, value))
            previous_blank = True
            continue
        squashed.append((kind, value))
        previous_blank = False
    while squashed and squashed[-1] == ("text", ""):
        squashed.pop()
    return squashed
