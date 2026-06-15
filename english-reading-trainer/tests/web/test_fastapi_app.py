"""
Tests for app/web/fastapi_app.py.

Uses FastAPI TestClient with real SQLite databases. No network or browser is
required for these route-level tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.ai.llm_sentence_analyzer import SentenceAnalysisResult
from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from app.web.fastapi_app import create_app

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
        assert count == 4
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
        assert "window.prompt" not in response.text
        assert f"reader:progress:book:${{bookId}}" in response.text
        assert 'data-restore-progress="1"' in response.text
        assert "top_sentence_id" in response.text
        assert "/mark/word" in response.text
        assert "selectedWordCardIds" in response.text
        assert "deleteWordCardsAndReload" in response.text

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
        assert f'<span data-word-card="{card_id}">cat</span>' in response.text

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

    def test_save_sentence_translation_creates_card_and_redirects(
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
                """SELECT user_translation, translation_created_at
                     FROM sentence_cards
                    WHERE sentence_id = ?""",
                (sentence_ids[0],),
            ).fetchone()
        assert row["user_translation"] == "猫坐在垫子上。"
        assert row["translation_created_at"] is not None

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
                "SELECT user_translation FROM sentence_cards WHERE sentence_id = ?",
                (sentence_ids[0],),
            ).fetchone()
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


class TestImportRoutes:
    def test_import_page_renders_both_forms(self, client: TestClient) -> None:
        response = client.get("/import")

        assert response.status_code == 200
        assert "Upload TXT file" in response.text
        assert "Paste text" in response.text
        assert "/import/file" in response.text
        assert "/import/paste" in response.text

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
