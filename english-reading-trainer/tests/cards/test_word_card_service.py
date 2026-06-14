"""
Tests for app/cards/word_card_service.py.

All tests use real SQLite (tmp_path). No mocking.
"""

from pathlib import Path

import pytest

from app.cards.word_card_service import (
    create_or_update_word_card,
    get_word_card,
    get_word_card_by_lemma,
    list_word_cards,
)
from app.db_connection import DatabaseConnection
from app.db_models import LexicalType, SM2_DEFAULT_EF

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


def _seed_sentence(db: DatabaseConnection, suffix: str = "") -> int:
    with db.get_connection() as conn:
        book_id = conn.execute(
            "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
            "VALUES ('B', '', 'txt', ?, '2026-01-01T00:00:00+00:00')",
            (f"hash_wc_{suffix}",),
        ).lastrowid
        ch_id = conn.execute(
            "INSERT INTO chapters (book_id, idx, title, sentence_start, sentence_end) "
            "VALUES (?, 1, 'Ch', 0, 1)", (book_id,)
        ).lastrowid
        par_id = conn.execute(
            "INSERT INTO paragraphs (chapter_id, idx, sentence_start, sentence_end) "
            "VALUES (?, 1, 0, 1)", (ch_id,)
        ).lastrowid
        sent_id = conn.execute(
            "INSERT INTO sentences (book_id, chapter_id, paragraph_id, idx, "
            "text, text_hash, char_offset_start, char_offset_end) "
            "VALUES (?, ?, ?, 0, 'A sentence.', 'abc', 0, 10)",
            (book_id, ch_id, par_id),
        ).lastrowid
    return sent_id


# ---------------------------------------------------------------------------
# create_or_update_word_card — creation path
# ---------------------------------------------------------------------------

class TestCreateWordCard:
    def test_returns_card_id_and_created_true(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "a")
        card_id, created = create_or_update_word_card(db, sid, "mitigate")
        assert isinstance(card_id, int)
        assert card_id > 0
        assert created is True

    def test_card_stored_in_db(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "b")
        card_id, _ = create_or_update_word_card(db, sid, "mitigate")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row is not None

    def test_lemma_is_lowercased_surface(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "c")
        card_id, _ = create_or_update_word_card(db, sid, "Mitigate")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT lemma FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["lemma"] == "mitigate"

    def test_surface_form_preserved(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "d")
        card_id, _ = create_or_update_word_card(db, sid, "Mitigating")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT surface_form FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["surface_form"] == "Mitigating"

    def test_lexical_type_stored(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "e")
        card_id, _ = create_or_update_word_card(
            db, sid, "give rise to", LexicalType.PHRASE
        )
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT lexical_type FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["lexical_type"] == "phrase"

    def test_sm2_defaults(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "f")
        card_id, _ = create_or_update_word_card(db, sid, "claim")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT ef, interval_days, repetitions, mastery_state "
                "FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert row["ef"] == SM2_DEFAULT_EF
        assert row["interval_days"] == 0
        assert row["repetitions"] == 0
        assert row["mastery_state"] == "new"

    def test_occurrence_count_starts_at_one(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "g")
        card_id, _ = create_or_update_word_card(db, sid, "assert")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT occurrence_count FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["occurrence_count"] == 1

    def test_user_note_stored(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "h")
        card_id, _ = create_or_update_word_card(
            db, sid, "allege", user_note="confuses with claim"
        )
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_note FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["user_note"] == "confuses with claim"

    def test_first_sentence_id_stored(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "i")
        card_id, _ = create_or_update_word_card(db, sid, "argue")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT first_sentence_id FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["first_sentence_id"] == sid

    def test_invalid_sentence_id_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="not found"):
            create_or_update_word_card(db, 99999, "word")

    def test_empty_surface_form_raises(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "j")
        with pytest.raises(ValueError, match="empty"):
            create_or_update_word_card(db, sid, "")

    def test_whitespace_only_surface_form_raises(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "k")
        with pytest.raises(ValueError, match="empty"):
            create_or_update_word_card(db, sid, "   ")


# ---------------------------------------------------------------------------
# create_or_update_word_card — update (duplicate lemma) path
# ---------------------------------------------------------------------------

class TestUpdateWordCard:
    def test_second_call_returns_created_false(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "l")
        create_or_update_word_card(db, sid, "claim")
        _, created = create_or_update_word_card(db, sid, "claim")
        assert created is False

    def test_second_call_returns_same_card_id(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "m")
        card_id1, _ = create_or_update_word_card(db, sid, "claim")
        card_id2, _ = create_or_update_word_card(db, sid, "claim")
        assert card_id1 == card_id2

    def test_occurrence_count_incremented(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "n")
        card_id, _ = create_or_update_word_card(db, sid, "claim")
        create_or_update_word_card(db, sid, "claim")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT occurrence_count FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["occurrence_count"] == 2

    def test_three_occurrences(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "o")
        card_id, _ = create_or_update_word_card(db, sid, "argue")
        for _ in range(2):
            create_or_update_word_card(db, sid, "argue")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT occurrence_count FROM word_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["occurrence_count"] == 3

    def test_case_insensitive_deduplication(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "p")
        card_id1, created1 = create_or_update_word_card(db, sid, "Argue")
        card_id2, created2 = create_or_update_word_card(db, sid, "argue")
        assert card_id1 == card_id2
        assert created1 is True
        assert created2 is False

    def test_total_word_cards_count(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "q")
        create_or_update_word_card(db, sid, "word1")
        create_or_update_word_card(db, sid, "word1")
        create_or_update_word_card(db, sid, "word2")
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM word_cards").fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# get_word_card / get_word_card_by_lemma
# ---------------------------------------------------------------------------

class TestGetWordCard:
    def test_returns_dict(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "r")
        card_id, _ = create_or_update_word_card(db, sid, "mitigate")
        card = get_word_card(db, card_id)
        assert isinstance(card, dict)

    def test_includes_first_sentence_text(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "s")
        card_id, _ = create_or_update_word_card(db, sid, "mitigate")
        card = get_word_card(db, card_id)
        assert "first_sentence_text" in card

    def test_returns_none_for_missing(self, db: DatabaseConnection) -> None:
        assert get_word_card(db, 99999) is None

    def test_get_by_lemma_found(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "t")
        create_or_update_word_card(db, sid, "Allege")
        card = get_word_card_by_lemma(db, "allege")
        assert card is not None

    def test_get_by_lemma_not_found(self, db: DatabaseConnection) -> None:
        assert get_word_card_by_lemma(db, "nonexistent") is None


# ---------------------------------------------------------------------------
# list_word_cards
# ---------------------------------------------------------------------------

class TestListWordCards:
    def test_empty_when_no_cards(self, db: DatabaseConnection) -> None:
        assert list_word_cards(db) == []

    def test_returns_all_cards(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "u")
        for word in ("alpha", "beta", "gamma"):
            create_or_update_word_card(db, sid, word)
        assert len(list_word_cards(db)) == 3

    def test_limit_respected(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "v")
        for word in ("a1", "b2", "c3", "d4", "e5"):
            create_or_update_word_card(db, sid, word)
        assert len(list_word_cards(db, limit=3)) == 3

    def test_offset_respected(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "w")
        for word in ("w1", "w2", "w3"):
            create_or_update_word_card(db, sid, word)
        page1 = list_word_cards(db, limit=2, offset=0)
        page2 = list_word_cards(db, limit=2, offset=2)
        assert len(page2) == 1
        assert page2[0]["lemma"] not in {c["lemma"] for c in page1}

    def test_ordered_by_occurrence_desc(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "x")
        create_or_update_word_card(db, sid, "frequent")
        for _ in range(3):
            create_or_update_word_card(db, sid, "frequent")
        create_or_update_word_card(db, sid, "rare")
        cards = list_word_cards(db)
        assert cards[0]["lemma"] == "frequent"
