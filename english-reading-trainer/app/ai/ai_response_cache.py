"""
AI response cache backed by the ai_cache SQLite table (§5 of design.md).

Cache key: (content_hash, prompt_version, model)
  content_hash = SHA256(normalize(sentence_text) + "|" + context)

Staleness: if an exact (content_hash, prompt_version, model) hit is not
found, the cache falls back to any entry sharing content_hash + model
(different prompt_version). The caller decides whether to use stale data.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db_connection import DatabaseConnection
from app.nlp.sentence_segmenter import normalize_for_hash


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class CachedEntry:
    cache_id: int
    data: dict            # parsed response JSON
    is_valid: bool
    prompt_version: str   # version stored in DB (may differ from requested)
    is_stale: bool        # True when served from a different prompt_version


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_content_hash(sentence_text: str, context: str = "") -> str:
    """
    SHA256 of the normalised sentence text concatenated with context.
    Matches the cache-key spec in §5.1 of design.md.
    """
    normalised = normalize_for_hash(sentence_text) + "|" + context.strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def get_cached(
    db: DatabaseConnection,
    content_hash: str,
    prompt_version: str,
    model: str,
) -> CachedEntry | None:
    """
    Look up a valid cached entry.

    Priority:
      1. Exact match (content_hash, prompt_version, model) with is_valid=1
      2. Any valid entry with the same (content_hash, model), any prompt_version
         → returned as stale

    Returns None when no valid entry exists at all.
    """
    with db.get_connection() as conn:
        # Exact match
        row = conn.execute(
            """SELECT id, response_json, prompt_version, is_valid
               FROM ai_cache
               WHERE content_hash = ? AND prompt_version = ? AND model = ?
                 AND is_valid = 1""",
            (content_hash, prompt_version, model),
        ).fetchone()
        if row:
            return CachedEntry(
                cache_id=row["id"],
                data=json.loads(row["response_json"]),
                is_valid=True,
                prompt_version=row["prompt_version"],
                is_stale=False,
            )

        # Stale fallback: any valid entry with same content + model
        row = conn.execute(
            """SELECT id, response_json, prompt_version, is_valid
               FROM ai_cache
               WHERE content_hash = ? AND model = ? AND is_valid = 1
               ORDER BY id DESC LIMIT 1""",
            (content_hash, model),
        ).fetchone()
        if row:
            return CachedEntry(
                cache_id=row["id"],
                data=json.loads(row["response_json"]),
                is_valid=True,
                prompt_version=row["prompt_version"],
                is_stale=True,
            )

    return None


def save_to_cache(
    db: DatabaseConnection,
    content_hash: str,
    prompt_version: str,
    model: str,
    response_json: str,
    is_valid: bool,
) -> int:
    """
    Insert a new cache entry. Returns the new row id.

    Uses INSERT OR IGNORE on the UNIQUE(content_hash, prompt_version, model)
    constraint so duplicate saves are silently dropped and the existing id
    is returned instead.
    """
    now = datetime.now(timezone.utc).isoformat()

    with db.get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO ai_cache
               (content_hash, prompt_version, model,
                response_json, is_valid, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content_hash, prompt_version, model,
             response_json, 1 if is_valid else 0, now),
        )
        row = conn.execute(
            """SELECT id FROM ai_cache
               WHERE content_hash = ? AND prompt_version = ? AND model = ?""",
            (content_hash, prompt_version, model),
        ).fetchone()

    return row["id"]
