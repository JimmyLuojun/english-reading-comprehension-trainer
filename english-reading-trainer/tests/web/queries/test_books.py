"""Tests for book and chapter query helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cards.word_card_service import create_or_update_word_card, list_word_card_sources
from app.db_connection import DatabaseConnection
from app.db_models import LexicalType
from app.importers.txt_importer import import_txt
from app.review.sm2_scheduler import apply_review
from app.web.queries.books import (
    _default_read_idx,
    _fetch_adjacent_chapters,
    _fetch_book,
    _fetch_books,
    _fetch_chapter_by_idx,
    _fetch_chapters,
    _fetch_library_tags,
    _fetch_library_tag_usage,
    _delete_library_tag,
    _delete_book,
    _rename_library_tag,
    _find_reanchor_sentence_id,
    _find_phrase_reanchor_sentence_id,
    _find_word_reanchor_sentence_id,
    _normalize_phrase_text,
    _phrase_card_terms,
    _sql_placeholders,
    _update_library_item,
    _word_card_terms,
    _word_tokens,
)

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _db(tmp_path: Path) -> DatabaseConnection:
    db = DatabaseConnection(tmp_path / "test.db")
    db.apply_migrations(MIGRATIONS_DIR)
    return db


def test_book_and_chapter_queries_return_expected_shapes(tmp_path: Path) -> None:
    db = _db(tmp_path)
    source = tmp_path / "book.txt"
    source.write_text(
        "Chapter 1\nFirst sentence.\n\nChapter 2\nSecond sentence.",
        encoding="utf-8",
    )
    result = import_txt(db, source, title="Book", author="Author")

    books = _fetch_books(db)
    chapters = _fetch_chapters(db, result.book_id)

    assert books[0]["title"] == "Book"
    assert books[0]["content_kind"] == "unclassified"
    assert books[0]["library_status"] == "inbox"
    assert books[0]["tags"] == ""
    assert _fetch_book(db, result.book_id)["author"] == "Author"
    assert _fetch_book(db, 999) is None
    assert [chapter["idx"] for chapter in chapters] == [1, 2]
    assert _default_read_idx(db, result.book_id) == 1
    assert _fetch_chapter_by_idx(db, result.book_id, 2)["title"] == "Chapter 2"

    adjacent = _fetch_adjacent_chapters(db, result.book_id, 1)
    assert adjacent["previous"] is None
    assert adjacent["next"]["idx"] == 2

    assert _update_library_item(
        db,
        result.book_id,
        title="Updated Article",
        author="Writer",
        content_kind="article",
        library_status="reading",
        tags=["Trade", " siemens ", "trade", ""],
    )
    updated = _fetch_book(db, result.book_id)
    assert updated["title"] == "Updated Article"
    assert updated["content_kind"] == "article"
    assert updated["library_status"] == "reading"
    assert set(updated["tags"].split(", ")) == {"Trade", "siemens"}
    assert _fetch_library_tags(db) == ["siemens", "Trade"]
    assert [row["id"] for row in _fetch_books(db, content_kind="article")] == [
        result.book_id
    ]
    assert [row["id"] for row in _fetch_books(db, library_status="reading")] == [
        result.book_id
    ]
    assert [row["id"] for row in _fetch_books(db, tag="TRADE")] == [result.book_id]
    assert _fetch_books(db, tag="missing") == []


def test_update_library_item_validates_fields_and_missing_item(tmp_path: Path) -> None:
    db = _db(tmp_path)

    assert not _update_library_item(
        db,
        999,
        title="Missing",
        author="",
        content_kind="book",
        library_status="inbox",
        tags=[],
    )
    for values, message in (
        ({"title": "", "content_kind": "book", "library_status": "inbox"}, "Title"),
        (
            {"title": "Item", "content_kind": "paragraph", "library_status": "inbox"},
            "content type",
        ),
        (
            {"title": "Item", "content_kind": "book", "library_status": "done"},
            "library status",
        ),
    ):
        try:
            _update_library_item(
                db,
                999,
                author="",
                tags=[],
                **values,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    try:
        _update_library_item(
            db,
            999,
            title="Item",
            author="",
            content_kind="book",
            library_status="inbox",
            tags=["x" * 61],
        )
    except ValueError as exc:
        assert "60 characters" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_library_tag_rename_and_delete_cascade_to_all_relationships(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    source = tmp_path / "book.txt"
    source.write_text(
        "Chapter 1\nFirst sentence.\n\nChapter 2\nSecond sentence.",
        encoding="utf-8",
    )
    result = import_txt(db, source, title="Book", author="Author")
    assert _update_library_item(
        db,
        result.book_id,
        title="Book",
        author="Author",
        content_kind="book",
        library_status="inbox",
        tags=["Trade", "logic"],
    )
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO tags (name, category) VALUES ('orphan', 'library')"
        )
        conn.execute(
            "INSERT INTO tags (name, category) VALUES ('cards-only', 'review')"
        )
        trade_id = int(
            conn.execute("SELECT id FROM tags WHERE name = 'Trade'").fetchone()["id"]
        )
        sentence_id = int(
            conn.execute(
                "SELECT id FROM sentences WHERE book_id = ? ORDER BY id LIMIT 1",
                (result.book_id,),
            ).fetchone()["id"]
        )
        sentence_card_id = conn.execute(
            """INSERT INTO sentence_cards
               (sentence_id, created_at, due_at)
               VALUES (?, '2026-01-01', '2026-01-02')""",
            (sentence_id,),
        ).lastrowid
        word_card_id = conn.execute(
            """INSERT INTO word_cards
               (lemma, surface_form, first_sentence_id, created_at, due_at)
               VALUES ('first', 'First', ?, '2026-01-01', '2026-01-02')""",
            (sentence_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO sentence_card_tags (card_id, tag_id) VALUES (?, ?)",
            (sentence_card_id, trade_id),
        )
        conn.execute(
            "INSERT INTO word_card_tags (card_id, tag_id) VALUES (?, ?)",
            (word_card_id, trade_id),
        )

    usage = _fetch_library_tag_usage(db)

    assert [
        (
            row["name"],
            row["item_count"],
            row["sentence_card_count"],
            row["word_card_count"],
        )
        for row in usage
    ] == [
        ("logic", 1, 0, 0),
        ("orphan", 0, 0, 0),
        ("Trade", 1, 1, 1),
    ]

    renamed = _rename_library_tag(db, trade_id, "  Commerce  ")
    assert renamed == {
        "old_name": "Trade",
        "new_name": "Commerce",
        "book_ids": [result.book_id],
        "sentence_card_count": 1,
        "word_card_count": 1,
    }
    assert set(_fetch_book(db, result.book_id)["tags"].split(", ")) == {
        "Commerce",
        "logic",
    }
    with db.get_connection() as conn:
        assert conn.execute(
            """SELECT t.name FROM tags t
               JOIN sentence_card_tags sct ON sct.tag_id = t.id
               WHERE sct.card_id = ?""",
            (sentence_card_id,),
        ).fetchone()["name"] == "Commerce"
        assert conn.execute(
            """SELECT t.name FROM tags t
               JOIN word_card_tags wct ON wct.tag_id = t.id
               WHERE wct.card_id = ?""",
            (word_card_id,),
        ).fetchone()["name"] == "Commerce"

    assert _delete_library_tag(db, trade_id) == {
        "name": "Commerce",
        "book_ids": [result.book_id],
        "sentence_card_count": 1,
        "word_card_count": 1,
    }
    assert _fetch_book(db, result.book_id)["tags"] == "logic"
    assert [row["name"] for row in _fetch_library_tag_usage(db)] == ["logic", "orphan"]
    assert _delete_library_tag(db, 999) is None
    assert _rename_library_tag(db, 999, "Missing") is None
    with db.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sentence_card_tags WHERE card_id = ?",
            (sentence_card_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM word_card_tags WHERE card_id = ?",
            (word_card_id,),
        ).fetchone()[0] == 0


def test_library_tag_rename_validates_name_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    with db.get_connection() as conn:
        source_id = int(
            conn.execute(
                "INSERT INTO tags (name, category) VALUES ('Source', 'library')"
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO tags (name, category) VALUES ('Existing', 'library')"
        )
        review_only_id = int(
            conn.execute(
                "INSERT INTO tags (name, category) VALUES ('Review', 'review')"
            ).lastrowid
        )

    for invalid_name, message in (
        ("   ", "Tag name is required"),
        ("x" * 61, "60 characters"),
        ("Trade, finance", "cannot contain commas"),
        ("existing", "already exists"),
    ):
        try:
            _rename_library_tag(db, source_id, invalid_name)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    assert _rename_library_tag(db, review_only_id, "Changed") is None
    assert _delete_library_tag(db, review_only_id) is None


def test_library_metadata_rejects_comma_inside_one_tag(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="cannot contain commas"):
        _update_library_item(
            db, 999, title="Item", author="", content_kind="book",
            library_status="inbox", tags=["Trade, finance"],
        )


@pytest.mark.parametrize("record_survivor", [False, True])
def test_deleting_book_reanchors_primary_and_recounts_all_affected_cards(
    tmp_path: Path, record_survivor: bool
) -> None:
    db = _db(tmp_path)
    books, sentences = [], []
    for index, text in enumerate(("A cat watches a dog.", "Another cat watches another dog.")):
        source = tmp_path / f"book-{index}.txt"
        source.write_text(text, encoding="utf-8")
        books.append(import_txt(db, source, title=f"Book {index}").book_id)
        with db.get_connection() as conn:
            sentences.append(conn.execute(
                "SELECT id FROM sentences WHERE book_id = ?", (books[-1],)
            ).fetchone()[0])
    cat_id, _ = create_or_update_word_card(db, sentences[0], "cat")
    if record_survivor:
        create_or_update_word_card(db, sentences[1], "cat")
        with db.get_connection() as conn:
            sense_id = conn.execute(
                """INSERT INTO word_senses (card_id, meaning_en, created_at, updated_at)
                   VALUES (?, 'a domestic feline', '2026-09-05', '2026-09-05')""",
                (cat_id,),
            ).lastrowid
            conn.execute(
                """UPDATE word_card_sources SET sense_id = ?, resolution_status = 'manual',
                          resolution_confidence = 0.9
                    WHERE card_id = ? AND sentence_id = ?""",
                (sense_id, cat_id, sentences[1]),
            )
    # This card loses only a secondary occurrence; its primary must stay put.
    dog_id, _ = create_or_update_word_card(db, sentences[1], "dog")
    create_or_update_word_card(db, sentences[0], "dog")
    before_sources = list_word_card_sources(db, cat_id)

    result = _delete_book(db, books[0])

    assert result.word_cards_reanchored == 1
    assert result.word_cards_deleted == 0
    for card_id, term in ((cat_id, "cat"), (dog_id, "dog")):
        sources = list_word_card_sources(db, card_id)
        assert len(sources) == 1
        assert sources[0]["is_primary"] == 1
        assert sources[0]["sentence_id"] == sentences[1]
        assert sources[0]["selected_text"] == term
        with db.get_connection() as conn:
            card = conn.execute("SELECT * FROM word_cards WHERE id = ?", (card_id,)).fetchone()
        assert card["occurrence_count"] == 1
        assert card["first_sentence_id"] == sentences[1]
    if record_survivor:
        survivor = list_word_card_sources(db, cat_id)[0]
        for key in ("id", "sense_id", "resolution_status", "resolution_confidence"):
            assert survivor[key] == before_sources[1][key]
    assert db.check_integrity().is_healthy


def test_book_deletion_rolls_back_if_source_recount_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    for name, text in (("First", "A cat sleeps."), ("Second", "Another cat watches.")):
        source = tmp_path / f"{name}.txt"
        source.write_text(text, encoding="utf-8")
        import_txt(db, source, title=name)
    with db.get_connection() as conn:
        sentence = conn.execute("SELECT id, book_id FROM sentences ORDER BY id LIMIT 1").fetchone()
    card_id, _ = create_or_update_word_card(db, sentence["id"], "cat")
    apply_review(db, "word", card_id, "pass")
    tables = ("books", "sentences", "word_cards", "word_card_sources", "review_logs")
    with db.get_connection() as conn:
        before = {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")] for table in tables}

    def fail_recount(conn: object, card_id: int) -> None:
        raise RuntimeError("recount failed")

    monkeypatch.setattr("app.web.queries.books._sync_occurrence_count_conn", fail_recount)
    with pytest.raises(RuntimeError, match="recount failed"):
        _delete_book(db, sentence["book_id"])

    with db.get_connection() as conn:
        after = {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")] for table in tables}
    assert after == before
    assert db.check_integrity().is_healthy


def test_reanchor_helpers_match_words_and_phrases() -> None:
    candidates = [
        {"id": 10, "text": "The black cat sleeps."},
        {"id": 11, "text": "A long term memory rule."},
    ]

    assert (
        _find_word_reanchor_sentence_id(
            {
                "surface_form": "Cat",
                "lemma": "cat",
                "lexical_type": LexicalType.WORD.value,
            },
            candidates,
        )
        == 10
    )
    assert (
        _find_phrase_reanchor_sentence_id(
            {
                "surface_form": "long term",
                "lemma": "long term",
                "lexical_type": LexicalType.PHRASE.value,
            },
            candidates,
        )
        == 11
    )
    assert _word_tokens("Cat's cradle, cat.") == ["cat's", "cradle", "cat"]
    assert _normalize_phrase_text(" long   term ") == "long term"
    assert _sql_placeholders([1, 2, 3]) == "?,?,?"


def test_reanchor_helpers_return_none_when_terms_are_empty() -> None:
    candidates = [{"id": 10, "text": "The black cat sleeps."}]

    assert _find_word_reanchor_sentence_id({"surface_form": "", "lemma": ""}, candidates) is None
    assert _find_phrase_reanchor_sentence_id({"surface_form": "", "lemma": ""}, candidates) is None
    assert _find_reanchor_sentence_id(
        {
            "surface_form": "black cat",
            "lemma": "",
            "lexical_type": LexicalType.PHRASE.value,
        },
        candidates,
    ) == 10
    assert _word_card_terms({"surface_form": "Cat", "lemma": "feline"}) == {
        "cat",
        "feline",
    }
    assert _phrase_card_terms({"surface_form": "Long Term", "lemma": "long term"}) == [
        "long term"
    ]


def test_default_read_idx_falls_back_to_first_section(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with db.get_connection() as conn:
        book_id = conn.execute(
            """INSERT INTO books
               (title, author, source_format, file_hash, imported_at)
               VALUES ('Appendix Book', '', 'txt', 'appendix-hash', '2026-01-01')"""
        ).lastrowid
        conn.execute(
            """INSERT INTO chapters
               (book_id, idx, title, sentence_start, sentence_end, section_kind)
               VALUES (?, 7, 'Appendix A', 0, 0, 'appendix')""",
            (book_id,),
        )

    assert _default_read_idx(db, book_id) == 7
    assert _default_read_idx(db, 99999) is None
