"""
Tests for app/review/sm2_scheduler.py.

Pure SM-2 formula tests use fixed dataclasses. Persistence tests use real
SQLite with migrations so card updates and review_logs are verified together.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.cards.sentence_card_service import create_sentence_card
from app.cards.word_card_service import create_or_update_word_card
from app.db_connection import DatabaseConnection
from app.db_models import CardType, MasteryState, ReviewOutcome
from app.review.sm2_scheduler import (
    ReviewCardNotFoundError,
    ReviewInputError,
    ReviewState,
    apply_review,
    next_review_state,
)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
REVIEWED_AT = datetime(2026, 1, 2, 12, 30, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


_seed_counter = 0


def _seed_sentence(db: DatabaseConnection, text: str = "A test sentence.") -> int:
    global _seed_counter
    _seed_counter += 1
    with db.get_connection() as conn:
        book_id = conn.execute(
            "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
            "VALUES ('B', '', 'txt', ?, '2026-01-01T00:00:00+00:00')",
            (f"review_hash_{_seed_counter}",),
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
                f"text_hash_{_seed_counter}",
                len(text),
            ),
        ).lastrowid
    return sentence_id


def _state(
    *,
    ef: float = 2.5,
    interval_days: int = 0,
    repetitions: int = 0,
    mastery_state: MasteryState = MasteryState.NEW,
) -> ReviewState:
    return ReviewState(
        ef=ef,
        interval_days=interval_days,
        repetitions=repetitions,
        mastery_state=mastery_state,
        due_at=REVIEWED_AT,
    )


class TestNextReviewState:
    def test_first_pass_moves_to_one_day_learning(self) -> None:
        result = next_review_state(_state(), 5, reviewed_at=REVIEWED_AT)

        assert result.interval_days == 1
        assert result.repetitions == 1
        assert result.mastery_state == MasteryState.LEARNING
        assert result.due_at == REVIEWED_AT + timedelta(days=1)

    def test_second_pass_moves_to_six_days(self) -> None:
        result = next_review_state(
            _state(interval_days=1, repetitions=1, mastery_state=MasteryState.LEARNING),
            5,
            reviewed_at=REVIEWED_AT,
        )

        assert result.interval_days == 6
        assert result.repetitions == 2

    def test_later_pass_uses_old_ef_to_scale_interval(self) -> None:
        result = next_review_state(
            _state(interval_days=6, repetitions=2, mastery_state=MasteryState.LEARNING),
            5,
            reviewed_at=REVIEWED_AT,
        )

        assert result.interval_days == 15
        assert result.repetitions == 3
        assert result.mastery_state == MasteryState.LEARNING

    def test_long_successful_card_becomes_mature(self) -> None:
        result = next_review_state(
            _state(interval_days=21, repetitions=3, mastery_state=MasteryState.LEARNING),
            5,
            reviewed_at=REVIEWED_AT,
        )

        assert result.interval_days == 52
        assert result.mastery_state == MasteryState.MATURE

    def test_partial_lowers_ef_but_keeps_success_path(self) -> None:
        result = next_review_state(_state(), 3, reviewed_at=REVIEWED_AT)

        assert result.ef == 2.36
        assert result.interval_days == 1
        assert result.repetitions == 1

    def test_fail_resets_non_mature_card_to_new(self) -> None:
        result = next_review_state(
            _state(interval_days=21, repetitions=3, mastery_state=MasteryState.LEARNING),
            1,
            reviewed_at=REVIEWED_AT,
        )

        assert result.interval_days == 1
        assert result.repetitions == 0
        assert result.mastery_state == MasteryState.NEW

    def test_fail_on_mature_card_marks_lapsed(self) -> None:
        result = next_review_state(
            _state(interval_days=30, repetitions=5, mastery_state=MasteryState.MATURE),
            1,
            reviewed_at=REVIEWED_AT,
        )

        assert result.mastery_state == MasteryState.LAPSED

    def test_ef_never_drops_below_minimum(self) -> None:
        result = next_review_state(_state(ef=1.31), 0, reviewed_at=REVIEWED_AT)

        assert result.ef == 1.3

    def test_naive_review_time_is_treated_as_utc(self) -> None:
        naive_time = datetime(2026, 1, 2, 8, 0)
        result = next_review_state(_state(), 5, reviewed_at=naive_time)

        assert result.due_at.tzinfo == timezone.utc
        assert result.due_at == naive_time.replace(tzinfo=timezone.utc) + timedelta(days=1)

    @pytest.mark.parametrize("quality", [-1, 6])
    def test_invalid_quality_raises(self, quality: int) -> None:
        with pytest.raises(ReviewInputError, match="quality"):
            next_review_state(_state(), quality, reviewed_at=REVIEWED_AT)


class TestApplyReview:
    def test_sentence_review_updates_card_and_writes_log(
        self, db: DatabaseConnection
    ) -> None:
        sentence_id = _seed_sentence(db)
        card_id = create_sentence_card(db, sentence_id)

        result = apply_review(
            db,
            "sentence",
            card_id,
            "pass",
            latency_ms=2500,
            reviewed_at=REVIEWED_AT,
        )

        assert result.card_type == CardType.SENTENCE
        assert result.outcome == ReviewOutcome.PASS
        assert result.quality == 5
        assert result.review_count_after == 1
        assert result.latency_ms == 2500

        with db.get_connection() as conn:
            card = conn.execute(
                "SELECT * FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            log = conn.execute(
                "SELECT * FROM review_logs WHERE id = ?",
                (result.log_id,),
            ).fetchone()

        assert card["review_count"] == 1
        assert card["last_reviewed_at"] == REVIEWED_AT.isoformat()
        assert card["due_at"] == (REVIEWED_AT + timedelta(days=1)).isoformat()
        assert card["mastery_state"] == "learning"
        assert log["card_type"] == "sentence"
        assert log["card_id"] == card_id
        assert log["ef_before"] == 2.5
        assert log["ef_after"] == result.state_after.ef
        assert log["interval_before"] == 0
        assert log["interval_after"] == 1
        assert log["repetitions_before"] == 0
        assert log["repetitions_after"] == 1
        assert log["latency_ms"] == 2500

    def test_word_review_accepts_enum_inputs(self, db: DatabaseConnection) -> None:
        sentence_id = _seed_sentence(db, "A cat sat.")
        card_id, _ = create_or_update_word_card(db, sentence_id, "cat")

        result = apply_review(
            db,
            CardType.WORD,
            card_id,
            ReviewOutcome.PARTIAL,
            reviewed_at=REVIEWED_AT,
        )

        assert result.card_type == CardType.WORD
        assert result.quality == 3
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT mastery_state, ef, interval_days FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert row["mastery_state"] == "learning"
        assert row["ef"] == 2.36
        assert row["interval_days"] == 1

    def test_default_review_time_is_timezone_aware(self, db: DatabaseConnection) -> None:
        sentence_id = _seed_sentence(db)
        card_id = create_sentence_card(db, sentence_id)

        result = apply_review(db, "sentence", card_id, "pass")

        assert result.reviewed_at.tzinfo == timezone.utc
        assert result.state_after.due_at.tzinfo == timezone.utc

    def test_missing_card_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ReviewCardNotFoundError, match="not found"):
            apply_review(db, "sentence", 999_999, "pass", reviewed_at=REVIEWED_AT)

    def test_invalid_card_type_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ReviewInputError, match="card_type"):
            apply_review(db, "phrase", 1, "pass", reviewed_at=REVIEWED_AT)

    def test_invalid_outcome_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ReviewInputError, match="outcome"):
            apply_review(db, "sentence", 1, "easy", reviewed_at=REVIEWED_AT)

    def test_negative_latency_raises(self, db: DatabaseConnection) -> None:
        sentence_id = _seed_sentence(db)
        card_id = create_sentence_card(db, sentence_id)

        with pytest.raises(ReviewInputError, match="latency_ms"):
            apply_review(
                db,
                "sentence",
                card_id,
                "pass",
                latency_ms=-1,
                reviewed_at=REVIEWED_AT,
            )
