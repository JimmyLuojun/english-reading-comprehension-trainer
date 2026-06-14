"""
Tests for app/profile/learner_profile_generator.py.

All tests use real SQLite with migrations. No LLM calls or network access.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.db_models import CardType, MasteryState, ReviewOutcome
from app.profile.learner_profile_generator import (
    ErrorTypeStat,
    ProfileCardPreview,
    ProfileInputError,
    ProfileSnapshot,
    build_profile_prompt,
    collect_profile_stats,
    get_latest_profile_snapshot,
    get_profile_trigger_status,
    profile_stats_to_payload,
    save_profile_snapshot,
)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
NOW = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)


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
            (f"profile_hash_{_seed_counter}",),
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
                f"profile_text_hash_{_seed_counter}",
                len(text),
            ),
        ).lastrowid
    return sentence_id


def _insert_sentence_card(
    db: DatabaseConnection,
    *,
    text: str = "A sentence card.",
    mastery_state: str = "new",
    review_count: int = 0,
) -> int:
    sentence_id = _seed_sentence(db, text)
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO sentence_cards
               (sentence_id, created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at, user_note)
               VALUES (?, ?, NULL, ?, ?, 2.5, 0, 0, ?, '')""",
            (
                sentence_id,
                NOW.isoformat(),
                review_count,
                mastery_state,
                NOW.isoformat(),
            ),
        ).lastrowid


def _insert_word_card(
    db: DatabaseConnection,
    *,
    surface_form: str = "mitigate",
    mastery_state: str = "new",
    review_count: int = 0,
) -> int:
    sentence_id = _seed_sentence(db, f"The word is {surface_form}.")
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO word_cards
               (lemma, surface_form, lexical_type, first_sentence_id,
                current_meaning, pos, created_at, last_reviewed_at,
                review_count, mastery_state, ef, interval_days, repetitions,
                due_at, occurrence_count, user_note)
               VALUES (?, ?, 'word', ?, '', '', ?, NULL, ?, ?, 2.5, 0, 0, ?, 1, '')""",
            (
                surface_form.lower(),
                surface_form,
                sentence_id,
                NOW.isoformat(),
                review_count,
                mastery_state,
                NOW.isoformat(),
            ),
        ).lastrowid


def _insert_review_log(
    db: DatabaseConnection,
    card_type: CardType,
    card_id: int,
    *,
    reviewed_at: datetime,
    outcome: ReviewOutcome,
) -> None:
    quality = {
        ReviewOutcome.PASS: 5,
        ReviewOutcome.PARTIAL: 3,
        ReviewOutcome.FAIL: 1,
    }[outcome]
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
                reviewed_at.isoformat(),
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


def _insert_snapshot(
    db: DatabaseConnection,
    *,
    created_at: datetime,
    summary_md: str = "## Current Weaknesses\n- Existing profile",
) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            """INSERT INTO learner_profile_snapshots
               (created_at, summary_md, payload_json, cards_at_snapshot,
                sentences_at_snapshot)
               VALUES (?, ?, '{}', 0, 0)""",
            (created_at.isoformat(), summary_md),
        ).lastrowid


class TestCollectProfileStats:
    def test_empty_database_returns_zero_stats(self, db: DatabaseConnection) -> None:
        stats = collect_profile_stats(db, as_of=NOW)

        assert stats.total_reviews == 0
        assert stats.sentence_card_count == 0
        assert stats.word_card_count == 0
        assert stats.error_type_stats == ()
        assert stats.lapsed_cards == ()
        assert stats.mastered_cards == ()
        assert stats.mastery_counts[MasteryState.NEW] == 0

    def test_invalid_lookback_days_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ProfileInputError, match="lookback_days"):
            collect_profile_stats(db, lookback_days=0, as_of=NOW)

    def test_counts_only_reviews_inside_lookback_window(
        self, db: DatabaseConnection
    ) -> None:
        card_id = _insert_sentence_card(db)
        _insert_review_log(
            db,
            CardType.SENTENCE,
            card_id,
            reviewed_at=NOW - timedelta(days=5),
            outcome=ReviewOutcome.PASS,
        )
        _insert_review_log(
            db,
            CardType.SENTENCE,
            card_id,
            reviewed_at=NOW - timedelta(days=91),
            outcome=ReviewOutcome.FAIL,
        )

        stats = collect_profile_stats(db, as_of=NOW)

        assert stats.total_reviews == 1

    def test_counts_distinct_sentence_and_word_cards_reviewed(
        self, db: DatabaseConnection
    ) -> None:
        sentence_card = _insert_sentence_card(db)
        word_card = _insert_word_card(db, surface_form="claim")
        _insert_review_log(
            db,
            CardType.SENTENCE,
            sentence_card,
            reviewed_at=NOW,
            outcome=ReviewOutcome.PASS,
        )
        _insert_review_log(
            db,
            CardType.SENTENCE,
            sentence_card,
            reviewed_at=NOW - timedelta(days=1),
            outcome=ReviewOutcome.PARTIAL,
        )
        _insert_review_log(
            db,
            CardType.WORD,
            word_card,
            reviewed_at=NOW,
            outcome=ReviewOutcome.FAIL,
        )

        stats = collect_profile_stats(db, as_of=NOW)

        assert stats.total_reviews == 3
        assert stats.sentence_card_count == 1
        assert stats.word_card_count == 1

    def test_mastery_distribution_counts_both_card_tables(
        self, db: DatabaseConnection
    ) -> None:
        _insert_sentence_card(db, mastery_state="new")
        _insert_sentence_card(db, mastery_state="mature")
        _insert_word_card(db, surface_form="learning-word", mastery_state="learning")
        _insert_word_card(db, surface_form="lapsed-word", mastery_state="lapsed")

        stats = collect_profile_stats(db, as_of=NOW)

        assert stats.mastery_counts[MasteryState.NEW] == 1
        assert stats.mastery_counts[MasteryState.LEARNING] == 1
        assert stats.mastery_counts[MasteryState.MATURE] == 1
        assert stats.mastery_counts[MasteryState.LAPSED] == 1

    def test_error_stats_merge_sentence_and_word_errors(self, db: DatabaseConnection) -> None:
        sentence_card = _insert_sentence_card(db)
        word_card = _insert_word_card(db, surface_form="however")
        _link_error(db, CardType.SENTENCE, sentence_card, "G02")
        _link_error(db, CardType.WORD, word_card, "G02")
        _link_error(db, CardType.WORD, word_card, "L01")
        _insert_review_log(
            db,
            CardType.SENTENCE,
            sentence_card,
            reviewed_at=NOW,
            outcome=ReviewOutcome.PARTIAL,
        )
        _insert_review_log(
            db,
            CardType.WORD,
            word_card,
            reviewed_at=NOW,
            outcome=ReviewOutcome.FAIL,
        )

        stats = collect_profile_stats(db, as_of=NOW)

        g02 = next(stat for stat in stats.error_type_stats if stat.code == "G02")
        assert g02.occurrences == 2
        assert g02.partial_count == 1
        assert g02.fail_count == 1
        assert stats.error_type_stats[0].code == "G02"

    def test_lapsed_cards_include_days_ago(self, db: DatabaseConnection) -> None:
        card_id = _insert_sentence_card(
            db,
            text="The policy, which officials had defended, collapsed.",
            mastery_state="lapsed",
        )
        _insert_review_log(
            db,
            CardType.SENTENCE,
            card_id,
            reviewed_at=NOW - timedelta(days=3),
            outcome=ReviewOutcome.FAIL,
        )

        stats = collect_profile_stats(db, as_of=NOW)

        assert stats.lapsed_cards[0].card_type == CardType.SENTENCE
        assert stats.lapsed_cards[0].days_ago == 3
        assert "policy" in stats.lapsed_cards[0].content_preview

    def test_mastered_cards_include_current_mature_cards_reviewed_in_period(
        self, db: DatabaseConnection
    ) -> None:
        card_id = _insert_word_card(db, surface_form="albeit", mastery_state="mature")
        _insert_review_log(
            db,
            CardType.WORD,
            card_id,
            reviewed_at=NOW,
            outcome=ReviewOutcome.PASS,
        )

        stats = collect_profile_stats(db, as_of=NOW)

        assert stats.mastered_cards[0].card_type == CardType.WORD
        assert stats.mastered_cards[0].content_preview == "albeit"


class TestBuildProfilePrompt:
    def test_prompt_contains_rendered_review_counts(self, db: DatabaseConnection) -> None:
        card_id = _insert_sentence_card(db)
        _insert_review_log(
            db,
            CardType.SENTENCE,
            card_id,
            reviewed_at=NOW,
            outcome=ReviewOutcome.PASS,
        )

        prompt = build_profile_prompt(db, as_of=NOW)

        assert "TOTAL REVIEWS: 1" in prompt
        assert "{{ total_reviews }}" not in prompt

    def test_prompt_contains_error_type_stats(self, db: DatabaseConnection) -> None:
        card_id = _insert_word_card(db, surface_form="claim")
        _link_error(db, CardType.WORD, card_id, "L01")
        _insert_review_log(
            db,
            CardType.WORD,
            card_id,
            reviewed_at=NOW,
            outcome=ReviewOutcome.PARTIAL,
        )

        prompt = build_profile_prompt(db, as_of=NOW)

        assert "L01" in prompt
        assert "partial 1" in prompt

    def test_prompt_uses_none_for_empty_sections(self, db: DatabaseConnection) -> None:
        prompt = build_profile_prompt(db, as_of=NOW)

        assert "(none)" in prompt

    def test_prompt_strips_frontmatter(self, db: DatabaseConnection) -> None:
        prompt = build_profile_prompt(db, as_of=NOW)

        assert not prompt.startswith("---")
        assert "# Learner Profile Summary Prompt" in prompt


class TestProfileTriggerStatus:
    def test_no_snapshot_not_due_before_review_threshold(
        self, db: DatabaseConnection
    ) -> None:
        card_id = _insert_sentence_card(db)
        for idx in range(19):
            _insert_review_log(
                db,
                CardType.SENTENCE,
                card_id,
                reviewed_at=NOW - timedelta(minutes=idx),
                outcome=ReviewOutcome.PASS,
            )

        status = get_profile_trigger_status(db, as_of=NOW)

        assert status.should_generate is False
        assert status.reason == "not_due"
        assert status.reviews_since_snapshot == 19
        assert status.last_snapshot_at is None

    def test_no_snapshot_due_at_review_threshold(self, db: DatabaseConnection) -> None:
        card_id = _insert_sentence_card(db)
        for idx in range(20):
            _insert_review_log(
                db,
                CardType.SENTENCE,
                card_id,
                reviewed_at=NOW - timedelta(minutes=idx),
                outcome=ReviewOutcome.PASS,
            )

        status = get_profile_trigger_status(db, as_of=NOW)

        assert status.should_generate is True
        assert status.reason == "review_count"
        assert status.reviews_since_snapshot == 20

    def test_existing_snapshot_due_after_20_new_reviews(
        self, db: DatabaseConnection
    ) -> None:
        snapshot_time = NOW - timedelta(days=1)
        _insert_snapshot(db, created_at=snapshot_time)
        card_id = _insert_sentence_card(db)
        for idx in range(20):
            _insert_review_log(
                db,
                CardType.SENTENCE,
                card_id,
                reviewed_at=snapshot_time + timedelta(minutes=idx + 1),
                outcome=ReviewOutcome.PASS,
            )

        status = get_profile_trigger_status(db, as_of=NOW)

        assert status.should_generate is True
        assert status.reason == "review_count"
        assert status.days_since_snapshot == 1

    def test_existing_snapshot_due_after_elapsed_days(self, db: DatabaseConnection) -> None:
        _insert_snapshot(db, created_at=NOW - timedelta(days=8))
        card_id = _insert_sentence_card(db)
        _insert_review_log(
            db,
            CardType.SENTENCE,
            card_id,
            reviewed_at=NOW - timedelta(days=6),
            outcome=ReviewOutcome.PASS,
        )

        status = get_profile_trigger_status(db, as_of=NOW)

        assert status.should_generate is True
        assert status.reason == "elapsed_days"
        assert status.days_since_snapshot == 8

    def test_existing_snapshot_not_due_without_review_or_day_trigger(
        self, db: DatabaseConnection
    ) -> None:
        _insert_snapshot(db, created_at=NOW - timedelta(days=2))

        status = get_profile_trigger_status(db, as_of=NOW)

        assert status.should_generate is False
        assert status.reason == "not_due"

    def test_invalid_trigger_values_raise(self, db: DatabaseConnection) -> None:
        with pytest.raises(ProfileInputError, match="review_trigger"):
            get_profile_trigger_status(db, review_trigger=0, as_of=NOW)
        with pytest.raises(ProfileInputError, match="day_trigger"):
            get_profile_trigger_status(db, day_trigger=0, as_of=NOW)


class TestProfileSnapshots:
    def test_save_profile_snapshot_returns_id(self, db: DatabaseConnection) -> None:
        snapshot_id = save_profile_snapshot(
            db,
            "## Current Weaknesses\n- Test",
            created_at=NOW,
        )

        assert snapshot_id > 0

    def test_empty_summary_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ProfileInputError, match="summary_md"):
            save_profile_snapshot(db, "   ", created_at=NOW)

    def test_snapshot_stores_payload_and_counts(self, db: DatabaseConnection) -> None:
        _insert_sentence_card(db)
        _insert_word_card(db, surface_form="mitigate")
        snapshot_id = save_profile_snapshot(
            db,
            "## Current Weaknesses\n- Test",
            payload={"total_reviews": 3},
            created_at=NOW,
        )

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM learner_profile_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()

        assert json.loads(row["payload_json"]) == {"total_reviews": 3}
        assert row["cards_at_snapshot"] == 2
        assert row["sentences_at_snapshot"] == 2

    def test_get_latest_profile_snapshot_returns_none_when_empty(
        self, db: DatabaseConnection
    ) -> None:
        assert get_latest_profile_snapshot(db) is None

    def test_get_latest_profile_snapshot_returns_newest(
        self, db: DatabaseConnection
    ) -> None:
        _insert_snapshot(db, created_at=NOW - timedelta(days=1), summary_md="Old")
        newest_id = _insert_snapshot(db, created_at=NOW, summary_md="New")

        snapshot = get_latest_profile_snapshot(db)

        assert isinstance(snapshot, ProfileSnapshot)
        assert snapshot.id == newest_id
        assert snapshot.summary_md == "New"


class TestProfilePayload:
    def test_profile_stats_to_payload_is_json_serialisable(
        self, db: DatabaseConnection
    ) -> None:
        card_id = _insert_word_card(db, surface_form="claim")
        _link_error(db, CardType.WORD, card_id, "L01")
        _insert_review_log(
            db,
            CardType.WORD,
            card_id,
            reviewed_at=NOW,
            outcome=ReviewOutcome.FAIL,
        )
        stats = collect_profile_stats(db, as_of=NOW)

        payload = profile_stats_to_payload(stats)

        encoded = json.dumps(payload, ensure_ascii=False)
        assert "L01" in encoded
        assert payload["mastery_counts"]["new"] == 1

    def test_public_dataclasses_expose_fields(self) -> None:
        stat = ErrorTypeStat("G01", "Long subject", 2, 1, 1, 0)
        card = ProfileCardPreview(CardType.SENTENCE, "Preview", days_ago=2)

        assert stat.code == "G01"
        assert card.days_ago == 2
