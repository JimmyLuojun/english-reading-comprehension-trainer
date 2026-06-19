"""
Tests for app/ai/ai_response_cache.py  — 100% line + branch coverage required.

Uses real SQLite (tmp_path). No mocking.

Covers every public function and every branch:
  compute_content_hash: same/different input, normalisation
  get_cached: exact hit, stale hit, no hit, is_valid=0 skipped
  save_to_cache: new entry, duplicate key (idempotent)
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.ai.ai_response_cache import (
    CachedEntry,
    compute_content_hash,
    get_cached,
    save_to_cache,
)
from app.db_connection import DatabaseConnection
from app.nlp.sentence_segmenter import normalize_for_hash

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

_SAMPLE_RESPONSE = json.dumps({"subject_skeleton": "The cat sat", "confidence": 0.9})
_MODEL = "gpt-4o-mini"
_PROMPT_V1 = "v1"
_PROMPT_V2 = "v2"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


# ---------------------------------------------------------------------------
# compute_content_hash — 100% branch coverage
# ---------------------------------------------------------------------------

class TestComputeContentHash:
    def test_returns_64_char_hex(self) -> None:
        h = compute_content_hash("Hello world.", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_inputs_same_hash(self) -> None:
        assert (
            compute_content_hash("Hello world.", "some context")
            == compute_content_hash("Hello world.", "some context")
        )

    def test_different_sentences_different_hash(self) -> None:
        assert (
            compute_content_hash("Cat sat.", "")
            != compute_content_hash("Dog ran.", "")
        )

    def test_different_context_different_hash(self) -> None:
        assert (
            compute_content_hash("Hello.", "context A")
            != compute_content_hash("Hello.", "context B")
        )

    def test_different_user_translation_different_hash(self) -> None:
        assert (
            compute_content_hash("Hello.", "context", "你好。")
            != compute_content_hash("Hello.", "context", "您好。")
        )

    def test_translation_is_normalized(self) -> None:
        assert (
            compute_content_hash("Hello.", "", "  你好   世界  ")
            == compute_content_hash("Hello.", "", "你好 世界")
        )

    def test_empty_structure_preserves_legacy_hash(self) -> None:
        assert (
            compute_content_hash("Hello.", "context", "你好。")
            == compute_content_hash("Hello.", "context", "你好。", "")
            == compute_content_hash("Hello.", "context", "你好。", "   ")
        )

    def test_non_empty_structure_changes_hash(self) -> None:
        assert (
            compute_content_hash("Hello.", "context", "你好。")
            != compute_content_hash("Hello.", "context", "你好。", "主干：Hello")
        )

    def test_structure_is_normalized(self) -> None:
        assert (
            compute_content_hash("Hello.", "", None, "  主干：Hello   world  ")
            == compute_content_hash("Hello.", "", None, "主干：Hello world")
        )

    def test_case_insensitive_sentence(self) -> None:
        # normalize_for_hash lowercases, so these should be equal
        assert (
            compute_content_hash("Hello World.", "")
            == compute_content_hash("hello world.", "")
        )

    def test_empty_context_handled(self) -> None:
        h = compute_content_hash("A sentence.", "")
        assert isinstance(h, str) and len(h) == 64

    def test_no_context_arg_defaults_to_empty(self) -> None:
        assert (
            compute_content_hash("A sentence.")
            == compute_content_hash("A sentence.", "")
        )

    def test_hash_matches_manual_sha256(self) -> None:
        sentence, context, translation = "The cat sat.", "prev sentence", "猫坐着。"
        normalised = (
            normalize_for_hash(sentence)
            + "|"
            + context.strip()
            + "|"
            + normalize_for_hash(translation)
        )
        expected = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
        assert compute_content_hash(sentence, context, translation) == expected

    def test_hash_with_structure_matches_manual_sha256(self) -> None:
        sentence = "The cat sat."
        context = "prev sentence"
        translation = "猫坐着。"
        structure = "主干：The cat sat"
        normalised = (
            normalize_for_hash(sentence)
            + "|"
            + context.strip()
            + "|"
            + normalize_for_hash(translation)
            + "|"
            + normalize_for_hash(structure)
        )
        expected = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
        assert compute_content_hash(sentence, context, translation, structure) == expected


# ---------------------------------------------------------------------------
# save_to_cache — 100% branch coverage
# ---------------------------------------------------------------------------

class TestSaveToCache:
    def test_returns_integer_id(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("sentence one.")
        cid = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        assert isinstance(cid, int) and cid > 0

    def test_row_inserted_in_db(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("sentence two.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_cache WHERE content_hash = ?", (h,)
            ).fetchone()
        assert row is not None

    def test_is_valid_true_stored(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("sentence three.")
        cid = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (cid,)
            ).fetchone()
        assert row["is_valid"] == 1

    def test_is_valid_false_stored(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("sentence four.")
        cid = save_to_cache(db, h, _PROMPT_V1, _MODEL, "invalid raw text", False)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT is_valid FROM ai_cache WHERE id = ?", (cid,)
            ).fetchone()
        assert row["is_valid"] == 0

    def test_duplicate_key_returns_existing_id(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("duplicate sentence.")
        cid1 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        cid2 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        assert cid1 == cid2

    def test_duplicate_does_not_create_extra_row(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("dup row check.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        with db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM ai_cache WHERE content_hash = ?", (h,)
            ).fetchone()[0]
        assert count == 1

    def test_valid_response_replaces_existing_invalid_row(
        self,
        db: DatabaseConnection,
    ) -> None:
        h = compute_content_hash("invalid then valid.")
        cid1 = save_to_cache(db, h, _PROMPT_V1, _MODEL, "bad json", False)
        cid2 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)

        assert cid1 == cid2
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is not None
        assert result.is_valid is True
        assert result.data == json.loads(_SAMPLE_RESPONSE)

    def test_invalid_response_does_not_replace_existing_valid_row(
        self,
        db: DatabaseConnection,
    ) -> None:
        h = compute_content_hash("valid then invalid.")
        cid1 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        cid2 = save_to_cache(db, h, _PROMPT_V1, _MODEL, "bad json", False)

        assert cid1 == cid2
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is not None
        assert result.is_valid is True
        assert result.data == json.loads(_SAMPLE_RESPONSE)

    def test_replace_valid_updates_existing_valid_row(
        self,
        db: DatabaseConnection,
    ) -> None:
        h = compute_content_hash("force refreshed sentence.")
        updated_response = json.dumps({"subject_skeleton": "The dog ran", "confidence": 0.8})
        cid1 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        cid2 = save_to_cache(
            db,
            h,
            _PROMPT_V1,
            _MODEL,
            updated_response,
            True,
            replace_valid=True,
        )

        assert cid1 == cid2
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is not None
        assert result.data == json.loads(updated_response)

    def test_replace_valid_does_not_let_invalid_response_replace_valid_row(
        self,
        db: DatabaseConnection,
    ) -> None:
        h = compute_content_hash("force refreshed invalid sentence.")
        cid1 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        cid2 = save_to_cache(
            db,
            h,
            _PROMPT_V1,
            _MODEL,
            "bad json",
            False,
            replace_valid=True,
        )

        assert cid1 == cid2
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is not None
        assert result.data == json.loads(_SAMPLE_RESPONSE)

    def test_different_prompt_version_creates_new_row(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("version test sentence.")
        cid1 = save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        cid2 = save_to_cache(db, h, _PROMPT_V2, _MODEL, _SAMPLE_RESPONSE, True)
        assert cid1 != cid2


# ---------------------------------------------------------------------------
# get_cached — 100% branch coverage
# ---------------------------------------------------------------------------

class TestGetCached:
    def test_exact_hit_returns_entry(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("exact match sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is not None
        assert isinstance(result, CachedEntry)

    def test_exact_hit_is_not_stale(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("fresh sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result.is_stale is False

    def test_exact_hit_data_matches(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("data match sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result.data == json.loads(_SAMPLE_RESPONSE)

    def test_stale_hit_when_different_version(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("stale version sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        # Request v2 which doesn't exist — should get stale v1 back
        result = get_cached(db, h, _PROMPT_V2, _MODEL)
        assert result is not None
        assert result.is_stale is True
        assert result.prompt_version == _PROMPT_V1

    def test_stale_hit_when_exact_version_exists_prefers_exact(
        self, db: DatabaseConnection
    ) -> None:
        h = compute_content_hash("prefer exact sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        save_to_cache(db, h, _PROMPT_V2, _MODEL, _SAMPLE_RESPONSE, True)
        # Requesting v2 should get exact v2, not stale v1
        result = get_cached(db, h, _PROMPT_V2, _MODEL)
        assert result.is_stale is False
        assert result.prompt_version == _PROMPT_V2

    def test_no_hit_returns_none(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("nonexistent sentence.")
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is None

    def test_invalid_entry_not_returned_as_exact(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("invalid entry sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, "bad json", False)
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert result is None

    def test_invalid_entry_not_returned_as_stale(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("invalid stale sentence.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, "bad json", False)
        result = get_cached(db, h, _PROMPT_V2, _MODEL)
        assert result is None

    def test_cache_id_is_integer(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("cache id check.")
        save_to_cache(db, h, _PROMPT_V1, _MODEL, _SAMPLE_RESPONSE, True)
        result = get_cached(db, h, _PROMPT_V1, _MODEL)
        assert isinstance(result.cache_id, int)

    def test_different_model_not_returned(self, db: DatabaseConnection) -> None:
        h = compute_content_hash("model mismatch sentence.")
        save_to_cache(db, h, _PROMPT_V1, "gpt-4o", _SAMPLE_RESPONSE, True)
        result = get_cached(db, h, _PROMPT_V1, "gpt-3.5-turbo")
        assert result is None
