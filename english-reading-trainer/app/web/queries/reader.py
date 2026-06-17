"""Reader page data query helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db_connection import DatabaseConnection
from app.web.queries.analysis import _active_sentence_prompt_version


def _fetch_chapter_sentences(
    db: DatabaseConnection,
    chapter_id: int,
) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT s.id, s.idx, s.text, s.paragraph_id, p.idx AS paragraph_idx,
                      CASE WHEN sc.id IS NULL THEN 0 ELSE 1 END AS has_card,
                      COALESCE(st.user_translation, '') AS user_translation,
                      COALESCE(st.user_note, '') AS user_note,
                      sc.ai_analysis_id,
                      ac.prompt_version AS analysis_prompt_version,
                      ac.model AS analysis_model,
                      COALESCE(ac.is_valid, 0) AS analysis_is_valid
                 FROM sentences s
                 JOIN paragraphs p ON p.id = s.paragraph_id
                 LEFT JOIN sentence_cards sc
                   ON sc.sentence_id = s.id AND sc.archived_at IS NULL
                 LEFT JOIN sentence_cards st
                   ON st.sentence_id = s.id
                 LEFT JOIN ai_cache ac
                   ON ac.id = sc.ai_analysis_id
                WHERE s.chapter_id = ?
                ORDER BY p.idx, s.idx""",
            (chapter_id,),
        ).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        has_analysis = bool(row.get("ai_analysis_id") and row.get("analysis_is_valid"))
        active_version = _active_sentence_prompt_version(
            db,
            row.get("user_translation") or None,
        )
        row["has_analysis"] = 1 if has_analysis else 0
        row["analysis_is_stale"] = (
            1
            if has_analysis and row.get("analysis_prompt_version") != active_version
            else 0
        )
    return result


def _fetch_chapter_blocks(
    db: DatabaseConnection,
    chapter_id: int,
) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT cb.id, cb.book_id, cb.chapter_id, cb.idx, cb.kind,
                      cb.paragraph_id, cb.asset_id, cb.text, cb.payload_json,
                      COALESCE(ba.source_href, '') AS asset_source_href,
                      COALESCE(ba.media_type, '') AS asset_media_type,
                      COALESCE(ba.alt_text, '') AS asset_alt_text,
                      COALESCE(ba.is_missing, 0) AS asset_is_missing
                 FROM chapter_blocks cb
                 LEFT JOIN book_assets ba ON ba.id = cb.asset_id
                WHERE cb.chapter_id = ?
                ORDER BY cb.idx""",
            (chapter_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_book_asset(
    db: DatabaseConnection,
    book_id: int,
    asset_id: int,
) -> dict[str, Any] | None:
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT id, book_id, source_href, media_type, storage_path,
                      is_missing
                 FROM book_assets
                WHERE id = ? AND book_id = ?""",
            (asset_id, book_id),
        ).fetchone()
    return dict(row) if row else None


def _asset_storage_path(db: DatabaseConnection, storage_path: str) -> Path:
    base_dir = Path(getattr(db, "_db_path")).parent / "assets"
    relative = Path(storage_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Asset storage path must be relative")
    candidate = (base_dir / relative).resolve()
    base_resolved = base_dir.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError("Asset storage path escapes asset root") from exc
    return candidate


def _fetch_active_word_cards(db: DatabaseConnection) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, lemma, surface_form, lexical_type, first_sentence_id,
                      current_meaning, user_note
                 FROM word_cards
                WHERE archived_at IS NULL
                ORDER BY created_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]
