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
    takeaway: str = ""
    ai_meaning: str = ""
    source_href: str = ""
    note_status: str = ""
    note_correction: str = ""


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

    assert '<th class="review-item-col">Review item</th>' in html
    assert "<th>Prompt</th>" not in html
    assert 'data-speak-text="cat"' in _review_prompt_cell(item)
    assert "/review/word/1" in html
    assert "answer-form" in html
    assert "<script>" in html
    # POST must be urlencoded: _read_form parses with parse_qs, which cannot
    # read multipart/form-data (FormData), so the inline fetch uses URLSearchParams.
    assert "URLSearchParams" in html
    assert "new FormData(form)" in html


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

    assert "Takeaway:" in html
    assert "AI meaning:" in html
    assert "Your note:" not in html
    assert 'value="pass"' in html
    assert 'name="return_to" value="/review"' in html


def test_review_answer_cell_shows_discrimination_hint_for_misread_word() -> None:
    item = _Item(
        card_type=CardType.WORD,
        card_id=2,
        mastery_state=MasteryState.LEARNING,
        due_at=datetime.now(timezone.utc),
        prompt="tie",
        answer="联系",
        ai_meaning="a stalemate",
        note_status="incorrect",
        note_correction="平局 (stalemate/deadlock)",
    )

    html = _review_answer_cell(item, "/review")

    assert "Your note (incorrect):" in html
    assert "Correct meaning:" in html
    assert "平局 (stalemate/deadlock)" in html
    assert "Takeaway:" not in html
    assert "AI meaning:" in html


def test_review_answer_cell_partly_correct_also_shows_discrimination() -> None:
    item = _Item(
        card_type=CardType.WORD,
        card_id=3,
        mastery_state=MasteryState.LEARNING,
        due_at=datetime.now(timezone.utc),
        prompt="broken",
        answer="破坏",
        note_status="partly_correct",
        note_correction="打破 (resolved)",
    )

    html = _review_answer_cell(item, "/review")

    assert "Your note (incorrect):" in html
    assert "Correct meaning:" in html
    assert "打破 (resolved)" in html
    assert "Takeaway:" not in html


def test_review_answer_cell_correct_status_shows_normal_takeaway() -> None:
    item = _Item(
        card_type=CardType.WORD,
        card_id=4,
        mastery_state=MasteryState.LEARNING,
        due_at=datetime.now(timezone.utc),
        prompt="ephemeral",
        answer="短暂的",
        note_status="correct",
    )

    html = _review_answer_cell(item, "/review")

    assert "Takeaway:" in html
    assert "Your note (incorrect):" not in html
    assert "Correct meaning:" not in html


def test_review_answer_cell_labels_sentence_translation_and_takeaway() -> None:
    item = _Item(
        card_type=CardType.SENTENCE,
        card_id=7,
        mastery_state=MasteryState.NEW,
        due_at=datetime.now(timezone.utc),
        prompt="The cat sat.",
        answer="猫坐着。",
        takeaway="先找主谓。",
        ai_meaning="Ignored for sentence",
    )

    html = _review_answer_cell(item, "/review")

    assert "Translation:" in html
    assert "Takeaway:" in html
    assert "猫坐着。" in html
    assert "先找主谓。" in html
    assert "AI meaning:" not in html
    assert "Your note:" not in html
