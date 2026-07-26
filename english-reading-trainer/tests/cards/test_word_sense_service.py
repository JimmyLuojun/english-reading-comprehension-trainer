"""Real-SQLite tests for stable word senses and occurrence assignments."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cards.word_card_service import create_or_update_word_card, list_word_card_sources
from app.cards.word_sense_service import (
    assign_source_sense,
    create_and_assign_source_sense,
    create_word_sense,
    existing_senses_prompt_text,
    get_word_source,
    list_word_senses,
    record_source_analysis,
)
from app.db_connection import DatabaseConnection

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    connection = DatabaseConnection(tmp_path / "word_senses.db")
    connection.apply_migrations(MIGRATIONS_DIR)
    return connection


def _seed_sentence(db: DatabaseConnection, text: str, suffix: str) -> int:
    with db.get_connection() as conn:
        book_id = conn.execute(
            """INSERT INTO books
               (title, author, source_format, file_hash, imported_at)
               VALUES (?, '', 'txt', ?, '2026-07-25T00:00:00+00:00')""",
            (f"Book {suffix}", f"sense-book-{suffix}"),
        ).lastrowid
        chapter_id = conn.execute(
            """INSERT INTO chapters
               (book_id, idx, title, sentence_start, sentence_end)
               VALUES (?, 1, 'Chapter', 0, 1)""",
            (book_id,),
        ).lastrowid
        paragraph_id = conn.execute(
            """INSERT INTO paragraphs
               (chapter_id, idx, sentence_start, sentence_end)
               VALUES (?, 1, 0, 1)""",
            (chapter_id,),
        ).lastrowid
        return int(
            conn.execute(
                """INSERT INTO sentences
                   (book_id, chapter_id, paragraph_id, idx, text, text_hash,
                    char_offset_start, char_offset_end)
                   VALUES (?, ?, ?, 0, ?, ?, 0, ?)""",
                (book_id, chapter_id, paragraph_id, text, f"sentence-{suffix}", len(text)),
            ).lastrowid
        )


def _analysis(meaning: str, chinese: str = "涂层") -> dict:
    return {
        "lemma": "coating",
        "lexical_type": "word",
        "pos": "noun",
        "meaning_in_context": meaning,
        "chinese_meaning": chinese,
        "role_in_sentence": "It names the relevant process or surface layer.",
        "register": "technical",
        "why_this_word": "It is more precise than layer in this context.",
        "vs_simpler": [{"simpler": "layer", "difference": "Layer is less specific."}],
        "learner_note_check": {
            "status": "not_provided",
            "feedback": "",
            "corrected_understanding": "",
        },
        "morphology": {"root": "", "family": ["coat"]},
        "predicted_error_types": ["L01"],
        "confidence": 0.94,
        "sense_resolution": {
            "decision": "new",
            "matched_sense_id": None,
            "reason": "No equivalent saved meaning applies.",
            "confidence": 0.9,
        },
    }


def _cache_analysis(db: DatabaseConnection, analysis: dict, suffix: str) -> int:
    with db.get_connection() as conn:
        return int(
            conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json, is_valid, created_at)
                   VALUES (?, 'v6', 'test', ?, 1, '2026-07-25T00:00:00+00:00')""",
                (f"sense-cache-{suffix}", json.dumps(analysis)),
            ).lastrowid
        )


def _seed_card_source(
    db: DatabaseConnection,
    text: str = "The coating protects the surface.",
    suffix: str = "one",
) -> tuple[int, int]:
    sentence_id = _seed_sentence(db, text, suffix)
    start = text.index("coating")
    card_id, _ = create_or_update_word_card(
        db,
        sentence_id,
        "coating",
        source_start_offset=start,
        source_end_offset=start + len("coating"),
        selected_text="coating",
    )
    source_id = int(list_word_card_sources(db, card_id)[0]["id"])
    return card_id, source_id


def test_create_list_and_prompt_word_sense(db: DatabaseConnection) -> None:
    card_id, source_id = _seed_card_source(db)
    analysis = _analysis("a protective material applied to a surface")
    cache_id = _cache_analysis(db, analysis, "one")

    sense_id = create_word_sense(db, card_id, cache_id, analysis)
    record_source_analysis(db, source_id, cache_id, confidence=0.9)
    assign_source_sense(
        db,
        source_id,
        sense_id,
        status="matched",
        confidence=0.9,
    )

    senses = list_word_senses(db, card_id)
    assert [(row["id"], row["meaning_en"]) for row in senses] == [
        (sense_id, "a protective material applied to a surface")
    ]
    source = get_word_source(db, source_id)
    assert source is not None
    assert source["sense_id"] == sense_id
    assert source["context_analysis_id"] == cache_id
    assert source["analysis"]["meaning_in_context"].startswith("a protective")
    assert f"SENSE {sense_id}" in existing_senses_prompt_text(db, card_id)


def test_assignment_rejects_sense_from_another_card(db: DatabaseConnection) -> None:
    _, first_source_id = _seed_card_source(db, suffix="first")
    second_sentence = _seed_sentence(db, "A seal prevents leaks.", "second")
    second_card_id, _ = create_or_update_word_card(db, second_sentence, "seal")
    second_analysis = {**_analysis("a closure that prevents leakage"), "lemma": "seal"}
    second_cache_id = _cache_analysis(db, second_analysis, "second")
    second_sense_id = create_word_sense(
        db,
        second_card_id,
        second_cache_id,
        second_analysis,
    )

    with pytest.raises(ValueError, match="does not belong"):
        assign_source_sense(
            db,
            first_source_id,
            second_sense_id,
            status="manual",
        )


def test_create_and_assign_uses_saved_context_analysis(db: DatabaseConnection) -> None:
    card_id, source_id = _seed_card_source(db)
    analysis = _analysis("liquid photoresist applied before lithography", "光刻胶涂覆")
    cache_id = _cache_analysis(db, analysis, "promote")
    record_source_analysis(db, source_id, cache_id, confidence=0.88)

    sense_id = create_and_assign_source_sense(db, source_id, confidence=0.88)

    source = get_word_source(db, source_id)
    assert source is not None
    assert source["sense_id"] == sense_id
    assert source["resolution_status"] == "new"
    assert list_word_senses(db, card_id)[0]["meaning_zh"] == "光刻胶涂覆"


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_invalid_confidence_is_rejected(
    db: DatabaseConnection,
    confidence: float,
) -> None:
    _, source_id = _seed_card_source(db, suffix=str(confidence))
    analysis = _analysis("a protective surface material")
    cache_id = _cache_analysis(db, analysis, str(confidence))

    with pytest.raises(ValueError, match="between 0 and 1"):
        record_source_analysis(db, source_id, cache_id, confidence=confidence)


def test_missing_source_and_empty_sense_prompt(db: DatabaseConnection) -> None:
    card_id, _ = _seed_card_source(db)

    assert get_word_source(db, 999_999) is None
    assert existing_senses_prompt_text(db, card_id).startswith("(none")


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ("missing_meaning", "requires meaning_in_context"),
        ("missing_card", "Word card not found"),
        ("missing_analysis", "Valid word analysis not found"),
        ("missing_record_source", "Word source not found"),
        ("missing_record_analysis", "Valid word analysis not found"),
        ("missing_assign_source", "Word source not found"),
        ("missing_assign_sense", "does not belong"),
        ("promote_missing_source", "Word source not found"),
        ("promote_without_analysis", "Analyze this occurrence"),
    ],
)
def test_word_sense_error_paths(
    db: DatabaseConnection,
    operation: str,
    message: str,
) -> None:
    card_id, source_id = _seed_card_source(db, suffix=operation)
    valid_analysis = _analysis("a protective surface material")
    cache_id = _cache_analysis(db, valid_analysis, operation)

    with pytest.raises(ValueError, match=message):
        if operation == "missing_meaning":
            create_word_sense(db, card_id, cache_id, {})
        elif operation == "missing_card":
            create_word_sense(db, 999_999, cache_id, valid_analysis)
        elif operation == "missing_analysis":
            create_word_sense(db, card_id, 999_999, valid_analysis)
        elif operation == "missing_record_source":
            record_source_analysis(db, 999_999, cache_id)
        elif operation == "missing_record_analysis":
            record_source_analysis(db, source_id, 999_999)
        elif operation == "missing_assign_source":
            assign_source_sense(
                db,
                999_999,
                999_999,
                status="manual",
            )
        elif operation == "missing_assign_sense":
            assign_source_sense(
                db,
                source_id,
                999_999,
                status="manual",
            )
        elif operation == "promote_missing_source":
            create_and_assign_source_sense(db, 999_999)
        else:
            create_and_assign_source_sense(db, source_id)


@pytest.mark.parametrize(
    "call",
    [
        lambda db, source_id: record_source_analysis(
            db,
            source_id,
            1,
            status="invented",
        ),
        lambda db, source_id: assign_source_sense(
            db,
            source_id,
            1,
            status="invented",
        ),
        lambda db, source_id: create_and_assign_source_sense(
            db,
            source_id,
            status="invented",
        ),
    ],
)
def test_invalid_resolution_status_is_rejected(
    db: DatabaseConnection,
    call,
) -> None:
    _, source_id = _seed_card_source(db)

    with pytest.raises(ValueError, match="Invalid word sense resolution status"):
        call(db, source_id)
