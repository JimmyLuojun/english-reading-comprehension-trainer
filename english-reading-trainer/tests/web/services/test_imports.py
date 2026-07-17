"""Tests for web import workflow services."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.web.services import imports


def test_import_text_bytes_returns_book_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_import_text(db, raw, title, author):
        captured["title"] = title
        captured["author"] = author
        return SimpleNamespace(book_id=7)

    monkeypatch.setattr(
        imports,
        "import_text",
        fake_import_text,
    )
    monkeypatch.setattr(
        imports,
        "_update_book_import_metadata",
        lambda db, book_id, **metadata: captured.update(
            {"book_id": book_id, **metadata}
        ),
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
    assert captured == {
        "title": "The_escappe_plan_lines",
        "author": "A",
        "book_id": 7,
        "content_kind": "unclassified",
        "import_method": "file",
        "source_uri": "",
    }


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
    visited_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited_hosts.append(request.url.host)
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
    assert visited_hosts == ["example.com"]


def test_fetch_url_article_rejects_hostname_resolving_to_private_address() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"This handler must not run.",
            request=request,
        )
    )

    with pytest.raises(imports.UrlImportError, match="host is not allowed"):
        imports.fetch_url_article(
            "https://example.com/private-dns",
            transport=transport,
            resolve_host=lambda host: ("127.0.0.1",),
        )


def test_fetch_url_article_follows_only_validated_redirects() -> None:
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "/article"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"Read me.",
            request=request,
        )

    article = imports.fetch_url_article(
        "https://example.com/start",
        transport=httpx.MockTransport(handler),
        resolve_host=lambda host: ("93.184.216.34",),
    )

    assert article.text == "Read me."
    assert visited == ["https://example.com/start", "https://example.com/article"]


def test_fetch_url_article_enforces_redirect_budget() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"location": "/again"},
            request=request,
        )
    )

    with pytest.raises(imports.UrlImportError, match="redirected too many"):
        imports.fetch_url_article(
            "https://example.com/loop",
            max_redirects=1,
            transport=transport,
            resolve_host=lambda host: ("93.184.216.34",),
        )


def test_fetch_url_article_rejects_redirect_without_location() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, request=request)
    )

    with pytest.raises(imports.UrlImportError, match="missing a location"):
        imports.fetch_url_article(
            "https://example.com/start",
            transport=transport,
            resolve_host=lambda host: ("93.184.216.34",),
        )


def test_resolve_public_host_rejects_dns_failures_and_empty_results(monkeypatch) -> None:
    def dns_failure(*args, **kwargs):
        raise imports.socket.gaierror("no dns")

    monkeypatch.setattr(imports.socket, "getaddrinfo", dns_failure)
    with pytest.raises(imports.UrlImportError, match="could not be resolved"):
        imports._resolve_public_host("missing.example")

    monkeypatch.setattr(imports.socket, "getaddrinfo", lambda *args, **kwargs: [])
    with pytest.raises(imports.UrlImportError, match="could not be resolved"):
        imports._resolve_public_host("empty.example")


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
    metadata: dict[str, object] = {}
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
    monkeypatch.setattr(
        imports,
        "_update_book_import_metadata",
        lambda db, book_id, **values: metadata.update(
            {"book_id": book_id, **values}
        ),
    )

    outcome = imports.import_url_content(
        object(),
        "https://example.com/post",
        form_title="",
        author=" A ",
    )

    assert outcome.book_id == 17
    assert not outcome.is_error
    assert metadata == {
        "book_id": 17,
        "content_kind": "article",
        "import_method": "url",
        "source_uri": "https://example.com/post",
    }


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
    monkeypatch.setattr(imports, "_update_book_import_metadata", lambda *args, **kwargs: None)

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
    monkeypatch.setattr(imports, "_update_book_import_metadata", lambda *args, **kwargs: None)

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


def test_import_content_kind_auto_rules_and_validation() -> None:
    assert imports._resolve_import_content_kind(
        "auto", import_method="url", source_format="txt"
    ) == "article"
    assert imports._resolve_import_content_kind(
        "auto", import_method="paste", source_format="txt"
    ) == "excerpt"
    assert imports._resolve_import_content_kind(
        "auto", import_method="file", source_format="epub"
    ) == "book"
    assert imports._resolve_import_content_kind(
        "auto", import_method="file", source_format="pdf"
    ) == "unclassified"
    assert imports._resolve_import_content_kind(
        "article", import_method="file", source_format="pdf"
    ) == "article"
    with pytest.raises(ValueError, match="Auto, Book, Article, or Excerpt"):
        imports._resolve_import_content_kind(
            "paragraph", import_method="paste", source_format="txt"
        )


def test_strip_trailing_interface_metadata_only_removes_final_notice() -> None:
    raw = (
        "Readable paragraph.\n\n"
        "• Model changed to gpt-5.6-sol xhigh\n"
    ).encode()

    assert imports._strip_trailing_interface_metadata(raw) == b"Readable paragraph."
    assert imports._strip_trailing_interface_metadata(
        b"Model changed to a better approach.\nMore prose."
    ) == b"Model changed to a better approach.\nMore prose."
    non_utf8 = b"\xffModel changed to model"
    assert imports._strip_trailing_interface_metadata(non_utf8) == non_utf8


def test_import_text_bytes_rejects_invalid_content_kind_before_import(monkeypatch) -> None:
    monkeypatch.setattr(
        imports,
        "import_text",
        lambda *args, **kwargs: pytest.fail("import_text must not run"),
    )

    outcome = imports.import_text_bytes(
        object(),
        b"Readable sentence.",
        form_title="",
        author="",
        content_kind="paragraph",
    )

    assert outcome.status_code == 400
    assert "Content type" in (outcome.error or "")
