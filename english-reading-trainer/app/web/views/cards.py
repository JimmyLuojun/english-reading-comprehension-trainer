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
        f"<td>{_sentence_translation_cell(card)}</td>"
        f"<td>{_sentence_takeaway_cell(card)}</td>"
        f"<td>{_sentence_source_link(card)}</td>"
        "</tr>"
        for card in cards
    )
    return (
        "<table><thead><tr><th>ID</th><th>State</th><th>Due</th>"
        "<th>Translation</th><th>Takeaway</th><th>Text</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )

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
        f"<td>{_word_card_actions_cell(card)}</td>"
        "</tr>"
        for card in cards
    )
    return (
        "<table><thead><tr>"
        "<th>ID</th><th>Word/Phrase</th><th>Type</th><th>State</th><th>Occ.</th>"
        "<th>Notes</th><th>AI Meaning</th><th>Source</th><th>Actions</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _sentence_translation_cell(card: dict[str, Any]) -> str:
    return _sentence_edit_cell(
        card,
        field="translation",
        value_key="user_translation",
        placeholder="Edit your Chinese understanding",
        aria_label="edit translation",
    )


def _sentence_takeaway_cell(card: dict[str, Any]) -> str:
    return _sentence_edit_cell(
        card,
        field="takeaway",
        value_key="user_note",
        placeholder="Edit your takeaway",
        aria_label="edit takeaway",
    )


def _sentence_edit_cell(
    card: dict[str, Any],
    *,
    field: str,
    value_key: str,
    placeholder: str,
    aria_label: str,
) -> str:
    sentence_id = card["sentence_id"]
    value = str(card.get(value_key) or "").strip()
    escaped_value = _escape(value)
    display = escaped_value if value else "—"
    return (
        f'<div class="sentence-field-cell sentence-field-{field}" '
        f'data-sentence-id="{sentence_id}" data-sentence-field="{field}">'
        f'<span class="sentence-field-text" data-sentence-id="{sentence_id}" '
        f'data-sentence-field="{field}">{display}</span>'
        '<button type="button" class="note-edit-btn sentence-field-edit-btn" '
        f'data-sentence-id="{sentence_id}" '
        f'data-sentence-field="{field}" aria-label="{aria_label}">✎</button>'
        f'<div class="sentence-field-edit" data-sentence-id="{sentence_id}" '
        f'data-sentence-field="{field}" hidden>'
        '<textarea class="sentence-field-input" rows="3" '
        f'data-sentence-id="{sentence_id}" data-sentence-field="{field}" '
        f'placeholder="{_escape(placeholder)}">'
        f"{escaped_value}</textarea>"
        '<div class="sentence-field-actions">'
        '<button type="button" class="small sentence-field-save-btn" '
        f'data-sentence-id="{sentence_id}" data-sentence-field="{field}">Save</button>'
        '<button type="button" class="small sentence-field-cancel-btn" '
        f'data-sentence-id="{sentence_id}" data-sentence-field="{field}">Cancel</button>'
        "</div>"
        f'<p class="toolbar-status sentence-field-status" data-sentence-id="{sentence_id}" '
        f'data-sentence-field="{field}" aria-live="polite"></p>'
        "</div>"
        "</div>"
    )


def _sentence_source_link(card: dict[str, Any]) -> str:
    text = _escape(str(card.get("sentence_text") or ""))
    href = str(card.get("source_href") or "").strip()
    if not href:
        return text
    return f'<a class="source-link" href="{_escape(href)}">{text}</a>'


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

def _word_card_actions_cell(card: dict[str, Any]) -> str:
    card_id = card["id"]
    label = _escape(card.get("surface_form") or f"card {card_id}")
    return (
        '<button type="button" class="small danger word-card-delete" '
        f'data-delete-word-card="{card_id}" data-delete-label="{label}">'
        "Delete"
        "</button>"
        f' <a class="button small" href="/cards/word/{card_id}/sources">Sources</a>'
    )


def _word_card_sources_page(
    card: dict[str, Any],
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    return (
        '<section class="toolbar">'
        "<div>"
        f"<h1>Sources: {_escape(card['surface_form'])}</h1>"
        f'<p class="muted">{_escape(card["lexical_type"])} · '
        f'{len(sources)} recorded source{"s" if len(sources) != 1 else ""}</p>'
        "</div>"
        '<a class="button" href="/cards">Back to Cards</a>'
        "</section>"
        '<section class="band">'
        "<h2>Recorded Sources</h2>"
        f"{_word_card_sources_table(sources)}"
        "<h2>Find Occurrences</h2>"
        f"{_word_card_candidates_table(card['id'], candidates)}"
        "</section>"
    )


def _word_card_sources_table(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return '<p class="empty">No recorded sources.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{_source_link(source.get('book_title') or '—', source.get('source_href'))}</td>"
        f"<td>{source['chapter_idx']}</td>"
        f"<td>{_escape(source['sentence_text'])}</td>"
        f"<td>{'Primary' if source['is_primary'] else _set_primary_source_form(source)}</td>"
        "</tr>"
        for source in sources
    )
    return (
        "<table><thead><tr>"
        "<th>Book</th><th>Chapter</th><th>Sentence</th><th>Primary</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _word_card_candidates_table(
    card_id: int,
    candidates: list[dict[str, Any]],
) -> str:
    if not candidates:
        return '<p class="empty">No matching sentences found.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{_source_link(candidate.get('book_title') or '—', candidate.get('source_href'))}</td>"
        f"<td>{candidate['chapter_idx']}</td>"
        f"<td>{_escape(candidate['sentence_text'])}</td>"
        f"<td>{_candidate_action(card_id, candidate)}</td>"
        "</tr>"
        for candidate in candidates
    )
    return (
        "<table><thead><tr>"
        "<th>Book</th><th>Chapter</th><th>Sentence</th><th>Action</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _set_primary_source_form(source: dict[str, Any]) -> str:
    return (
        f'<form method="post" action="/cards/word/{source["card_id"]}/sources/'
        f'{source["id"]}/primary" class="inline-form">'
        '<button type="submit" class="small">Set primary</button>'
        "</form>"
    )


def _candidate_action(card_id: int, candidate: dict[str, Any]) -> str:
    if candidate["is_primary"]:
        return "Primary"
    if candidate["is_recorded"]:
        return "Recorded"
    return (
        f'<form method="post" action="/cards/word/{card_id}/sources" class="inline-form">'
        f'<input type="hidden" name="sentence_id" value="{candidate["sentence_id"]}">'
        '<button type="submit" class="small">Add source</button>'
        "</form>"
    )
