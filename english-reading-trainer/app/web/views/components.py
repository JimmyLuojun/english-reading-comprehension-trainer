"""Shared small HTML components."""

from __future__ import annotations

from typing import Any

from app.web.views.layout import _escape

def _hover_popover(label: str, body_html: str, *, align: str = "left") -> str:
    align_class = " hover-popover-right" if align == "right" else ""
    return (
        f'<span class="hover-popover{align_class}">'
        f'<span class="hover-popover-trigger" tabindex="0">{_escape(label)}</span>'
        f'<span class="hover-popover-panel" role="tooltip">{body_html}</span>'
        "</span>"
    )

def _source_link(label: Any, href: Any, *, class_name: str = "source-link") -> str:
    text = str(label or "—")
    safe_href = _safe_source_href(href)
    if not safe_href or text == "—":
        return _escape(text)
    return f'<a class="{_escape(class_name)}" href="{_escape(safe_href)}">{_escape(text)}</a>'

def _safe_source_href(href: Any) -> str:
    value = str(href or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return ""

def _pronunciation_cell(
    display_text: Any,
    *,
    speak_text: Any | None = None,
    href: Any = "",
) -> str:
    text = str(display_text)
    return (
        '<span class="speak-inline">'
        f"{_speak_button(text if speak_text is None else speak_text)}"
        f'{_source_link(text, href, class_name="speak-text source-link")}'
        "</span>"
    )

def _speak_button(text: Any) -> str:
    speak_text = str(text).strip()
    if not speak_text:
        return ""
    return (
        '<button class="speak-button" type="button" '
        f'data-speak-text="{_escape(speak_text)}" '
        'title="Play pronunciation" aria-label="Play pronunciation">▶</button>'
    )
