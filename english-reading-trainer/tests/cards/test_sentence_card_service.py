"""
Tests for app/cards/sentence_card_service.py.

All tests use real SQLite (tmp_path). No mocking.
"""

from pathlib import Path

import pytest

from app.cards.sentence_card_service import (
    SentenceCardAlreadyExistsError,
    SentenceCardNotFoundError,
    archive_sentence_card,
    create_sentence_card,
    delete_sentence_translation,
    get_sentence_card,
    get_sentence_card_by_sentence,
    list_sentence_cards,
    save_sentence_structure,
    save_sentence_translation,
    update_sentence_card_note,
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

    def test_user_translation_can_be_stored_on_create(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid, user_translation="你好，世界。")

        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT user_translation, translation_created_at
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
        assert row["user_translation"] == "你好，世界。"
        assert row["translation_created_at"] is not None


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
# save_sentence_structure
# ---------------------------------------------------------------------------

class TestSaveSentenceStructure:
    def test_saves_structure_on_archived_container_card(
        self,
        db: DatabaseConnection,
    ) -> None:
        sid = _seed_sentence(db)
        card_id = save_sentence_structure(db, sid, "主干：The cat sat")

        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT user_structure, structure_created_at, archived_at
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()

        assert row["user_structure"] == "主干：The cat sat"
        assert row["structure_created_at"] is not None
        assert row["archived_at"] is not None

    def test_updates_existing_card_without_archiving(
        self,
        db: DatabaseConnection,
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)

        assert save_sentence_structure(db, sid, "主干：A") == card_id

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_structure, archived_at FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()

        assert row["user_structure"] == "主干：A"
        assert row["archived_at"] is None

    def test_rejects_empty_structure(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)

        with pytest.raises(ValueError, match="user_structure"):
            save_sentence_structure(db, sid, "   ")

    def test_invalid_sentence_id_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="not found"):
            save_sentence_structure(db, 99999, "主干：A")


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
        assert cards[0]["source_href"].startswith("/read/")
        assert f"sentence_id={sid}" in cards[0]["source_href"]
        assert cards[0]["source_href"].endswith(f"#sentence-{sid}")

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


class TestArchiveSentenceCard:
    def test_archive_sets_archived_at(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)

        archived_id = archive_sentence_card(db, sid)

        assert archived_id == card_id
        with db.get_connection() as conn:
            archived_at = conn.execute(
                "SELECT archived_at FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()["archived_at"]
        assert archived_at is not None

    def test_archived_card_is_excluded_from_public_reads(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        archive_sentence_card(db, sid)

        assert get_sentence_card(db, card_id) is None
        assert get_sentence_card_by_sentence(db, sid) is None
        assert list_sentence_cards(db) == []

    def test_recreate_reactivates_same_archived_card(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid, user_note="keep me")
        archive_sentence_card(db, sid)

        restored_id = create_sentence_card(db, sid)

        assert restored_id == card_id
        card = get_sentence_card(db, card_id)
        assert card is not None
        assert card["archived_at"] is None
        assert card["user_note"] == "keep me"

    def test_archive_missing_active_card_raises(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)

        with pytest.raises(SentenceCardNotFoundError):
            archive_sentence_card(db, sid)


class TestSaveSentenceTranslation:
    def test_creates_archived_translation_record_when_missing(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)

        card_id = save_sentence_translation(db, sid, "我的译文")

        with db.get_connection() as conn:
            card = conn.execute(
                """SELECT user_translation, archived_at
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
        assert get_sentence_card(db, card_id) is None
        assert card["user_translation"] == "我的译文"
        assert card["archived_at"] is not None

    def test_overwrites_existing_translation(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = save_sentence_translation(db, sid, "旧译文")

        same_id = save_sentence_translation(db, sid, "新译文")

        assert same_id == card_id
        with db.get_connection() as conn:
            card = conn.execute(
                "SELECT user_translation FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert card["user_translation"] == "新译文"

    def test_preserves_active_card_when_updating_translation(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)

        same_id = save_sentence_translation(db, sid, "保留复习卡的译文")

        assert same_id == card_id
        card = get_sentence_card(db, card_id)
        assert card is not None
        assert card["archived_at"] is None
        assert card["user_translation"] == "保留复习卡的译文"

    def test_preserves_archived_card_when_updating_translation(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        archive_sentence_card(db, sid)

        restored_id = save_sentence_translation(db, sid, "恢复译文")

        assert restored_id == card_id
        with db.get_connection() as conn:
            card = conn.execute(
                """SELECT archived_at, user_translation
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
        assert card["archived_at"] is not None
        assert card["user_translation"] == "恢复译文"

    def test_empty_translation_raises(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)

        with pytest.raises(ValueError, match="user_translation"):
            save_sentence_translation(db, sid, "   ")

    def test_invalid_sentence_id_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="not found"):
            save_sentence_translation(db, 99999, "译文")

    def test_translation_update_preserves_stale_analysis_and_clears_errors(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid)
        with db.get_connection() as conn:
            cache_id = conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json,
                    is_valid, created_at)
                   VALUES ('h', 'v1', 'manual', '{}', 1, '2026-01-01')"""
            ).lastrowid
            error_id = conn.execute(
                "SELECT id FROM error_types WHERE code = 'G01'"
            ).fetchone()["id"]
            conn.execute(
                "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )
            conn.execute(
                """INSERT INTO sentence_card_errors (card_id, error_type_id)
                   VALUES (?, ?)""",
                (card_id, error_id),
            )

        save_sentence_translation(db, sid, "新的理解")

        with db.get_connection() as conn:
            card_row = conn.execute(
                "SELECT ai_analysis_id FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            error_count = conn.execute(
                "SELECT COUNT(*) FROM sentence_card_errors WHERE card_id = ?",
                (card_id,),
            ).fetchone()[0]
        assert card_row["ai_analysis_id"] == cache_id
        assert error_count == 0


class TestDeleteSentenceTranslation:
    def test_clears_archived_translation_record(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = save_sentence_translation(db, sid, "我的译文")

        deleted_id = delete_sentence_translation(db, sid)

        assert deleted_id == card_id
        with db.get_connection() as conn:
            card = conn.execute(
                """SELECT user_translation, translation_created_at, archived_at
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
        assert card["user_translation"] is None
        assert card["translation_created_at"] is None
        assert card["archived_at"] is not None

    def test_deleting_active_translation_archives_review_card_and_clears_analysis(
        self, db: DatabaseConnection
    ) -> None:
        sid = _seed_sentence(db)
        card_id = create_sentence_card(db, sid, user_translation="有疑问的译文")
        with db.get_connection() as conn:
            cache_id = conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json,
                    is_valid, created_at)
                   VALUES ('h', 'v1', 'manual', '{}', 1, '2026-01-01')"""
            ).lastrowid
            error_id = conn.execute(
                "SELECT id FROM error_types WHERE code = 'G01'"
            ).fetchone()["id"]
            conn.execute(
                "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )
            conn.execute(
                """INSERT INTO sentence_card_errors (card_id, error_type_id)
                   VALUES (?, ?)""",
                (card_id, error_id),
            )

        delete_sentence_translation(db, sid)

        assert get_sentence_card(db, card_id) is None
        with db.get_connection() as conn:
            card = conn.execute(
                """SELECT archived_at, user_translation, translation_created_at,
                          ai_analysis_id
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
            error_count = conn.execute(
                "SELECT COUNT(*) FROM sentence_card_errors WHERE card_id = ?",
                (card_id,),
            ).fetchone()[0]
        assert card["archived_at"] is not None
        assert card["user_translation"] is None
        assert card["translation_created_at"] is None
        assert card["ai_analysis_id"] is None
        assert error_count == 0

    def test_missing_translation_raises(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        create_sentence_card(db, sid)

        with pytest.raises(ValueError, match="No saved translation"):
            delete_sentence_translation(db, sid)


class TestUpdateSentenceCardNote:
    def test_updates_existing_sentence_card_note(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)
        card_id = save_sentence_translation(db, sid, "我的译文")

        updated_id = update_sentence_card_note(db, sid, "搭配 hash into 要按整体理解")

        assert updated_id == card_id
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_note, archived_at FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert row["user_note"] == "搭配 hash into 要按整体理解"
        assert row["archived_at"] is not None

    def test_creates_archived_note_only_record(self, db: DatabaseConnection) -> None:
        sid = _seed_sentence(db)

        card_id = update_sentence_card_note(db, sid, "这句要先找主谓")

        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT user_note, user_translation, archived_at
                     FROM sentence_cards
                    WHERE id = ?""",
                (card_id,),
            ).fetchone()
        assert row["user_note"] == "这句要先找主谓"
        assert row["user_translation"] is None
        assert row["archived_at"] is not None

    def test_invalid_sentence_id_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(ValueError, match="not found"):
            update_sentence_card_note(db, 99999, "note")
