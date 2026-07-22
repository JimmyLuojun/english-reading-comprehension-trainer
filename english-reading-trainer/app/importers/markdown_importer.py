"""Markdown importer for normalized reader-text imports."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import mimetypes
from pathlib import Path
import re
import shutil

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.importers.txt_importer import (
    DuplicateBookError,
    ImportResult,
    _decode,
    _sha256,
    _text_hash,
)
from app.nlp.sentence_segmenter import segment_sentences


_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SETEXT_HEADING_RE = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_REFERENCE_DEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+\S+")
_DATA_IMAGE_REFERENCE_DEF_RE = re.compile(
    r"^\s{0,3}\[([^\]]+)\]:\s+(data:image/[^\s]+)", re.I
)
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_HORIZONTAL_RULE_RE = re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$")
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_LIST_PREFIX_RE = re.compile(r"^\s{0,3}([-+*]|\d{1,4}[.)])\s+")
_TASK_MARKER_RE = re.compile(r"^\[[ xX]\]\s+")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_REFERENCE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
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
_DATA_IMAGE_URL_RE = re.compile(
    r"^data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$",
    re.I,
)
_INLINE_IMAGE_TOKEN_RE = re.compile(r"\[\[md-image-token:(\d+)\]\]")
_MAX_BLOCKQUOTE_DEPTH = 6
_WHOLE_STRONG_RE = re.compile(r"^\s*(\*\*|__)(?=\S).+?(?<=\S)\1\s*$")
_WHOLE_EMPHASIS_RE = re.compile(r"^\s*(\*|_)(?=\S).+?(?<=\S)\1\s*$")


@dataclass(frozen=True)
class _MarkdownInlineImage:
    token_index: int
    data_url: str
    media_type: str
    content: bytes
    alt_text: str


@dataclass(frozen=True)
class _MarkdownBlock:
    kind: str
    text: str
    payload_json: str = ""


class _MarkdownImageRegistry:
    def __init__(self) -> None:
        self._images: list[_MarkdownInlineImage] = []
        self._tokens_by_data_url: dict[str, str] = {}

    @property
    def images(self) -> list[_MarkdownInlineImage]:
        return self._images

    def token_for(self, data_url: str, alt_text: str) -> str:
        normalized = _normalize_data_url(data_url)
        existing = self._tokens_by_data_url.get(normalized)
        if existing is not None:
            return existing
        media_type, content = _decode_data_image(normalized)
        token = f"[[md-image-token:{len(self._images)}]]"
        self._tokens_by_data_url[normalized] = token
        self._images.append(
            _MarkdownInlineImage(
                token_index=len(self._images),
                data_url=normalized,
                media_type=media_type,
                content=content,
                alt_text=alt_text,
            )
        )
        return token


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
    image_registry = _MarkdownImageRegistry()
    chapter = _parse_markdown_chapter(markdown, image_registry=image_registry)
    if not _has_trainable_markdown_text(chapter):
        raise ValueError("Markdown contains no usable text")
    result = _insert_markdown(
        db,
        title=title,
        author=author,
        language=language,
        file_hash=file_hash,
        chapter=chapter,
    )
    if image_registry.images:
        try:
            _store_inline_images(db, result.book_id, image_registry.images)
        except Exception:
            _delete_imported_book(db, result.book_id)
            raise
    return result


def _split_markdown_chapters(
    markdown: str,
    image_registry: _MarkdownImageRegistry | None = None,
) -> list[dict[str, str]]:
    """Return one chapter per Markdown file with syntax normalized as text."""
    chapter = _parse_markdown_chapter(markdown, image_registry=image_registry)
    text_blocks = [
        block.text
        for block in chapter["blocks"]
        if block.kind in {"prose", "list_item"} and block.text.strip()
    ]
    if not text_blocks:
        return []
    chapters: list[dict[str, str]] = []
    _append_markdown_chapter(
        chapters,
        "Chapter 1",
        text_blocks,
    )
    return chapters


def _parse_markdown_chapter(
    markdown: str,
    *,
    image_registry: _MarkdownImageRegistry | None = None,
) -> dict[str, object]:
    return {
        "title": "Chapter 1",
        "blocks": _markdown_blocks(markdown, image_registry=image_registry),
    }


def _has_trainable_markdown_text(chapter: dict[str, object]) -> bool:
    return any(
        block.kind in {"prose", "list_item"} and bool(block.text.strip())
        for block in chapter["blocks"]
    )


def _append_markdown_chapter(
    chapters: list[dict[str, str]],
    title: str,
    lines: list[str],
) -> None:
    body = "\n".join(lines).strip()
    if body:
        chapters.append({"title": title, "body": body})


def _markdown_blocks(
    markdown: str,
    *,
    image_registry: _MarkdownImageRegistry | None = None,
) -> list[_MarkdownBlock]:
    text = _strip_front_matter(_HTML_COMMENT_RE.sub("", markdown))
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    image_refs = _data_image_references(raw_lines)
    blocks: list[_MarkdownBlock] = []
    paragraph_lines: list[str] = []
    paragraph_quote_depth = 0
    paragraph_style = ""
    in_fence = False
    fence_char = ""
    index = 0

    def flush_paragraph() -> None:
        nonlocal paragraph_quote_depth, paragraph_style
        if paragraph_lines:
            text = " ".join(paragraph_lines).strip()
            if text:
                payload: dict[str, object] = {}
                if paragraph_quote_depth:
                    payload["quote_depth"] = paragraph_quote_depth
                if paragraph_style:
                    payload["block_style"] = paragraph_style
                payload_json = json.dumps(payload) if payload else ""
                blocks.append(_MarkdownBlock("prose", text, payload_json))
            paragraph_lines.clear()
        paragraph_quote_depth = 0
        paragraph_style = ""

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
            flush_paragraph()
            heading = _clean_inline_markdown(
                atx_heading.group(2),
                image_registry=image_registry,
                image_refs=image_refs,
            )
            if heading:
                blocks.append(
                    _MarkdownBlock(
                        "heading",
                        heading,
                        json.dumps({"level": len(atx_heading.group(1))}),
                    )
                )
            index += 1
            continue

        if (
            index + 1 < len(raw_lines)
            and line.strip()
            and _SETEXT_HEADING_RE.match(raw_lines[index + 1])
        ):
            flush_paragraph()
            heading = _clean_inline_markdown(
                line,
                image_registry=image_registry,
                image_refs=image_refs,
            )
            if heading:
                level = 1 if raw_lines[index + 1].lstrip().startswith("=") else 2
                blocks.append(
                    _MarkdownBlock(
                        "heading",
                        heading,
                        json.dumps({"level": level}),
                    )
                )
            index += 2
            continue

        if not line.strip() or _HORIZONTAL_RULE_RE.match(line):
            flush_paragraph()
            index += 1
            continue
        if _REFERENCE_DEF_RE.match(line) or _TABLE_SEPARATOR_RE.match(line):
            flush_paragraph()
            index += 1
            continue

        quote_depth = _blockquote_depth(line)
        blockquote_stripped = _strip_blockquote_prefixes(line)
        list_match = _LIST_PREFIX_RE.match(blockquote_stripped)
        if list_match:
            flush_paragraph()
            cleaned = _clean_markdown_line(
                blockquote_stripped,
                image_registry=image_registry,
                image_refs=image_refs,
            )
            if cleaned:
                marker = list_match.group(1)
                task_text = blockquote_stripped[list_match.end() :]
                task_match = _TASK_MARKER_RE.match(task_text)
                payload: dict[str, object] = {
                    "ordered": marker[0].isdigit(),
                    "marker": marker,
                }
                if quote_depth:
                    payload["quote_depth"] = quote_depth
                if task_match:
                    payload["task"] = True
                    payload["checked"] = task_text[1].lower() == "x"
                    task_text = task_text[task_match.end() :]
                block_style = _whole_line_style(task_text)
                if block_style:
                    payload["block_style"] = block_style
                blocks.append(
                    _MarkdownBlock(
                        "list_item",
                        cleaned,
                        json.dumps(payload),
                    )
                )
            index += 1
            continue

        cleaned = _clean_markdown_line(
            line,
            image_registry=image_registry,
            image_refs=image_refs,
        )
        if cleaned:
            if paragraph_lines and quote_depth != paragraph_quote_depth:
                flush_paragraph()
            line_style = _whole_line_style(blockquote_stripped)
            if paragraph_lines and line_style != paragraph_style:
                paragraph_style = ""
            elif not paragraph_lines:
                paragraph_style = line_style
            paragraph_quote_depth = quote_depth
            paragraph_lines.append(cleaned)
        elif quote_depth:
            flush_paragraph()
        index += 1

    flush_paragraph()
    return blocks


def _strip_front_matter(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    delimiter = lines[0].strip()
    if delimiter not in {"---", "+++"}:
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == delimiter:
            return "\n".join(lines[index + 1 :])
    return text


def _data_image_references(lines: list[str]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in lines:
        match = _DATA_IMAGE_REFERENCE_DEF_RE.match(line)
        if match:
            refs[match.group(1)] = match.group(2)
    return refs


def _strip_blockquote_prefixes(line: str) -> str:
    stripped = line
    while True:
        next_line = _BLOCKQUOTE_RE.sub("", stripped)
        if next_line == stripped:
            return stripped
        stripped = next_line


def _blockquote_depth(line: str) -> int:
    depth = 0
    stripped = line
    while depth < _MAX_BLOCKQUOTE_DEPTH:
        match = _BLOCKQUOTE_RE.match(stripped)
        if not match:
            break
        depth += 1
        stripped = stripped[match.end() :]
    return depth


def _whole_line_style(line: str) -> str:
    if _WHOLE_STRONG_RE.match(line):
        return "strong"
    if _WHOLE_EMPHASIS_RE.match(line):
        return "emphasis"
    return ""


def _clean_markdown_line(
    line: str,
    *,
    image_registry: _MarkdownImageRegistry | None = None,
    image_refs: dict[str, str] | None = None,
) -> str | None:
    if not line.strip():
        return ""
    if _REFERENCE_DEF_RE.match(line) or _TABLE_SEPARATOR_RE.match(line):
        return None
    if _HORIZONTAL_RULE_RE.match(line):
        return ""

    stripped = _strip_blockquote_prefixes(line)
    stripped = _LIST_PREFIX_RE.sub("", stripped)
    stripped = _TASK_MARKER_RE.sub("", stripped)
    return _clean_inline_markdown(
        stripped,
        image_registry=image_registry,
        image_refs=image_refs,
    )


def _insert_markdown(
    db: DatabaseConnection,
    *,
    title: str,
    author: str,
    language: str,
    file_hash: str,
    chapter: dict[str, object],
) -> ImportResult:
    now = datetime.now(timezone.utc).isoformat()
    paragraph_count = 0
    sentence_count = 0
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
            (title, author, language, SourceFormat.MD.value, file_hash, now),
        ).lastrowid
        chapter_id: int = conn.execute(
            """INSERT INTO chapters
               (book_id, idx, title, sentence_start, sentence_end)
               VALUES (?, 1, ?, 0, 0)""",
            (book_id, chapter["title"]),
        ).lastrowid

        for block_idx, block in enumerate(chapter["blocks"], start=1):
            paragraph_id: int | None = None
            if block.kind in {"prose", "list_item"}:
                paragraph_count += 1
                par_start = global_sentence_idx
                paragraph_id = conn.execute(
                    """INSERT INTO paragraphs
                       (chapter_id, idx, sentence_start, sentence_end)
                       VALUES (?, ?, ?, ?)""",
                    (chapter_id, paragraph_count, par_start, par_start),
                ).lastrowid
                sentences = segment_sentences(block.text)
                sentence_rows = [
                    (sent.text, sent.char_start, sent.char_end)
                    for sent in sentences
                ] or [(block.text, 0, len(block.text))]
                for sentence_text, char_start, char_end in sentence_rows:
                    conn.execute(
                        """INSERT INTO sentences
                           (book_id, chapter_id, paragraph_id, idx,
                            text, text_hash, char_offset_start, char_offset_end)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            book_id,
                            chapter_id,
                            paragraph_id,
                            global_sentence_idx,
                            sentence_text,
                            _text_hash(sentence_text),
                            char_start,
                            char_end,
                        ),
                    )
                    global_sentence_idx += 1
                    sentence_count += 1
                conn.execute(
                    "UPDATE paragraphs SET sentence_end = ? WHERE id = ?",
                    (global_sentence_idx, paragraph_id),
                )

            conn.execute(
                """INSERT INTO chapter_blocks
                   (book_id, chapter_id, idx, kind, paragraph_id, text, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    book_id,
                    chapter_id,
                    block_idx,
                    block.kind,
                    paragraph_id,
                    block.text if block.kind == "heading" else "",
                    block.payload_json,
                ),
            )

        conn.execute(
            "UPDATE chapters SET sentence_end = ? WHERE id = ?",
            (global_sentence_idx, chapter_id),
        )
        conn.execute(
            "UPDATE books SET total_chapters = 1, total_sentences = ? WHERE id = ?",
            (sentence_count, book_id),
        )

    return ImportResult(
        book_id=book_id,
        chapter_count=1,
        paragraph_count=paragraph_count,
        sentence_count=sentence_count,
    )


def _replacement_for_image(
    image_registry: _MarkdownImageRegistry | None,
    target: str,
    alt_text: str,
) -> str:
    if image_registry is not None and target.startswith("data:image/"):
        try:
            return f" {image_registry.token_for(target, alt_text)} "
        except ValueError:
            pass
    return alt_text


def _clean_inline_markdown(
    text: str,
    image_registry: _MarkdownImageRegistry | None = None,
    image_refs: dict[str, str] | None = None,
) -> str:
    cleaned = _REFERENCE_IMAGE_RE.sub(
        lambda match: _replacement_for_image(
            image_registry,
            (image_refs or {}).get(match.group(2) or match.group(1), ""),
            match.group(1),
        ),
        text,
    )
    cleaned = _IMAGE_RE.sub(
        lambda match: _replacement_for_image(
            image_registry,
            match.group(2),
            match.group(1),
        ),
        cleaned,
    )
    cleaned = _LINK_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _REFERENCE_LINK_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _AUTOLINK_URL_RE.sub("", cleaned)
    cleaned = _INLINE_CODE_RE.sub(lambda match: match.group(1), cleaned)
    for pattern in _EMPHASIS_PATTERNS:
        cleaned = pattern.sub(lambda match: match.group(2), cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _ESCAPED_MARKDOWN_RE.sub(lambda match: match.group(1), cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _normalize_data_url(data_url: str) -> str:
    return _WHITESPACE_RE.sub("", data_url.strip())


def _decode_data_image(data_url: str) -> tuple[str, bytes]:
    match = _DATA_IMAGE_URL_RE.match(data_url)
    if not match:
        raise ValueError("Unsupported Markdown data image URL")
    media_type = match.group(1).lower()
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid Markdown data image payload") from exc
    if not content:
        raise ValueError("Empty Markdown data image payload")
    return media_type, content


def _store_inline_images(
    db: DatabaseConnection,
    book_id: int,
    images: list[_MarkdownInlineImage],
) -> None:
    asset_id_by_token: dict[int, int] = {}
    asset_base_dir = Path(getattr(db, "_db_path")).parent / "assets"
    book_asset_dir = asset_base_dir / "books" / str(book_id)
    book_asset_dir.mkdir(parents=True, exist_ok=True)

    with db.get_connection() as conn:
        for image in images:
            digest = _sha256(image.content)
            storage_path = _inline_image_storage_path(book_id, image, digest)
            target_path = asset_base_dir / storage_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(image.content)
            asset_id = conn.execute(
                """INSERT INTO book_assets
                   (book_id, source_href, media_type, storage_path, sha256,
                    byte_size, alt_text, is_missing)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    book_id,
                    f"markdown-inline-{image.token_index}",
                    image.media_type,
                    storage_path,
                    digest,
                    len(image.content),
                    image.alt_text,
                ),
            ).lastrowid
            asset_id_by_token[image.token_index] = asset_id

        rows = conn.execute(
            "SELECT id, text FROM sentences WHERE book_id = ? ORDER BY id",
            (book_id,),
        ).fetchall()
        for row in rows:
            original = row["text"]
            updated = _INLINE_IMAGE_TOKEN_RE.sub(
                lambda match: _final_inline_image_token(
                    asset_id_by_token,
                    int(match.group(1)),
                ),
                original,
            )
            if updated != original:
                conn.execute(
                    """UPDATE sentences
                          SET text = ?, text_hash = ?, char_offset_end = ?
                        WHERE id = ?""",
                    (updated, _text_hash(updated), len(updated), row["id"]),
                )

        block_rows = conn.execute(
            "SELECT id, text FROM chapter_blocks WHERE book_id = ? AND text != ''",
            (book_id,),
        ).fetchall()
        for row in block_rows:
            original = row["text"]
            updated = _INLINE_IMAGE_TOKEN_RE.sub(
                lambda match: _final_inline_image_token(
                    asset_id_by_token,
                    int(match.group(1)),
                ),
                original,
            )
            if updated != original:
                conn.execute(
                    "UPDATE chapter_blocks SET text = ? WHERE id = ?",
                    (updated, row["id"]),
                )


def _inline_image_storage_path(
    book_id: int,
    image: _MarkdownInlineImage,
    digest: str,
) -> str:
    extension = mimetypes.guess_extension(image.media_type) or ".bin"
    if extension == ".jpe":
        extension = ".jpg"
    return (
        f"books/{book_id}/markdown-inline-{image.token_index}-"
        f"{digest[:12]}{extension}"
    )


def _final_inline_image_token(asset_id_by_token: dict[int, int], token_index: int) -> str:
    asset_id = asset_id_by_token.get(token_index)
    return f"[[md-image:{asset_id}]]" if asset_id is not None else ""


def _delete_imported_book(db: DatabaseConnection, book_id: int) -> None:
    asset_dir = Path(getattr(db, "_db_path")).parent / "assets" / "books" / str(book_id)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    shutil.rmtree(asset_dir, ignore_errors=True)
