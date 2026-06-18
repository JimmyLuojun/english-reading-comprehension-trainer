"""Page layout, styling, and shared formatting helpers."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from fastapi.responses import HTMLResponse

from app.web.views.cards_script import _def_edit_script
from app.web.views.styles import _css


_THEME_BOOTSTRAP_SCRIPT = (
    "try{var t=localStorage.getItem('theme');"
    "if(t)document.documentElement.dataset.theme=t;}catch(e){}"
)
_THEME_TOGGLE_SCRIPT = (
    "(function(){var d=document.documentElement,s=d.dataset.theme==='sepia';"
    "if(s){delete d.dataset.theme;localStorage.removeItem('theme');}"
    "else{d.dataset.theme='sepia';localStorage.setItem('theme','sepia');}})()"
)
_FAVICON_HREF = (
    "data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 "
    "viewBox=%270 0 32 32%27%3E%3Crect width=%2732%27 height=%2732%27 "
    "rx=%276%27 fill=%27%230f8f83%27/%3E%3Ctext x=%2716%27 y=%2722%27 "
    "font-family=%27Georgia,serif%27 font-size=%2718%27 font-weight=%27600%27 "
    "fill=%27%23ffffff%27 text-anchor=%27middle%27%3E%E8%AF%BB%3C/text%3E%3C/svg%3E"
)


def _html_page(
    title: str,
    body: str,
    *,
    active: str,
    page_class: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    body_class = f' class="{_escape(page_class)}"' if page_class else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} - English Reading Trainer</title>
  <link rel="icon" href="{_FAVICON_HREF}">
  <script>{_THEME_BOOTSTRAP_SCRIPT}</script>
  <style>{_css()}</style>
</head>
<body{body_class}>
  <nav>
    <a class="{_active(active, "dashboard")}" href="/">Dashboard</a>
    <a class="{_active(active, "books")}" href="/books">Books</a>
    <a class="{_active(active, "import")}" href="/import">Import</a>
    <a class="{_active(active, "cards")}" href="/cards">Cards</a>
    <a class="{_active(active, "review")}" href="/review">Review</a>
    <a class="{_active(active, "profile")}" href="/profile">Profile</a>
    <button type="button" id="theme-toggle" onclick="{_escape(_THEME_TOGGLE_SCRIPT)}">护眼</button>
  </nav>
  <main>{body}</main>
  <script>{_def_edit_script()}</script>
</body>
</html>""",
        status_code=status_code,
    )


def _page_header(title: str, subtitle: str = "", actions: str = "") -> str:
    sub = f'<p class="muted">{_escape(subtitle)}</p>' if subtitle else ""
    return (
        '<section class="toolbar"><div>'
        f"<h1>{_escape(title)}</h1>{sub}</div>"
        f"{actions}</section>"
    )


def _metric(label: str, value: int, href: str | None = None) -> str:
    content = f"<span>{_escape(label)}</span><strong>{value}</strong>"
    if href is not None:
        return (
            f'<a class="metric metric-link" href="{_escape(href)}" '
            f'aria-label="{_escape(label)}: {value}">{content}</a>'
        )
    return f'<div class="metric">{content}</div>'

def _continue_reading_script(button_class: str = "button primary") -> str:
    return """
    <script>
      (() => {
        let bookId = "";
        try {
          bookId = window.localStorage.getItem("reader:last-book-id") || "";
        } catch (error) {
          bookId = "";
        }
        if (!bookId) return;
        const toolbar = document.querySelector("section.toolbar");
        if (!toolbar) return;
        let href = `/read/${encodeURIComponent(bookId)}`;
        try {
          const progress = JSON.parse(
            window.localStorage.getItem(`reader:progress:book:${bookId}`) || "null",
          );
          const chapter = Number.parseInt(progress?.chapter_idx, 10);
          if (chapter) href = `${href}?chapter=${chapter}&restore=1`;
        } catch (error) {
          href = `/read/${encodeURIComponent(bookId)}`;
        }
        const link = document.createElement("a");
        link.className = "__BUTTON_CLASS__";
        link.href = href;
        link.textContent = "Continue reading";
        toolbar.append(link);
      })();
    </script>
    """.replace("__BUTTON_CLASS__", button_class)

def _date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return value[:10]

def _active(current: str, expected: str) -> str:
    return "active" if current == expected else ""

def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)
