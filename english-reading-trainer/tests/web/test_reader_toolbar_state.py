"""
Browser-level tests for the reader selection toolbar state machine.

These tests use a local uvicorn server plus Playwright when a browser can be
started in the current environment. Route-level toolbar assertions live in
test_fastapi_app.py so the core regression coverage remains available without
a browser runtime.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn import Config, Server

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Error as PlaywrightError, Page, sync_playwright

from app.db_connection import DatabaseConnection
from app.importers.txt_importer import import_txt
from app.web.fastapi_app import create_app

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
PANEL_IDS = {
    "sentence": "toolbar-sentence-form",
    "word": "toolbar-word-form",
    "word_detail": "toolbar-word-detail",
    "analysis_word": "toolbar-analysis-word-form",
    "cross_sentence": "toolbar-cross-sentence",
    "translation": "toolbar-translation-editor",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Server on port {port} did not start")


def _seed_reader(db: DatabaseConnection, tmp_path: Path) -> int:
    source = tmp_path / "reader.txt"
    source.write_text(
        "The cat sat on the mat. It was a bright cold day.\n\n"
        "The clocks struck thirteen.",
        encoding="utf-8",
    )
    result = import_txt(db, source, title="Toolbar Book", author="Author")
    with db.get_connection() as conn:
        sentence_id = conn.execute(
            "SELECT id FROM sentences WHERE book_id = ? ORDER BY id LIMIT 1",
            (result.book_id,),
        ).fetchone()["id"]

    client = TestClient(create_app(lambda: db))
    response = client.post(
        "/mark/word",
        data={
            "sentence_id": str(sentence_id),
            "surface_form": "cat",
            "lexical_type": "word",
            "return_to": "/cards",
        },
    )
    assert response.status_code == 200
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE word_cards SET current_meaning = ? WHERE lemma = ?",
            ("a small domestic feline", "cat"),
        )
    _attach_sentence_analysis(db, sentence_id)
    return int(result.book_id)


def _attach_sentence_analysis(db: DatabaseConnection, sentence_id: int) -> int:
    payload = {
        "subject_skeleton": "The cat sat",
        "clauses": [{"type": "main", "text": "The cat sat", "role": "statement"}],
        "modifiers": [],
        "logic_markers": [],
        "anaphora": [],
        "simplified_en": "The feline rested.",
        "chinese_gloss": "Cat rests.",
        "predicted_error_types": ["G01"],
        "diagnosis_basis": "predicted",
        "diagnosed_error_types": [],
        "diagnosis_evidence": [],
        "confidence": 0.9,
    }
    now = datetime.now(timezone.utc).isoformat()
    with db.get_connection() as conn:
        card_id = conn.execute(
            """INSERT INTO sentence_cards
               (sentence_id, created_at, last_reviewed_at, review_count,
                mastery_state, ef, interval_days, repetitions, due_at)
               VALUES (?, ?, NULL, 0, 'new', 2.5, 1, 0, ?)""",
            (sentence_id, now, now),
        ).lastrowid
        cache_id = conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES (?, 'v1', 'manual', ?, 1, ?)""",
            (
                f"toolbar-analysis-{sentence_id}",
                json.dumps(payload),
                now,
            ),
        ).lastrowid
        conn.execute(
            "UPDATE sentence_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    return int(cache_id)


def _visible_panels(page: Page) -> dict[str, bool]:
    return page.evaluate(
        """(panelIds) => {
          const state = {
            toolbar: !document.getElementById("selection-toolbar").hidden,
            word_existing_present: Boolean(document.getElementById("toolbar-word-existing")),
          };
          for (const [key, id] of Object.entries(panelIds)) {
            const element = document.getElementById(id);
            state[key] = Boolean(element && !element.hidden);
          }
          return state;
        }""",
        PANEL_IDS,
    )


def _assert_only_panel(page: Page, panel_name: str) -> None:
    state = _visible_panels(page)
    assert state["toolbar"] is True
    assert state["word_existing_present"] is False
    for key in PANEL_IDS:
        assert state[key] is (key == panel_name), state


def _select_across_first_two_sentences(page: Page) -> None:
    page.evaluate(
        """() => {
          const spans = Array.from(document.querySelectorAll("[data-sentence-id]"));
          const range = document.createRange();
          range.setStartBefore(spans[0]);
          range.setEndAfter(spans[1]);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.dispatchEvent(new Event("selectionchange"));
        }"""
    )
    page.wait_for_timeout(60)


def _select_sentence_contents(page: Page, sentence_index: int) -> None:
    page.evaluate(
        """(sentenceIndex) => {
          const sentence = document.querySelectorAll("[data-sentence-id]")[sentenceIndex];
          const range = document.createRange();
          range.selectNodeContents(sentence);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.dispatchEvent(new Event("selectionchange"));
        }""",
        sentence_index,
    )
    page.wait_for_timeout(60)


def _select_sentence_touching_previous_boundary(page: Page, sentence_index: int) -> None:
    page.evaluate(
        """(sentenceIndex) => {
          const spans = Array.from(document.querySelectorAll("[data-sentence-id]"));
          const previous = spans[sentenceIndex - 1];
          const sentence = spans[sentenceIndex];
          const range = document.createRange();
          range.setStart(previous, previous.childNodes.length);
          range.setEndAfter(sentence);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.dispatchEvent(new Event("selectionchange"));
        }""",
        sentence_index,
    )
    page.wait_for_timeout(60)


def _select_text(page: Page, sentence_index: int, text: str) -> None:
    page.evaluate(
        """({sentenceIndex, text}) => {
          const sentence = document.querySelectorAll("[data-sentence-id]")[sentenceIndex];
          const walker = document.createTreeWalker(sentence, NodeFilter.SHOW_TEXT);
          let node = walker.nextNode();
          while (node) {
            const index = node.nodeValue.indexOf(text);
            if (index >= 0) {
              const range = document.createRange();
              range.setStart(node, index);
              range.setEnd(node, index + text.length);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
              return;
            }
            node = walker.nextNode();
          }
          throw new Error(`Text not found: ${text}`);
        }""",
        {"sentenceIndex": sentence_index, "text": text},
    )
    page.wait_for_timeout(60)


def _select_text_until_panel(page: Page, sentence_index: int, text: str, panel_id: str) -> None:
    for _ in range(3):
        _select_text(page, sentence_index, text)
        try:
            page.wait_for_function(
                f'!document.getElementById("{panel_id}").hidden',
                timeout=1000,
            )
            return
        except PlaywrightError:
            page.evaluate("document.dispatchEvent(new Event('selectionchange'))")
    page.wait_for_function(f'!document.getElementById("{panel_id}").hidden')


def _new_page(browser: Browser, url: str) -> Iterator[Page]:
    page = browser.new_page()
    page.goto(url)
    try:
        yield page
    finally:
        page.close()


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    connection = DatabaseConnection(tmp_path / "toolbar.db")
    connection.apply_migrations(MIGRATIONS_DIR)
    return connection


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Playwright Chromium is unavailable in this environment: {exc}")
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def reader_url(db: DatabaseConnection, tmp_path: Path) -> Iterator[str]:
    book_id = _seed_reader(db, tmp_path)
    port = _free_port()
    server = Server(
        Config(
            create_app(lambda: db),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_port(port)
    try:
        yield f"http://127.0.0.1:{port}/read/{book_id}?chapter=1"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_initial_toolbar_panels_are_hidden(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        state = _visible_panels(page)

    assert state == {
        "toolbar": False,
        "word_existing_present": False,
        "sentence": False,
        "word": False,
        "word_detail": False,
        "analysis_word": False,
        "cross_sentence": False,
        "translation": False,
    }


def test_analysis_panel_overlays_reader_without_layout_shift(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        before = page.evaluate(
            """() => {
              const rect = document.querySelector(".reader").getBoundingClientRect();
              return { left: rect.left, width: rect.width };
            }"""
        )

        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        after = page.evaluate(
            """() => {
              const readerRect = document.querySelector(".reader").getBoundingClientRect();
              const panel = document.getElementById("analysis-panel");
              const panelStyle = getComputedStyle(panel);
              const panelRect = panel.getBoundingClientRect();
              return {
                bodyClass: document.body.className,
                left: readerRect.left,
                panelPosition: panelStyle.position,
                panelRight: Math.round(window.innerWidth - panelRect.right),
                panelWidth: panelRect.width,
                width: readerRect.width,
              };
            }"""
        )

    assert after["bodyClass"] == "reader-page analysis-open"
    assert after["left"] == before["left"]
    assert after["width"] == before["width"]
    assert after["panelPosition"] == "fixed"
    assert after["panelRight"] == 0
    assert after["panelWidth"] <= 520


def test_click_marked_word_shows_only_word_detail(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')

        _assert_only_panel(page, "word_detail")


def test_double_click_marked_word_shows_only_word_detail(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").dblclick()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')

        _assert_only_panel(page, "word_detail")


def test_word_detail_save_updates_span_and_hides_toolbar(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").click()
        page.locator("#toolbar-word-detail-meaning").fill("feline")
        page.locator("#toolbar-word-detail-note").fill("common noun")
        page.locator("#toolbar-word-detail-save").click()
        page.wait_for_function(
            """() => {
              const span = document.querySelector("[data-word-card]");
              return document.getElementById("selection-toolbar").hidden
                && span.dataset.meaning === "feline"
                && span.dataset.note === "common noun";
            }"""
        )

        state = _visible_panels(page)

    assert state["toolbar"] is False
    assert state["word_detail"] is False


def test_selection_modes_are_mutually_exclusive(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        _select_across_first_two_sentences(page)
        _assert_only_panel(page, "cross_sentence")

        _select_sentence_contents(page, 0)
        _assert_only_panel(page, "sentence")

        _select_text(page, 1, "bright")
        _assert_only_panel(page, "word")


def test_mark_word_keeps_reader_scroll_position(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    for page in _new_page(browser, reader_url):
        page.evaluate(
            """() => {
              document.querySelector(".reader").style.paddingTop = "1000px";
              window.scrollTo(0, 880);
            }"""
        )
        _select_text_until_panel(page, 1, "bright", "toolbar-word-form")
        before = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[1];
              return {
                sentenceTop: sentence.getBoundingClientRect().top,
                scrollY: window.scrollY,
                url: window.location.href,
              };
            }"""
        )

        page.locator('#toolbar-word-form button[value="word"]').click()
        page.wait_for_function(
            """() => Array.from(document.querySelectorAll("[data-word-card]"))
              .some((node) => node.textContent === "bright")"""
        )
        after = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[1];
              return {
                brightMarked: Array.from(document.querySelectorAll("[data-word-card]"))
                  .some((node) => node.textContent === "bright"),
                sentenceTop: sentence.getBoundingClientRect().top,
                scrollY: window.scrollY,
                toolbarHidden: document.getElementById("selection-toolbar").hidden,
                url: window.location.href,
              };
            }"""
        )

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT lexical_type FROM word_cards WHERE lemma = ? AND archived_at IS NULL",
            ("bright",),
        ).fetchone()

    assert before["scrollY"] > 0
    assert after["url"] == before["url"]
    assert abs(after["sentenceTop"] - before["sentenceTop"]) <= 1
    assert after["scrollY"] > 0
    assert after["toolbarHidden"] is True
    assert after["brightMarked"] is True
    assert row is not None
    assert row["lexical_type"] == "word"


def test_remove_word_card_keeps_reader_scroll_position(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.evaluate(
            """() => {
              document.querySelector(".reader").style.paddingTop = "1000px";
              window.scrollTo(0, 880);
            }"""
        )
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        before = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[0];
              return {
                sentenceTop: sentence.getBoundingClientRect().top,
                scrollY: window.scrollY,
                url: window.location.href,
              };
            }"""
        )

        page.locator("#toolbar-word-detail-remove").click()
        page.wait_for_function('document.querySelectorAll("[data-word-card]").length === 0')
        after = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[0];
              return {
                remainingWordCards: document.querySelectorAll("[data-word-card]").length,
                sentenceTop: sentence.getBoundingClientRect().top,
                scrollY: window.scrollY,
                toolbarHidden: document.getElementById("selection-toolbar").hidden,
                url: window.location.href,
              };
            }"""
        )

    assert before["scrollY"] > 0
    assert after["url"] == before["url"]
    assert abs(after["sentenceTop"] - before["sentenceTop"]) <= 1
    assert after["scrollY"] > 0
    assert after["toolbarHidden"] is True
    assert after["remainingWordCards"] == 0


def test_sentence_boundary_touch_does_not_count_as_cross_sentence(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_sentence_touching_previous_boundary(page, 1)
        _assert_only_panel(page, "sentence")
        analysis_hidden = page.locator("#toolbar-analysis-open").evaluate(
            "element => element.hidden"
        )

    assert analysis_hidden is False


def test_collapsed_selection_after_word_detail_hides_toolbar(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.wait_for_timeout(300)
        page.evaluate(
            """() => {
              window.getSelection().removeAllRanges();
              document.dispatchEvent(new Event("selectionchange"));
            }"""
        )
        page.wait_for_function('document.getElementById("selection-toolbar").hidden')

        state = _visible_panels(page)

    assert state["toolbar"] is False
    assert state["word_detail"] is False


def test_selection_after_visible_toolbar_focus_shows_word_actions(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.locator("#toolbar-word-detail-meaning").focus()
        page.evaluate(
            """() => {
              document.dispatchEvent(new Event("selectionchange"));
            }"""
        )

        _select_text(page, 1, "bright")
        _assert_only_panel(page, "word")


def test_analysis_panel_selection_shows_mark_word(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        page.evaluate(
            """() => {
              const node = document.getElementById("analysis-simplified").firstChild;
              const index = node.nodeValue.indexOf("feline");
              const range = document.createRange();
              range.setStart(node, index);
              range.setEnd(node, index + "feline".length);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }"""
        )
        page.wait_for_function('!document.getElementById("toolbar-analysis-word-form").hidden')
        _assert_only_panel(page, "analysis_word")
        form_values = page.evaluate(
            """() => ({
              sentenceId: document.getElementById("toolbar-analysis-word-sentence-id").value,
              surfaceForm: document.getElementById("toolbar-analysis-word-surface-form").value,
              markWord: Boolean(document.querySelector('[data-analysis-mark="word"]')),
              markPhrase: Boolean(document.querySelector('[data-analysis-mark="phrase"]')),
              markCollocation: Boolean(document.querySelector('[data-analysis-mark="collocation"]')),
              aiAnalysis: Boolean(document.querySelector('[data-analysis-analyze="word"]')),
            })"""
        )

    assert form_values["sentenceId"]
    assert form_values["surfaceForm"] == "feline"
    assert form_values["markWord"] is True
    assert form_values["markPhrase"] is True
    assert form_values["markCollocation"] is True
    assert form_values["aiAnalysis"] is True


def test_analysis_panel_mark_phrase_keeps_current_analysis(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        before_url = page.url
        page.evaluate(
            """() => {
              const node = document.getElementById("analysis-simplified").firstChild;
              const index = node.nodeValue.indexOf("feline");
              const range = document.createRange();
              range.setStart(node, index);
              range.setEnd(node, index + "feline".length);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }"""
        )
        page.wait_for_function('!document.getElementById("toolbar-analysis-word-form").hidden')
        page.locator('[data-analysis-mark="phrase"]').click()
        page.wait_for_function(
            'document.getElementById("toolbar-analysis-word-status").textContent === "Saved"'
        )
        state = page.evaluate(
            """() => ({
              url: window.location.href,
              panelHidden: document.getElementById("analysis-panel").hidden,
              simplified: document.getElementById("analysis-simplified").textContent,
              highlighted: Boolean(document.querySelector("#analysis-simplified .glossary-word")),
            })"""
        )

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT lexical_type FROM word_cards WHERE lemma = ? AND archived_at IS NULL",
            ("feline",),
        ).fetchone()

    assert state == {
        "url": before_url,
        "panelHidden": False,
        "simplified": "The feline rested.",
        "highlighted": True,
    }
    assert row is not None
    assert row["lexical_type"] == "phrase"


def test_analysis_panel_ai_analysis_marks_then_returns_to_previous_analysis(
    browser: Browser,
    reader_url: str,
) -> None:
    def fulfill_word_analysis(route) -> None:  # type: ignore[no-untyped-def]
        card_id = int(route.request.url.rstrip("/").rsplit("/", 1)[-1])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True,
                "card_id": card_id,
                "sentence_id": 1,
                "lemma": "feline",
                "surface_form": "feline",
                "lexical_type": "word",
                "analysis": {
                    "meaning_in_context": "catlike animal",
                    "chinese_meaning": "猫科动物",
                    "register": "neutral",
                    "why_this_word": "It names the animal precisely.",
                    "vs_simpler": [],
                    "morphology": {"root": "felis", "family": ["feline"]},
                    "predicted_error_types": ["L01"],
                },
                "cache_id": 1,
                "prompt_version": "v3",
                "active_prompt_version": "v3",
                "from_cache": False,
                "is_stale": False,
            }),
        )

    for page in _new_page(browser, reader_url):
        page.route("**/analysis/word/*", fulfill_word_analysis)
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        page.evaluate(
            """() => {
              const node = document.getElementById("analysis-simplified").firstChild;
              const index = node.nodeValue.indexOf("feline");
              const range = document.createRange();
              range.setStart(node, index);
              range.setEnd(node, index + "feline".length);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }"""
        )
        page.wait_for_function('!document.getElementById("toolbar-analysis-word-form").hidden')
        page.locator('[data-analysis-analyze="word"]').click()
        page.wait_for_function(
            'document.getElementById("analysis-word-meaning").textContent === "catlike animal"'
        )
        word_state = page.evaluate(
            """() => ({
              previousHidden: document.getElementById("analysis-panel-previous").hidden,
              previousText: document.getElementById("analysis-panel-previous").textContent,
              wordSectionsHidden: document.getElementById("analysis-word-sections").hidden,
            })"""
        )

        page.locator("#analysis-panel-previous").click()
        page.wait_for_function('!document.getElementById("analysis-sentence-sections").hidden')
        restored_state = page.evaluate(
            """() => ({
              previousHidden: document.getElementById("analysis-panel-previous").hidden,
              simplified: document.getElementById("analysis-simplified").textContent,
              sentenceSectionsHidden: document.getElementById("analysis-sentence-sections").hidden,
            })"""
        )

    assert word_state == {
        "previousHidden": False,
        "previousText": "Back to sentence analysis",
        "wordSectionsHidden": False,
    }
    assert restored_state == {
        "previousHidden": True,
        "simplified": "The feline rested.",
        "sentenceSectionsHidden": False,
    }


def test_analysis_panel_glossary_word_opens_detail_then_links_to_cards_and_back(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        glossary_word = page.locator("#analysis-gloss .glossary-word").first
        glossary_word.wait_for()
        glossary_state = glossary_word.evaluate(
            """(element) => ({
              text: element.textContent,
              cardId: element.dataset.cardId,
              meaning: element.dataset.meaning,
            })"""
        )

        glossary_word.hover()
        page.wait_for_timeout(120)
        assert page.locator("#toolbar-word-detail").evaluate("(element) => element.hidden") is True
        glossary_word.click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        _assert_only_panel(page, "word_detail")
        detail_state = page.evaluate(
            """() => ({
              surface: document.getElementById("toolbar-word-detail-surface").textContent,
              meaning: document.getElementById("toolbar-word-detail-meaning").value,
              viewCardId: document.getElementById("toolbar-word-detail-view-card").dataset.cardId,
            })"""
        )

        page.locator("#toolbar-word-detail-view-card").click()
        page.wait_for_url("**/cards#card-*")
        cards_state = page.evaluate(
            """(cardId) => ({
              hash: window.location.hash,
              targetFound: Boolean(document.getElementById(`card-${cardId}`)),
              returnVisible: Boolean(document.querySelector(".glossary-return")),
              returnHref: document.querySelector(".glossary-return")?.href || "",
            })""",
            glossary_state["cardId"],
        )
        page.locator(".glossary-return").click()
        page.wait_for_url("**/read/*")
        returned_path = page.evaluate("window.location.pathname")

    assert glossary_state == {
        "text": "Cat",
        "cardId": glossary_state["cardId"],
        "meaning": "a small domestic feline",
    }
    assert glossary_state["cardId"]
    assert detail_state == {
        "surface": "Cat",
        "meaning": "a small domestic feline",
        "viewCardId": glossary_state["cardId"],
    }
    assert cards_state["hash"] == f"#card-{glossary_state['cardId']}"
    assert cards_state["targetFound"] is True
    assert cards_state["returnVisible"] is True
    assert "/read/" in cards_state["returnHref"]
    assert returned_path.startswith("/read/")


def test_analysis_panel_remove_glossary_word_stays_in_analysis_panel(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        initial_url = page.evaluate("window.location.href")
        glossary_word = page.locator("#analysis-gloss .glossary-word").first
        glossary_word.wait_for()
        card_id = glossary_word.get_attribute("data-card-id")

        glossary_word.click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.locator("#toolbar-word-detail-remove").click()
        page.wait_for_function(
            f"""() => (
              document.getElementById("analysis-panel").hidden === false
              && document.getElementById("toolbar-word-detail").hidden === true
              && document.querySelectorAll('.glossary-word[data-card-id="{card_id}"]').length === 0
            )""",
        )
        state = page.evaluate(
            """(cardId) => ({
              url: window.location.href,
              panelHidden: document.getElementById("analysis-panel").hidden,
              wordDetailHidden: document.getElementById("toolbar-word-detail").hidden,
              highlighted: document.querySelectorAll(`.glossary-word[data-card-id="${cardId}"]`).length,
              analysisText: document.getElementById("analysis-gloss").textContent,
            })""",
            card_id,
        )

    assert state == {
        "url": initial_url,
        "panelHidden": False,
        "wordDetailHidden": True,
        "highlighted": 0,
        "analysisText": "Cat rests.",
    }


def test_word_analysis_nested_explain_can_return_to_previous_analysis(
    browser: Browser,
    reader_url: str,
) -> None:
    calls = {"count": 0}

    def fulfill_word_analysis(route) -> None:  # type: ignore[no-untyped-def]
        calls["count"] += 1
        nested = calls["count"] > 1
        payload = {
            "ok": True,
            "card_id": 1,
            "sentence_id": 1,
            "lemma": "cat",
            "surface_form": "Cat",
            "lexical_type": "word",
            "analysis": {
                "meaning_in_context": "second meaning" if nested else "first meaning",
                "chinese_meaning": "猫",
                "register": "common",
                "why_this_word": (
                    "Nested Cat explanation."
                    if nested
                    else "First Cat explanation with Cat as a glossary link."
                ),
                "vs_simpler": [],
                "morphology": {"root": "cat", "family": ["catlike"]},
                "predicted_error_types": ["L01"],
            },
            "cache_id": calls["count"],
            "prompt_version": "v3",
            "active_prompt_version": "v3",
            "from_cache": False,
            "is_stale": False,
        }
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    for page in _new_page(browser, reader_url):
        page.route("**/analysis/word/*", fulfill_word_analysis)
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.locator("#toolbar-word-detail-explain").click()
        page.wait_for_function(
            'document.getElementById("analysis-word-meaning").textContent === "first meaning"'
        )
        first_state = page.evaluate(
            """() => ({
              previousHidden: document.getElementById("analysis-panel-previous").hidden,
              why: document.getElementById("analysis-word-why").textContent,
            })"""
        )

        nested_link = page.locator("#analysis-word-why .glossary-word").first
        nested_link.wait_for()
        nested_link.click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.locator("#toolbar-word-detail-explain").click()
        page.wait_for_function(
            'document.getElementById("analysis-word-meaning").textContent === "second meaning"'
        )
        nested_state = page.evaluate(
            """() => ({
              previousHidden: document.getElementById("analysis-panel-previous").hidden,
              previousText: document.getElementById("analysis-panel-previous").textContent,
              meaning: document.getElementById("analysis-word-meaning").textContent,
            })"""
        )

        page.locator("#analysis-panel-previous").click()
        page.wait_for_function(
            'document.getElementById("analysis-word-meaning").textContent === "first meaning"'
        )
        restored_state = page.evaluate(
            """() => ({
              previousHidden: document.getElementById("analysis-panel-previous").hidden,
              meaning: document.getElementById("analysis-word-meaning").textContent,
              why: document.getElementById("analysis-word-why").textContent,
            })"""
        )

    assert calls["count"] == 2
    assert first_state == {
        "previousHidden": True,
        "why": "First Cat explanation with Cat as a glossary link.",
    }
    assert nested_state == {
        "previousHidden": False,
        "previousText": "Back to Cat analysis",
        "meaning": "second meaning",
    }
    assert restored_state == {
        "previousHidden": True,
        "meaning": "first meaning",
        "why": "First Cat explanation with Cat as a glossary link.",
    }


def test_word_analysis_notes_do_not_fallback_to_definition(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE word_cards SET user_note = current_meaning WHERE lemma = ?",
            ("cat",),
        )

    def fulfill_word_analysis(route) -> None:  # type: ignore[no-untyped-def]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True,
                "card_id": 1,
                "sentence_id": 1,
                "lemma": "cat",
                "surface_form": "Cat",
                "lexical_type": "word",
                "analysis": {
                    "meaning_in_context": "a small domestic feline",
                    "chinese_meaning": "猫",
                    "register": "common",
                    "why_this_word": "It names the animal.",
                    "vs_simpler": [],
                    "morphology": {"root": "cat", "family": ["catlike"]},
                    "predicted_error_types": ["L01"],
                },
                "cache_id": 1,
                "prompt_version": "v3",
                "active_prompt_version": "v3",
                "from_cache": False,
                "is_stale": False,
            }),
        )

    for page in _new_page(browser, reader_url):
        page.route("**/analysis/word/*", fulfill_word_analysis)
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.locator("#toolbar-word-detail-explain").click()
        page.wait_for_function(
            'document.getElementById("word-panel-meaning").value === "a small domestic feline"'
        )
        notes_state = page.evaluate(
            """() => ({
              definition: document.getElementById("word-panel-meaning").value,
              note: document.getElementById("word-panel-note").value,
            })"""
        )

    assert notes_state == {
        "definition": "a small domestic feline",
        "note": "",
    }
