"""Import workflow services for the FastAPI web interface."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.db_connection import DatabaseConnection
from app.importers.epub_importer import DuplicateBookError as EpubDuplicateBookError
from app.importers.epub_importer import calculate_epub_file_hash, import_epub
from app.importers.markdown_importer import import_markdown_bytes
from app.importers.pdf_importer import calculate_pdf_file_hash, import_pdf
from app.importers.txt_importer import DuplicateBookError, import_text
from app.web.config import (
    _MAX_URL_IMPORT_BYTES,
    _URL_IMPORT_MAX_REDIRECTS,
    _URL_IMPORT_TIMEOUT_SECONDS,
)
from app.web.queries import _lookup_book_id_by_hash
from app.web.utils import _resolve_title

_ALLOWED_URL_SCHEMES = {"http", "https"}
_ALLOWED_URL_CONTENT_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "text/plain",
}
_ARTICLE_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre")
_REMOVED_HTML_TAGS = (
    "aside",
    "button",
    "canvas",
    "footer",
    "form",
    "header",
    "iframe",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
)
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


class UrlImportError(ValueError):
    """Raised when a remote URL cannot be imported as readable text."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FetchedUrlArticle:
    """Readable text extracted from a URL plus an optional page title."""

    title: str
    text: str


@dataclass(frozen=True)
class ImportOutcome:
    """Result of an import workflow, independent of HTTP rendering."""

    book_id: int | None = None
    duplicate_book_id: int | None = None
    error: str | None = None
    status_code: int = 200

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_book_id is not None

    @property
    def is_error(self) -> bool:
        return self.error is not None


def import_text_bytes(
    db: DatabaseConnection,
    raw: bytes,
    *,
    form_title: str,
    author: str,
    fallback_title: str = "",
) -> ImportOutcome:
    """Import raw TXT bytes and return a routing-neutral outcome."""
    title = _resolve_title(form_title, raw, fallback_title=fallback_title)
    try:
        result = import_text(db, raw, title=title, author=author.strip())
    except DuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, hashlib.sha256(raw).hexdigest())
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except ValueError as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)


def import_url_content(
    db: DatabaseConnection,
    url: str,
    *,
    form_title: str,
    author: str,
) -> ImportOutcome:
    """Fetch a web page, extract readable text, and import it as TXT content."""
    try:
        article = fetch_url_article(url)
        raw = article.text.encode("utf-8")
        result = import_text_bytes(
            db,
            raw,
            form_title=form_title.strip() or article.title,
            author=author,
        )
    except UrlImportError as exc:
        return ImportOutcome(error=str(exc), status_code=exc.status_code)
    return result


def fetch_url_article(
    url: str,
    *,
    max_bytes: int = _MAX_URL_IMPORT_BYTES,
    timeout_seconds: float = _URL_IMPORT_TIMEOUT_SECONDS,
    max_redirects: int = _URL_IMPORT_MAX_REDIRECTS,
    transport: httpx.BaseTransport | None = None,
) -> FetchedUrlArticle:
    """Download a URL with size/type limits and return extracted article text."""
    normalized_url = _validate_import_url(url)
    headers = {
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        "User-Agent": "EnglishReadingTrainer/0.1 URL Import",
    }
    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=max_redirects,
            timeout=timeout_seconds,
            transport=transport,
        ) as client:
            with client.stream("GET", normalized_url, headers=headers) as response:
                _validate_import_url(str(response.url))
                if response.status_code >= 400:
                    raise UrlImportError(f"URL returned HTTP {response.status_code}.")
                content_type = _response_content_type(response.headers.get("content-type", ""))
                if content_type and content_type not in _ALLOWED_URL_CONTENT_TYPES:
                    raise UrlImportError(
                        "URL must return HTML or plain text content.",
                    )
                content_length = _parse_content_length(response.headers.get("content-length", ""))
                if content_length is not None and content_length > max_bytes:
                    raise UrlImportError(
                        f"URL content exceeds {_format_byte_limit(max_bytes)} limit.",
                        status_code=413,
                    )
                raw = _read_limited_response(response, max_bytes=max_bytes)
                encoding = _response_charset(response.headers.get("content-type", ""))
    except httpx.TooManyRedirects as exc:
        raise UrlImportError("URL redirected too many times.") from exc
    except httpx.TimeoutException as exc:
        raise UrlImportError("URL request timed out.") from exc
    except httpx.RequestError as exc:
        raise UrlImportError(f"URL request failed: {exc}") from exc

    if not raw.strip():
        raise UrlImportError("URL returned empty content.")
    decoded = raw.decode(encoding or "utf-8", errors="replace")
    if content_type == "text/plain":
        text = _normalize_plain_text(decoded)
        title = ""
    else:
        title, text = _extract_html_text(decoded)
    if not text.strip():
        raise UrlImportError("URL page contains no readable text.")
    return FetchedUrlArticle(title=title, text=text)


def _validate_import_url(url: str) -> str:
    normalized = str(url or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise UrlImportError("Enter a valid http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise UrlImportError("URL user info is not supported.")
    host = parsed.hostname or ""
    if _is_blocked_host(host):
        raise UrlImportError("URL host is not allowed.")
    return normalized


def _is_blocked_host(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def _response_content_type(header: str) -> str:
    return header.split(";", 1)[0].strip().lower()


def _response_charset(header: str) -> str:
    for part in header.split(";")[1:]:
        key, sep, value = part.strip().partition("=")
        if sep and key.lower() == "charset":
            return value.strip().strip('"')
    return ""


def _parse_content_length(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_limited_response(response: httpx.Response, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise UrlImportError(
                f"URL content exceeds {_format_byte_limit(max_bytes)} limit.",
                status_code=413,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _format_byte_limit(max_bytes: int) -> str:
    if max_bytes % (1024 * 1024) == 0:
        return f"{max_bytes // (1024 * 1024)} MB"
    if max_bytes % 1024 == 0:
        return f"{max_bytes // 1024} KB"
    return f"{max_bytes} bytes"


def _extract_html_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_REMOVED_HTML_TAGS):
        tag.decompose()
    for tag in soup.select("[hidden], [aria-hidden='true']"):
        tag.decompose()
    title = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    container = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = _extract_text_blocks(container)
    if not blocks:
        fallback = _clean_text(container.get_text("\n", strip=True))
        blocks = [fallback] if fallback else []
    return title, "\n\n".join(blocks)


def _extract_text_blocks(container: Any) -> list[str]:
    blocks: list[str] = []
    for tag in container.find_all(_ARTICLE_BLOCK_TAGS):
        text = _clean_text(tag.get_text(" ", strip=True))
        if text and (not blocks or blocks[-1] != text):
            blocks.append(text)
    return blocks


def _normalize_plain_text(text: str) -> str:
    lines = [_clean_text(line) for line in text.splitlines()]
    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if normalized and not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False
    return "\n".join(normalized).strip()


def _clean_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip()


def import_epub_file(
    db: DatabaseConnection,
    file_path: str | Path,
    *,
    form_title: str,
    author: str,
) -> ImportOutcome:
    """Import an EPUB file and return a routing-neutral outcome."""
    try:
        file_hash = calculate_epub_file_hash(file_path)
        result = import_epub(
            db,
            file_path,
            title=form_title.strip() or None,
            author=author.strip() or None,
        )
    except EpubDuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, file_hash)
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except (ValueError, FileNotFoundError) as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)


def import_markdown_file(
    db: DatabaseConnection,
    file_path: str | Path,
    *,
    form_title: str,
    author: str,
    fallback_title: str = "",
) -> ImportOutcome:
    """Import a Markdown file and return a routing-neutral outcome."""
    path = Path(file_path)
    try:
        raw = path.read_bytes()
        result = import_markdown_bytes(
            db,
            raw,
            title=form_title.strip() or fallback_title.strip() or path.stem,
            author=author.strip(),
        )
    except DuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, hashlib.sha256(raw).hexdigest())
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except (ValueError, OSError) as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)


def import_pdf_file(
    db: DatabaseConnection,
    file_path: str | Path,
    *,
    form_title: str,
    author: str,
) -> ImportOutcome:
    """Import a PDF file and return a routing-neutral outcome."""
    try:
        file_hash = calculate_pdf_file_hash(file_path)
        result = import_pdf(
            db,
            file_path,
            title=form_title.strip() or None,
            author=author.strip() or None,
        )
    except EpubDuplicateBookError:
        existing_id = _lookup_book_id_by_hash(db, file_hash)
        return ImportOutcome(duplicate_book_id=existing_id, status_code=409)
    except (ValueError, FileNotFoundError) as exc:
        return ImportOutcome(error=str(exc), status_code=400)
    return ImportOutcome(book_id=result.book_id)
