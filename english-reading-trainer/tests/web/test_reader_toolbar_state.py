"""
Browser-level tests for the reader selection toolbar state machine.

These tests use a local uvicorn server plus Playwright when a browser can be
started in the current environment. Route-level toolbar assertions live in
test_fastapi_app.py so the core regression coverage remains available without
a browser runtime.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
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
    return int(result.book_id)


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
        "cross_sentence": False,
        "translation": False,
    }


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


def test_collapsed_selection_after_word_detail_hides_toolbar(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
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
