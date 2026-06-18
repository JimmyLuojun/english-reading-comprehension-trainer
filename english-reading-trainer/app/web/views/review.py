"""Review queue table rendering helpers."""

from __future__ import annotations

from typing import Any

from app.db_models import CardType, ReviewOutcome
from app.web.views.components import _hover_popover, _pronunciation_cell, _source_link
from app.web.views.layout import _date, _escape

def _due_table(items: list[Any], return_to: str) -> str:
    if not items:
        return '<p class="empty">No cards due for review.</p>'
    rows = "\n".join(
        "<tr>"
        f"<td>{_escape(item.card_type.value)}</td>"
        f"<td>{item.card_id}</td>"
        f"<td>{_escape(item.mastery_state.value)}</td>"
        f"<td>{_escape(_date(item.due_at.isoformat()))}</td>"
        f"<td>{_review_prompt_cell(item)}</td>"
        f"<td>{_review_answer_cell(item, return_to)}</td>"
        "</tr>"
        for item in items
    )
    return f"""
    <table>
      <thead><tr><th>Type</th><th>ID</th><th>State</th><th>Due</th><th class="review-item-col">Review item</th><th>Answer</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """

def _review_prompt_cell(item: Any) -> str:
    prompt = str(getattr(item, "prompt", "") or "")
    href = getattr(item, "source_href", "")
    if item.card_type == CardType.WORD:
        return _pronunciation_cell(
            prompt,
            speak_text=prompt,
            href=href,
        )
    return _source_link(prompt, href, class_name="source-link review-item-link")

def _review_answer_cell(item: Any, return_to: str) -> str:
    answer = (getattr(item, "answer", "") or "").strip()
    ai_meaning = (getattr(item, "ai_meaning", "") or "").strip()
    reveal_parts = []
    if answer:
        reveal_parts.append(
            f'<p class="hover-popover-text"><strong>Your note:</strong> {_escape(answer)}</p>'
        )
    if ai_meaning:
        reveal_parts.append(
            f'<p class="hover-popover-text"><strong>AI meaning:</strong> {_escape(ai_meaning)}</p>'
        )
    reveal = _hover_popover("▶ Reveal", "".join(reveal_parts), align="right") if reveal_parts else ""
    options = "".join(
        f'<button type="submit" name="outcome" value="{outcome.value}">{outcome.value}</button>'
        for outcome in (ReviewOutcome.PASS, ReviewOutcome.PARTIAL, ReviewOutcome.FAIL)
    )
    form = (
        f'<form method="post" action="/review/{item.card_type.value}/{item.card_id}" class="answer-form">'
        f'<input type="hidden" name="return_to" value="{_escape(return_to)}">'
        f"{options}</form>"
    )
    return reveal + form
