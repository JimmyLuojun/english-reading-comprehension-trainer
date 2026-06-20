"""Tests for page layout helpers."""

from __future__ import annotations

from app.web.views.layout import (
    _active,
    _date,
    _escape,
    _html_page,
    _metric,
    _page_header,
    _resume_nav_script,
    _scroll_memory_script,
)


def test_html_page_escapes_title_and_marks_active_nav() -> None:
    response = _html_page("<Title>", "<p>Body</p>", active="books", page_class="reader")

    body = response.body.decode()
    assert response.status_code == 200
    assert "&lt;Title&gt; - English Reading Trainer" in body
    assert '<body class="reader">' in body
    assert '<a id="nav-books" class="active" href="/books">Books</a>' in body
    assert '<a class="" href="/books">Library</a>' in body
    assert 'getElementById("nav-books")' in body
    assert "reader:last-book-id" in body


def test_html_page_includes_pre_paint_theme_bootstrap_and_toggle() -> None:
    response = _html_page("Title", "<p>Body</p>", active="dashboard")

    body = response.body.decode()
    bootstrap_index = body.index("localStorage.getItem('theme')")
    style_index = body.index("<style>")
    assert bootstrap_index < style_index
    assert "document.documentElement.dataset.theme=t" in body
    assert 'id="theme-toggle"' in body
    assert ">护眼</button>" in body
    assert "localStorage.setItem(&#x27;theme&#x27;,&#x27;sepia&#x27;)" in body
    assert "localStorage.removeItem(&#x27;theme&#x27;)" in body


def test_html_page_includes_encoded_inline_svg_favicon() -> None:
    response = _html_page("Title", "<p>Body</p>", active="dashboard")

    body = response.body.decode()
    head = body[: body.index("</head>")]
    favicon_start = head.index('<link rel="icon" href="')
    favicon_end = head.index('">', favicon_start)
    href = head[favicon_start + len('<link rel="icon" href="') : favicon_end]
    assert "data:image/svg+xml," in href
    assert "%230f8f83" in href
    assert "%23ffffff" in href
    assert "%E8%AF%BB" in href
    assert "#" not in href
    assert "<" not in href
    assert ">" not in href
    assert '"' not in href


def test_page_header_renders_consistent_toolbar_variants() -> None:
    assert _page_header("<Title>") == (
        '<section class="toolbar"><div><h1>&lt;Title&gt;</h1></div></section>'
    )
    assert _page_header("Title", "Muted <copy>") == (
        '<section class="toolbar"><div><h1>Title</h1>'
        '<p class="muted">Muted &lt;copy&gt;</p></div></section>'
    )
    assert _page_header("Title", actions='<a class="button" href="/x">Action</a>') == (
        '<section class="toolbar"><div><h1>Title</h1></div>'
        '<a class="button" href="/x">Action</a></section>'
    )


def test_resume_nav_script_rewrites_books_nav() -> None:
    script = _resume_nav_script()

    assert 'getElementById("nav-books")' in script
    assert "reader:last-book-id" in script
    assert "reader:progress:book:${bookId}" in script
    assert "?chapter=${chapter}&restore=1" in script
    assert "link.href = href" in script
    assert "Continue reading" not in script


def test_scroll_memory_script_persists_and_restores_per_url() -> None:
    script = _scroll_memory_script()

    # Saves position keyed by path+query, on exit signals only.
    assert 'const key = "scroll:" + location.pathname + location.search;' in script
    assert "window.sessionStorage.setItem(key, String(window.scrollY))" in script
    assert 'window.addEventListener("pagehide", save)' in script
    assert 'document.addEventListener("visibilitychange"' in script
    # Restores on load unless a hash anchor targets a specific element.
    assert "if (location.hash) return;" in script
    assert "window.requestAnimationFrame(() => window.scrollTo(0, y))" in script
    # The reader owns its own progress restore, so skip it here.
    assert 'if (location.pathname.indexOf("/read/") === 0) return;' in script


def test_html_page_includes_scroll_memory_script() -> None:
    response = _html_page("Title", "<p>Body</p>", active="review")

    body = response.body.decode()
    assert 'const key = "scroll:" + location.pathname + location.search;' in body


def test_formatting_helpers() -> None:
    assert _metric("<Cards>", 3) == '<div class="metric"><span>&lt;Cards&gt;</span><strong>3</strong></div>'
    assert _metric("Books", 8, href="/books") == (
        '<a class="metric metric-link" href="/books" aria-label="Books: 8">'
        "<span>Books</span><strong>8</strong></a>"
    )
    assert _date("2026-06-17T12:34:00+00:00") == "2026-06-17"
    assert _date("bad-value") == "bad-value"
    assert _active("cards", "cards") == "active"
    assert _active("cards", "books") == ""
    assert _escape('"quoted"') == "&quot;quoted&quot;"
