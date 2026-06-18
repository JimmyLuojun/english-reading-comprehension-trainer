"""
Daily review queue builder.

Selects due sentence and word cards with the MVP budget rules from design §7.5:
daily limit, new/old split, sentence/word mix, error-code coverage, and a
stable difficulty-first ordering.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import (
    CardType,
    MasteryState,
    QUEUE_DAILY_LIMIT,
    QUEUE_MIN_PER_ERROR_CODE,
    QUEUE_NEW_CARD_SLOTS,
    QUEUE_OLD_CARD_SLOTS,
    QUEUE_TOP_ERROR_CODES,
    ReviewOutcome,
)


@dataclass(frozen=True)
class ReviewQueueItem:
    """One due card selected or considered for the daily review queue."""

    card_type: CardType
    card_id: int
    mastery_state: MasteryState
    ef: float
    interval_days: int
    repetitions: int
    review_count: int
    due_at: datetime
    prompt: str
    answer: str = ""
    ai_meaning: str = ""
    source_book_title: str = ""
    source_href: str = ""
    error_codes: tuple[str, ...] = ()
    last_quality: int | None = None
    last_outcome: ReviewOutcome | None = None

    @property
    def is_new(self) -> bool:
        """Return True only for cards that have never been reviewed."""
        return self.review_count == 0


def list_due_cards(
    db: DatabaseConnection,
    *,
    as_of: datetime | None = None,
    card_type: CardType | str | None = None,
    limit: int | None = None,
) -> list[ReviewQueueItem]:
    """Return due cards across one or both card tables, sorted by priority."""
    as_of = _normalize_datetime(as_of)
    card_types = _card_types(card_type)
    rows: list[Any] = []
    for ctype in card_types:
        rows.extend(_fetch_due_rows(db, ctype, as_of))

    error_codes = _error_codes_for_rows(db, rows)
    items = [_item_from_row(row, error_codes) for row in rows]
    items.sort(key=lambda item: _priority_key(item, ()))
    return items if limit is None else items[:limit]


def build_daily_review_queue(
    db: DatabaseConnection,
    *,
    as_of: datetime | None = None,
    daily_limit: int = QUEUE_DAILY_LIMIT,
    new_card_slots: int = QUEUE_NEW_CARD_SLOTS,
    old_card_slots: int = QUEUE_OLD_CARD_SLOTS,
    top_error_codes: int = QUEUE_TOP_ERROR_CODES,
    min_per_error_code: int = QUEUE_MIN_PER_ERROR_CODE,
) -> list[ReviewQueueItem]:
    """Build the daily mixed queue using the configured budget rules."""
    _validate_budget(daily_limit, new_card_slots, old_card_slots, top_error_codes)
    if daily_limit == 0:
        return []

    candidates = list_due_cards(db, as_of=as_of)
    if not candidates:
        return []

    high_frequency_errors = _top_error_codes(candidates, top_error_codes)
    ordered = sorted(candidates, key=lambda item: _priority_key(item, high_frequency_errors))
    selected: list[ReviewQueueItem] = []
    selected_keys: set[tuple[CardType, int]] = set()

    _add_error_coverage(
        ordered,
        selected,
        selected_keys,
        high_frequency_errors,
        min_per_error_code,
        daily_limit,
    )

    kind_quota = _kind_quotas(daily_limit, new_card_slots, old_card_slots)
    type_quota = _type_quotas(daily_limit)
    _fill_with_quotas(ordered, selected, selected_keys, daily_limit, kind_quota, type_quota)
    _fill_with_type_quota(ordered, selected, selected_keys, daily_limit, type_quota)
    _fill_without_quotas(ordered, selected, selected_keys, daily_limit)
    return selected


def _normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_budget(
    daily_limit: int,
    new_card_slots: int,
    old_card_slots: int,
    top_error_codes: int,
) -> None:
    if daily_limit < 0:
        raise ValueError("daily_limit must be non-negative.")
    if new_card_slots < 0 or old_card_slots < 0:
        raise ValueError("card slot counts must be non-negative.")
    if top_error_codes < 0:
        raise ValueError("top_error_codes must be non-negative.")


def _card_types(card_type: CardType | str | None) -> tuple[CardType, ...]:
    if card_type is None:
        return (CardType.SENTENCE, CardType.WORD)
    try:
        return (card_type if isinstance(card_type, CardType) else CardType(card_type),)
    except ValueError as e:
        raise ValueError("card_type must be 'sentence' or 'word'.") from e


def _fetch_due_rows(
    db: DatabaseConnection,
    card_type: CardType,
    as_of: datetime,
) -> list[Any]:
    if card_type == CardType.SENTENCE:
        sql = _sentence_due_sql()
    else:
        sql = _word_due_sql()
    with db.get_connection() as conn:
        return conn.execute(sql, (as_of.isoformat(),)).fetchall()


def _sentence_due_sql() -> str:
    return """
        SELECT
            'sentence' AS card_type,
            sc.id AS card_id,
            sc.mastery_state,
            sc.ef,
            sc.interval_days,
            sc.repetitions,
            sc.review_count,
            sc.due_at,
            s.text AS prompt,
            COALESCE(sc.user_translation, '') AS answer,
            '' AS ai_meaning,
            COALESCE(b.title, '') AS source_book_title,
            '/read/' || s.book_id || '?chapter=' || c.idx ||
            '&sentence_id=' || s.id || '&panel=analysis#sentence-' || s.id AS source_href,
            (
                SELECT rl.quality FROM review_logs rl
                 WHERE rl.card_type = 'sentence' AND rl.card_id = sc.id
                 ORDER BY rl.reviewed_at DESC, rl.id DESC
                 LIMIT 1
            ) AS last_quality,
            (
                SELECT rl.outcome FROM review_logs rl
                 WHERE rl.card_type = 'sentence' AND rl.card_id = sc.id
                 ORDER BY rl.reviewed_at DESC, rl.id DESC
                 LIMIT 1
            ) AS last_outcome
          FROM sentence_cards sc
          JOIN sentences s ON s.id = sc.sentence_id
          JOIN chapters c ON c.id = s.chapter_id
          JOIN books b ON b.id = s.book_id
         WHERE sc.due_at <= ?
           AND sc.archived_at IS NULL
    """


def _word_due_sql() -> str:
    return """
        SELECT
            'word' AS card_type,
            wc.id AS card_id,
            wc.mastery_state,
            wc.ef,
            wc.interval_days,
            wc.repetitions,
            wc.review_count,
            wc.due_at,
            wc.surface_form AS prompt,
            CASE
                WHEN NULLIF(wc.user_note, '') IS NOT NULL
                 AND wc.user_note != COALESCE(wc.current_meaning, '')
                 AND wc.user_note != COALESCE(json_extract(ac.response_json, '$.meaning_in_context'), '')
                THEN wc.user_note
                ELSE ''
            END AS answer,
            COALESCE(json_extract(ac.response_json, '$.meaning_in_context'), '') AS ai_meaning,
            COALESCE(b.title, '') AS source_book_title,
            CASE
                WHEN s.id IS NULL OR c.idx IS NULL THEN ''
                WHEN wc.ai_analysis_id IS NOT NULL
                  THEN '/read/' || s.book_id || '?chapter=' || c.idx || '&word_card=' || wc.id || '#sentence-' || s.id
                ELSE '/read/' || s.book_id || '?chapter=' || c.idx || '#sentence-' || s.id
            END AS source_href,
            (
                SELECT rl.quality FROM review_logs rl
                 WHERE rl.card_type = 'word' AND rl.card_id = wc.id
                 ORDER BY rl.reviewed_at DESC, rl.id DESC
                 LIMIT 1
            ) AS last_quality,
            (
                SELECT rl.outcome FROM review_logs rl
                 WHERE rl.card_type = 'word' AND rl.card_id = wc.id
                 ORDER BY rl.reviewed_at DESC, rl.id DESC
                 LIMIT 1
            ) AS last_outcome
          FROM word_cards wc
          LEFT JOIN sentences s ON s.id = wc.first_sentence_id
          LEFT JOIN chapters c ON c.id = s.chapter_id
          LEFT JOIN books b ON b.id = s.book_id
          LEFT JOIN ai_cache ac ON ac.id = wc.ai_analysis_id
         WHERE wc.due_at <= ?
           AND wc.archived_at IS NULL
    """


def _error_codes_for_rows(
    db: DatabaseConnection,
    rows: list[Any],
) -> dict[tuple[CardType, int], tuple[str, ...]]:
    sentence_ids = [row["card_id"] for row in rows if row["card_type"] == CardType.SENTENCE.value]
    word_ids = [row["card_id"] for row in rows if row["card_type"] == CardType.WORD.value]
    error_codes: dict[tuple[CardType, int], tuple[str, ...]] = {}
    error_codes.update(_fetch_error_codes(db, CardType.SENTENCE, sentence_ids))
    error_codes.update(_fetch_error_codes(db, CardType.WORD, word_ids))
    return error_codes


def _fetch_error_codes(
    db: DatabaseConnection,
    card_type: CardType,
    card_ids: list[int],
) -> dict[tuple[CardType, int], tuple[str, ...]]:
    if not card_ids:
        return {}

    placeholders = ", ".join("?" * len(card_ids))
    if card_type == CardType.SENTENCE:
        link_table = "sentence_card_errors"
    else:
        link_table = "word_card_errors"

    with db.get_connection() as conn:
        rows = conn.execute(
            f"""SELECT l.card_id, et.code
                  FROM {link_table} l
                  JOIN error_types et ON et.id = l.error_type_id
                 WHERE l.card_id IN ({placeholders})
                 ORDER BY et.code""",
            card_ids,
        ).fetchall()

    grouped: dict[tuple[CardType, int], list[str]] = {}
    for row in rows:
        grouped.setdefault((card_type, row["card_id"]), []).append(row["code"])
    return {key: tuple(values) for key, values in grouped.items()}


def _item_from_row(
    row: Any,
    error_codes: dict[tuple[CardType, int], tuple[str, ...]],
) -> ReviewQueueItem:
    card_type = CardType(row["card_type"])
    card_id = int(row["card_id"])
    last_outcome = row["last_outcome"]
    return ReviewQueueItem(
        card_type=card_type,
        card_id=card_id,
        mastery_state=MasteryState(row["mastery_state"]),
        ef=float(row["ef"]),
        interval_days=int(row["interval_days"]),
        repetitions=int(row["repetitions"]),
        review_count=int(row["review_count"]),
        due_at=datetime.fromisoformat(row["due_at"]),
        prompt=row["prompt"],
        answer=row["answer"] or "",
        ai_meaning=row["ai_meaning"] or "",
        source_book_title=row["source_book_title"] or "",
        source_href=row["source_href"] or "",
        error_codes=error_codes.get((card_type, card_id), ()),
        last_quality=row["last_quality"],
        last_outcome=ReviewOutcome(last_outcome) if last_outcome else None,
    )


def _top_error_codes(
    candidates: list[ReviewQueueItem],
    limit: int,
) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for item in candidates:
        counts.update(item.error_codes)
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return tuple(code for code, _ in ranked[:limit])


def _priority_key(
    item: ReviewQueueItem,
    high_frequency_errors: tuple[str, ...],
) -> tuple[int, float, datetime, str, int]:
    return (
        _priority_bucket(item, high_frequency_errors),
        item.ef,
        item.due_at,
        item.card_type.value,
        item.card_id,
    )


def _priority_bucket(
    item: ReviewQueueItem,
    high_frequency_errors: tuple[str, ...],
) -> int:
    if item.mastery_state == MasteryState.LAPSED:
        return 0
    if item.last_quality is not None and item.last_quality < 3:
        return 0
    if item.last_outcome == ReviewOutcome.PARTIAL or item.last_quality == 3:
        return 1
    if any(code in high_frequency_errors for code in item.error_codes):
        return 2
    return 3


def _add_error_coverage(
    ordered: list[ReviewQueueItem],
    selected: list[ReviewQueueItem],
    selected_keys: set[tuple[CardType, int]],
    high_frequency_errors: tuple[str, ...],
    min_per_error_code: int,
    daily_limit: int,
) -> None:
    if min_per_error_code <= 0:
        return
    for code in high_frequency_errors:
        added_for_code = 0
        for item in ordered:
            if added_for_code >= min_per_error_code or len(selected) >= daily_limit:
                break
            if code not in item.error_codes:
                continue
            if _add_item(item, selected, selected_keys):
                added_for_code += 1


def _fill_with_quotas(
    ordered: list[ReviewQueueItem],
    selected: list[ReviewQueueItem],
    selected_keys: set[tuple[CardType, int]],
    daily_limit: int,
    kind_quota: dict[str, int],
    type_quota: dict[CardType, int],
) -> None:
    for item in ordered:
        if len(selected) >= daily_limit:
            return
        if _item_key(item) in selected_keys:
            continue
        if not _fits_kind_quota(item, selected, kind_quota):
            continue
        if not _fits_type_quota(item, selected, type_quota):
            continue
        _add_item(item, selected, selected_keys)


def _fill_with_type_quota(
    ordered: list[ReviewQueueItem],
    selected: list[ReviewQueueItem],
    selected_keys: set[tuple[CardType, int]],
    daily_limit: int,
    type_quota: dict[CardType, int],
) -> None:
    for item in ordered:
        if len(selected) >= daily_limit:
            return
        if _item_key(item) in selected_keys:
            continue
        if not _fits_type_quota(item, selected, type_quota):
            continue
        _add_item(item, selected, selected_keys)


def _fill_without_quotas(
    ordered: list[ReviewQueueItem],
    selected: list[ReviewQueueItem],
    selected_keys: set[tuple[CardType, int]],
    daily_limit: int,
) -> None:
    for item in ordered:
        if len(selected) >= daily_limit:
            return
        _add_item(item, selected, selected_keys)


def _kind_quotas(
    daily_limit: int,
    new_card_slots: int,
    old_card_slots: int,
) -> dict[str, int]:
    total_slots = new_card_slots + old_card_slots
    if total_slots == 0:
        return {"new": 0, "old": 0}
    if total_slots > daily_limit:
        new_quota = round(daily_limit * (new_card_slots / total_slots))
    else:
        new_quota = new_card_slots
    new_quota = min(new_quota, daily_limit)
    return {"new": new_quota, "old": daily_limit - new_quota}


def _type_quotas(daily_limit: int) -> dict[CardType, int]:
    if daily_limit == 0:
        return {CardType.SENTENCE: 0, CardType.WORD: 0}
    sentence_quota = max(1, daily_limit // 4)
    return {
        CardType.SENTENCE: sentence_quota,
        CardType.WORD: daily_limit - sentence_quota,
    }


def _fits_kind_quota(
    item: ReviewQueueItem,
    selected: list[ReviewQueueItem],
    kind_quota: dict[str, int],
) -> bool:
    key = "new" if item.is_new else "old"
    return sum(1 for existing in selected if existing.is_new == item.is_new) < kind_quota[key]


def _fits_type_quota(
    item: ReviewQueueItem,
    selected: list[ReviewQueueItem],
    type_quota: dict[CardType, int],
) -> bool:
    return sum(1 for existing in selected if existing.card_type == item.card_type) < type_quota[item.card_type]


def _add_item(
    item: ReviewQueueItem,
    selected: list[ReviewQueueItem],
    selected_keys: set[tuple[CardType, int]],
) -> bool:
    key = _item_key(item)
    if key in selected_keys:
        return False
    selected.append(item)
    selected_keys.add(key)
    return True


def _item_key(item: ReviewQueueItem) -> tuple[CardType, int]:
    return (item.card_type, item.card_id)
