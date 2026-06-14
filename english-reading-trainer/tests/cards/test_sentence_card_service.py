"""
Tests for app/cards/sentence_card_service.py.

All tests use real SQLite (tmp_path). No mocking.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    create_sentence_card,
    get_sentence_card,
    get_sentence_card_by_sentence,
    list_sentence_cards,
)
from app.db_connection import DatabaseConnection
from app.db_models import SM2_DEFAULT_EF, SM2_INITIAL_INTERVAL_DAYS, SM2_INITIAL_REPETITIONS

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    c = DatabaseConnection(tmp_path / "test.db")
    c.apply_migrations(MIGRATIONS_DIR)
    return c


_seed_counter = 0


def _seed_sentence(db: DatabaseConnection, text: str = "Hello world.") -> int:
    """Insert minimum hierarchy and return a sentence id."""
    global _seed_counter
    _seed_counter += 1
    with db.get_connection() as conn:
        book_id = conn.execute(
            "INSERT INTO books (title, author, source_format, file_hash, imported_at) "
            "VALUES ('B', '', 'txt', ?, '2026-01-01T00:00:00+00:00')",
            (f"hash_{_seed_counter}_{text[:20]}",),
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
            "VALUES (?, ?, ?, 0, ?, 'xx', 0, ?)",
            (book_id, ch_id, par_id, text, len(text)),
        ).lastrowid
    return sent_id


# ---------------------------------------------------------------------------
# create_sentence_card
# ---------------------------------------------------------------------------

class TestCreateSentenceCard:
    def test_returns_card_id(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        assert isinstance(card_id, int)
        assert card_id > 0

    def test_card_exists_in_db(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sentence_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row is not None
        assert row["sentence_id"] == sid

    def test_sm2_defaults(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT ef, interval_days, repetitions, mastery_state "
                "FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert row["ef"] == SM2_DEFAULT_EF
        assert row["interval_days"] == SM2_INITIAL_INTERVAL_DAYS
        assert row["repetitions"] == SM2_INITIAL_REPETITIONS
        assert row["mastery_state"] == "new"

    def test_due_at_is_set(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT due_at FROM sentence_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["due_at"] is not None

    def test_user_note_stored(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid, user_note="tricky clause")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_note FROM sentence_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["user_note"] == "tricky clause"

    def test_duplicate_raises(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        create_sentence_card(db, sid)
        with pytest.raises(SentenceCardAlreadyExistsError):
            create_sentence_card(db, sid)

    def test_invalid_sentence_id_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="not found"):
            create_sentence_card(db, 99999)

    def test_review_count_starts_at_zero(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT review_count FROM sentence_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["review_count"] == 0

    def test_last_reviewed_at_is_null(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT last_reviewed_at FROM sentence_cards WHERE id = ?", (card_id,)
            ).fetchone()
        assert row["last_reviewed_at"] is None


# ---------------------------------------------------------------------------
# get_sentence_card
# ---------------------------------------------------------------------------

class TestGetSentenceCard:
    def test_returns_dict_with_sentence_text(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "The cat sat on the mat.")
        card_id = create_sentence_card(db, sid)
        card = get_sentence_card(db, card_id)
        assert card is not None
        assert card["sentence_text"] == "The cat sat on the mat."

    def test_returns_none_for_missing_id(self, db: DatabaseConnection) -> None:
        assert get_sentence_card(db, 99999) is None

    def test_returned_dict_has_required_fields(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        card = get_sentence_card(db, card_id)
        for field in ["id", "sentence_id", "mastery_state", "ef",
                      "interval_days", "repetitions", "due_at", "sentence_text"]:
            assert field in card


# ---------------------------------------------------------------------------
# get_sentence_card_by_sentence
# ---------------------------------------------------------------------------

class TestGetSentenceCardBySentence:
    def test_finds_existing_card(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        card = get_sentence_card_by_sentence(db, sid)
        assert card is not None
        assert card["id"] == card_id

    def test_returns_none_when_no_card(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        assert get_sentence_card_by_sentence(db, sid) is None


# ---------------------------------------------------------------------------
# list_sentence_cards
# ---------------------------------------------------------------------------

class TestListSentenceCards:
    def test_empty_when_no_cards(self, db: DatabaseConnection) -> None:
        assert list_sentence_cards(db) == []

    def test_returns_all_cards(self, db: DatabaseConnection) -> None:
        for i in range(3):
            sid = _seed_sentence(db, f"Sentence number {i}.")
            create_sentence_card(db, sid)
        cards = list_sentence_cards(db)
        assert len(cards) == 3

    def test_limit_respected(self, db: DatabaseConnection) -> None:
        for i in range(5):
            sid = _seed_sentence(db, f"Sent {i} here.")
            create_sentence_card(db, sid)
        cards = list_sentence_cards(db, limit=2)
        assert len(cards) == 2

    def test_offset_respected(self, db: DatabaseConnection) -> None:
        for i in range(4):
            sid = _seed_sentence(db, f"Offset test {i}.")
            create_sentence_card(db, sid)
        all_cards  = list_sentence_cards(db, limit=100)
        page2      = list_sentence_cards(db, limit=2, offset=2)
        assert len(page2) == 2
        assert page2[0]["id"] != all_cards[0]["id"]

    def test_includes_sentence_text(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db, "Hello world.")
        create_sentence_card(db, sid)
        cards = list_sentence_cards(db)
        assert cards[0]["sentence_text"] == "Hello world."

    def test_book_id_filter(self, db: DatabaseConnection) -> None:
        # book 1
        sid1 = _seed_sentence(db, "Book one sentence here.")
        create_sentence_card(db, sid1)
        # get book_id for filtering
        with db.get_connection() as conn:
            book_id = conn.execute(
                "SELECT book_id FROM sentences WHERE id = ?", (sid1,)
            ).fetchone()["book_id"]

        # book 2 (different hash)
        sid2 = _seed_sentence(db, "Book two sentence here.")
        create_sentence_card(db, sid2)

        cards = list_sentence_cards(db, book_id=book_id)
        assert len(cards) == 1
        assert cards[0]["sentence_text"] == "Book one sentence here."
