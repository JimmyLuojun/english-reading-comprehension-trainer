"""Tests for web import workflow services."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.web.services import imports


def test_import_text_bytes_returns_book_id(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_import_text(db, raw, title, author):
        captured["title"] = title
        captured["author"] = author
        return SimpleNamespace(book_id=7)

    monkeypatch.setattr(
        imports,
        "import_text",
        fake_import_text,
    )

    outcome = imports.import_text_bytes(
        object(),
        b"Movie Scripts\n\nHello.",
        form_title="",
        author=" A ",
        fallback_title="The_escappe_plan_lines",
    )

    assert outcome.book_id == 7
    assert not outcome.is_error
    assert not outcome.is_duplicate
    assert captured == {"title": "The_escappe_plan_lines", "author": "A"}


def test_import_text_bytes_maps_duplicate_to_existing_book(monkeypatch) -> None:
    def raise_duplicate(db, raw, title, author):
        raise imports.DuplicateBookError()

    monkeypatch.setattr(imports, "import_text", raise_duplicate)
    monkeypatch.setattr(imports, "_lookup_book_id_by_hash", lambda db, file_hash: 99)

    outcome = imports.import_text_bytes(object(), b"Hello.", form_title="", author="")

    assert outcome.duplicate_book_id == 99
    assert outcome.status_code == 409


def test_import_text_bytes_maps_value_error(monkeypatch) -> None:
    def raise_value_error(db, raw, title, author):
        raise ValueError("bad text")

    monkeypatch.setattr(imports, "import_text", raise_value_error)

    outcome = imports.import_text_bytes(object(), b"Hello.", form_title="", author="")

    assert outcome.error == "bad text"
    assert outcome.status_code == 400


def test_fetch_url_article_extracts_article_text_and_removes_chrome() -> None:
    html = b"""
    <html>
      <head><title>Page Title</title><script>bad()</script></head>
      <body>
        <nav>Navigation should disappear.</nav>
        <article>
          <h1>Article Heading</h1>
          <p>The first paragraph remains.</p>
          <p>The second paragraph remains.</p>
        </article>
      </body>
    </html>
    """

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=html,
            request=request,
        )
    )

    article = imports.fetch_url_article("https://example.com/article", transport=transport)

    assert article.title == "Page Title"
    assert "Article Heading" in article.text
    assert "The first paragraph remains." in article.text
    assert "Navigation should disappear." not in article.text
    assert "bad()" not in article.text


def test_fetch_url_article_extracts_plain_text() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"First line.\n\n\nSecond line.",
            request=request,
        )
    )

    article = imports.fetch_url_article("https://example.com/article.txt", transport=transport)

    assert article.title == ""
    assert article.text == "First line.\n\nSecond line."


def test_fetch_url_article_rejects_non_http_urls() -> None:
    try:
        imports.fetch_url_article("file:///tmp/article.html")
    except imports.UrlImportError as exc:
        assert "http:// or https://" in str(exc)
    else:
        raise AssertionError("Expected UrlImportError")


def test_fetch_url_article_rejects_url_user_info() -> None:
    with pytest.raises(imports.UrlImportError, match="user info"):
        imports.fetch_url_article("https://user:pass@example.com/article")


def test_fetch_url_article_rejects_blocked_hosts() -> None:
    with pytest.raises(imports.UrlImportError, match="host is not allowed"):
        imports.fetch_url_article("https://localhost/article")
    with pytest.raises(imports.UrlImportError, match="host is not allowed"):
        imports.fetch_url_article("http://127.0.0.1/article")


def test_fetch_url_article_rejects_private_redirect_targets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(
                302,
                headers={"location": "http://10.0.0.1/private"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<p>Private target.</p>",
            request=request,
        )

    with pytest.raises(imports.UrlImportError, match="host is not allowed"):
        imports.fetch_url_article(
            "https://example.com/article",
            transport=httpx.MockTransport(handler),
        )


def test_fetch_url_article_rejects_unsupported_content_type() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF",
            request=request,
        )
    )

    try:
        imports.fetch_url_article("https://example.com/file.pdf", transport=transport)
    except imports.UrlImportError as exc:
        assert "HTML or plain text" in str(exc)
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected UrlImportError")


def test_fetch_url_article_rejects_http_errors() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            404,
            headers={"content-type": "text/html"},
            content=b"Not found",
            request=request,
        )
    )

    with pytest.raises(imports.UrlImportError, match="HTTP 404"):
        imports.fetch_url_article("https://example.com/missing", transport=transport)


def test_fetch_url_article_rejects_oversized_content() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"abcdef",
            request=request,
        )
    )

    try:
        imports.fetch_url_article("https://example.com/big.txt", max_bytes=5, transport=transport)
    except imports.UrlImportError as exc:
        assert "exceeds" in str(exc)
        assert exc.status_code == 413
    else:
        raise AssertionError("Expected UrlImportError")


def test_fetch_url_article_rejects_streamed_oversized_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            stream=httpx.ByteStream(b"abcdef"),
            request=request,
        )

    with pytest.raises(imports.UrlImportError, match="exceeds") as exc_info:
        imports.fetch_url_article(
            "https://example.com/big-stream.txt",
            max_bytes=5,
            transport=httpx.MockTransport(handler),
        )
    assert exc_info.value.status_code == 413


def test_fetch_url_article_maps_httpx_errors() -> None:
    def too_many_redirects(request: httpx.Request) -> httpx.Response:
        raise httpx.TooManyRedirects("too many", request=request)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    def request_error(request: httpx.Request) -> httpx.Response:
        raise httpx.RequestError("broken", request=request)

    with pytest.raises(imports.UrlImportError, match="redirected too many"):
        imports.fetch_url_article(
            "https://example.com/loop",
            transport=httpx.MockTransport(too_many_redirects),
        )
    with pytest.raises(imports.UrlImportError, match="timed out"):
        imports.fetch_url_article(
            "https://example.com/slow",
            transport=httpx.MockTransport(timeout),
        )
    with pytest.raises(imports.UrlImportError, match="request failed"):
        imports.fetch_url_article(
            "https://example.com/broken",
            transport=httpx.MockTransport(request_error),
        )


def test_fetch_url_article_rejects_empty_and_unreadable_content() -> None:
    empty_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"   ",
            request=request,
        )
    )
    hidden_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body><p hidden>Hidden only.</p></body></html>",
            request=request,
        )
    )

    with pytest.raises(imports.UrlImportError, match="empty content"):
        imports.fetch_url_article("https://example.com/empty", transport=empty_transport)
    with pytest.raises(imports.UrlImportError, match="no readable text"):
        imports.fetch_url_article("https://example.com/hidden", transport=hidden_transport)


def test_extract_html_text_falls_back_to_body_text() -> None:
    title, text = imports._extract_html_text(
        "<html><head><title>Fallback</title></head><body>Loose body text.</body></html>"
    )

    assert title == "Fallback"
    assert text == "Loose body text."


def test_small_url_import_helpers_cover_format_and_parse_edges() -> None:
    assert imports._response_charset("text/html") == ""
    assert imports._parse_content_length("not-a-number") is None
    assert imports._format_byte_limit(1024 * 1024) == "1 MB"
    assert imports._format_byte_limit(1024) == "1 KB"
    assert imports._format_byte_limit(7) == "7 bytes"


def test_import_url_content_imports_extracted_text(monkeypatch) -> None:
    monkeypatch.setattr(
        imports,
        "fetch_url_article",
        lambda url: imports.FetchedUrlArticle(
            title="Remote Title",
            text="Remote text. It has two sentences.",
        ),
    )
    monkeypatch.setattr(
        imports,
        "import_text",
        lambda db, raw, title, author: SimpleNamespace(book_id=17),
    )

    outcome = imports.import_url_content(
        object(),
        "https://example.com/post",
        form_title="",
        author=" A ",
    )

    assert outcome.book_id == 17
    assert not outcome.is_error


def test_import_url_content_maps_fetch_errors() -> None:
    outcome = imports.import_url_content(
        object(),
        "ftp://example.com/post",
        form_title="",
        author="",
    )

    assert outcome.error
    assert outcome.status_code == 400


def test_import_epub_file_maps_import_errors(monkeypatch, tmp_path: Path) -> None:
    epub_path = tmp_path / "bad.epub"
    epub_path.write_bytes(b"not really epub")

    monkeypatch.setattr(imports, "calculate_epub_file_hash", lambda path: "hash")

    def raise_value_error(*args, **kwargs):
        raise ValueError("bad epub")

    monkeypatch.setattr(imports, "import_epub", raise_value_error)

    outcome = imports.import_epub_file(
        object(),
        epub_path,
        form_title="",
        author="",
    )

    assert outcome.error == "bad epub"
    assert outcome.status_code == 400


def test_import_markdown_file_returns_book_id(monkeypatch, tmp_path: Path) -> None:
    md_path = tmp_path / "note.md"
    md_path.write_text("# Heading\n\nReadable sentence.", encoding="utf-8")

    monkeypatch.setattr(
        imports,
        "import_markdown_bytes",
        lambda *args, **kwargs: SimpleNamespace(book_id=41),
    )

    outcome = imports.import_markdown_file(
        object(),
        md_path,
        form_title="Markdown Title",
        author=" Writer ",
    )

    assert outcome.book_id == 41
    assert not outcome.is_error


def test_import_markdown_file_uses_fallback_title_before_temp_stem(
    monkeypatch,
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "tmp110d0ebd.md"
    md_path.write_text("# Heading\n\nReadable sentence.", encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_import_markdown_bytes(*args, **kwargs):
        captured["title"] = kwargs["title"]
        return SimpleNamespace(book_id=42)

    monkeypatch.setattr(imports, "import_markdown_bytes", fake_import_markdown_bytes)

    outcome = imports.import_markdown_file(
        object(),
        md_path,
        form_title="",
        author="",
        fallback_title="Logic Rules Summary",
    )

    assert outcome.book_id == 42
    assert captured["title"] == "Logic Rules Summary"


def test_import_markdown_file_maps_duplicate_to_existing_book(
    monkeypatch,
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "dup.md"
    md_path.write_text("# Heading\n\nReadable sentence.", encoding="utf-8")

    def raise_duplicate(*args, **kwargs):
        raise imports.DuplicateBookError()

    monkeypatch.setattr(imports, "import_markdown_bytes", raise_duplicate)
    monkeypatch.setattr(imports, "_lookup_book_id_by_hash", lambda db, file_hash: 88)

    outcome = imports.import_markdown_file(
        object(),
        md_path,
        form_title="",
        author="",
    )

    assert outcome.duplicate_book_id == 88
    assert outcome.status_code == 409


def test_import_markdown_file_maps_import_errors(monkeypatch, tmp_path: Path) -> None:
    md_path = tmp_path / "bad.md"
    md_path.write_text("```python\nprint('x')\n```", encoding="utf-8")

    def raise_value_error(*args, **kwargs):
        raise ValueError("bad markdown")

    monkeypatch.setattr(imports, "import_markdown_bytes", raise_value_error)

    outcome = imports.import_markdown_file(
        object(),
        md_path,
        form_title="",
        author="",
    )

    assert outcome.error == "bad markdown"
    assert outcome.status_code == 400


def test_import_pdf_file_maps_duplicate_to_existing_book(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "dup.pdf"
    pdf_path.write_bytes(b"%PDF")

    monkeypatch.setattr(imports, "calculate_pdf_file_hash", lambda path: "hash")

    def raise_duplicate(*args, **kwargs):
        raise imports.EpubDuplicateBookError()

    monkeypatch.setattr(imports, "import_pdf", raise_duplicate)
    monkeypatch.setattr(imports, "_lookup_book_id_by_hash", lambda db, file_hash: 55)

    outcome = imports.import_pdf_file(
        object(),
        pdf_path,
        form_title="",
        author="",
    )

    assert outcome.duplicate_book_id == 55
    assert outcome.status_code == 409


def test_import_pdf_file_maps_import_errors(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_bytes(b"not really pdf")

    monkeypatch.setattr(imports, "calculate_pdf_file_hash", lambda path: "hash")

    def raise_value_error(*args, **kwargs):
        raise ValueError("bad pdf")

    monkeypatch.setattr(imports, "import_pdf", raise_value_error)

    outcome = imports.import_pdf_file(
        object(),
        pdf_path,
        form_title="",
        author="",
    )

    assert outcome.error == "bad pdf"
    assert outcome.status_code == 400
