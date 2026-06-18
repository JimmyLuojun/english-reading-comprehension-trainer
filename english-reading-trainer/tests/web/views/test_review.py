"""Tests for review queue rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.db_models import CardType, MasteryState
from app.web.views.review import _due_table, _review_answer_cell, _review_prompt_cell


@dataclass(frozen=True)
class _Item:
    card_type: CardType
    card_id: int
    mastery_state: MasteryState
    due_at: datetime
    prompt: str
    answer: str = ""
    ai_meaning: str = ""
    source_href: str = ""


def test_due_table_renders_empty_state_and_word_prompt_audio() -> None:
    assert _due_table([], "/review") == '<p class="empty">No cards due for review.</p>'
    item = _Item(
        card_type=CardType.WORD,
        card_id=1,
        mastery_state=MasteryState.NEW,
        due_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        prompt="cat",
        source_href="/read/1",
    )

    html = _due_table([item], "/review")

    assert "<th>Review item</th>" in html
    assert "<th>Prompt</th>" not in html
    assert 'data-speak-text="cat"' in _review_prompt_cell(item)
    assert "/review/word/1" in html


def test_review_prompt_cell_shows_complete_sentence() -> None:
    prompt = (
        "The network timestamps transactions by hashing them into an ongoing chain "
        "of hash-based proof-of-work, forming a record that cannot be changed without "
        "redoing the proof-of-work."
    )
    item = _Item(
        card_type=CardType.SENTENCE,
        card_id=7,
        mastery_state=MasteryState.NEW,
        due_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        prompt=prompt,
        source_href="/read/1?chapter=2&sentence_id=7&panel=analysis#sentence-7",
    )

    html = _review_prompt_cell(item)

    assert 'href="/read/1?chapter=2&amp;sentence_id=7&amp;panel=analysis#sentence-7"' in html
    assert "redoing the proof-of-work." in html


def test_review_answer_cell_combines_reveal_and_outcomes() -> None:
    item = _Item(
        card_type=CardType.WORD,
        card_id=1,
        mastery_state=MasteryState.NEW,
        due_at=datetime.now(timezone.utc),
        prompt="cat",
        answer="my note",
        ai_meaning="AI meaning",
    )

    html = _review_answer_cell(item, "/review")

    assert "Your note:" in html
    assert "AI meaning:" in html
    assert 'value="pass"' in html
    assert 'name="return_to" value="/review"' in html
