"""Page layout, styling, and shared formatting helpers."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from fastapi.responses import HTMLResponse

from app.web.views.cards_script import _def_edit_script
from app.web.views.styles import _css

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
  </nav>
  <main>{body}</main>
  <script>{_def_edit_script()}</script>
</body>
</html>""",
        status_code=status_code,
    )


def _metric(label: str, value: int) -> str:
    return f'<div class="metric"><span>{_escape(label)}</span><strong>{value}</strong></div>'

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
