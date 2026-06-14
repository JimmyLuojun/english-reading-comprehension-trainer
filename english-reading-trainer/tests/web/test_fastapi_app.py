"""
Tests for app/web/fastapi_app.py.

Uses FastAPI TestClient with real SQLite databases. No network or browser is
required for these route-level tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from app.web.fastapi_app import create_app

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


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
        "The cat sat on the mat. It was a bright cold day. The clocks struck thirteen.",
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


def _make_due_yesterday(db: DatabaseConnection, table_name: str, card_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute(
            f"UPDATE {table_name} SET due_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), card_id),
        )


class TestBasicPages:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

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


class TestReadingAndMarking:
    def test_read_page_shows_sentences_and_mark_forms(
        self, client: TestClient, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        book_id, sentence_ids = _seed_book(db, tmp_path)

        response = client.get(f"/read/{book_id}")

        assert response.status_code == 200
        assert "The cat sat" in response.text
        assert f"/mark/sentence/{sentence_ids[0]}" in response.text
        assert "/mark/word" in response.text

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
