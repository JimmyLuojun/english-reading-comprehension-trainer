"""Cards page table rendering helpers."""

from __future__ import annotations

from typing import Any

from app.web.views.components import (
    _hover_popover,
    _pronunciation_cell,
    _source_link,
)
from app.web.views.layout import _date, _escape

def _sentence_cards_table(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return '<p class="empty">No sentence cards.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{card['id']}</td>"
        f"<td>{_escape(card['mastery_state'])}</td>"
        f"<td>{_escape(_date(card['due_at']))}</td>"
        f"<td>{_escape((card.get('user_translation') or '')[:80])}</td>"
        f"<td>{_escape(card['sentence_text'][:100])}</td>"
        "</tr>"
        for card in cards
    )
    return f"<table><thead><tr><th>ID</th><th>State</th><th>Due</th><th>Translation</th><th>Text</th></tr></thead><tbody>{rows}</tbody></table>"

def _word_cards_table(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return '<p class="empty">No word cards.</p>'
    rows = "\n".join(
        f'<tr id="card-{card["id"]}" class="card-anchor">'
        f"<td>{card['id']}</td>"
        f"<td>{_pronunciation_cell(card['surface_form'], href=card.get('source_href'))}</td>"
        f"<td>{_escape(card['lexical_type'])}</td>"
        f"<td>{_escape(card['mastery_state'])}</td>"
        f"<td>{card['occurrence_count']}</td>"
        f"<td>{_note_edit_cell(card)}</td>"
        f"<td>{_ai_meaning_cell(card)}</td>"
        f"<td>{_source_link(card.get('first_book_title') or '—', card.get('source_href'))}</td>"
        "</tr>"
        for card in cards
    )
    return (
        "<table><thead><tr>"
        "<th>ID</th><th>Word/Phrase</th><th>Type</th><th>State</th><th>Occ.</th>"
        "<th>Notes</th><th>AI Meaning</th><th>Source</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )

def _cards_return_script() -> str:
    return """
        <script>
          (() => {
            const url = window.sessionStorage.getItem("glossary_return_url");
            if (!url) return;
            window.sessionStorage.removeItem("glossary_return_url");
            const link = document.createElement("a");
            link.href = url;
            link.className = "button glossary-return";
            link.textContent = "Back to reading";
            const toolbar = document.querySelector("section.toolbar");
            if (toolbar) toolbar.append(link);
          })();
        </script>
    """

def _note_edit_cell(card: dict[str, Any]) -> str:
    card_id = card["id"]
    user_note = str(card.get("user_note") or "").strip()
    current_meaning = str(card.get("current_meaning") or "").strip()
    ai_meaning = str(card.get("ai_meaning") or "").strip()
    value = (
        user_note
        if user_note and user_note not in {current_meaning, ai_meaning}
        else ""
    )
    display = _escape(value) if value else "—"
    escaped_value = _escape(value)
    escaped_meaning = _escape(current_meaning)
    return (
        f'<span class="note-text" data-card-id="{card_id}">{display}</span>'
        f'<button class="note-edit-btn" data-card-id="{card_id}" aria-label="edit notes">✎</button>'
        f'<input class="note-input" data-card-id="{card_id}" '
        f'data-current-meaning="{escaped_meaning}" value="{escaped_value}" style="display:none">'
    )

def _ai_meaning_cell(card: dict[str, Any]) -> str:
    ai_meaning = card.get("ai_meaning") or ""
    if not ai_meaning:
        return "—"
    return _hover_popover(
        "▶ Reveal",
        f'<p class="hover-popover-text">{_escape(ai_meaning)}</p>',
        align="right",
    )
