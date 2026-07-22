"""Reader page data query helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.ai.ai_response_cache import compute_content_hash
from app.db_connection import DatabaseConnection
from app.web.config import _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION
from app.web.queries.analysis import _active_sentence_prompt_version

_CONTEXT_WINDOW = 2
_PARAGRAPH_LOGIC_PROMPT_VERSION = _DEFAULT_PARAGRAPH_LOGIC_PROMPT_VERSION


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
                      COALESCE(st.user_structure, '') AS user_structure,
                      sc.ai_analysis_id,
                      ac.content_hash AS analysis_content_hash,
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
    contexts_by_sentence = _sentence_contexts_for_rows(result)
    paragraph_states = _paragraph_analysis_states_for_rows(db, result)
    for row in result:
        has_analysis = bool(row.get("ai_analysis_id") and row.get("analysis_is_valid"))
        active_version = _active_sentence_prompt_version(
            db,
            row.get("user_translation") or None,
        )
        paragraph_state = paragraph_states.get(int(row["paragraph_id"]), {})
        current_content_hash = compute_content_hash(
            row.get("text") or "",
            contexts_by_sentence.get(int(row["id"]), ""),
            row.get("user_translation") or None,
            row.get("user_structure") or None,
        )
        row["has_analysis"] = 1 if has_analysis else 0
        row["analysis_is_stale"] = (
            1
            if has_analysis
            and (
                row.get("analysis_prompt_version") != active_version
                or row.get("analysis_content_hash") != current_content_hash
            )
            else 0
        )
        row["paragraph_has_analysis"] = 1 if paragraph_state else 0
        row["paragraph_ai_analysis_id"] = paragraph_state.get("cache_id")
        row["paragraph_analysis_is_stale"] = (
            1 if paragraph_state.get("is_stale") else 0
        )
    return result


def _paragraph_analysis_states_for_rows(
    db: DatabaseConnection,
    rows: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    paragraphs = _paragraph_groups_for_rows(rows)
    if not paragraphs:
        return {}

    paragraph_hashes: dict[int, str] = {}
    for index, (paragraph_id, paragraph_rows) in enumerate(paragraphs):
        text = " ".join(
            str(row.get("text") or "").strip() for row in paragraph_rows
        ).strip()
        context_parts = []
        if index > 0:
            previous_text = " ".join(
                str(row.get("text") or "").strip() for row in paragraphs[index - 1][1]
            ).strip()
            if previous_text:
                context_parts.append(f"Previous paragraph: {previous_text}")
        if index + 1 < len(paragraphs):
            next_text = " ".join(
                str(row.get("text") or "").strip() for row in paragraphs[index + 1][1]
            ).strip()
            if next_text:
                context_parts.append(f"Next paragraph: {next_text}")
        paragraph_hashes[paragraph_id] = compute_content_hash(
            text,
            "\n\n".join(context_parts),
        )

    unique_hashes = sorted(set(paragraph_hashes.values()))
    placeholders = ",".join("?" for _ in unique_hashes)
    with db.get_connection() as conn:
        cache_rows = conn.execute(
            f"""SELECT id, content_hash, prompt_version
                  FROM ai_cache
                 WHERE content_hash IN ({placeholders})
                   AND prompt_version LIKE 'paragraph_logic_lens.%'
                   AND is_valid = 1
                 ORDER BY CASE WHEN prompt_version = ? THEN 0 ELSE 1 END,
                          id DESC""",
            (*unique_hashes, _PARAGRAPH_LOGIC_PROMPT_VERSION),
        ).fetchall()

    cache_by_hash: dict[str, dict[str, Any]] = {}
    for row in cache_rows:
        content_hash = row["content_hash"]
        if content_hash in cache_by_hash:
            continue
        cache_by_hash[content_hash] = {
            "cache_id": row["id"],
            "is_stale": row["prompt_version"] != _PARAGRAPH_LOGIC_PROMPT_VERSION,
        }

    return {
        paragraph_id: cache_by_hash[content_hash]
        for paragraph_id, content_hash in paragraph_hashes.items()
        if content_hash in cache_by_hash
    }


def _paragraph_groups_for_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[int, list[dict[str, Any]]]]:
    paragraphs: list[tuple[int, list[dict[str, Any]]]] = []
    current_id: int | None = None
    for row in rows:
        paragraph_id = int(row["paragraph_id"])
        if paragraph_id != current_id:
            paragraphs.append((paragraph_id, []))
            current_id = paragraph_id
        paragraphs[-1][1].append(row)
    return paragraphs


def _sentence_contexts_for_rows(rows: list[dict[str, Any]]) -> dict[int, str]:
    contexts: dict[int, str] = {}
    for index, row in enumerate(rows):
        start = max(0, index - _CONTEXT_WINDOW)
        end = min(len(rows), index + _CONTEXT_WINDOW + 1)
        parts: list[str] = []
        for item in rows[start:end]:
            text = str(item.get("text") or "")
            if item["id"] == row["id"]:
                parts.append(f">>> {text} <<<")
            else:
                parts.append(text)
        contexts[int(row["id"])] = " ".join(parts)
    return contexts


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
            """SELECT wc.id, wc.lemma, wc.surface_form, wc.lexical_type,
                      wc.first_sentence_id, wc.current_meaning, wc.user_note,
                      CASE WHEN ac.id IS NULL THEN 0 ELSE 1 END AS has_analysis,
                      wcs.id AS source_id,
                      wcs.sentence_id AS source_sentence_id,
                      source_sentence.book_id AS source_book_id,
                      wcs.start_offset,
                      wcs.end_offset,
                      wcs.selected_text
                 FROM word_cards wc
                 LEFT JOIN ai_cache ac
                   ON ac.id = wc.ai_analysis_id AND ac.is_valid = 1
                 LEFT JOIN word_card_sources wcs
                   ON wcs.card_id = wc.id
                 LEFT JOIN sentences source_sentence
                   ON source_sentence.id = wcs.sentence_id
                WHERE wc.archived_at IS NULL
                ORDER BY wc.created_at DESC, wcs.is_primary DESC, wcs.created_at ASC, wcs.id ASC"""
        ).fetchall()
    return [dict(row) for row in rows]
