"""
SM-2 review scheduler and persistence helpers.

Computes SM-2 transitions, updates sentence/word card review state, and writes
review_logs rows so every review can be audited or replayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import (
    CardType,
    MasteryState,
    OUTCOME_TO_QUALITY,
    ReviewOutcome,
    SM2_MIN_EF,
)


class ReviewInputError(ValueError):
    """Raised when review input cannot be mapped to a valid SM-2 update."""


class ReviewCardNotFoundError(ValueError):
    """Raised when the requested review card does not exist."""


@dataclass(frozen=True)
class ReviewState:
    """SM-2 state for a card at a specific point in time."""

    ef: float
    interval_days: int
    repetitions: int
    mastery_state: MasteryState
    due_at: datetime


@dataclass(frozen=True)
class ReviewResult:
    """Result returned after applying one review to a card."""

    log_id: int
    card_type: CardType
    card_id: int
    reviewed_at: datetime
    outcome: ReviewOutcome
    quality: int
    state_before: ReviewState
    state_after: ReviewState
    review_count_after: int
    latency_ms: int


def next_review_state(
    state_before: ReviewState,
    quality: int,
    *,
    reviewed_at: datetime | None = None,
) -> ReviewState:
    """Return the next SM-2 state for a card without touching the database."""
    _validate_quality(quality)
    reviewed_at = _normalize_datetime(reviewed_at)

    if quality < 3:
        repetitions_after = 0
        interval_after = 1
    else:
        repetitions_after = state_before.repetitions + 1
        if state_before.repetitions == 0:
            interval_after = 1
        elif state_before.repetitions == 1:
            interval_after = 6
        else:
            interval_after = max(1, round(state_before.interval_days * state_before.ef))

    ef_after = _next_ef(state_before.ef, quality)
    mastery_state_after = _derive_mastery_state(
        previous_state=state_before.mastery_state,
        quality=quality,
        ef=ef_after,
        interval_days=interval_after,
        repetitions=repetitions_after,
    )
    return ReviewState(
        ef=ef_after,
        interval_days=interval_after,
        repetitions=repetitions_after,
        mastery_state=mastery_state_after,
        due_at=reviewed_at + timedelta(days=interval_after),
    )


def apply_review(
    db: DatabaseConnection,
    card_type: CardType | str,
    card_id: int,
    outcome: ReviewOutcome | str,
    *,
    latency_ms: int = 0,
    reviewed_at: datetime | None = None,
) -> ReviewResult:
    """
    Apply one review outcome to a sentence or word card.

    Updates the card's SM-2 fields, increments review_count, sets due_at, and
    appends a review_logs row containing before/after state.
    """
    card_type = _coerce_card_type(card_type)
    outcome = _coerce_outcome(outcome)
    reviewed_at = _normalize_datetime(reviewed_at)
    _validate_latency(latency_ms)

    quality = OUTCOME_TO_QUALITY[outcome]
    table_name = _card_table(card_type)

    with db.get_connection() as conn:
        row = conn.execute(
            f"SELECT * FROM {table_name} WHERE id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            raise ReviewCardNotFoundError(
                f"{card_type.value.capitalize()} card id={card_id} not found."
            )

        state_before = _state_from_row(row)
        state_after = next_review_state(
            state_before,
            quality,
            reviewed_at=reviewed_at,
        )
        review_count_after = int(row["review_count"]) + 1

        conn.execute(
            f"""UPDATE {table_name}
                   SET last_reviewed_at = ?,
                       review_count = ?,
                       mastery_state = ?,
                       ef = ?,
                       interval_days = ?,
                       repetitions = ?,
                       due_at = ?
                 WHERE id = ?""",
            (
                reviewed_at.isoformat(),
                review_count_after,
                state_after.mastery_state.value,
                state_after.ef,
                state_after.interval_days,
                state_after.repetitions,
                state_after.due_at.isoformat(),
                card_id,
            ),
        )

        log_id = conn.execute(
            """INSERT INTO review_logs
               (card_type, card_id, reviewed_at, quality, outcome,
                ef_before, ef_after, interval_before, interval_after,
                repetitions_before, repetitions_after, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                card_type.value,
                card_id,
                reviewed_at.isoformat(),
                quality,
                outcome.value,
                state_before.ef,
                state_after.ef,
                state_before.interval_days,
                state_after.interval_days,
                state_before.repetitions,
                state_after.repetitions,
                latency_ms,
            ),
        ).lastrowid

    return ReviewResult(
        log_id=log_id,
        card_type=card_type,
        card_id=card_id,
        reviewed_at=reviewed_at,
        outcome=outcome,
        quality=quality,
        state_before=state_before,
        state_after=state_after,
        review_count_after=review_count_after,
        latency_ms=latency_ms,
    )


def _validate_quality(quality: int) -> None:
    if quality < 0 or quality > 5:
        raise ReviewInputError("quality must be between 0 and 5.")


def _validate_latency(latency_ms: int) -> None:
    if latency_ms < 0:
        raise ReviewInputError("latency_ms must be non-negative.")


def _next_ef(ef: float, quality: int) -> float:
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    return round(max(SM2_MIN_EF, ef + delta), 4)


def _derive_mastery_state(
    *,
    previous_state: MasteryState,
    quality: int,
    ef: float,
    interval_days: int,
    repetitions: int,
) -> MasteryState:
    if quality < 3 and previous_state == MasteryState.MATURE:
        return MasteryState.LAPSED
    if repetitions == 0:
        return MasteryState.NEW
    if repetitions <= 2:
        return MasteryState.LEARNING
    if ef >= 2.0 and interval_days >= 21:
        return MasteryState.MATURE
    return MasteryState.LEARNING


def _coerce_card_type(card_type: CardType | str) -> CardType:
    try:
        return card_type if isinstance(card_type, CardType) else CardType(card_type)
    except ValueError as e:
        raise ReviewInputError("card_type must be 'sentence' or 'word'.") from e


def _coerce_outcome(outcome: ReviewOutcome | str) -> ReviewOutcome:
    try:
        return outcome if isinstance(outcome, ReviewOutcome) else ReviewOutcome(outcome)
    except ValueError as e:
        raise ReviewInputError("outcome must be 'pass', 'partial', or 'fail'.") from e


def _card_table(card_type: CardType) -> str:
    if card_type == CardType.SENTENCE:
        return "sentence_cards"
    return "word_cards"


def _state_from_row(row: Any) -> ReviewState:
    return ReviewState(
        ef=float(row["ef"]),
        interval_days=int(row["interval_days"]),
        repetitions=int(row["repetitions"]),
        mastery_state=MasteryState(row["mastery_state"]),
        due_at=datetime.fromisoformat(row["due_at"]),
    )


def _normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
