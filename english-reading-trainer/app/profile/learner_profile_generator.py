"""
Learner profile statistics, prompt rendering, and snapshot persistence.

Builds the manual-AI profile summary prompt from recent review history and
saves the resulting Markdown into learner_profile_snapshots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db_connection import DatabaseConnection
from app.db_models import (
    PROFILE_DAY_TRIGGER,
    PROFILE_LOOKBACK_DAYS,
    PROFILE_REVIEW_TRIGGER,
    CardType,
    MasteryState,
    ReviewOutcome,
)


_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"
_SNAPSHOT_PREVIEW_CHARS = 80


class ProfileInputError(ValueError):
    """Raised when profile generation input is invalid."""


@dataclass(frozen=True)
class ErrorTypeStat:
    """Aggregated review outcomes for one error code in the lookback window."""

    code: str
    name: str
    occurrences: int
    pass_count: int
    partial_count: int
    fail_count: int


@dataclass(frozen=True)
class ProfileCardPreview:
    """Compact card preview used in profile prompt statistics."""

    card_type: CardType
    content_preview: str
    days_ago: int | None = None


@dataclass(frozen=True)
class ProfileStats:
    """All data needed to render a profile summary prompt."""

    lookback_days: int
    total_reviews: int
    sentence_card_count: int
    word_card_count: int
    mastery_counts: dict[MasteryState, int]
    error_type_stats: tuple[ErrorTypeStat, ...]
    lapsed_cards: tuple[ProfileCardPreview, ...]
    mastered_cards: tuple[ProfileCardPreview, ...]
    period_start: datetime
    period_end: datetime


@dataclass(frozen=True)
class ProfileTriggerStatus:
    """Whether a new learner profile should be generated now."""

    should_generate: bool
    reason: str
    reviews_since_snapshot: int
    days_since_snapshot: int | None
    last_snapshot_at: datetime | None


@dataclass(frozen=True)
class ProfileSnapshot:
    """A saved learner profile snapshot."""

    id: int
    created_at: datetime
    summary_md: str
    payload_json: str
    cards_at_snapshot: int
    sentences_at_snapshot: int


def collect_profile_stats(
    db: DatabaseConnection,
    *,
    lookback_days: int = PROFILE_LOOKBACK_DAYS,
    as_of: datetime | None = None,
) -> ProfileStats:
    """Collect recent review statistics for profile prompt rendering."""
    if lookback_days <= 0:
        raise ProfileInputError("lookback_days must be positive.")

    period_end = _normalize_datetime(as_of)
    period_start = period_end - timedelta(days=lookback_days)

    with db.get_connection() as conn:
        total_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_logs WHERE reviewed_at >= ? AND reviewed_at <= ?",
            (period_start.isoformat(), period_end.isoformat()),
        ).fetchone()[0]

        reviewed_counts = {
            row["card_type"]: row["card_count"]
            for row in conn.execute(
                """SELECT card_type, COUNT(DISTINCT card_id) AS card_count
                     FROM review_logs
                    WHERE reviewed_at >= ? AND reviewed_at <= ?
                    GROUP BY card_type""",
                (period_start.isoformat(), period_end.isoformat()),
            ).fetchall()
        }

        mastery_counts = _fetch_mastery_counts(conn)
        error_stats = _fetch_error_type_stats(conn, period_start, period_end)
        lapsed_cards = _fetch_lapsed_cards(conn, period_start, period_end)
        mastered_cards = _fetch_mastered_cards(conn, period_start, period_end)

    return ProfileStats(
        lookback_days=lookback_days,
        total_reviews=total_reviews,
        sentence_card_count=reviewed_counts.get(CardType.SENTENCE.value, 0),
        word_card_count=reviewed_counts.get(CardType.WORD.value, 0),
        mastery_counts=mastery_counts,
        error_type_stats=error_stats,
        lapsed_cards=_with_days_ago(lapsed_cards, period_end),
        mastered_cards=tuple(card for card, _ in mastered_cards),
        period_start=period_start,
        period_end=period_end,
    )


def build_profile_prompt(
    db: DatabaseConnection,
    *,
    lookback_days: int = PROFILE_LOOKBACK_DAYS,
    as_of: datetime | None = None,
) -> str:
    """Return a rendered profile_summary prompt for manual AI completion."""
    stats = collect_profile_stats(db, lookback_days=lookback_days, as_of=as_of)
    template = _load_prompt("profile_summary", "v1")
    return _render(template, _template_variables(stats))


def get_profile_trigger_status(
    db: DatabaseConnection,
    *,
    as_of: datetime | None = None,
    review_trigger: int = PROFILE_REVIEW_TRIGGER,
    day_trigger: int = PROFILE_DAY_TRIGGER,
) -> ProfileTriggerStatus:
    """
    Return whether a profile is due by review-count or elapsed-day trigger.

    A first profile is due only after enough reviews exist; the elapsed-day
    trigger applies once at least one snapshot has already been saved.
    """
    if review_trigger <= 0:
        raise ProfileInputError("review_trigger must be positive.")
    if day_trigger <= 0:
        raise ProfileInputError("day_trigger must be positive.")

    now = _normalize_datetime(as_of)
    last_snapshot = get_latest_profile_snapshot(db)

    if last_snapshot is None:
        reviews_since = _count_reviews_since(db, None, now)
        should_generate = reviews_since >= review_trigger
        reason = "review_count" if should_generate else "not_due"
        return ProfileTriggerStatus(should_generate, reason, reviews_since, None, None)

    reviews_since = _count_reviews_since(db, last_snapshot.created_at, now)
    days_since = (now - last_snapshot.created_at).days
    if reviews_since >= review_trigger:
        return ProfileTriggerStatus(
            True, "review_count", reviews_since, days_since, last_snapshot.created_at
        )
    if days_since >= day_trigger and _count_reviews_since(db, None, now) > 0:
        return ProfileTriggerStatus(
            True, "elapsed_days", reviews_since, days_since, last_snapshot.created_at
        )
    return ProfileTriggerStatus(
        False, "not_due", reviews_since, days_since, last_snapshot.created_at
    )


def save_profile_snapshot(
    db: DatabaseConnection,
    summary_md: str,
    *,
    payload: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> int:
    """Save a Markdown learner profile summary and return the snapshot id."""
    summary_md = summary_md.strip()
    if not summary_md:
        raise ProfileInputError("summary_md must not be empty.")

    created_at = _normalize_datetime(created_at)
    payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    cards_at_snapshot, sentences_at_snapshot = _snapshot_counts(db)

    with db.get_connection() as conn:
        snapshot_id = conn.execute(
            """INSERT INTO learner_profile_snapshots
               (created_at, summary_md, payload_json, cards_at_snapshot,
                sentences_at_snapshot)
               VALUES (?, ?, ?, ?, ?)""",
            (
                created_at.isoformat(),
                summary_md,
                payload_json,
                cards_at_snapshot,
                sentences_at_snapshot,
            ),
        ).lastrowid
    return snapshot_id


def get_latest_profile_snapshot(db: DatabaseConnection) -> ProfileSnapshot | None:
    """Return the newest saved learner profile snapshot, or None."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT *
                 FROM learner_profile_snapshots
                ORDER BY created_at DESC, id DESC
                LIMIT 1"""
        ).fetchone()
    return _snapshot_from_row(row) if row else None


def profile_stats_to_payload(stats: ProfileStats) -> dict[str, Any]:
    """Return a JSON-serialisable payload for audit/debug storage."""
    return {
        "lookback_days": stats.lookback_days,
        "total_reviews": stats.total_reviews,
        "sentence_card_count": stats.sentence_card_count,
        "word_card_count": stats.word_card_count,
        "mastery_counts": {
            state.value: stats.mastery_counts.get(state, 0)
            for state in MasteryState
        },
        "error_type_stats": [
            {
                "code": stat.code,
                "name": stat.name,
                "occurrences": stat.occurrences,
                "pass_count": stat.pass_count,
                "partial_count": stat.partial_count,
                "fail_count": stat.fail_count,
            }
            for stat in stats.error_type_stats
        ],
        "lapsed_cards": [
            {
                "card_type": card.card_type.value,
                "content_preview": card.content_preview,
                "days_ago": card.days_ago,
            }
            for card in stats.lapsed_cards
        ],
        "mastered_cards": [
            {
                "card_type": card.card_type.value,
                "content_preview": card.content_preview,
            }
            for card in stats.mastered_cards
        ],
        "period_start": stats.period_start.isoformat(),
        "period_end": stats.period_end.isoformat(),
    }


def _fetch_mastery_counts(conn: Any) -> dict[MasteryState, int]:
    counts = {state: 0 for state in MasteryState}
    for table_name in ("sentence_cards", "word_cards"):
        rows = conn.execute(
            f"""SELECT mastery_state, COUNT(*) AS state_count
                  FROM {table_name}
                 WHERE archived_at IS NULL
                 GROUP BY mastery_state"""
        ).fetchall()
        for row in rows:
            counts[MasteryState(row["mastery_state"])] += row["state_count"]
    return counts


def _fetch_error_type_stats(
    conn: Any,
    period_start: datetime,
    period_end: datetime,
) -> tuple[ErrorTypeStat, ...]:
    rows = conn.execute(
        """SELECT et.code, et.name,
                  COUNT(*) AS occurrences,
                  SUM(CASE WHEN rl.outcome = 'pass' THEN 1 ELSE 0 END) AS pass_count,
                  SUM(CASE WHEN rl.outcome = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                  SUM(CASE WHEN rl.outcome = 'fail' THEN 1 ELSE 0 END) AS fail_count
             FROM review_logs rl
             JOIN sentence_card_errors sce
               ON rl.card_type = 'sentence' AND sce.card_id = rl.card_id
             JOIN sentence_cards sc ON sc.id = rl.card_id
             JOIN error_types et ON et.id = sce.error_type_id
            WHERE rl.reviewed_at >= ? AND rl.reviewed_at <= ?
              AND sc.archived_at IS NULL
            GROUP BY et.code, et.name
            UNION ALL
           SELECT et.code, et.name,
                  COUNT(*) AS occurrences,
                  SUM(CASE WHEN rl.outcome = 'pass' THEN 1 ELSE 0 END) AS pass_count,
                  SUM(CASE WHEN rl.outcome = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                  SUM(CASE WHEN rl.outcome = 'fail' THEN 1 ELSE 0 END) AS fail_count
             FROM review_logs rl
             JOIN word_card_errors wce
               ON rl.card_type = 'word' AND wce.card_id = rl.card_id
             JOIN word_cards wc ON wc.id = rl.card_id
             JOIN error_types et ON et.id = wce.error_type_id
            WHERE rl.reviewed_at >= ? AND rl.reviewed_at <= ?
              AND wc.archived_at IS NULL
            GROUP BY et.code, et.name""",
        (
            period_start.isoformat(),
            period_end.isoformat(),
            period_start.isoformat(),
            period_end.isoformat(),
        ),
    ).fetchall()

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = merged.setdefault(
            row["code"],
            {
                "name": row["name"],
                "occurrences": 0,
                "pass_count": 0,
                "partial_count": 0,
                "fail_count": 0,
            },
        )
        current["occurrences"] += row["occurrences"] or 0
        current["pass_count"] += row["pass_count"] or 0
        current["partial_count"] += row["partial_count"] or 0
        current["fail_count"] += row["fail_count"] or 0

    ranked = sorted(
        merged.items(),
        key=lambda pair: (-pair[1]["occurrences"], pair[0]),
    )
    return tuple(
        ErrorTypeStat(
            code=code,
            name=data["name"],
            occurrences=data["occurrences"],
            pass_count=data["pass_count"],
            partial_count=data["partial_count"],
            fail_count=data["fail_count"],
        )
        for code, data in ranked
    )


def _fetch_lapsed_cards(
    conn: Any,
    period_start: datetime,
    period_end: datetime,
) -> tuple[tuple[ProfileCardPreview, datetime], ...]:
    rows = conn.execute(
        """SELECT 'sentence' AS card_type, s.text AS content, rl.reviewed_at
             FROM sentence_cards sc
            JOIN sentences s ON s.id = sc.sentence_id
            JOIN review_logs rl ON rl.card_type = 'sentence' AND rl.card_id = sc.id
            WHERE sc.mastery_state = 'lapsed'
              AND sc.archived_at IS NULL
              AND rl.quality < 3
              AND rl.reviewed_at >= ? AND rl.reviewed_at <= ?
            UNION ALL
           SELECT 'word' AS card_type, wc.surface_form AS content, rl.reviewed_at
             FROM word_cards wc
             JOIN review_logs rl ON rl.card_type = 'word' AND rl.card_id = wc.id
            WHERE wc.mastery_state = 'lapsed'
              AND wc.archived_at IS NULL
              AND rl.quality < 3
              AND rl.reviewed_at >= ? AND rl.reviewed_at <= ?
            ORDER BY reviewed_at DESC
            LIMIT 10""",
        (
            period_start.isoformat(),
            period_end.isoformat(),
            period_start.isoformat(),
            period_end.isoformat(),
        ),
    ).fetchall()
    return tuple(
        (
            ProfileCardPreview(
                card_type=CardType(row["card_type"]),
                content_preview=_preview(row["content"]),
            ),
            datetime.fromisoformat(row["reviewed_at"]),
        )
        for row in rows
    )


def _fetch_mastered_cards(
    conn: Any,
    period_start: datetime,
    period_end: datetime,
) -> tuple[tuple[ProfileCardPreview, datetime], ...]:
    rows = conn.execute(
        """SELECT 'sentence' AS card_type, s.text AS content, rl.reviewed_at
             FROM sentence_cards sc
            JOIN sentences s ON s.id = sc.sentence_id
            JOIN review_logs rl ON rl.card_type = 'sentence' AND rl.card_id = sc.id
            WHERE sc.mastery_state = 'mature'
              AND sc.archived_at IS NULL
              AND rl.quality >= 3
              AND rl.reviewed_at >= ? AND rl.reviewed_at <= ?
            UNION ALL
           SELECT 'word' AS card_type, wc.surface_form AS content, rl.reviewed_at
             FROM word_cards wc
             JOIN review_logs rl ON rl.card_type = 'word' AND rl.card_id = wc.id
            WHERE wc.mastery_state = 'mature'
              AND wc.archived_at IS NULL
              AND rl.quality >= 3
              AND rl.reviewed_at >= ? AND rl.reviewed_at <= ?
            ORDER BY reviewed_at DESC
            LIMIT 10""",
        (
            period_start.isoformat(),
            period_end.isoformat(),
            period_start.isoformat(),
            period_end.isoformat(),
        ),
    ).fetchall()
    return tuple(
        (
            ProfileCardPreview(
                card_type=CardType(row["card_type"]),
                content_preview=_preview(row["content"]),
            ),
            datetime.fromisoformat(row["reviewed_at"]),
        )
        for row in rows
    )


def _with_days_ago(
    cards: tuple[tuple[ProfileCardPreview, datetime], ...],
    as_of: datetime,
) -> tuple[ProfileCardPreview, ...]:
    return tuple(
        ProfileCardPreview(
            card_type=card.card_type,
            content_preview=card.content_preview,
            days_ago=max(0, (as_of - reviewed_at).days),
        )
        for card, reviewed_at in cards
    )


def _template_variables(stats: ProfileStats) -> dict[str, str]:
    return {
        "lookback_days": str(stats.lookback_days),
        "total_reviews": str(stats.total_reviews),
        "sentence_card_count": str(stats.sentence_card_count),
        "word_card_count": str(stats.word_card_count),
        "new_count": str(stats.mastery_counts.get(MasteryState.NEW, 0)),
        "learning_count": str(stats.mastery_counts.get(MasteryState.LEARNING, 0)),
        "mature_count": str(stats.mastery_counts.get(MasteryState.MATURE, 0)),
        "lapsed_count": str(stats.mastery_counts.get(MasteryState.LAPSED, 0)),
        "error_type_stats": _format_error_type_stats(stats.error_type_stats),
        "lapsed_cards": _format_lapsed_cards(stats.lapsed_cards),
        "mastered_cards": _format_mastered_cards(stats.mastered_cards),
    }


def _format_error_type_stats(stats: tuple[ErrorTypeStat, ...]) -> str:
    if not stats:
        return "  (none)"
    return "\n".join(
        "  "
        f"{stat.code} — {stat.name} — {stat.occurrences} occurrences — "
        "outcome breakdown: "
        f"pass {stat.pass_count} / partial {stat.partial_count} / fail {stat.fail_count}"
        for stat in stats
    )


def _format_lapsed_cards(cards: tuple[ProfileCardPreview, ...]) -> str:
    if not cards:
        return "  (none)"
    return "\n".join(
        f"  {card.card_type.value} — {card.content_preview} — "
        f"lapsed {card.days_ago} days ago"
        for card in cards
    )


def _format_mastered_cards(cards: tuple[ProfileCardPreview, ...]) -> str:
    if not cards:
        return "  (none)"
    return "\n".join(
        f"  {card.card_type.value} — {card.content_preview}"
        for card in cards
    )


def _count_reviews_since(
    db: DatabaseConnection,
    since: datetime | None,
    until: datetime,
) -> int:
    with db.get_connection() as conn:
        if since is None:
            return conn.execute(
                "SELECT COUNT(*) FROM review_logs WHERE reviewed_at <= ?",
                (until.isoformat(),),
            ).fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM review_logs WHERE reviewed_at > ? AND reviewed_at <= ?",
            (since.isoformat(), until.isoformat()),
        ).fetchone()[0]


def _snapshot_counts(db: DatabaseConnection) -> tuple[int, int]:
    with db.get_connection() as conn:
        sentence_cards = conn.execute(
            "SELECT COUNT(*) FROM sentence_cards WHERE archived_at IS NULL"
        ).fetchone()[0]
        word_cards = conn.execute(
            "SELECT COUNT(*) FROM word_cards WHERE archived_at IS NULL"
        ).fetchone()[0]
        sentences = conn.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]
    return sentence_cards + word_cards, sentences


def _snapshot_from_row(row: Any) -> ProfileSnapshot:
    return ProfileSnapshot(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        summary_md=row["summary_md"],
        payload_json=row["payload_json"],
        cards_at_snapshot=row["cards_at_snapshot"],
        sentences_at_snapshot=row["sentences_at_snapshot"],
    )


def _load_prompt(name: str, version: str) -> str:
    path = _PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    return text[end + 3:].lstrip("\n") if end != -1 else text


def _render(template: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        template = template.replace(f"{{{{ {key} }}}}", value)
    return template


def _preview(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _SNAPSHOT_PREVIEW_CHARS:
        return one_line
    return one_line[: _SNAPSHOT_PREVIEW_CHARS - 3] + "..."


def _normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
