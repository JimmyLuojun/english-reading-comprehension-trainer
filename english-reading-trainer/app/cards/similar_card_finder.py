"""
Similar card finder.

Surfaces word cards related to a query surface_form via three match layers:
  1. surface  (score 1.0) — case-insensitive exact match on surface_form
  2. lemma    (score 0.8) — spaCy lemma of query matches stored lemma
  3. error_tag(score 0.6) — shared error_type codes via word_card_errors join

Also surfaces sentence cards that share diagnosed sentence error codes with a
current sentence card. Sentence matching intentionally uses only existing
diagnosis data from active translated Review cards; it does not introduce a
second free-text mistake taxonomy.

Cards are deduplicated by card_id; the highest-scoring layer is kept.
Results are ordered by score DESC and truncated to `limit`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db_connection import DatabaseConnection
from app.nlp.english_lemmatizer import lemmatize

_SCORES: dict[str, float] = {"surface": 1.0, "lemma": 0.8, "error_tag": 0.6}
_MIN_SENTENCE_DIAGNOSIS_CONFIDENCE = 0.75
_SENTENCE_CANDIDATE_MULTIPLIER = 4


@dataclass
class SimilarCard:
    card_id: int
    card_type: str       # "word" (sentence cards may be added in future)
    match_layer: str     # "surface" | "lemma" | "error_tag"
    score: float
    surface_form: str
    lemma: str
    current_meaning: str


@dataclass(frozen=True)
class SimilarSentenceMistake:
    card_id: int
    sentence_id: int
    match_layer: str
    score: float
    shared_error_codes: tuple[str, ...]
    sentence_text: str
    user_translation: str
    diagnosis_evidence: tuple[dict[str, str], ...]
    confidence: float


def find_similar_word_cards(
    db: DatabaseConnection,
    surface_form: str,
    *,
    exclude_lemma: str | None = None,
    limit: int = 5,
) -> list[SimilarCard]:
    """
    Find word cards similar to `surface_form` using three match layers.

    exclude_lemma: skip any card whose stored lemma equals this value.
                   Typically set to the lemma of the card being shown so
                   the card doesn't recommend itself.
    """
    surface_form = surface_form.strip()
    if not surface_form:
        return []

    query_lemma = lemmatize(surface_form)
    seen: dict[int, SimilarCard] = {}

    _collect_surface(db, surface_form, exclude_lemma, seen)
    _collect_lemma(db, query_lemma, exclude_lemma, seen)
    _collect_error_tag(db, surface_form, query_lemma, exclude_lemma, seen)

    results = sorted(seen.values(), key=lambda c: -c.score)
    return results[:limit]


def find_similar_cards_for_word_card(
    db: DatabaseConnection,
    card_id: int,
    limit: int = 5,
) -> list[SimilarCard]:
    """
    Convenience wrapper: find similar cards for an existing word card.

    Looks up the card's surface_form and lemma, then delegates to
    find_similar_word_cards with exclude_lemma set to avoid self-matches.

    Raises ValueError if card_id is not found.
    """
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT surface_form, lemma
                 FROM word_cards
                WHERE id = ? AND archived_at IS NULL""",
            (card_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Word card id={card_id} not found.")
    return find_similar_word_cards(
        db,
        row["surface_form"],
        exclude_lemma=row["lemma"],
        limit=limit,
    )


def find_similar_sentence_mistakes(
    db: DatabaseConnection,
    card_id: int,
    limit: int = 3,
) -> list[SimilarSentenceMistake]:
    """
    Find active translated sentence cards with similar diagnosed mistakes.

    The current card and candidate cards must both be valid user-translation
    diagnoses with confidence above the conservative threshold. Candidate cards
    must remain active Review cards and retain a saved user translation.
    """
    if limit <= 0:
        return []

    with db.get_connection() as conn:
        current = conn.execute(
            """SELECT sc.id, sc.user_translation, ac.response_json
                 FROM sentence_cards sc
                 JOIN ai_cache ac ON ac.id = sc.ai_analysis_id
                WHERE sc.id = ?
                  AND sc.archived_at IS NULL
                  AND ac.is_valid = 1""",
            (card_id,),
        ).fetchone()
        if current is None:
            raise ValueError(f"Sentence card id={card_id} not found.")
        if not (current["user_translation"] or "").strip():
            return []

        current_data = _loads_json(current["response_json"])
        if not _is_confident_translation_diagnosis(current_data):
            return []

        error_rows = conn.execute(
            """SELECT sce.error_type_id, et.code
                 FROM sentence_card_errors sce
                 JOIN error_types et ON et.id = sce.error_type_id
                WHERE sce.card_id = ?""",
            (card_id,),
        ).fetchall()
        if not error_rows:
            return []

        error_ids = [row["error_type_id"] for row in error_rows]
        codes_by_id = {row["error_type_id"]: row["code"] for row in error_rows}
        placeholders = ", ".join("?" * len(error_ids))
        rows = conn.execute(
            f"""SELECT sc.id AS card_id, sc.sentence_id, s.text AS sentence_text,
                       sc.user_translation, ac.response_json,
                       GROUP_CONCAT(DISTINCT sce.error_type_id) AS shared_error_ids,
                       COUNT(DISTINCT sce.error_type_id) AS shared_count
                  FROM sentence_cards sc
                  JOIN sentence_card_errors sce ON sce.card_id = sc.id
                  JOIN sentences s ON s.id = sc.sentence_id
                  JOIN ai_cache ac ON ac.id = sc.ai_analysis_id
                 WHERE sce.error_type_id IN ({placeholders})
                   AND sc.id != ?
                   AND sc.archived_at IS NULL
                   AND TRIM(COALESCE(sc.user_translation, '')) != ''
                   AND ac.is_valid = 1
                 GROUP BY sc.id
                 ORDER BY shared_count DESC, ac.created_at DESC, sc.id DESC
                 LIMIT ?""",
            [*error_ids, card_id, max(limit * _SENTENCE_CANDIDATE_MULTIPLIER, limit)],
        ).fetchall()

    results: list[SimilarSentenceMistake] = []
    for row in rows:
        data = _loads_json(row["response_json"])
        if not _is_confident_translation_diagnosis(data):
            continue
        shared_codes = _shared_sentence_codes(row["shared_error_ids"], codes_by_id)
        evidence = _diagnosis_evidence_for_codes(data, shared_codes)
        if not shared_codes or not evidence:
            continue
        score = _SCORES["error_tag"] + 0.1 * (len(shared_codes) - 1)
        results.append(
            SimilarSentenceMistake(
                card_id=row["card_id"],
                sentence_id=row["sentence_id"],
                match_layer="error_tag",
                score=score,
                shared_error_codes=shared_codes,
                sentence_text=row["sentence_text"],
                user_translation=row["user_translation"] or "",
                diagnosis_evidence=evidence,
                confidence=_confidence(data),
            )
        )

    results.sort(key=lambda item: (-item.score, -item.confidence, item.card_id))
    return results[:limit]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _collect_surface(
    db: DatabaseConnection,
    surface_form: str,
    exclude_lemma: str | None,
    seen: dict[int, SimilarCard],
) -> None:
    sql = (
        "SELECT id, surface_form, lemma, current_meaning FROM word_cards"
        " WHERE LOWER(surface_form) = LOWER(?) AND archived_at IS NULL"
    )
    params: list = [surface_form]
    if exclude_lemma is not None:
        sql += " AND lemma != ?"
        params.append(exclude_lemma)
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        _record(seen, row, "surface")


def _collect_lemma(
    db: DatabaseConnection,
    query_lemma: str,
    exclude_lemma: str | None,
    seen: dict[int, SimilarCard],
) -> None:
    sql = (
        "SELECT id, surface_form, lemma, current_meaning FROM word_cards"
        " WHERE lemma = ? AND archived_at IS NULL"
    )
    params: list = [query_lemma]
    if exclude_lemma is not None:
        sql += " AND lemma != ?"
        params.append(exclude_lemma)
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        _record(seen, row, "lemma")


def _collect_error_tag(
    db: DatabaseConnection,
    surface_form: str,
    query_lemma: str,
    exclude_lemma: str | None,
    seen: dict[int, SimilarCard],
) -> None:
    with db.get_connection() as conn:
        query_card = conn.execute(
            "SELECT id FROM word_cards"
            " WHERE (lemma = ? OR LOWER(surface_form) = LOWER(?))"
            " AND archived_at IS NULL"
            " LIMIT 1",
            (query_lemma, surface_form),
        ).fetchone()
        if query_card is None:
            return

        qid = query_card["id"]
        error_rows = conn.execute(
            "SELECT error_type_id FROM word_card_errors WHERE card_id = ?",
            (qid,),
        ).fetchall()
        if not error_rows:
            return

        eid_list = [r["error_type_id"] for r in error_rows]
        placeholders = ", ".join("?" * len(eid_list))
        sql = (
            f"SELECT DISTINCT wc.id, wc.surface_form, wc.lemma, wc.current_meaning"
            f" FROM word_cards wc"
            f" JOIN word_card_errors wce ON wce.card_id = wc.id"
            f" WHERE wce.error_type_id IN ({placeholders})"
            f" AND wc.id != ?"
            f" AND wc.archived_at IS NULL"
        )
        params: list = eid_list + [qid]
        if exclude_lemma is not None:
            sql += " AND wc.lemma != ?"
            params.append(exclude_lemma)
        rows = conn.execute(sql, params).fetchall()

    for row in rows:
        _record(seen, row, "error_tag")


def _record(
    seen: dict[int, SimilarCard], row: object, layer: str
) -> None:
    card_id: int = row["id"]
    score = _SCORES[layer]
    if card_id in seen and seen[card_id].score >= score:
        return
    seen[card_id] = SimilarCard(
        card_id=card_id,
        card_type="word",
        match_layer=layer,
        score=score,
        surface_form=row["surface_form"],
        lemma=row["lemma"],
        current_meaning=row["current_meaning"],
    )


def _loads_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_confident_translation_diagnosis(data: dict[str, Any]) -> bool:
    return (
        data.get("diagnosis_basis") == "user_translation"
        and _confidence(data) >= _MIN_SENTENCE_DIAGNOSIS_CONFIDENCE
    )


def _confidence(data: dict[str, Any]) -> float:
    value = data.get("confidence", 0.0)
    return value if isinstance(value, int | float) else 0.0


def _shared_sentence_codes(
    raw_error_ids: str | None,
    codes_by_id: dict[int, str],
) -> tuple[str, ...]:
    if not raw_error_ids:
        return ()
    codes: list[str] = []
    for raw_id in raw_error_ids.split(","):
        try:
            error_id = int(raw_id)
        except ValueError:
            continue
        code = codes_by_id.get(error_id)
        if code and code not in codes:
            codes.append(code)
    return tuple(sorted(codes))


def _diagnosis_evidence_for_codes(
    data: dict[str, Any],
    error_codes: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    if not error_codes:
        return ()
    wanted = set(error_codes)
    evidence = data.get("diagnosis_evidence", [])
    if not isinstance(evidence, list):
        return ()
    items: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict) or item.get("error_type") not in wanted:
            continue
        items.append(
            {
                "error_type": str(item.get("error_type", "")),
                "evidence": str(item.get("evidence", "")),
            }
        )
    return tuple(items)
