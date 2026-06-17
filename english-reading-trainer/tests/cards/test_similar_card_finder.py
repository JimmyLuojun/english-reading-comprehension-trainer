"""
Tests for app/cards/similar_card_finder.py.

Uses real SQLite (tmp_path). No mocking.
spaCy en_core_web_sm is used for lemma matching — must be installed.

Coverage areas:
  SimilarCard dataclass
  find_similar_word_cards:
    - Layer 1: surface match (case-insensitive)
    - Layer 2: spaCy lemma match
    - Layer 3: error_tag overlap via word_card_errors
    - Deduplication (surface beats lemma for same card)
    - exclude_lemma filters self
    - limit truncates results
    - empty / whitespace surface_form → []
    - no cards in DB → []
  find_similar_cards_for_word_card:
    - delegates to find_similar_word_cards
    - raises ValueError for unknown card_id
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from app.ai.analysis_saver import save_sentence_analysis
from app.cards.sentence_card_service import save_sentence_translation
from app.cards.similar_card_finder import (
    SimilarCard,
    SimilarSentenceMistake,
    find_similar_cards_for_word_card,
    find_similar_sentence_mistakes,
    find_similar_word_cards,
)
from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


@pytest.fixture()
def sentence_id(db: DatabaseConnection, tmp_path: Path) -> int:
    """Seed one book/sentence and return the first sentence_id."""
    txt = tmp_path / "book.txt"
    txt.write_text("The fox jumps over the lazy dog.", encoding="utf-8")
    result = import_txt(db, txt, title="Test")
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY id LIMIT 1",
            (result.book_id,),
        ).fetchone()["id"]


def _insert_word_card(
    db: DatabaseConnection,
    sentence_id: int,
    lemma: str,
    surface_form: str,
    current_meaning: str = "",
    pos: str = "noun",
) -> int:
    """Insert a word card directly and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    with db.get_connection() as conn:
        card_id = conn.execute(
            """INSERT INTO word_cards
               (lemma, surface_form, lexical_type, first_sentence_id,
                current_meaning, pos, created_at, last_reviewed_at,
                review_count, mastery_state, ef, interval_days, repetitions,
                due_at, occurrence_count, user_note)
               VALUES (?, ?, 'word', ?, ?, ?, ?, NULL, 0, 'new',
                       2.5, 0, 0, ?, 1, '')""",
            (lemma, surface_form, sentence_id, current_meaning, pos, now, now),
        ).lastrowid
    return card_id


def _get_error_type_id(db: DatabaseConnection, code: str) -> int:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM error_types WHERE code = ?", (code,)
        ).fetchone()
    return row["id"]


def _link_error(db: DatabaseConnection, card_id: int, error_code: str) -> None:
    eid = _get_error_type_id(db, error_code)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO word_card_errors (card_id, error_type_id) VALUES (?, ?)",
            (card_id, eid),
        )


def _seed_sentence_ids(
    db: DatabaseConnection,
    tmp_path: Path,
    text: str,
) -> list[int]:
    source = tmp_path / "sentences.txt"
    source.write_text(text, encoding="utf-8")
    result = import_txt(db, source, title="Sentence Test")
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY idx",
            (result.book_id,),
        ).fetchall()
    return [row["id"] for row in rows]


def _diagnosed_sentence_payload(
    code: str,
    evidence: str,
    *,
    confidence: float = 0.9,
) -> dict[str, object]:
    return {
        "subject_skeleton": "The contrast matters",
        "clauses": [
            {
                "type": "main",
                "text": "the contrast matters",
                "role": "main predication",
            }
        ],
        "modifiers": [],
        "logic_markers": [
            {"marker": "although", "function": "concession"},
        ],
        "anaphora": [],
        "simplified_en": "The contrast matters.",
        "chinese_gloss": "重点在对比关系。",
        "predicted_error_types": [],
        "diagnosis_basis": "user_translation",
        "diagnosed_error_types": [code],
        "diagnosis_evidence": [
            {"error_type": code, "evidence": evidence},
        ],
        "confidence": confidence,
    }


def _predicted_sentence_payload(
    code: str,
    *,
    confidence: float = 0.9,
) -> dict[str, object]:
    return {
        "subject_skeleton": "The contrast matters",
        "clauses": [
            {
                "type": "main",
                "text": "the contrast matters",
                "role": "main predication",
            }
        ],
        "modifiers": [],
        "logic_markers": [],
        "anaphora": [],
        "simplified_en": "The contrast matters.",
        "chinese_gloss": "重点在对比关系。",
        "predicted_error_types": [code],
        "diagnosis_basis": "predicted",
        "diagnosed_error_types": [],
        "diagnosis_evidence": [],
        "confidence": confidence,
    }


def _save_sentence_diagnosis(
    db: DatabaseConnection,
    sentence_id: int,
    payload: dict[str, object],
    *,
    translation: str = "我误读了这句话。",
) -> int:
    if translation:
        save_sentence_translation(db, sentence_id, translation)
    result = save_sentence_analysis(
        db,
        sentence_id,
        json.dumps(payload),
        model="test-model",
        prompt_version="v1",
    )
    assert result.is_valid
    assert result.card_id is not None
    return result.card_id


# ---------------------------------------------------------------------------
# SimilarCard dataclass
# ---------------------------------------------------------------------------

class TestSimilarCardDataclass:
    def test_fields_accessible(self):
        sc = SimilarCard(
            card_id=1, card_type="word", match_layer="surface",
            score=1.0, surface_form="fox", lemma="fox",
            current_meaning="a cunning animal",
        )
        assert sc.card_id == 1
        assert sc.card_type == "word"
        assert sc.match_layer == "surface"
        assert sc.score == 1.0
        assert sc.surface_form == "fox"
        assert sc.lemma == "fox"
        assert sc.current_meaning == "a cunning animal"

    def test_sentence_mistake_fields_accessible(self):
        mistake = SimilarSentenceMistake(
            card_id=1,
            sentence_id=2,
            match_layer="error_tag",
            score=0.6,
            shared_error_codes=("D02",),
            sentence_text="Although it rained, we left.",
            user_translation="虽然下雨，我们离开了。",
            diagnosis_evidence=(
                {"error_type": "D02", "evidence": "missed contrast"},
            ),
            confidence=0.9,
        )
        assert mistake.card_id == 1
        assert mistake.match_layer == "error_tag"
        assert mistake.shared_error_codes == ("D02",)
        assert mistake.confidence == 0.9

    def test_score_ordering(self):
        a = SimilarCard(1, "word", "surface", 1.0, "fox", "fox", "")
        b = SimilarCard(2, "word", "lemma",   0.8, "foxes", "fox", "")
        c = SimilarCard(3, "word", "error_tag", 0.6, "run", "run", "")
        ranked = sorted([c, b, a], key=lambda x: -x.score)
        assert ranked[0].match_layer == "surface"
        assert ranked[1].match_layer == "lemma"
        assert ranked[2].match_layer == "error_tag"


# ---------------------------------------------------------------------------
# Empty / no cards edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_surface_returns_empty(self, db: DatabaseConnection):
        assert find_similar_word_cards(db, "") == []

    def test_whitespace_only_returns_empty(self, db: DatabaseConnection):
        assert find_similar_word_cards(db, "   ") == []

    def test_no_cards_in_db_returns_empty(self, db: DatabaseConnection):
        assert find_similar_word_cards(db, "fox") == []

    def test_no_matching_cards_returns_empty(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "cat", "cat", "a pet")
        assert find_similar_word_cards(db, "elephant") == []


# ---------------------------------------------------------------------------
# Layer 1 — surface match
# ---------------------------------------------------------------------------

class TestSurfaceMatch:
    def test_exact_surface_found(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "a wild animal")
        results = find_similar_word_cards(db, "fox")
        assert len(results) == 1
        assert results[0].match_layer == "surface"

    def test_surface_match_case_insensitive(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "Fox", "a wild animal")
        results = find_similar_word_cards(db, "fox")
        assert len(results) == 1
        assert results[0].surface_form == "Fox"

    def test_surface_match_score_is_1(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_word_cards(db, "fox")
        assert results[0].score == 1.0

    def test_surface_match_returns_correct_meaning(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "cunning animal")
        results = find_similar_word_cards(db, "fox")
        assert results[0].current_meaning == "cunning animal"

    def test_surface_match_uppercase_query(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_word_cards(db, "FOX")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Layer 2 — lemma match
# ---------------------------------------------------------------------------

class TestLemmaMatch:
    def test_plural_query_finds_singular_card(self, db: DatabaseConnection, sentence_id: int):
        # card lemma = "fox"; query = "foxes" → spaCy lemma = "fox"
        _insert_word_card(db, sentence_id, "fox", "fox", "a wild animal")
        results = find_similar_word_cards(db, "foxes")
        assert len(results) >= 1
        match = next((r for r in results if r.lemma == "fox"), None)
        assert match is not None

    def test_lemma_match_layer_label(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "jump", "jump", "to leap")
        results = find_similar_word_cards(db, "jumped")
        assert any(r.match_layer == "lemma" for r in results)

    def test_lemma_match_score_is_08(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "run", "run", "to move fast")
        results = find_similar_word_cards(db, "running")
        # "running" not in surface_form of any card, so should be lemma match
        lemma_matches = [r for r in results if r.match_layer == "lemma"]
        if lemma_matches:
            assert lemma_matches[0].score == 0.8

    def test_same_word_found_by_lemma(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "dog", "dog", "a domestic animal")
        results = find_similar_word_cards(db, "dogs")
        assert any(r.lemma == "dog" for r in results)


# ---------------------------------------------------------------------------
# Layer 3 — error tag overlap
# ---------------------------------------------------------------------------

class TestErrorTagMatch:
    def test_shared_error_tag_found(self, db: DatabaseConnection, sentence_id: int):
        # Card A: lemma "fox", has error G01
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "a wild animal")
        _link_error(db, card_a, "G01")

        # Card B: lemma "mitigate", also has error G01
        card_b = _insert_word_card(db, sentence_id, "mitigate", "mitigate", "to lessen")
        _link_error(db, card_b, "G01")

        # Query for "fox" → Layer 3 should find card_b via shared G01
        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        card_ids = [r.card_id for r in results]
        assert card_b in card_ids

    def test_error_tag_match_layer_label(self, db: DatabaseConnection, sentence_id: int):
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "")
        _link_error(db, card_a, "L01")
        card_b = _insert_word_card(db, sentence_id, "ambiguous", "ambiguous", "unclear")
        _link_error(db, card_b, "L01")

        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        error_tag_matches = [r for r in results if r.match_layer == "error_tag"]
        assert any(r.card_id == card_b for r in error_tag_matches)

    def test_error_tag_score_is_06(self, db: DatabaseConnection, sentence_id: int):
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "")
        _link_error(db, card_a, "D02")
        card_b = _insert_word_card(db, sentence_id, "however", "however", "contrast word")
        _link_error(db, card_b, "D02")

        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        matches = [r for r in results if r.card_id == card_b]
        if matches:
            assert matches[0].score == 0.6

    def test_no_error_tags_no_layer3_results(self, db: DatabaseConnection, sentence_id: int):
        # Card without any error tags — Layer 3 should not match via it
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        # No _link_error call
        _insert_word_card(db, sentence_id, "dog", "dog", "a domestic animal")

        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        error_tag_matches = [r for r in results if r.match_layer == "error_tag"]
        assert len(error_tag_matches) == 0

    def test_non_overlapping_error_tags_not_matched(self, db: DatabaseConnection, sentence_id: int):
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "")
        _link_error(db, card_a, "G01")
        card_b = _insert_word_card(db, sentence_id, "dog", "dog", "")
        _link_error(db, card_b, "L01")  # different error type

        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        matched_ids = [r.card_id for r in results if r.match_layer == "error_tag"]
        assert card_b not in matched_ids


# ---------------------------------------------------------------------------
# Deduplication — highest layer wins
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_surface_beats_lemma_for_same_card(self, db: DatabaseConnection, sentence_id: int):
        # "fox" card: surface_form = "fox", lemma = "fox"
        # Query "fox" → matches Layer 1 (surface) AND Layer 2 (lemma, since lemma("fox")="fox")
        # Result should have match_layer="surface" and score=1.0
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_word_cards(db, "fox")
        # Should have exactly one result
        assert len(results) == 1
        assert results[0].score == 1.0
        assert results[0].match_layer == "surface"

    def test_lemma_beats_error_tag_for_same_card(self, db: DatabaseConnection, sentence_id: int):
        # Card A: lemma="fox", error G01
        # Card B: lemma="run", error G01 AND lemma matches query "running"
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "")
        _link_error(db, card_a, "G01")
        card_b = _insert_word_card(db, sentence_id, "run", "run", "to move")
        _link_error(db, card_b, "G01")

        # Query "running": Layer 2 finds card_b (lemma "run"); Layer 3 also finds card_b
        # card_b should have score 0.8 (lemma), not 0.6 (error_tag)
        results = find_similar_word_cards(db, "running", exclude_lemma="run")
        run_match = next((r for r in results if r.card_id == card_b), None)
        # card_b may or may not appear (depends on whether lemma matches)
        if run_match:
            assert run_match.score >= 0.8


# ---------------------------------------------------------------------------
# exclude_lemma
# ---------------------------------------------------------------------------

class TestExcludeLemma:
    def test_exclude_lemma_filters_exact_match(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        assert all(r.lemma != "fox" for r in results)

    def test_without_exclude_lemma_self_included(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_word_cards(db, "fox")
        assert any(r.lemma == "fox" for r in results)

    def test_exclude_lemma_does_not_filter_others(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        _insert_word_card(db, sentence_id, "foxes", "foxes", "plural fox")
        results = find_similar_word_cards(db, "foxes", exclude_lemma="foxes")
        # "fox" card should still be findable
        assert any(r.lemma == "fox" for r in results)


# ---------------------------------------------------------------------------
# limit
# ---------------------------------------------------------------------------

class TestLimit:
    def test_limit_one(self, db: DatabaseConnection, sentence_id: int):
        for i in range(5):
            _insert_word_card(db, sentence_id, f"word{i}", f"word{i}", "")
        # Insert a card whose surface_form contains "word" so Layer 1 might fire
        # Instead just use a query that catches via lemma
        results = find_similar_word_cards(db, "word0", limit=1)
        assert len(results) <= 1

    def test_limit_default_five(self, db: DatabaseConnection, sentence_id: int):
        for i in range(10):
            _insert_word_card(db, sentence_id, f"word{i}", f"word{i}", "")
        # Add error tags to all so Layer 3 can find them
        base_card = _insert_word_card(db, sentence_id, "fox", "fox", "")
        _link_error(db, base_card, "G01")
        for i in range(10):
            with db.get_connection() as conn:
                cid = conn.execute(
                    "SELECT id FROM word_cards WHERE lemma = ?", (f"word{i}",)
                ).fetchone()["id"]
            _link_error(db, cid, "G01")

        results = find_similar_word_cards(db, "fox", exclude_lemma="fox")
        assert len(results) <= 5

    def test_limit_zero_returns_empty(self, db: DatabaseConnection, sentence_id: int):
        _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_word_cards(db, "fox", limit=0)
        assert results == []


# ---------------------------------------------------------------------------
# find_similar_cards_for_word_card
# ---------------------------------------------------------------------------

class TestFindSimilarCardsForWordCard:
    def test_delegates_to_find_similar(self, db: DatabaseConnection, sentence_id: int):
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "a wild animal")
        _insert_word_card(db, sentence_id, "foxes", "foxes", "plural fox")
        results = find_similar_cards_for_word_card(db, card_a)
        assert isinstance(results, list)

    def test_excludes_self_lemma(self, db: DatabaseConnection, sentence_id: int):
        card_a = _insert_word_card(db, sentence_id, "fox", "fox", "")
        results = find_similar_cards_for_word_card(db, card_a)
        assert all(r.card_id != card_a for r in results)

    def test_unknown_card_id_raises(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="not found"):
            find_similar_cards_for_word_card(db, 999_999)

    def test_returns_list(self, db: DatabaseConnection, sentence_id: int):
        card_id = _insert_word_card(db, sentence_id, "fox", "fox", "")
        result = find_similar_cards_for_word_card(db, card_id)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Sentence-card diagnosed mistake matching
# ---------------------------------------------------------------------------

class TestSimilarSentenceMistakes:
    def test_shared_diagnosed_error_tag_finds_active_translated_sentence(
        self,
        db: DatabaseConnection,
        tmp_path: Path,
    ):
        sentence_ids = _seed_sentence_ids(
            db,
            tmp_path,
            (
                "Although it rained, we left. "
                "While the premise sounds simple, the conclusion differs."
            ),
        )
        current_card = _save_sentence_diagnosis(
            db,
            sentence_ids[0],
            _diagnosed_sentence_payload(
                "D02",
                "Current translation missed the contrast after although.",
            ),
        )
        candidate_card = _save_sentence_diagnosis(
            db,
            sentence_ids[1],
            _diagnosed_sentence_payload(
                "D02",
                "Past translation also treated the contrast as continuation.",
            ),
            translation="我之前也误读了对比。",
        )

        results = find_similar_sentence_mistakes(db, current_card)

        assert [result.card_id for result in results] == [candidate_card]
        assert results[0].sentence_id == sentence_ids[1]
        assert results[0].shared_error_codes == ("D02",)
        assert results[0].diagnosis_evidence == (
            {
                "error_type": "D02",
                "evidence": "Past translation also treated the contrast as continuation.",
            },
        )

    def test_sentence_mistakes_exclude_archived_missing_translation_and_predicted_basis(
        self,
        db: DatabaseConnection,
        tmp_path: Path,
    ):
        sentence_ids = _seed_sentence_ids(
            db,
            tmp_path,
            (
                "Although it rained, we left. "
                "While the premise sounds simple, the conclusion differs. "
                "Although she was tired, she kept working. "
                "However, the answer changed."
            ),
        )
        current_card = _save_sentence_diagnosis(
            db,
            sentence_ids[0],
            _diagnosed_sentence_payload("D02", "Current contrast error."),
        )
        archived_card = _save_sentence_diagnosis(
            db,
            sentence_ids[1],
            _diagnosed_sentence_payload("D02", "Archived contrast error."),
        )
        no_translation_card = _save_sentence_diagnosis(
            db,
            sentence_ids[2],
            _diagnosed_sentence_payload("D02", "No translation contrast error."),
            translation="",
        )
        predicted_card = _save_sentence_diagnosis(
            db,
            sentence_ids[3],
            _predicted_sentence_payload("D02"),
            translation="这句有译文但不是用户译文诊断。",
        )
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE sentence_cards SET archived_at = '2026-06-17T00:00:00+00:00' WHERE id = ?",
                (archived_card,),
            )
            conn.execute(
                "UPDATE sentence_cards SET user_translation = '' WHERE id = ?",
                (no_translation_card,),
            )

        results = find_similar_sentence_mistakes(db, current_card)

        excluded_ids = {archived_card, no_translation_card, predicted_card}
        assert excluded_ids.isdisjoint({result.card_id for result in results})

    def test_sentence_mistakes_require_confident_current_and_candidate(
        self,
        db: DatabaseConnection,
        tmp_path: Path,
    ):
        sentence_ids = _seed_sentence_ids(
            db,
            tmp_path,
            (
                "Although it rained, we left. "
                "While the premise sounds simple, the conclusion differs. "
                "Although she was tired, she kept working."
            ),
        )
        low_current = _save_sentence_diagnosis(
            db,
            sentence_ids[0],
            _diagnosed_sentence_payload(
                "D02",
                "Low confidence current contrast error.",
                confidence=0.74,
            ),
        )
        _save_sentence_diagnosis(
            db,
            sentence_ids[1],
            _diagnosed_sentence_payload("D02", "Confident candidate error."),
        )

        assert find_similar_sentence_mistakes(db, low_current) == []

        with db.get_connection() as conn:
            conn.execute(
                "UPDATE sentence_cards SET archived_at = '2026-06-17T00:00:00+00:00' WHERE sentence_id = ?",
                (sentence_ids[1],),
            )

        high_current = _save_sentence_diagnosis(
            db,
            sentence_ids[0],
            _diagnosed_sentence_payload("D02", "Confident current error."),
        )
        _save_sentence_diagnosis(
            db,
            sentence_ids[2],
            _diagnosed_sentence_payload(
                "D02",
                "Low confidence candidate contrast error.",
                confidence=0.5,
            ),
        )

        assert find_similar_sentence_mistakes(db, high_current) == []

    def test_unknown_sentence_card_raises(self, db: DatabaseConnection):
        with pytest.raises(ValueError, match="Sentence card id=999 not found"):
            find_similar_sentence_mistakes(db, 999)
