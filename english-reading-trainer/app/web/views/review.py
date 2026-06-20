"""Review queue table rendering helpers."""

from __future__ import annotations

from typing import Any

from app.db_models import CardType, ReviewOutcome
from app.web.views.components import _hover_popover, _pronunciation_cell, _source_link
from app.web.views.layout import _date, _escape

_REVIEW_SCRIPT = """\
<script>
(function(){
  document.addEventListener('submit', function(e){
    var form = e.target;
    if (!form.classList.contains('answer-form')) return;
    e.preventDefault();
    var data = new URLSearchParams(new FormData(form));
    var btn = e.submitter;
    if (btn && btn.name) data.set(btn.name, btn.value);
    fetch(form.action, {method:'POST', body:data, redirect:'follow'})
      .then(function(r){
        if (!r.ok && !r.redirected) return;
        var row = form.closest('tr');
        if (!row) return;
        var tbody = row.parentNode;
        row.remove();
        if (tbody && !tbody.querySelector('tr')) {
          var table = tbody.closest('table');
          if (table) {
            var p = document.createElement('p');
            p.className = 'empty';
            p.textContent = 'No cards due for review.';
            table.replaceWith(p);
          }
        }
      });
  });
})();
</script>
"""


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
    {_REVIEW_SCRIPT}"""

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
    takeaway = (getattr(item, "takeaway", "") or "").strip()
    ai_meaning = (getattr(item, "ai_meaning", "") or "").strip()
    reveal_parts = []
    if item.card_type == CardType.SENTENCE:
        if answer:
            reveal_parts.append(
                f'<p class="hover-popover-text"><strong>Translation:</strong> {_escape(answer)}</p>'
            )
        if takeaway:
            reveal_parts.append(
                f'<p class="hover-popover-text"><strong>Takeaway:</strong> {_escape(takeaway)}</p>'
            )
    else:
        note_status = str(getattr(item, "note_status", "") or "")
        note_correction = str(getattr(item, "note_correction", "") or "")
        is_misread = note_status in {"incorrect", "partly_correct"}
        if answer:
            label = "Your note (incorrect)" if is_misread else "Takeaway"
            reveal_parts.append(
                f'<p class="hover-popover-text"><strong>{label}:</strong> {_escape(answer)}</p>'
            )
        if is_misread and note_correction:
            reveal_parts.append(
                f'<p class="hover-popover-text"><strong>Correct meaning:</strong> {_escape(note_correction)}</p>'
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
