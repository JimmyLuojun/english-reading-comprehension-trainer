"""
Tests for app/web/fastapi_app.py.

Uses FastAPI TestClient with real SQLite databases. No network or browser is
required for these route-level tests.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.ai.llm_sentence_analyzer import SentenceAnalysisResult
from app.db_connection import DatabaseConnection
from app.importers.epub_importer import import_epub
from app.importers.txt_importer import import_txt
from app.review.sm2_scheduler import apply_review
from app.web.fastapi_app import create_app
from tests.importers.epub_builder import (
    PNG_1X1_BYTES,
    make_epub_with_image,
    make_epub_with_sections,
)
from tests.importers.pdf_builder import make_text_pdf

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

_VALID_SENTENCE_ANALYSIS = {
    "subject_skeleton": "The cat sat",
    "clauses": [{"type": "main", "text": "The cat sat", "role": "statement"}],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat.",
    "chinese_gloss": "猫坐着。",
    "predicted_error_types": ["G01"],
    "diagnosis_basis": "predicted",
    "diagnosed_error_types": [],
    "diagnosis_evidence": [],
    "confidence": 0.9,
}

_VALID_WORD_ANALYSIS = {
    "lemma": "cat",
    "lexical_type": "word",
    "pos": "noun",
    "meaning_in_context": "a small domestic feline animal",
    "chinese_meaning": "小型家养猫科动物",
    "register": "neutral",
    "why_this_word": "Cat is the neutral everyday term for the animal. Feline would be more formal or literary. Writing 'a small domestic feline animal' would sound clinical rather than natural.",
    "vs_simpler": [
        {"simpler": "pet", "difference": "Pet is a general term for any kept animal; cat is specific to the species."},
    ],
    "morphology": {"root": "", "family": []},
    "predicted_error_types": ["L01"],
    "confidence": 0.9,
}

_VALID_DIAGNOSED_ANALYSIS = {
    "subject_skeleton": "The cat sat",
    "clauses": [{"type": "main", "text": "The cat sat", "role": "statement"}],
    "modifiers": [],
    "logic_markers": [],
    "anaphora": [],
    "simplified_en": "The cat sat.",
    "chinese_gloss": "猫坐着。",
    "predicted_error_types": [],
    "diagnosis_basis": "user_translation",
    "diagnosed_error_types": ["G02"],
    "diagnosis_evidence": [
        {
            "error_type": "G02",
            "evidence": "The translation misses the phrase \"on the mat\".",
        }
    ],
    "confidence": 0.9,
}


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


@pytest.fixture()
def client(db: DatabaseConnection) -> TestClient:
    return TestClient(create_app(lambda: db))


def _seed_book(db: DatabaseConnection, tmp_path: Path) -> tuple[int, list[int]]:
    path = tmp_path / "book.txt"
    path.write_text(
        "The cat sat on the mat. It was a bright cold day.\n\n"
        "The clocks struck thirteen.",
        encoding="utf-8",
    )
    result = import_txt(db, path, title="Test Book", author="Author")
    with db.get_connection() as conn:
        sentence_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM sentences WHERE book_id = ? ORDER BY id",
                (result.book_id,),
            ).fetchall()
        ]
    return result.book_id, sentence_ids


def _seed_text_book(
    db: DatabaseConnection,
    tmp_path: Path,
    filename: str,
    *,
    title: str,
    text: str,
    author: str = "Author",
) -> tuple[int, list[int]]:
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    result = import_txt(db, path, title=title, author=author)
    with db.get_connection() as conn:
        sentence_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM sentences WHERE book_id = ? ORDER BY id",
                (result.book_id,),
            ).fetchall()
        ]
    return result.book_id, sentence_ids


def _seed_three_chapter_book(db: DatabaseConnection, tmp_path: Path) -> int:
    path = tmp_path / "three-chapters.txt"
    path.write_text(
        "Chapter 1\n"
        "First chapter sentence. Another first chapter sentence.\n\n"
        "Chapter 2\n"
        "Second chapter sentence. Another second chapter sentence.\n\n"
        "Chapter 3\n"
        "Third chapter sentence. Another third chapter sentence.",
        encoding="utf-8",
    )
    return import_txt(db, path, title="Three Chapter Book", author="Author").book_id


def _sentence_card_id(db: DatabaseConnection, sentence_id: int) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT id FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()["id"]


def _word_card_id(db: DatabaseConnection, lemma: str) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT id FROM word_cards WHERE lemma = ?",
            (lemma,),
        ).fetchone()["id"]


def _table_count(db: DatabaseConnection, table_name: str) -> int:
    with db.get_connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


def _make_due_yesterday(db: DatabaseConnection, table_name: str, card_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute(
            f"UPDATE {table_name} SET due_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), card_id),
        )


def _attach_sentence_analysis(
    db: DatabaseConnection,
    sentence_id: int,
    *,
    prompt_version: str = "v1",
) -> int:
    with db.get_connection() as conn:
        cache_id = conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES (?, ?, 'manual', ?, 1, ?)""",
            (
                f"analysis-{sentence_id}-{prompt_version}",
                prompt_version,
                json.dumps(_VALID_SENTENCE_ANALYSIS),
                datetime.now(timezone.utc).isoformat(),
            ),
        ).lastrowid
        card_id = conn.execute(
            "SELECT id FROM sentence_cards WHERE sentence_id = ?",
            (sentence_id,),
        ).fetchone()["id"]
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    return cache_id


def _sentence_error_codes(db: DatabaseConnection, sentence_id: int) -> set[str]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT et.code
                 FROM sentence_cards sc
                 JOIN sentence_card_errors sce ON sce.card_id = sc.id
                 JOIN error_types et ON et.id = sce.error_type_id
                WHERE sc.sentence_id = ?""",
            (sentence_id,),
        ).fetchall()
    return {row["code"] for row in rows}


class TestBasicPages:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_default_db_factory_syncs_prompt_versions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "web.db"
        monkeypatch.setenv("TRAINER_DB", str(db_path))
        client = TestClient(create_app())

        response = client.get("/")

        assert response.status_code == 200
        db = DatabaseConnection(db_path)
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0]
            active_count = conn.execute(
                "SELECT COUNT(*) FROM prompt_versions WHERE is_active = 1"
            ).fetchone()[0]
        assert count == 7
        assert active_count == 4

    def test_dashboard_empty(self, client: TestClient) -> None:
        response = client.get("/")

        assert response.status_code == 200
        assert "Reading Trainer" in response.text
        assert "Due now" in response.text

    def test_books_page_lists_imported_book(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _seed_book(db, tmp_path)

        response = client.get("/books")

        assert response.status_code == 200
        assert "Test Book" in response.text
        assert "/books/1" in response.text

    def test_book_detail_lists_chapters(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        response = client.get(f"/books/{book_id}")

        assert response.status_code == 200
        assert "Read" in response.text
        assert f"/read/{book_id}?chapter=1" in response.text

    def test_epub_frontmatter_does_not_become_chapter_one(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_sections(
            tmp_path,
            "frontmatter.epub",
            sections=[
                {
                    "title": "Praise for Mastering Bitcoin",
                    "file_name": "praise.xhtml",
                    "epub_type": "preface",
                    "body_html": (
                        "<p>Useful praise text with enough words to import here.</p>"
                    ),
                },
                {
                    "title": "1. Introduction",
                    "file_name": "ch01.xhtml",
                    "epub_type": "chapter",
                    "body_html": (
                        "<p>Body chapter text with enough words to import here.</p>"
                    ),
                },
            ],
        )
        result = import_epub(db, ep)

        detail = client.get(f"/books/{result.book_id}")
        read_default = client.get(f"/read/{result.book_id}")
        read_frontmatter = client.get(f"/read/{result.book_id}?chapter=1")

        assert detail.status_code == 200
        assert f"/read/{result.book_id}?chapter=2" in detail.text
        assert "Praise for Mastering Bitcoin" in detail.text
        assert "Chapter 1: Introduction" in detail.text
        assert "Chapter 1: Praise" not in detail.text
        assert read_default.status_code == 200
        assert "Chapter 1: Introduction" in read_default.text
        assert "Body chapter text" in read_default.text
        assert (
            f'href="/read/{result.book_id}?chapter=1#chapter-end"'
            in read_default.text
        )
        assert "Previous section: Praise for Mastering Bitcoin" in read_default.text
        assert read_frontmatter.status_code == 200
        assert (
            f'href="/read/{result.book_id}?chapter=2#chapter-start"'
            in read_frontmatter.text
        )
        assert "Next section: Chapter 1: Introduction" in read_frontmatter.text

    def test_missing_book_returns_404(self, client: TestClient) -> None:
        response = client.get("/books/999")

        assert response.status_code == 404
        assert "Book not found" in response.text

    def test_missing_chapter_returns_404(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        response = client.get(f"/read/{book_id}?chapter=999")

        assert response.status_code == 404
        assert "Chapter not found" in response.text


class TestBookDeletion:
    def test_books_page_has_delete_form_and_deletion_redirects(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        page = client.get("/books")
        response = client.post(f"/books/{book_id}/delete", follow_redirects=False)

        assert page.status_code == 200
        assert "Actions" in page.text
        assert "Delete" in page.text
        assert f'action="/books/{book_id}/delete"' in page.text
        assert response.status_code == 303
        assert response.headers["location"] == "/books"

    def test_delete_missing_book_returns_404(self, client: TestClient) -> None:
        response = client.post("/books/999/delete")

        assert response.status_code == 404
        assert "Book not found" in response.text

    def test_delete_txt_book_cascades_sentence_data_and_keeps_ai_cache(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        sentence_card_id = _sentence_card_id(db, sentence_ids[0])
        _attach_sentence_analysis(db, sentence_ids[0])
        with db.get_connection() as conn:
            tag_id = conn.execute(
                "INSERT INTO tags (name, category) VALUES ('important', 'user')"
            ).lastrowid
            error_type_id = conn.execute(
                "SELECT id FROM error_types ORDER BY id LIMIT 1"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO sentence_card_tags (card_id, tag_id) VALUES (?, ?)",
                (sentence_card_id, tag_id),
            )
            conn.execute(
                """INSERT INTO sentence_card_errors (card_id, error_type_id)
                   VALUES (?, ?)""",
                (sentence_card_id, error_type_id),
            )
        ai_cache_before = _table_count(db, "ai_cache")

        response = client.post(f"/books/{book_id}/delete", follow_redirects=False)

        assert response.status_code == 303
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM books WHERE id = ?",
                (book_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?",
                (book_id,),
            ).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (book_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM sentence_cards WHERE id = ?",
                (sentence_card_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM sentence_card_tags WHERE card_id = ?",
                (sentence_card_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM sentence_card_errors WHERE card_id = ?",
                (sentence_card_id,),
            ).fetchone()[0] == 0
        assert _table_count(db, "ai_cache") == ai_cache_before

    def test_delete_epub_book_removes_asset_rows_and_directory(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        epub_path = make_epub_with_image(tmp_path, "delete-image.epub")
        result = import_epub(db, epub_path)
        asset_dir = tmp_path / "assets" / "books" / str(result.book_id)

        response = client.post(f"/books/{result.book_id}/delete", follow_redirects=False)

        assert response.status_code == 303
        assert not asset_dir.exists()
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM book_assets WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM chapter_blocks WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0] == 0

    def test_delete_book_ignores_asset_cleanup_failure_after_db_commit(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        with patch("app.web.fastapi_app.shutil.rmtree", side_effect=OSError("denied")):
            response = client.post(f"/books/{book_id}/delete", follow_redirects=False)

        assert response.status_code == 303
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM books WHERE id = ?",
                (book_id,),
            ).fetchone()[0] == 0

    def test_delete_book_reanchors_word_card_and_preserves_state_and_logs(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_a, sentence_ids_a = _seed_text_book(
            db,
            tmp_path,
            "anchor-a.txt",
            title="Anchor A",
            text="The cat sat on the mat.",
        )
        _, sentence_ids_b = _seed_text_book(
            db,
            tmp_path,
            "anchor-b.txt",
            title="Anchor B",
            text="Later a cat slept near the window.",
        )
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids_a[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")
        apply_review(db, "word", card_id, "pass")
        with db.get_connection() as conn:
            before = dict(conn.execute(
                """SELECT first_sentence_id, ef, interval_days, repetitions,
                          review_count, due_at, archived_at, user_note,
                          current_meaning
                     FROM word_cards WHERE id = ?""",
                (card_id,),
            ).fetchone())
            log_count_before = conn.execute(
                "SELECT COUNT(*) FROM review_logs WHERE card_type = 'word' AND card_id = ?",
                (card_id,),
            ).fetchone()[0]

        response = client.post(f"/books/{book_a}/delete", follow_redirects=False)

        assert response.status_code == 303
        with db.get_connection() as conn:
            after = dict(conn.execute(
                """SELECT first_sentence_id, ef, interval_days, repetitions,
                          review_count, due_at, archived_at, user_note,
                          current_meaning
                     FROM word_cards WHERE id = ?""",
                (card_id,),
            ).fetchone())
            log_count_after = conn.execute(
                "SELECT COUNT(*) FROM review_logs WHERE card_type = 'word' AND card_id = ?",
                (card_id,),
            ).fetchone()[0]
        assert before["first_sentence_id"] == sentence_ids_a[0]
        assert after["first_sentence_id"] in sentence_ids_b
        for key in (
            "ef", "interval_days", "repetitions", "review_count",
            "due_at", "archived_at", "user_note", "current_meaning",
        ):
            assert after[key] == before[key]
        assert log_count_after == log_count_before == 1

    def test_delete_book_removes_unanchored_word_logs_without_touching_other_logs(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_a, sentence_ids_a = _seed_text_book(
            db,
            tmp_path,
            "delete-a.txt",
            title="Delete A",
            text="The cat sat on the mat.",
        )
        _, sentence_ids_b = _seed_text_book(
            db,
            tmp_path,
            "delete-b.txt",
            title="Delete B",
            text="The dog slept near the window.",
        )
        client.post(f"/mark/sentence/{sentence_ids_a[0]}", data={"return_to": "/cards"})
        client.post(f"/mark/sentence/{sentence_ids_b[0]}", data={"return_to": "/cards"})
        sentence_card_b = _sentence_card_id(db, sentence_ids_b[0])
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids_a[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids_b[0]),
                "surface_form": "dog",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        cat_card = _word_card_id(db, "cat")
        dog_card = _word_card_id(db, "dog")
        apply_review(db, "sentence", _sentence_card_id(db, sentence_ids_a[0]), "pass")
        apply_review(db, "sentence", sentence_card_b, "pass")
        apply_review(db, "word", cat_card, "pass")
        apply_review(db, "word", dog_card, "pass")

        response = client.post(f"/books/{book_a}/delete", follow_redirects=False)

        assert response.status_code == 303
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM word_cards WHERE id = ?",
                (cat_card,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM review_logs WHERE card_type = 'word' AND card_id = ?",
                (cat_card,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM sentence_cards WHERE id = ?",
                (sentence_card_b,),
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM word_cards WHERE id = ?",
                (dog_card,),
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM review_logs WHERE card_type = 'word' AND card_id = ?",
                (dog_card,),
            ).fetchone()[0] == 1
            assert conn.execute(
                """SELECT COUNT(*) FROM review_logs
                    WHERE card_type = 'sentence' AND card_id = ?""",
                (sentence_card_b,),
            ).fetchone()[0] == 1

    def test_delete_book_reanchors_phrase_with_normalized_whitespace(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_a, sentence_ids_a = _seed_text_book(
            db,
            tmp_path,
            "phrase-a.txt",
            title="Phrase A",
            text="Climate change affects coastal cities.",
        )
        _, sentence_ids_b = _seed_text_book(
            db,
            tmp_path,
            "phrase-b.txt",
            title="Phrase B",
            text="Climate    change shapes public policy.",
        )
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids_a[0]),
                "surface_form": "climate change",
                "lexical_type": "phrase",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "climate change")

        response = client.post(f"/books/{book_a}/delete", follow_redirects=False)

        assert response.status_code == 303
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT first_sentence_id FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert row["first_sentence_id"] in sentence_ids_b

    def test_delete_book_uses_strict_word_boundaries_for_reanchor(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_a, sentence_ids_a = _seed_text_book(
            db,
            tmp_path,
            "boundary-a.txt",
            title="Boundary A",
            text="The cat sat on the mat.",
        )
        _seed_text_book(
            db,
            tmp_path,
            "boundary-b.txt",
            title="Boundary B",
            text="Education can concatenate ideas quickly.",
        )
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids_a[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")
        apply_review(db, "word", card_id, "pass")

        response = client.post(f"/books/{book_a}/delete", follow_redirects=False)

        assert response.status_code == 303
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM review_logs WHERE card_type = 'word' AND card_id = ?",
                (card_id,),
            ).fetchone()[0] == 0


class TestReadingAndMarking:
    def test_read_page_shows_sentences_and_selection_toolbar(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert "The cat sat" in response.text
        assert '<article class="reader"' in response.text
        assert '<h1 class="reader-title">Test Book</h1>' in response.text
        assert response.text.count('<p class="reader-para">') == 2
        assert 'class="reader-text"' not in response.text
        assert f'data-sentence-id="{sentence_ids[0]}"' in response.text
        assert f'id="sentence-{sentence_ids[0]}"' in response.text
        assert 'id="selection-toolbar"' in response.text
        assert 'id="word-card-index"' in response.text
        assert 'id="toolbar-translation-open"' in response.text
        assert 'id="toolbar-analysis-open"' in response.text
        assert 'id="toolbar-translation-editor"' in response.text
        assert 'id="analysis-panel"' in response.text
        assert 'id="analysis-word-meaning-zh"' in response.text
        assert ".analysis-panel {\n      position: fixed;" in response.text
        assert "width: min(520px, 92vw);" in response.text
        assert ".reader-page.analysis-open .reader" not in response.text
        assert "window.prompt" not in response.text
        assert "reader:progress:book:${bookId}" in response.text
        assert 'data-restore-progress="1"' in response.text
        assert "top_sentence_id" in response.text
        assert "/mark/word" in response.text
        assert "selectedWordCardIds" in response.text
        assert "captureReadingAnchor" in response.text
        assert "restoreReadingAnchor" in response.text
        assert "markReaderSelection" in response.text
        assert "range.intersectsNode(span)" in response.text
        assert "deleteWordCardsAndReload" in response.text
        assert ".reader-sentence:target" in response.text

    def test_read_page_links_to_adjacent_chapter_boundaries(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id = _seed_three_chapter_book(db, tmp_path)

        response = client.get(f"/read/{book_id}?chapter=2")

        assert response.status_code == 200
        assert 'id="chapter-start"' in response.text
        assert 'id="chapter-end"' in response.text
        assert f'href="/read/{book_id}?chapter=1#chapter-end"' in response.text
        assert f'href="/read/{book_id}?chapter=3#chapter-start"' in response.text
        assert "Previous section: Chapter 1" in response.text
        assert "Next section: Chapter 3" in response.text

    def test_read_page_omits_missing_boundary_links_at_book_edges(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id = _seed_three_chapter_book(db, tmp_path)

        first = client.get(f"/read/{book_id}?chapter=1")
        last = client.get(f"/read/{book_id}?chapter=3")

        assert first.status_code == 200
        assert "Previous section:" not in first.text
        assert f'href="/read/{book_id}?chapter=2#chapter-start"' in first.text
        assert last.status_code == 200
        assert f'href="/read/{book_id}?chapter=2#chapter-end"' in last.text
        assert "Next section:" not in last.text

    def test_read_page_renders_epub_figure_blocks_and_serves_asset(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        epub_path = make_epub_with_image(tmp_path, "web-image.epub")
        result = import_epub(db, epub_path)
        with db.get_connection() as conn:
            asset_id = conn.execute(
                "SELECT id FROM book_assets WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()["id"]

        response = client.get(f"/read/{result.book_id}")

        assert response.status_code == 200
        assert '<figure class="reader-figure">' in response.text
        assert f'src="/assets/books/{result.book_id}/{asset_id}"' in response.text
        assert "Figure 1. Network diagram caption." in response.text
        assert "Before image prose" in response.text
        assert "After image prose" in response.text
        assert response.text.index("Before image prose") < response.text.index(
            '<figure class="reader-figure">'
        )
        assert response.text.index('<figure class="reader-figure">') < response.text.index(
            "After image prose"
        )

        asset_response = client.get(f"/assets/books/{result.book_id}/{asset_id}")

        assert asset_response.status_code == 200
        assert asset_response.headers["content-type"] == "image/png"
        assert asset_response.content == PNG_1X1_BYTES

    def test_read_page_dismisses_selection_without_clear_label(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert 'id="toolbar-dismiss"' in response.text
        assert ">Dismiss</button>" in response.text
        assert 'id="toolbar-clear"' not in response.text
        assert ">Clear</button>" not in response.text

    def test_read_page_includes_cross_sentence_bulk_unmark_actions(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        client.post(f"/mark/sentence/{sentence_ids[1]}", data={"return_to": "/cards"})

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert 'id="toolbar-cross-sentence-delete"' in response.text
        assert "activeCrossSentenceIds" in response.text
        assert "configureCrossSentenceActions(spans)" in response.text
        assert "Unmark ${activeCrossSentenceIds.length} sentence" in response.text
        assert "Promise.all(requests)" in response.text
        assert 'classList.remove("marked", "analyzed", "analyzed-stale")' in response.text
        assert 'sentence.dataset.marked = "0";' in response.text
        assert 'sentence.dataset.analysisId = "";' in response.text

    def test_read_page_marks_active_sentence_in_metadata(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert f'data-sentence-id="{sentence_ids[0]}"' in response.text
        assert 'data-marked="1"' in response.text
        assert 'class="reader-sentence marked"' in response.text

    def test_read_page_marks_analyzed_sentence_in_metadata(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        cache_id = _attach_sentence_analysis(db, sentence_ids[0])

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert 'class="reader-sentence marked analyzed"' in response.text
        assert f'data-analysis-id="{cache_id}"' in response.text
        assert 'data-analysis-stale="0"' in response.text

    def test_read_page_marks_stale_analysis_in_metadata(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        cache_id = _attach_sentence_analysis(
            db,
            sentence_ids[0],
            prompt_version="v0",
        )

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert 'class="reader-sentence marked analyzed-stale"' in response.text
        assert f'data-analysis-id="{cache_id}"' in response.text
        assert 'data-analysis-stale="1"' in response.text

    def test_read_page_underlines_existing_word_card(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert f'data-word-card="{card_id}"' in response.text
        assert 'data-meaning=""' in response.text
        assert 'data-note=""' in response.text
        assert ">cat</span>" in response.text
        assert "box-decoration-break: clone" in response.text
        assert "text-decoration-thickness: 0.12em" in response.text
        assert "rgba(251, 191, 36, 0.34)" in response.text

    def test_explicit_chapter_does_not_restore_saved_progress(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        response = client.get(f"/read/{book_id}?chapter=1")

        assert response.status_code == 200
        assert 'data-restore-progress="0"' in response.text

    def test_mark_sentence_creates_card_and_redirects(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            f"/mark/sentence/{sentence_ids[0]}",
            data={"return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/cards"
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sentence_cards").fetchone()[0]
        assert count == 1

    def test_save_sentence_translation_creates_archived_record_and_redirects(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            f"/mark/sentence/{sentence_ids[0]}/translation",
            data={"user_translation": "猫坐在垫子上。", "return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/cards"
        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT user_translation, translation_created_at, archived_at
                     FROM sentence_cards
                    WHERE sentence_id = ?""",
                (sentence_ids[0],),
            ).fetchone()
        assert row["user_translation"] == "猫坐在垫子上。"
        assert row["translation_created_at"] is not None
        assert row["archived_at"] is not None

    def test_save_sentence_translation_overwrites_previous_value(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            f"/mark/sentence/{sentence_ids[0]}/translation",
            data={"user_translation": "旧译文", "return_to": "/cards"},
        )

        client.post(
            f"/mark/sentence/{sentence_ids[0]}/translation",
            data={"user_translation": "新译文", "return_to": "/cards"},
        )

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_translation FROM sentence_cards WHERE sentence_id = ?",
                (sentence_ids[0],),
            ).fetchone()
        assert row["user_translation"] == "新译文"

    def test_empty_sentence_translation_returns_400(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            f"/mark/sentence/{sentence_ids[0]}/translation",
            data={"user_translation": "  ", "return_to": "/cards"},
        )

        assert response.status_code == 400
        assert "user_translation" in response.text

    def test_delete_sentence_translation_archives_review_card(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            f"/mark/sentence/{sentence_ids[0]}",
            data={"return_to": "/cards"},
        )
        client.post(
            f"/mark/sentence/{sentence_ids[0]}/translation",
            data={"user_translation": "猫坐在垫子上。", "return_to": "/cards"},
        )

        response = client.delete(
            f"/mark/sentence/{sentence_ids[0]}/translation",
            params={"return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/cards"
        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT archived_at, user_translation, translation_created_at
                     FROM sentence_cards
                    WHERE sentence_id = ?""",
                (sentence_ids[0],),
            ).fetchone()
        assert row["archived_at"] is not None
        assert row["user_translation"] is None
        assert row["translation_created_at"] is None

    def test_analyze_sentence_endpoint_saves_analysis_and_errors(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        result = SentenceAnalysisResult(
            data=_VALID_SENTENCE_ANALYSIS,
            cache_id=0,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

        with patch("app.web.fastapi_app.analyze_sentence", return_value=result) as mock:
            response = client.post(
                f"/analysis/sentence/{sentence_ids[0]}",
                data={"return_to": "/read/1"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["from_cache"] is False
        assert payload["analysis"]["simplified_en"] == "The cat sat."
        mock.assert_called_once()
        assert mock.call_args.kwargs["user_translation"] is None
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT ai_analysis_id FROM sentence_cards WHERE sentence_id = ?",
                (sentence_ids[0],),
            ).fetchone()
        assert row["ai_analysis_id"] == payload["cache_id"]
        assert _sentence_error_codes(db, sentence_ids[0]) == {"G01"}

    def test_analyze_sentence_endpoint_saves_translation_first(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        result = SentenceAnalysisResult(
            data=_VALID_DIAGNOSED_ANALYSIS,
            cache_id=0,
            from_cache=False,
            is_stale=False,
            is_valid=True,
        )

        with patch("app.web.fastapi_app.analyze_sentence", return_value=result) as mock:
            response = client.post(
                f"/analysis/sentence/{sentence_ids[0]}",
                data={
                    "user_translation": "猫坐在垫子上。",
                    "return_to": "/read/1",
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["user_translation"] == "猫坐在垫子上。"
        assert payload["analysis"]["diagnosis_basis"] == "user_translation"
        assert mock.call_args.kwargs["user_translation"] == "猫坐在垫子上。"
        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT archived_at, user_translation
                     FROM sentence_cards
                    WHERE sentence_id = ?""",
                (sentence_ids[0],),
            ).fetchone()
        assert row["archived_at"] is None
        assert row["user_translation"] == "猫坐在垫子上。"
        assert _sentence_error_codes(db, sentence_ids[0]) == {"G02"}

    def test_get_sentence_analysis_returns_saved_payload(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        cache_id = _attach_sentence_analysis(db, sentence_ids[0])

        response = client.get(f"/analysis/sentence/{sentence_ids[0]}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["cache_id"] == cache_id
        assert payload["from_cache"] is True
        assert payload["analysis"]["subject_skeleton"] == "The cat sat"

    def test_get_sentence_analysis_missing_returns_404(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.get(f"/analysis/sentence/{sentence_ids[0]}")

        assert response.status_code == 404
        assert response.json()["retry"] is True

    def test_analyze_sentence_endpoint_returns_retryable_error(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        with patch(
            "app.web.fastapi_app.analyze_sentence",
            side_effect=RuntimeError("LLM call failed"),
        ):
            response = client.post(f"/analysis/sentence/{sentence_ids[0]}")

        assert response.status_code == 502
        payload = response.json()
        assert payload["ok"] is False
        assert payload["retry"] is True
        assert "LLM call failed" in payload["error"]

    def test_unmark_sentence_archives_card_and_redirects(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})

        response = client.request(
            "DELETE",
            f"/mark/sentence/{sentence_ids[0]}",
            params={"return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/cards"
        with db.get_connection() as conn:
            archived_at = conn.execute(
                "SELECT archived_at FROM sentence_cards WHERE sentence_id = ?",
                (sentence_ids[0],),
            ).fetchone()["archived_at"]
        assert archived_at is not None

    def test_unmark_sentence_keeps_word_cards_active(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")

        response = client.request(
            "DELETE",
            f"/mark/sentence/{sentence_ids[0]}",
            params={"return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            archived_at = conn.execute(
                "SELECT archived_at FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()["archived_at"]
        assert archived_at is None

    def test_mark_sentence_missing_returns_400(self, client: TestClient) -> None:
        response = client.post("/mark/sentence/999", data={"return_to": "/cards"})

        assert response.status_code == 400
        assert "not found" in response.text

    def test_duplicate_sentence_mark_is_idempotent(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})

        response = client.post(
            f"/mark/sentence/{sentence_ids[0]}",
            data={"return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sentence_cards").fetchone()[0]
        assert count == 1

    def test_mark_word_creates_word_card(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert _word_card_id(db, "cat") > 0

    def test_mark_word_ajax_returns_word_card_payload(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ice masses",
                "lexical_type": "phrase",
                "return_to": "/read/1",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["created"] is True
        assert payload["card_id"] == _word_card_id(db, "ice masses")
        assert payload["word_card"] == {
            "id": payload["card_id"],
            "lemma": "ice masses",
            "surface_form": "ice masses",
            "lexical_type": "phrase",
            "current_meaning": "",
            "user_note": "",
        }

    def test_unmark_word_archives_word_card(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")

        response = client.request(
            "DELETE",
            f"/mark/word/{card_id}",
            params={"return_to": "/cards"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            archived_at = conn.execute(
                "SELECT archived_at FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()["archived_at"]
        assert archived_at is not None

    def test_patch_word_note_updates_meaning_and_note(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")

        response = client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "猫", "user_note": "常见词"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT current_meaning, user_note FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert row["current_meaning"] == "猫"
        assert row["user_note"] == "常见词"

    def test_patch_word_note_missing_card_returns_404(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        response = client.patch(
            "/mark/word/99999",
            data={"current_meaning": "x", "user_note": ""},
        )
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_read_page_embeds_meaning_and_note_in_word_card_spans(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )
        card_id = _word_card_id(db, "cat")
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "猫", "user_note": "宠物"},
        )

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert 'data-meaning="猫"' in response.text
        assert 'data-note="宠物"' in response.text

    def test_get_word_analysis_no_saved_returns_404(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={"sentence_id": str(sentence_ids[0]), "surface_form": "cat",
                  "lexical_type": "word", "return_to": "/cards"},
        )
        card_id = _word_card_id(db, "cat")

        response = client.get(f"/analysis/word/{card_id}")

        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_get_word_analysis_missing_card_returns_404(self, client: TestClient) -> None:
        response = client.get("/analysis/word/99999")
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_post_word_analysis_missing_card_returns_404(self, client: TestClient) -> None:
        response = client.post("/analysis/word/99999")
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_post_word_analysis_saves_and_returns_payload(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        from app.ai.llm_word_analyzer import WordAnalysisResult

        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={"sentence_id": str(sentence_ids[0]), "surface_form": "cat",
                  "lexical_type": "word", "return_to": "/cards"},
        )
        card_id = _word_card_id(db, "cat")
        mock_result = WordAnalysisResult(
            data=_VALID_WORD_ANALYSIS, cache_id=1, from_cache=False,
            is_stale=False, is_valid=True,
        )
        with patch("app.web.fastapi_app.analyze_word", return_value=mock_result), \
             patch("app.web.fastapi_app._update_word_card_analysis_id"):
            # Inject the cache row so _fetch_word_analysis_payload can find it
            with db.get_connection() as conn:
                cache_id = conn.execute(
                    """INSERT INTO ai_cache
                       (content_hash, prompt_version, model, response_json, is_valid, created_at)
                       VALUES ('h1', 'v1', 'test', ?, 1, '2026-01-01T00:00:00+00:00')""",
                    (json.dumps(_VALID_WORD_ANALYSIS),),
                ).lastrowid
                conn.execute(
                    "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                    (cache_id, card_id),
                )
            response = client.post(f"/analysis/word/{card_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["card_id"] == card_id
        assert payload["analysis"]["lemma"] == "cat"

    def test_post_word_analysis_falls_back_to_saved_payload_when_new_ai_invalid(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        from app.ai.llm_word_analyzer import WordAnalysisResult

        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={"sentence_id": str(sentence_ids[0]), "surface_form": "cat",
                  "lexical_type": "word", "return_to": "/cards"},
        )
        card_id = _word_card_id(db, "cat")
        with db.get_connection() as conn:
            cache_id = conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json, is_valid, created_at)
                   VALUES ('h_fallback', 'v1', 'test', ?, 1, '2026-01-01T00:00:00+00:00')""",
                (json.dumps(_VALID_WORD_ANALYSIS),),
            ).lastrowid
            conn.execute(
                "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )
        mock_result = WordAnalysisResult(
            data={}, cache_id=999, from_cache=False,
            is_stale=False, is_valid=False,
        )

        with patch("app.web.fastapi_app.analyze_word", return_value=mock_result):
            response = client.post(f"/analysis/word/{card_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["card_id"] == card_id
        assert payload["is_stale"] is True
        assert payload["retry"] is True
        assert "failed validation" in payload["warning"]
        assert payload["analysis"]["lemma"] == "cat"

    def test_get_word_analysis_returns_saved_payload(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={"sentence_id": str(sentence_ids[0]), "surface_form": "cat",
                  "lexical_type": "word", "return_to": "/cards"},
        )
        card_id = _word_card_id(db, "cat")
        with db.get_connection() as conn:
            cache_id = conn.execute(
                """INSERT INTO ai_cache
                   (content_hash, prompt_version, model, response_json, is_valid, created_at)
                   VALUES ('h2', 'v1', 'test', ?, 1, '2026-01-01T00:00:00+00:00')""",
                (json.dumps(_VALID_WORD_ANALYSIS),),
            ).lastrowid
            conn.execute(
                "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )

        response = client.get(f"/analysis/word/{card_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["surface_form"] == "cat"
        assert payload["sentence_id"] == sentence_ids[0]
        assert payload["active_prompt_version"] == "v4"
        assert payload["is_stale"] is True
        assert payload["analysis"]["meaning_in_context"] == "a small domestic feline animal"
        assert payload["analysis"]["chinese_meaning"] == "小型家养猫科动物"

    def test_read_page_includes_explain_button(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={"sentence_id": str(sentence_ids[0]), "surface_form": "cat",
                  "lexical_type": "word", "return_to": "/cards"},
        )

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert 'id="toolbar-word-detail-explain"' in response.text
        assert 'id="toolbar-word-detail-view-card"' in response.text
        assert 'id="analysis-panel-previous"' in response.text
        assert 'data-analysis-mark="word"' in response.text
        assert 'data-analysis-mark="phrase"' in response.text
        assert 'data-analysis-mark="collocation"' in response.text
        assert 'data-analysis-analyze="word"' in response.text
        assert 'id="toolbar-analysis-word-status"' in response.text
        assert 'id="analysis-word-sections"' in response.text
        assert 'id="analysis-sentence-sections"' in response.text
        assert "requestWordAnalysis" in response.text
        assert "markAnalysisSelection" in response.text
        assert "context_text" in response.text
        assert "analysisContextFromRange" in response.text
        assert "registerWordCard" in response.text
        assert "rebuildGlossaryRegex" in response.text
        assert '"X-Requested-With": "fetch"' in response.text
        assert "pushCurrentAnalysis" in response.text
        assert "restorePreviousAnalysis" in response.text
        assert "Back to ${previous.label} analysis" in response.text
        # §22 elements
        assert 'id="analysis-word-register"' in response.text
        assert 'id="analysis-word-why"' in response.text
        assert 'id="analysis-word-vs-simpler"' in response.text
        assert 'id="word-panel-notes"' in response.text
        assert 'id="word-panel-save"' in response.text
        assert 'id="analysis-word-pronunciation"' in response.text
        assert 'data-speak-text=""' in response.text
        assert "ERROR_CODE_LABELS" in response.text
        assert "word-analysis-active" in response.text
        assert "renderVsSimpler" in response.text
        assert "payload.surface_form || payload.lemma" in response.text
        assert "voiceschanged" in response.text
        assert "speechSynthesis.cancel()" in response.text
        assert "function applyGlossaryHighlights(element)" in response.text
        assert "glossaryEntries" in response.text
        assert "glossary-word" in response.text
        assert "function unregisterWordCard(cardId)" in response.text
        assert "function deleteAnalysisWordCardInPlace(cardId)" in response.text
        assert "showGlossaryWordDetail" in response.text
        assert 'panel.addEventListener("mouseover"' not in response.text
        assert "saveAnalysisMeaningIfEmpty" in response.text
        assert "glossary_return_url" in response.text
        assert "/cards#card-${cardId}" in response.text
        assert "background: #fef3c7" in response.text
        assert "max-width: min(calc(100vw - 16px), 520px)" in response.text
        assert ".word-detail-actions button" in response.text
        assert "flex-wrap: wrap" in response.text

    def test_toolbar_defaults_to_mutually_hidden_panels(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert '<form id="toolbar-sentence-form" method="post" class="toolbar-group" hidden>' in response.text
        assert (
            '<form id="toolbar-word-form" method="post" action="/mark/word" '
            'class="toolbar-group" hidden>'
        ) in response.text
        assert (
            '<form id="toolbar-analysis-word-form" method="post" action="/mark/word" '
            'class="toolbar-group" hidden>'
        ) in response.text
        assert 'id="toolbar-word-detail" class="toolbar-group word-detail-panel" hidden' in response.text
        assert 'id="toolbar-cross-sentence" class="toolbar-group" hidden' in response.text
        assert "toolbar-word-existing" not in response.text
        assert "toolbar-word-delete" not in response.text

    def test_toolbar_script_routes_existing_words_to_word_detail(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
                "return_to": "/cards",
            },
        )

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert "function hideAllPanels()" in response.text
        assert "function blurToolbarFocus()" in response.text
        assert "function selectionInsideToolbar(range)" in response.text
        assert "function selectionInsideAnalysisPanel(range)" in response.text
        assert "function showAnalysisWordToolbar(range, selectedText)" in response.text
        assert "if (toolbarContainsFocus()) return;" in response.text
        assert "if (selectionInsideToolbar(range)) return;" in response.text
        assert "if (selectionInsideAnalysisPanel(range))" in response.text
        assert 'reader.addEventListener("mousedown", () => {' in response.text
        assert "blurToolbarFocus();" in response.text
        assert "(!toolbar.hidden && toolbarContainsFocus())" not in response.text
        assert "let suppressNextUpdate = false;" in response.text
        assert "suppressNextUpdate = true;" in response.text
        assert "setVisible(wordDetail, true);" in response.text
        assert "setVisible(wordExisting" not in response.text
        assert "wordDelete.addEventListener" not in response.text

    def test_mark_word_invalid_input_returns_400(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "",
                "lexical_type": "word",
            },
        )

        assert response.status_code == 400
        assert "empty" in response.text

    def test_mark_word_ajax_invalid_input_returns_json_400(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)

        response = client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "",
                "lexical_type": "word",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["ok"] is False
        assert "empty" in response.json()["error"]

    def test_cards_page_shows_created_cards(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/cards"})
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
            },
        )

        response = client.get("/cards")

        assert response.status_code == 200
        assert "Sentence Cards" in response.text
        assert "cat" in response.text
        assert 'id="card-' in response.text
        assert 'data-delete-word-card="' in response.text
        assert ">Delete</button>" in response.text
        assert "glossary_return_url" in response.text
        assert "Back to reading" in response.text

    def test_cards_page_word_table_has_notes_column(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )

        response = client.get("/cards")

        assert "Notes" in response.text
        assert "AI Meaning" in response.text
        assert "Source" in response.text

    def test_cards_page_word_phrase_and_collocation_have_pronunciation_buttons(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        for surface_form, lexical_type in (
            ("cat", "word"),
            ("bright cold", "phrase"),
            ("sat on", "collocation"),
        ):
            client.post(
                "/mark/word",
                data={
                    "sentence_id": str(sentence_ids[0]),
                    "surface_form": surface_form,
                    "lexical_type": lexical_type,
                },
            )

        response = client.get("/cards")

        assert response.status_code == 200
        assert 'data-speak-text="cat"' in response.text
        assert 'data-speak-text="bright cold"' in response.text
        assert 'data-speak-text="sat on"' in response.text
        assert "Play pronunciation" in response.text

    def test_cards_page_links_word_and_source_to_first_sentence(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
            },
        )
        source_href = f"/read/{book_id}?chapter=1#sentence-{sentence_ids[0]}"

        response = client.get("/cards")

        assert response.status_code == 200
        assert response.text.count(f'href="{source_href}"') >= 2
        assert 'data-speak-text="cat"' in response.text

    def test_word_card_sources_page_adds_source_and_sets_primary(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
            },
        )
        card_id = _word_card_id(db, "cat")

        response = client.get(f"/cards/word/{card_id}/sources")

        assert response.status_code == 200
        assert "Sources: cat" in response.text
        assert "Find Occurrences" in response.text
        assert "Primary" in response.text

        response = client.post(
            f"/cards/word/{card_id}/sources",
            data={"sentence_id": str(sentence_ids[1])},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            card = conn.execute(
                "SELECT occurrence_count FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            source_id = conn.execute(
                "SELECT id FROM word_card_sources WHERE card_id = ? AND sentence_id = ?",
                (card_id, sentence_ids[1]),
            ).fetchone()["id"]
        assert card["occurrence_count"] == 2

        response = client.post(
            f"/cards/word/{card_id}/sources/{source_id}/primary",
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            card = conn.execute(
                "SELECT first_sentence_id FROM word_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        assert card["first_sentence_id"] == sentence_ids[1]

    def test_cards_page_note_input_preserves_current_meaning(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "rudimentary",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'rudimentary'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "basic and elementary", "user_note": ""},
        )

        response = client.get("/cards")

        assert 'data-current-meaning="basic and elementary"' in response.text

    def test_cards_page_ai_meaning_details_element(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        import json
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ontological",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ontological'"
            ).fetchone()["id"]
            cache_id = conn.execute(
                "INSERT INTO ai_cache (content_hash, prompt_version, model, "
                "response_json, is_valid, created_at) "
                "VALUES ('hashX', 'v2', 'gpt-4o-mini', ?, 1, '2026-01-01T00:00:00')",
                (json.dumps({"meaning_in_context": "relating to being or existence"}),),
            ).lastrowid
            conn.execute(
                "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )

        response = client.get("/cards")

        assert "<details>" not in response.text
        assert "▶ Reveal" in response.text
        assert "hover-popover-panel" in response.text
        assert "relating to being or existence" in response.text
        assert (
            f'href="/read/{book_id}?chapter=1&amp;word_card={card_id}#sentence-{sentence_ids[0]}"'
            in response.text
        )

    def test_cards_page_word_note_cell_has_edit_elements(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )

        response = client.get("/cards")

        assert "note-text" in response.text
        assert "note-edit-btn" in response.text
        assert "note-input" in response.text
        assert "data-card-id" in response.text

    def test_cards_page_note_cell_does_not_show_current_meaning(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ephemeral'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "lasting a very short time", "user_note": ""},
        )

        response = client.get("/cards")

        assert f'<span class="note-text" data-card-id="{card_id}">—</span>' in response.text
        assert 'data-current-meaning="lasting a very short time"' in response.text

    def test_cards_page_note_cell_shows_user_note(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ephemeral'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "lasting a very short time", "user_note": "my own note"},
        )

        response = client.get("/cards")

        assert "my own note" in response.text
        assert '<span class="note-text" data-card-id="' in response.text
        assert 'data-current-meaning="lasting a very short time"' in response.text

    def test_cards_page_note_cell_suppresses_note_duplicate_of_meaning(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ephemeral'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={
                "current_meaning": "lasting a very short time",
                "user_note": "lasting a very short time",
            },
        )

        response = client.get("/cards")

        assert f'<span class="note-text" data-card-id="{card_id}">—</span>' in response.text
        assert 'value=""' in response.text
        assert 'data-current-meaning="lasting a very short time"' in response.text


class TestReviewRoutes:
    def test_review_empty_message(self, client: TestClient) -> None:
        response = client.get("/review")

        assert response.status_code == 200
        assert "No cards due" in response.text

    def test_review_page_shows_due_card(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/review"})
        card_id = _sentence_card_id(db, sentence_ids[0])
        _make_due_yesterday(db, "sentence_cards", card_id)

        response = client.get("/review")

        assert response.status_code == 200
        assert "pass" in response.text
        assert f"/review/sentence/{card_id}" in response.text

    def test_review_page_shows_reveal_for_word_with_definition(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ephemeral'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "lasting a very short time", "user_note": "my own note"},
        )
        _make_due_yesterday(db, "word_cards", card_id)

        response = client.get("/review")

        assert "▶ Reveal" in response.text
        assert "hover-popover-panel" in response.text
        assert "Your note:" in response.text
        assert "my own note" in response.text

    def test_review_page_no_reveal_when_definition_empty(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ontological",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ontological'"
            ).fetchone()["id"]
        _make_due_yesterday(db, "word_cards", card_id)

        response = client.get("/review")

        assert "▶ Reveal" not in response.text
        assert 'class="hover-popover"' not in response.text

    def test_review_page_does_not_show_definition_as_note(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ephemeral'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "AI-backed meaning", "user_note": ""},
        )
        _make_due_yesterday(db, "word_cards", card_id)

        response = client.get("/review")

        assert "Your note:" not in response.text
        assert "AI-backed meaning" not in response.text

    def test_review_page_does_not_show_note_when_it_duplicates_definition(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "rudimentary",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'rudimentary'"
            ).fetchone()["id"]
            conn.execute(
                "UPDATE word_cards SET current_meaning = ?, user_note = ? WHERE id = ?",
                ("basic and undeveloped", "basic and undeveloped", card_id),
            )
        _make_due_yesterday(db, "word_cards", card_id)

        response = client.get("/review")

        assert "Your note:" not in response.text
        assert "basic and undeveloped" not in response.text

    def test_review_page_reveal_shows_ai_meaning(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "ephemeral",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'ephemeral'"
            ).fetchone()["id"]
            cache_id = conn.execute(
                "INSERT INTO ai_cache (content_hash, prompt_version, model, "
                "response_json, is_valid, created_at) "
                "VALUES ('hashR1', 'v2', 'gpt-4o-mini', ?, 1, '2026-01-01T00:00:00')",
                (json.dumps({"meaning_in_context": "lasting a very short time"}),),
            ).lastrowid
            conn.execute(
                "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )
        _make_due_yesterday(db, "word_cards", card_id)

        response = client.get("/review")

        assert "▶ Reveal" in response.text
        assert "hover-popover-panel" in response.text
        assert "AI meaning:" in response.text
        assert "lasting a very short time" in response.text

    def test_review_page_reveal_shows_both_user_and_ai(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "rudimentary",
                "lexical_type": "word",
            },
        )
        with db.get_connection() as conn:
            card_id = conn.execute(
                "SELECT id FROM word_cards WHERE surface_form = 'rudimentary'"
            ).fetchone()["id"]
        client.patch(
            f"/mark/word/{card_id}",
            data={"current_meaning": "基础的且简单的", "user_note": "我自己的笔记"},
        )
        with db.get_connection() as conn:
            cache_id = conn.execute(
                "INSERT INTO ai_cache (content_hash, prompt_version, model, "
                "response_json, is_valid, created_at) "
                "VALUES ('hashR2', 'v2', 'gpt-4o-mini', ?, 1, '2026-01-01T00:00:00')",
                (json.dumps({"meaning_in_context": "basic and undeveloped"}),),
            ).lastrowid
            conn.execute(
                "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                (cache_id, card_id),
            )
        _make_due_yesterday(db, "word_cards", card_id)

        response = client.get("/review")

        assert "▶ Reveal" in response.text
        assert "hover-popover-panel" in response.text
        assert "Your note:" in response.text
        assert "AI meaning:" in response.text
        assert "我自己的笔记" in response.text
        assert "basic and undeveloped" in response.text

    def test_review_page_pronunciation_only_for_word_prompts(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/review"})
        sentence_card_id = _sentence_card_id(db, sentence_ids[0])
        _make_due_yesterday(db, "sentence_cards", sentence_card_id)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
            },
        )
        word_card_id = _word_card_id(db, "cat")
        _make_due_yesterday(db, "word_cards", word_card_id)

        response = client.get("/review")

        assert response.status_code == 200
        assert 'data-speak-text="cat"' in response.text
        assert 'data-speak-text="The cat sat on the mat."' not in response.text

    def test_review_page_word_prompt_links_to_first_source_sentence(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={
                "sentence_id": str(sentence_ids[0]),
                "surface_form": "cat",
                "lexical_type": "word",
            },
        )
        word_card_id = _word_card_id(db, "cat")
        _make_due_yesterday(db, "word_cards", word_card_id)
        source_href = f"/read/{book_id}?chapter=1#sentence-{sentence_ids[0]}"

        response = client.get("/review")

        assert response.status_code == 200
        assert f'href="{source_href}"' in response.text
        assert 'data-speak-text="cat"' in response.text

    def test_review_page_sentence_prompt_has_no_source_link(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/review"})
        sentence_card_id = _sentence_card_id(db, sentence_ids[0])
        _make_due_yesterday(db, "sentence_cards", sentence_card_id)
        source_href = f"/read/{book_id}?chapter=1#sentence-{sentence_ids[0]}"

        response = client.get("/review")

        assert response.status_code == 200
        assert f'href="{source_href}"' not in response.text
        assert "The cat sat on the mat." in response.text

    def test_review_post_records_answer(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/review"})
        card_id = _sentence_card_id(db, sentence_ids[0])
        _make_due_yesterday(db, "sentence_cards", card_id)

        response = client.post(
            f"/review/sentence/{card_id}",
            data={"outcome": "pass", "return_to": "/review"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            log_count = conn.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
            review_count = conn.execute(
                "SELECT review_count FROM sentence_cards WHERE id = ?",
                (card_id,),
            ).fetchone()["review_count"]
        assert log_count == 1
        assert review_count == 1

    def test_review_post_invalid_outcome_returns_400(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(f"/mark/sentence/{sentence_ids[0]}", data={"return_to": "/review"})
        card_id = _sentence_card_id(db, sentence_ids[0])

        response = client.post(
            f"/review/sentence/{card_id}",
            data={"outcome": "easy"},
        )

        assert response.status_code == 400


class TestProfileRoutes:
    def test_profile_page_shows_empty_snapshot_state(self, client: TestClient) -> None:
        response = client.get("/profile")

        assert response.status_code == 200
        assert "No learner profile snapshots yet" in response.text

    def test_profile_prompt_renders_template(self, client: TestClient) -> None:
        response = client.get("/profile/prompt")

        assert response.status_code == 200
        assert "Learner Profile Summary Prompt" in response.text
        assert "{{ total_reviews }}" not in response.text

    def test_profile_save_persists_snapshot(self, client: TestClient, db: DatabaseConnection) -> None:
        response = client.post(
            "/profile/save",
            data={"summary_md": "## Current Weaknesses\n- Pronoun reference."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            row = conn.execute("SELECT summary_md FROM learner_profile_snapshots").fetchone()
        assert "Pronoun reference" in row["summary_md"]

    def test_profile_save_empty_returns_400(self, client: TestClient) -> None:
        response = client.post("/profile/save", data={"summary_md": ""})

        assert response.status_code == 400
        assert "summary_md" in response.text

    def test_profile_page_shows_latest_snapshot(self, client: TestClient, db: DatabaseConnection) -> None:
        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO learner_profile_snapshots
                   (created_at, summary_md, payload_json, cards_at_snapshot,
                    sentences_at_snapshot)
                   VALUES (?, ?, ?, 0, 0)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    "## Current Weaknesses\n- Modifier attachment.",
                    json.dumps({}),
                ),
            )

        response = client.get("/profile")

        assert response.status_code == 200
        assert "Modifier attachment" in response.text


class TestImportRoutes:
    def test_import_page_renders_both_forms(self, client: TestClient) -> None:
        response = client.get("/import")

        assert response.status_code == 200
        assert "Upload file" in response.text
        assert "Paste text" in response.text
        assert "/import/file" in response.text
        assert "/import/paste" in response.text
        assert ".epub" in response.text
        assert ".pdf" in response.text

    def test_import_nav_link_present(self, client: TestClient) -> None:
        response = client.get("/")

        assert "/import" in response.text

    # --- POST /import/file ---

    def test_import_file_success_redirects_to_read(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        content = b"The morning sun rose. Birds began to sing outside the window."
        response = client.post(
            "/import/file",
            files={"file": ("article.txt", content, "text/plain")},
            data={"title": "Morning Article", "author": "Test Author"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith("/read/")
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        assert count == 1

    def test_import_file_auto_title_from_first_line(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        content = b"The Grand Adventure\n\nThis story begins on a cold day."
        client.post(
            "/import/file",
            files={"file": ("a.txt", content, "text/plain")},
            data={"title": "", "author": ""},
            follow_redirects=False,
        )

        with db.get_connection() as conn:
            row = conn.execute("SELECT title FROM books LIMIT 1").fetchone()
        assert row["title"] == "The Grand Adventure"

    def test_import_file_auto_title_fallback_when_blank_bytes(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        # All lines empty/whitespace → title falls back to "Untitled Import …"
        content = b"   \n\nSome actual sentence here."
        client.post(
            "/import/file",
            files={"file": ("b.txt", content, "text/plain")},
            data={"title": "", "author": ""},
            follow_redirects=False,
        )

        with db.get_connection() as conn:
            row = conn.execute("SELECT title FROM books LIMIT 1").fetchone()
        assert "Some actual sentence here." in row["title"] or row["title"].startswith("Untitled Import")

    def test_import_file_empty_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/import/file",
            files={"file": ("empty.txt", b"", "text/plain")},
            data={"title": "Empty"},
        )

        assert response.status_code == 400
        assert "empty" in response.text.lower()

    def test_import_file_oversized_returns_413(self, client: TestClient) -> None:
        big = b"A" * (10 * 1024 * 1024 + 1)
        response = client.post(
            "/import/file",
            files={"file": ("big.txt", big, "text/plain")},
            data={"title": "Big"},
        )

        assert response.status_code == 413
        assert "10 MB" in response.text

    def test_import_file_duplicate_returns_409_with_link(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        content = b"A unique sentence for the duplicate file test."
        client.post(
            "/import/file",
            files={"file": ("dup.txt", content, "text/plain")},
            data={"title": "First Import"},
            follow_redirects=False,
        )
        response = client.post(
            "/import/file",
            files={"file": ("dup2.txt", content, "text/plain")},
            data={"title": "Second Import"},
        )

        assert response.status_code == 409
        assert "Already imported" in response.text
        assert "/read/" in response.text

    # --- POST /import/paste ---

    def test_import_paste_success_redirects_to_read(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        response = client.post(
            "/import/paste",
            data={
                "title": "Pasted Article",
                "author": "Paste Author",
                "text": "Science advances one experiment at a time. Results matter.",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith("/read/")
        with db.get_connection() as conn:
            row = conn.execute("SELECT title, author FROM books LIMIT 1").fetchone()
        assert row["title"] == "Pasted Article"
        assert row["author"] == "Paste Author"

    def test_import_paste_auto_title_from_text(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        client.post(
            "/import/paste",
            data={"title": "", "author": "", "text": "Auto Title Line\n\nBody paragraph here."},
            follow_redirects=False,
        )

        with db.get_connection() as conn:
            row = conn.execute("SELECT title FROM books LIMIT 1").fetchone()
        assert row["title"] == "Auto Title Line"

    def test_import_paste_empty_text_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/import/paste",
            data={"title": "Blank", "author": "", "text": ""},
        )

        assert response.status_code == 400
        assert "empty" in response.text.lower()

    def test_import_paste_whitespace_only_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/import/paste",
            data={"title": "WS", "author": "", "text": "   \n\t  "},
        )

        assert response.status_code == 400

    def test_import_paste_oversized_returns_413(self, client: TestClient) -> None:
        big = "A" * (10 * 1024 * 1024 + 1)
        response = client.post(
            "/import/paste",
            data={"title": "Big", "author": "", "text": big},
        )

        assert response.status_code == 413

    def test_import_paste_duplicate_returns_409(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        text = "A unique sentence for the paste duplicate test."
        client.post(
            "/import/paste",
            data={"title": "First Paste", "author": "", "text": text},
            follow_redirects=False,
        )
        response = client.post(
            "/import/paste",
            data={"title": "Second Paste", "author": "", "text": text},
        )

        assert response.status_code == 409
        assert "Already imported" in response.text

    def test_file_and_paste_same_content_collide(
        self, client: TestClient, db: DatabaseConnection
    ) -> None:
        """File import and paste import share file_hash space — same bytes = duplicate."""
        content = "Cross-channel duplicate detection sentence."
        client.post(
            "/import/file",
            files={"file": ("x.txt", content.encode("utf-8"), "text/plain")},
            data={"title": "Via File"},
            follow_redirects=False,
        )
        response = client.post(
            "/import/paste",
            data={"title": "Via Paste", "author": "", "text": content},
        )

        assert response.status_code == 409

    # --- POST /import/file (EPUB) ---

    def test_import_epub_file_success_redirects_to_read(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        from tests.importers.epub_builder import make_epub

        epub_path = make_epub(tmp_path, "test.epub", title="My EPUB Book")
        epub_bytes = epub_path.read_bytes()

        response = client.post(
            "/import/file",
            files={"file": ("test.epub", epub_bytes, "application/epub+zip")},
            data={"title": "My EPUB Book", "author": "Author One"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith("/read/")
        with db.get_connection() as conn:
            row = conn.execute("SELECT title, source_format FROM books LIMIT 1").fetchone()
        assert row["title"] == "My EPUB Book"
        assert row["source_format"] == "epub"

    def test_import_epub_file_auto_title_from_epub_metadata(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        from tests.importers.epub_builder import make_epub

        epub_path = make_epub(tmp_path, "meta.epub", title="Metadata Title", author="Meta Author")
        epub_bytes = epub_path.read_bytes()

        response = client.post(
            "/import/file",
            files={"file": ("meta.epub", epub_bytes, "application/epub+zip")},
            data={"title": "", "author": ""},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with db.get_connection() as conn:
            row = conn.execute("SELECT title, author FROM books LIMIT 1").fetchone()
        assert row["title"] == "Metadata Title"
        assert row["author"] == "Meta Author"

    def test_import_epub_file_duplicate_returns_409(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        from tests.importers.epub_builder import make_epub

        epub_path = make_epub(tmp_path, "dup.epub")
        epub_bytes = epub_path.read_bytes()

        client.post(
            "/import/file",
            files={"file": ("dup.epub", epub_bytes, "application/epub+zip")},
            data={"title": "First", "author": ""},
            follow_redirects=False,
        )
        response = client.post(
            "/import/file",
            files={"file": ("dup2.epub", epub_bytes, "application/epub+zip")},
            data={"title": "Second", "author": ""},
        )

        assert response.status_code == 409
        assert "Already imported" in response.text

    def test_import_epub_file_oversized_returns_413_and_removes_temp(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.web.fastapi_app as fastapi_app

        real_named_temporary_file = tempfile.NamedTemporaryFile

        def named_temporary_file_in_tmp(*args, **kwargs):
            kwargs["dir"] = tmp_path
            return real_named_temporary_file(*args, **kwargs)

        monkeypatch.setattr(fastapi_app, "_MAX_EPUB_IMPORT_BYTES", 1024 * 1024)
        monkeypatch.setattr(
            fastapi_app.tempfile,
            "NamedTemporaryFile",
            named_temporary_file_in_tmp,
        )

        response = client.post(
            "/import/file",
            files={
                "file": (
                    "big.epub",
                    b"A" * (1024 * 1024 + 1),
                    "application/epub+zip",
                )
            },
            data={"title": "Big"},
        )

        assert response.status_code == 413
        assert "Uploaded EPUB exceeds 1 MB limit" in response.text
        assert list(tmp_path.glob("*.epub")) == []

    # --- POST /import/file (PDF) ---

    def test_import_pdf_file_success_redirects_to_read(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        pdf_path = make_text_pdf(tmp_path, "test.pdf", title="My PDF Book")
        pdf_bytes = pdf_path.read_bytes()

        response = client.post(
            "/import/file",
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
            data={"title": "My PDF Book", "author": "Author One"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith("/read/")
        with db.get_connection() as conn:
            row = conn.execute("SELECT title, source_format FROM books LIMIT 1").fetchone()
        assert row["title"] == "My PDF Book"
        assert row["source_format"] == "pdf"

    def test_import_pdf_file_duplicate_returns_409(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        pdf_path = make_text_pdf(tmp_path, "dup.pdf")
        pdf_bytes = pdf_path.read_bytes()

        client.post(
            "/import/file",
            files={"file": ("dup.pdf", pdf_bytes, "application/pdf")},
            data={"title": "First", "author": ""},
            follow_redirects=False,
        )
        response = client.post(
            "/import/file",
            files={"file": ("dup2.pdf", pdf_bytes, "application/pdf")},
            data={"title": "Second", "author": ""},
        )

        assert response.status_code == 409
        assert "Already imported" in response.text

    def test_import_pdf_file_oversized_returns_413_and_removes_temp(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.web.fastapi_app as fastapi_app

        real_named_temporary_file = tempfile.NamedTemporaryFile

        def named_temporary_file_in_tmp(*args, **kwargs):
            kwargs["dir"] = tmp_path
            return real_named_temporary_file(*args, **kwargs)

        monkeypatch.setattr(fastapi_app, "_MAX_PDF_IMPORT_BYTES", 1024 * 1024)
        monkeypatch.setattr(
            fastapi_app.tempfile,
            "NamedTemporaryFile",
            named_temporary_file_in_tmp,
        )

        response = client.post(
            "/import/file",
            files={
                "file": (
                    "big.pdf",
                    b"A" * (1024 * 1024 + 1),
                    "application/pdf",
                )
            },
            data={"title": "Big"},
        )

        assert response.status_code == 413
        assert "Uploaded PDF exceeds 1 MB limit" in response.text
        assert list(tmp_path.glob("*.pdf")) == []


# ---------------------------------------------------------------------------
# §22 — Word analysis panel v2 improvements
# ---------------------------------------------------------------------------

class TestWordAnalysisPanelV2:
    """Tests for §22: word highlight, error code expansion, v2 schema, notes section."""

    @pytest.fixture()
    def client(self, db: DatabaseConnection) -> TestClient:
        app = create_app(lambda: db)
        return TestClient(app, raise_server_exceptions=True)

    def test_panel_has_no_collocations_or_synonyms_sections(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert 'id="analysis-word-collocations"' not in response.text
        assert 'id="analysis-word-synonyms"' not in response.text

    def test_panel_has_register_and_why_sections(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert 'id="analysis-word-register"' in response.text
        assert 'id="analysis-word-why"' in response.text
        assert 'id="analysis-word-vs-simpler"' in response.text
        assert 'id="analysis-word-meaning-zh"' in response.text

    def test_panel_has_notes_section_inputs(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert 'id="word-panel-notes"' in response.text
        assert 'id="word-panel-meaning"' in response.text
        assert 'id="word-panel-note"' in response.text
        assert 'id="word-panel-save"' in response.text
        assert 'id="word-panel-save-status"' in response.text

    def test_js_has_error_code_labels_table(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert "ERROR_CODE_LABELS" in response.text
        assert "L06" in response.text
        assert "G01" in response.text

    def test_js_has_render_vs_simpler(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert "renderVsSimpler" in response.text
        assert "vs-simpler-item" in response.text

    def test_js_has_word_highlight_logic(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert "word-analysis-active" in response.text

    def test_js_has_panel_save_listener(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert "wordPanelSave" in response.text
        assert "wordPanelSaveStatus" in response.text

    def test_js_renders_chinese_word_meaning(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, _ = _seed_book(db, tmp_path)
        response = client.get(f"/read/{book_id}")
        assert response.status_code == 200
        assert "wordAnalysisMeaningZh" in response.text
        assert "a.chinese_meaning || a.chinese_gloss" in response.text
        assert "中文：" in response.text

    def test_post_word_analysis_v2_payload_returned(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        from app.ai.llm_word_analyzer import WordAnalysisResult

        _, sentence_ids = _seed_book(db, tmp_path)
        client.post(
            "/mark/word",
            data={"sentence_id": str(sentence_ids[0]), "surface_form": "cat",
                  "lexical_type": "word", "return_to": "/cards"},
        )
        card_id = _word_card_id(db, "cat")
        mock_result = WordAnalysisResult(
            data=_VALID_WORD_ANALYSIS, cache_id=10, from_cache=False,
            is_stale=False, is_valid=True,
        )
        with patch("app.web.fastapi_app.analyze_word", return_value=mock_result), \
             patch("app.web.fastapi_app._update_word_card_analysis_id"):
            with db.get_connection() as conn:
                cache_id = conn.execute(
                    """INSERT INTO ai_cache
                       (content_hash, prompt_version, model, response_json, is_valid, created_at)
                       VALUES ('hv2', 'v2', 'test', ?, 1, '2026-01-01T00:00:00+00:00')""",
                    (json.dumps(_VALID_WORD_ANALYSIS),),
                ).lastrowid
                conn.execute(
                    "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
                    (cache_id, card_id),
                )
            response = client.post(f"/analysis/word/{card_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["analysis"]["register"] == "neutral"
        assert "vs_simpler" in payload["analysis"]
