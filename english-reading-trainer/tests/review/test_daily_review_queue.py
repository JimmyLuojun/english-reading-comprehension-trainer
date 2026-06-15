"""
Tests for app/review/daily_review_queue.py.

Uses real SQLite so due-card selection, review-log priority, and error-code
coverage all exercise the actual schema.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.db_models import CardType, MasteryState, ReviewOutcome
from app.review.daily_review_queue import (
    ReviewQueueItem,
    build_daily_review_queue,
    list_due_cards,
)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
NOW = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


_seed_counter = 0


def _seed_sentence(db: DatabaseConnection, text: str) -> int:
    global _seed_counter
    _seed_counter += 1
    with db.get_connection() as conn:
        book_id = conn.execute(
            "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
            "VALUES ('B', '', 'txt', ?, '2026-01-01T00:00:00+00:00')",
            (f"queue_hash_{_seed_counter}",),
        ).lastrowid
        chapter_id = conn.execute(
            "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
            "VALUES (?, 1, 'Ch', 0, 1)",
            (book_id,),
        ).lastrowid
        paragraph_id = conn.execute(
            "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
            "VALUES (?, 1, 0, 1)",
            (chapter_id,),
        ).lastrowid
        sentence_id = conn.execute(
            "INSERT INTO sentences (book_id, chapter_id, paragraph_id, idx, "
            "text, text_hash, char_offset_start, char_offset_end) "
            "VALUES (?, ?, ?, 0, ?, ?, 0, ?)",
            (
                book_id,
                chapter_id,
                paragraph_id,
                text,
                f"queue_text_hash_{_seed_counter}",
                len(text),
            ),
        ).lastrowid
    return sentence_id


def _insert_sentence_card(
    db: DatabaseConnection,
    *,
    text: str = "A due sentence.",
    due_at: datetime = NOW,
    mastery_state: str = "new",
    ef: float = 2.5,
    review_count: int = 0,
    repetitions: int = 0,
) -> int:
    sentence_id = _seed_sentence(db, text)
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO sentence_cards
               (sentence_id, created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at, user_note)
               VALUES (?, ?, NULL, ?, ?, ?, 0, ?, ?, '')""",
            (
                sentence_id,
                NOW.isoformat(),
                review_count,
                mastery_state,
                ef,
                repetitions,
                due_at.isoformat(),
            ),
        ).lastrowid


def _insert_word_card(
    db: DatabaseConnection,
    *,
    surface_form: str,
    due_at: datetime = NOW,
    mastery_state: str = "new",
    ef: float = 2.5,
    review_count: int = 0,
    repetitions: int = 0,
) -> int:
    sentence_id = _seed_sentence(db, f"The word is {surface_form}.")
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO word_cards
               (lemma, surface_form, lexical_type, first_sentence_id,
                current_meaning, pos, created_at, last_reviewed_at,
                review_count, mastery_state, ef, interval_days, repetitions,
                due_at, occurrence_count, user_note)
               VALUES (?, ?, 'word', ?, '', '', ?, NULL, ?, ?, ?, 0, ?, ?, 1, '')""",
            (
                surface_form.lower(),
                surface_form,
                sentence_id,
                NOW.isoformat(),
                review_count,
                mastery_state,
                ef,
                repetitions,
                due_at.isoformat(),
            ),
        ).lastrowid


def _insert_review_log(
    db: DatabaseConnection,
    card_type: CardType,
    card_id: int,
    quality: int,
    outcome: ReviewOutcome,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO review_logs
               (card_type, card_id, reviewed_at, quality, outcome,
                ef_before, ef_after, interval_before, interval_after,
                repetitions_before, repetitions_after, latency_ms)
               VALUES (?, ?, ?, ?, ?, 2.5, 2.5, 1, 1, 1, 1, 0)""",
            (
                card_type.value,
                card_id,
                (NOW - timedelta(days=1)).isoformat(),
                quality,
                outcome.value,
            ),
        )


def _link_error(db: DatabaseConnection, card_type: CardType, card_id: int, code: str) -> None:
    table = "sentence_card_errors" if card_type == CardType.SENTENCE else "word_card_errors"
    with db.get_connection() as conn:
        error_id = conn.execute(
            "SELECT id FROM error_types WHERE code = ?",
            (code,),
        ).fetchone()["id"]
        conn.execute(
            f"INSERT INTO {table} (card_id, error_type_id) VALUES (?, ?)",
            (card_id, error_id),
        )


class TestReviewQueueItem:
    def test_is_new_true_only_when_review_count_zero(self) -> None:
        item = ReviewQueueItem(
            card_type=CardType.SENTENCE,
            card_id=1,
            mastery_state=MasteryState.NEW,
            ef=2.5,
            interval_days=0,
            repetitions=0,
            review_count=0,
            due_at=NOW,
            prompt="text",
        )

        assert item.is_new is True

    def test_is_new_false_after_any_review(self) -> None:
        item = ReviewQueueItem(
            card_type=CardType.WORD,
            card_id=1,
            mastery_state=MasteryState.NEW,
            ef=2.5,
            interval_days=1,
            repetitions=0,
            review_count=1,
            due_at=NOW,
            prompt="word",
        )

        assert item.is_new is False


class TestListDueCards:
    def test_empty_when_no_cards(self, db: DatabaseConnection) -> None:
        assert list_due_cards(db, as_of=NOW) == []

    def test_due_cards_are_included_and_future_cards_excluded(
        self, db: DatabaseConnection
    ) -> None:
        due_id = _insert_sentence_card(db, text="Due now.", due_at=NOW)
        _insert_sentence_card(db, text="Future.", due_at=NOW + timedelta(days=1))

        items = list_due_cards(db, as_of=NOW)

        assert [item.card_id for item in items] == [due_id]

    def test_archived_cards_are_excluded(self, db: DatabaseConnection) -> None:
        archived_id = _insert_sentence_card(db, text="Archived.", due_at=NOW)
        word_id = _insert_word_card(db, surface_form="active", due_at=NOW)
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE sentence_cards SET archived_at = ? WHERE id = ?",
                (NOW.isoformat(), archived_id),
            )

        items = list_due_cards(db, as_of=NOW)

        assert [(item.card_type, item.card_id) for item in items] == [
            (CardType.WORD, word_id)
        ]

    def test_can_filter_to_word_cards(self, db: DatabaseConnection) -> None:
        _insert_sentence_card(db)
        word_id = _insert_word_card(db, surface_form="mitigate")

        items = list_due_cards(db, as_of=NOW, card_type="word")

        assert len(items) == 1
        assert items[0].card_type == CardType.WORD
        assert items[0].card_id == word_id

    def test_invalid_card_type_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="card_type"):
            list_due_cards(db, as_of=NOW, card_type="phrase")

    def test_limit_is_applied_after_sorting(self, db: DatabaseConnection) -> None:
        first_id = _insert_sentence_card(db, text="Lower EF.", ef=1.5)
        _insert_sentence_card(db, text="Higher EF.", ef=2.5)

        items = list_due_cards(db, as_of=NOW, limit=1)

        assert len(items) == 1
        assert items[0].card_id == first_id

    def test_lapsed_or_failed_cards_sort_first(self, db: DatabaseConnection) -> None:
        normal_id = _insert_sentence_card(db, text="Normal.", mastery_state="learning")
        failed_id = _insert_sentence_card(db, text="Failed.", mastery_state="learning")
        lapsed_id = _insert_sentence_card(db, text="Lapsed.", mastery_state="lapsed")
        _insert_review_log(db, CardType.SENTENCE, failed_id, 1, ReviewOutcome.FAIL)

        items = list_due_cards(db, as_of=NOW)

        assert [item.card_id for item in items[:2]] == [failed_id, lapsed_id]
        assert items[-1].card_id == normal_id

    def test_partial_cards_sort_before_unreviewed_normal_cards(
        self, db: DatabaseConnection
    ) -> None:
        normal_id = _insert_sentence_card(db, text="Normal.", review_count=1)
        partial_id = _insert_sentence_card(db, text="Partial.", review_count=1)
        _insert_review_log(db, CardType.SENTENCE, partial_id, 3, ReviewOutcome.PARTIAL)

        items = list_due_cards(db, as_of=NOW)

        assert [item.card_id for item in items] == [partial_id, normal_id]

    def test_older_due_date_breaks_priority_tie(self, db: DatabaseConnection) -> None:
        older_id = _insert_sentence_card(db, due_at=NOW - timedelta(days=3))
        newer_id = _insert_sentence_card(db, due_at=NOW - timedelta(days=1))

        items = list_due_cards(db, as_of=NOW)

        assert [item.card_id for item in items] == [older_id, newer_id]

    def test_error_codes_are_attached(self, db: DatabaseConnection) -> None:
        card_id = _insert_word_card(db, surface_form="however")
        _link_error(db, CardType.WORD, card_id, "D02")

        items = list_due_cards(db, as_of=NOW)

        assert items[0].error_codes == ("D02",)


class TestBuildDailyReviewQueue:
    def test_zero_limit_returns_empty(self, db: DatabaseConnection) -> None:
        _insert_sentence_card(db)

        assert build_daily_review_queue(db, as_of=NOW, daily_limit=0) == []

    @pytest.mark.parametrize(
        "kwargs,message",
        [
            ({"daily_limit": -1}, "daily_limit"),
            ({"new_card_slots": -1}, "slot"),
            ({"old_card_slots": -1}, "slot"),
            ({"top_error_codes": -1}, "top_error_codes"),
        ],
    )
    def test_invalid_budget_raises(
        self, db: DatabaseConnection, kwargs: dict, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            build_daily_review_queue(db, as_of=NOW, **kwargs)

    def test_daily_limit_is_respected(self, db: DatabaseConnection) -> None:
        for idx in range(5):
            _insert_word_card(db, surface_form=f"word{idx}")

        items = build_daily_review_queue(db, as_of=NOW, daily_limit=3)

        assert len(items) == 3

    def test_sentence_word_ratio_prefers_one_sentence_for_four_cards(
        self, db: DatabaseConnection
    ) -> None:
        for idx in range(3):
            _insert_sentence_card(db, text=f"Sentence {idx}.")
            _insert_word_card(db, surface_form=f"word{idx}")

        items = build_daily_review_queue(db, as_of=NOW, daily_limit=4)

        assert sum(1 for item in items if item.card_type == CardType.SENTENCE) == 1
        assert sum(1 for item in items if item.card_type == CardType.WORD) == 3

    def test_unused_type_slots_are_backfilled(self, db: DatabaseConnection) -> None:
        for idx in range(4):
            _insert_word_card(db, surface_form=f"onlyword{idx}")

        items = build_daily_review_queue(db, as_of=NOW, daily_limit=4)

        assert len(items) == 4
        assert all(item.card_type == CardType.WORD for item in items)

    def test_scaled_new_old_slots_are_respected_when_possible(
        self, db: DatabaseConnection
    ) -> None:
        _insert_sentence_card(db, text="New sentence.", review_count=0)
        for idx in range(3):
            _insert_word_card(
                db,
                surface_form=f"old{idx}",
                review_count=1,
                mastery_state="learning",
                repetitions=1,
            )

        items = build_daily_review_queue(
            db,
            as_of=NOW,
            daily_limit=4,
            new_card_slots=10,
            old_card_slots=30,
        )

        assert sum(1 for item in items if item.is_new) == 1
        assert sum(1 for item in items if not item.is_new) == 3

    def test_error_code_coverage_prefills_top_error_cards(
        self, db: DatabaseConnection
    ) -> None:
        for idx in range(4):
            card_id = _insert_word_card(db, surface_form=f"g{idx}")
            _link_error(db, CardType.WORD, card_id, "G01")
        for idx in range(2):
            card_id = _insert_word_card(db, surface_form=f"l{idx}")
            _link_error(db, CardType.WORD, card_id, "L01")

        items = build_daily_review_queue(
            db,
            as_of=NOW,
            daily_limit=5,
            top_error_codes=1,
            min_per_error_code=3,
        )

        assert sum(1 for item in items if "G01" in item.error_codes) >= 3

    def test_high_frequency_error_cards_sort_before_plain_cards(
        self, db: DatabaseConnection
    ) -> None:
        tagged_id = _insert_sentence_card(db, text="Tagged.")
        plain_id = _insert_sentence_card(db, text="Plain.")
        _link_error(db, CardType.SENTENCE, tagged_id, "G01")

        items = build_daily_review_queue(
            db,
            as_of=NOW,
            daily_limit=2,
            top_error_codes=1,
            min_per_error_code=0,
        )

        assert [item.card_id for item in items] == [tagged_id, plain_id]


# ---------------------------------------------------------------------------
# answer field (§23)
# ---------------------------------------------------------------------------

class TestReviewQueueItemAnswer:
    def test_word_card_answer_is_current_meaning(
        self, db: DatabaseConnection
    ) -> None:
        sentence_id = _seed_sentence(db, "Ephemeral beauty fades quickly.")
        with db.get_connection() as conn:
            card_id = conn.execute(
                """INSERT INTO word_cards
                   (lemma, surface_form, lexical_type, first_sentence_id,
                    current_meaning, pos, created_at, last_reviewed_at,
                    review_count, mastery_state, ef, interval_days, repetitions,
                    due_at, occurrence_count, user_note)
                   VALUES ('ephemeral', 'ephemeral', 'word', ?, 'lasting a very short time',
                           '', ?, NULL, 0, 'new', 2.5, 0, 0, ?, 1, '')""",
                (sentence_id, NOW.isoformat(), NOW.isoformat()),
            ).lastrowid

        items = list_due_cards(db, as_of=NOW, card_type="word")

        assert len(items) == 1
        assert items[0].card_id == card_id
        assert items[0].answer == "lasting a very short time"

    def test_word_card_answer_empty_when_current_meaning_blank(
        self, db: DatabaseConnection
    ) -> None:
        _insert_word_card(db, surface_form="ontological")
        items = list_due_cards(db, as_of=NOW, card_type="word")
        assert items[0].answer == ""

    def test_sentence_card_answer_is_user_translation(
        self, db: DatabaseConnection
    ) -> None:
        sentence_id = _seed_sentence(db, "Coral reefs are fragile ecosystems.")
        with db.get_connection() as conn:
            card_id = conn.execute(
                """INSERT INTO sentence_cards
                   (sentence_id, created_at, last_reviewed_at, review_count,
                    mastery_state, ef, interval_days, repetitions, due_at,
                    user_note, user_translation)
                   VALUES (?, ?, NULL, 0, 'new', 2.5, 0, 0, ?, '', '珊瑚礁是脆弱的生态系统。')""",
                (sentence_id, NOW.isoformat(), NOW.isoformat()),
            ).lastrowid

        items = list_due_cards(db, as_of=NOW, card_type="sentence")

        assert len(items) == 1
        assert items[0].card_id == card_id
        assert items[0].answer == "珊瑚礁是脆弱的生态系统。"

    def test_sentence_card_answer_empty_when_no_translation(
        self, db: DatabaseConnection
    ) -> None:
        _insert_sentence_card(db)
        items = list_due_cards(db, as_of=NOW, card_type="sentence")
        assert items[0].answer == ""

    def test_review_queue_item_answer_defaults_to_empty(self) -> None:
        item = ReviewQueueItem(
            card_type=CardType.WORD,
            card_id=1,
            mastery_state=MasteryState.NEW,
            ef=2.5,
            interval_days=0,
            repetitions=0,
            review_count=0,
            due_at=NOW,
            prompt="ephemeral",
        )
        assert item.answer == ""
