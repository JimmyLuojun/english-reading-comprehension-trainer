"""
Similar card finder.

Surfaces word cards related to a query surface_form via three match layers:
  1. surface  (score 1.0) — case-insensitive exact match on surface_form
  2. lemma    (score 0.8) — spaCy lemma of query matches stored lemma
  3. error_tag(score 0.6) — shared error_type codes via word_card_errors join

Cards are deduplicated by card_id; the highest-scoring layer is kept.
Results are ordered by score DESC and truncated to `limit`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db_connection import DatabaseConnection
from app.nlp.english_lemmatizer import lemmatize

_SCORES: dict[str, float] = {"surface": 1.0, "lemma": 0.8, "error_tag": 0.6}


@dataclass
class SimilarCard:
    card_id: int
    card_type: str       # "word" (sentence cards may be added in future)
    match_layer: str     # "surface" | "lemma" | "error_tag"
    score: float
    surface_form: str
    lemma: str
    current_meaning: str


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
            "SELECT surface_form, lemma FROM word_cards WHERE id = ?", (card_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Word card id={card_id} not found.")
    return find_similar_word_cards(
        db,
        row["surface_form"],
        exclude_lemma=row["lemma"],
        limit=limit,
    )


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
        " WHERE LOWER(surface_form) = LOWER(?)"
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
        " WHERE lemma = ?"
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
            " WHERE lemma = ? OR LOWER(surface_form) = LOWER(?)"
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
