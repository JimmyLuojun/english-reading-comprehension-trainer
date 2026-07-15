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
from urllib.parse import parse_qs

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
    "structure": "toolbar-structure-editor",
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


def _attach_word_analysis(db: DatabaseConnection, lemma: str = "cat") -> int:
    payload = {
        "meaning_in_context": "a small domestic feline",
        "chinese_meaning": "猫",
        "register": "common",
        "role_in_sentence": "subject",
        "why_this_word": "It names the animal.",
        "vs_simpler": [],
        "morphology": {"root": "cat", "family": ["catlike"]},
        "predicted_error_types": ["L01"],
    }
    now = datetime.now(timezone.utc).isoformat()
    with db.get_connection() as conn:
        card_id = conn.execute(
            "SELECT id FROM word_cards WHERE lemma = ?",
            (lemma,),
        ).fetchone()["id"]
        cache_id = conn.execute(
            """INSERT INTO ai_cache
               (content_hash, prompt_version, model, response_json, is_valid, created_at)
               VALUES (?, 'word.v1', 'manual', ?, 1, ?)""",
            (
                f"toolbar-word-analysis-{card_id}",
                json.dumps(payload),
                now,
            ),
        ).lastrowid
        conn.execute(
            "UPDATE word_cards SET ai_analysis_id = ? WHERE id = ?",
            (cache_id, card_id),
        )
    return int(cache_id)


def _visible_panels(page: Page) -> dict[str, bool]:
    return page.evaluate(
        """(panelIds) => {
          const isRendered = (element) => Boolean(
            element
            && window.getComputedStyle(element).display !== "none"
            && element.getClientRects().length
          );
          const state = {
            toolbar: isRendered(document.getElementById("selection-toolbar")),
            word_existing_present: Boolean(document.getElementById("toolbar-word-existing")),
          };
          for (const [key, id] of Object.entries(panelIds)) {
            const element = document.getElementById(id);
            state[key] = isRendered(element);
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


def _select_analysis_text(page: Page, selector: str, text: str) -> None:
    page.evaluate(
        """({selector, text}) => {
          const root = document.querySelector(selector);
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
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
        {"selector": selector, "text": text},
    )
    page.wait_for_timeout(60)


def _new_page(browser: Browser, url: str) -> Iterator[Page]:
    context = browser.new_context(bypass_csp=True)
    page = context.new_page()
    page.goto(url)
    try:
        yield page
    finally:
        context.close()


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
        "structure": False,
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


def test_external_prompt_panel_stays_a_drawer_at_tablet_width(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.set_viewport_size({"width": 1120, "height": 800})
        page.evaluate(
            """() => {
              Object.defineProperty(navigator, "clipboard", {
                configurable: true,
                value: { writeText: async () => {} },
              });
            }"""
        )
        _select_sentence_contents(page, 1)
        page.locator("#toolbar-external-prompt").click()
        page.wait_for_function(
            '!document.getElementById("analysis-external-section").hidden'
        )
        geometry = page.evaluate(
            """() => {
              const panelRect = document.getElementById("analysis-panel").getBoundingClientRect();
              return {
                viewportWidth: window.innerWidth,
                left: Math.round(panelRect.left),
                right: Math.round(window.innerWidth - panelRect.right),
                top: Math.round(panelRect.top),
                width: Math.round(panelRect.width),
              };
            }"""
        )

    assert geometry == {
        "viewportWidth": 1120,
        "left": 600,
        "right": 0,
        "top": 49,
        "width": 520,
    }


def test_analysis_panel_uses_full_screen_only_on_narrow_viewports(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.set_viewport_size({"width": 700, "height": 800})
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        geometry = page.evaluate(
            """() => {
              const panelRect = document.getElementById("analysis-panel").getBoundingClientRect();
              return {
                viewportWidth: window.innerWidth,
                left: Math.round(panelRect.left),
                right: Math.round(window.innerWidth - panelRect.right),
                top: Math.round(panelRect.top),
                width: Math.round(panelRect.width),
              };
            }"""
        )

    assert geometry == {
        "viewportWidth": 700,
        "left": 0,
        "right": 0,
        "top": 0,
        "width": 700,
    }


def test_collapsed_analysis_tools_do_not_leave_a_sticky_header_gap(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.set_viewport_size({"width": 1120, "height": 800})
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        page.evaluate(
            """() => {
              const panel = document.getElementById("analysis-panel");
              const header = panel.querySelector(".analysis-panel-header");
              panel.scrollTop = header.offsetHeight + 120;
              panel.dispatchEvent(new Event("scroll"));
            }"""
        )
        page.wait_for_function(
            'document.getElementById("analysis-panel").classList.contains("analysis-tools-collapsed")'
        )
        page.wait_for_timeout(60)
        collapsed_state = page.evaluate(
            """() => {
              const panel = document.getElementById("analysis-panel");
              const header = panel.querySelector(".analysis-panel-header");
              const handle = document.getElementById("analysis-tools-handle");
              const panelRect = panel.getBoundingClientRect();
              const headerRect = header.getBoundingClientRect();
              return {
                collapsed: panel.classList.contains("analysis-tools-collapsed"),
                peeking: panel.classList.contains("analysis-tools-peeking"),
                headerPosition: getComputedStyle(header).position,
                headerBottom: Math.round(headerRect.bottom),
                panelTop: Math.round(panelRect.top),
                handleHidden: handle.hidden,
                handleText: handle.textContent,
                handleExpanded: handle.getAttribute("aria-expanded"),
              };
            }"""
        )
        panel_box = page.locator("#analysis-panel").bounding_box()
        assert panel_box is not None
        page.mouse.move(panel_box["x"] + panel_box["width"] - 6, panel_box["y"] + 20)
        page.wait_for_function(
            'document.getElementById("analysis-panel").classList.contains("analysis-tools-peeking")'
        )
        peek_state = page.evaluate(
            """() => {
              const panel = document.getElementById("analysis-panel");
              const header = panel.querySelector(".analysis-panel-header");
              return {
                headerPosition: getComputedStyle(header).position,
                headerTop: Math.round(header.getBoundingClientRect().top),
                panelTop: Math.round(panel.getBoundingClientRect().top),
                panelPaddingTop: Math.round(parseFloat(getComputedStyle(panel).paddingTop)),
              };
            }"""
        )
        page.mouse.move(panel_box["x"] + 80, panel_box["y"] + panel_box["height"] - 40)
        page.wait_for_function(
            '!document.getElementById("analysis-panel").classList.contains("analysis-tools-peeking")'
        )
        page.wait_for_timeout(60)
        settled_state = page.evaluate(
            """() => {
              const panel = document.getElementById("analysis-panel");
              const header = panel.querySelector(".analysis-panel-header");
              return {
                collapsed: panel.classList.contains("analysis-tools-collapsed"),
                headerPosition: getComputedStyle(header).position,
                headerBottom: Math.round(header.getBoundingClientRect().bottom),
                panelTop: Math.round(panel.getBoundingClientRect().top),
              };
            }"""
        )

    assert collapsed_state["collapsed"] is True
    assert collapsed_state["peeking"] is False
    assert collapsed_state["headerPosition"] == "static"
    assert collapsed_state["handleHidden"] is False
    assert collapsed_state["handleText"] == "…"
    assert collapsed_state["handleExpanded"] == "false"
    assert collapsed_state["headerBottom"] <= collapsed_state["panelTop"]
    assert peek_state["headerPosition"] == "sticky"
    assert peek_state["headerTop"] == peek_state["panelTop"] + peek_state["panelPaddingTop"]
    assert settled_state["collapsed"] is True
    assert settled_state["headerPosition"] == "static"
    assert settled_state["headerBottom"] <= settled_state["panelTop"]


def test_click_marked_word_shows_only_word_detail(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')

        _assert_only_panel(page, "word_detail")


def test_click_marked_word_with_saved_analysis_opens_analysis_panel(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    _attach_word_analysis(db)

    for page in _new_page(browser, reader_url):
        word = page.locator("[data-word-card]").first
        assert word.get_attribute("data-has-analysis") == "1"
        word.click()
        page.wait_for_function(
            'document.getElementById("analysis-word-meaning").textContent '
            '=== "a small domestic feline"'
        )
        state = page.evaluate(
            """() => ({
              panelHidden: document.getElementById("analysis-panel").hidden,
              toolbarHidden: document.getElementById("selection-toolbar").hidden,
              activeWord: document.querySelector("[data-word-card]")
                .classList.contains("word-analysis-active"),
            })"""
        )

    assert state == {
        "panelHidden": False,
        "toolbarHidden": True,
        "activeWord": True,
    }


def test_double_click_marked_word_shows_only_word_detail(browser: Browser, reader_url: str) -> None:
    for page in _new_page(browser, reader_url):
        page.locator("[data-word-card]").dblclick()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')

        _assert_only_panel(page, "word_detail")


def test_selection_spanning_marked_word_opens_a_new_phrase_toolbar(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.evaluate(
            """() => {
              const span = document.querySelector('[data-word-card]');
              const range = document.createRange();
              range.setStart(span.firstChild, 0);
              range.setEnd(span.nextSibling, 4);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }"""
        )
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        state = page.evaluate(
            """() => ({
              selectedText: window.getSelection().toString(),
              surfaceForm: document.getElementById("toolbar-word-surface-form").value,
              detailHidden: document.getElementById("toolbar-word-detail").hidden,
            })"""
        )

    assert state == {
        "selectedText": "cat sat",
        "surfaceForm": "cat sat",
        "detailHidden": True,
    }


def test_w_and_double_click_select_a_word_inside_a_marked_phrase(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    with db.get_connection() as conn:
        sentence_id = conn.execute(
            "SELECT id FROM sentences ORDER BY id LIMIT 1"
        ).fetchone()["id"]
    response = TestClient(create_app(lambda: db)).post(
        "/mark/word",
        data={
            "sentence_id": str(sentence_id),
            "surface_form": "cat sat",
            "lexical_type": "phrase",
            "start_offset": "4",
            "end_offset": "11",
        },
    )
    assert response.status_code == 200

    for interaction in ("shortcut", "double_click"):
        for page in _new_page(browser, reader_url):
            if interaction == "shortcut":
                point = page.evaluate(
                    """() => {
                      const span = document.querySelector('[data-word-card]');
                      const node = span.firstChild;
                      const range = document.createRange();
                      range.setStart(node, 0);
                      range.setEnd(node, 3);
                      const rect = range.getBoundingClientRect();
                      return { x: rect.left + (rect.width / 2), y: rect.top + (rect.height / 2) };
                    }"""
                )
                page.mouse.move(point["x"], point["y"])
                page.keyboard.press("w")
            else:
                page.evaluate(
                    """() => {
                      const span = document.querySelector('[data-word-card]');
                      const node = span.firstChild;
                      const range = document.createRange();
                      range.setStart(node, 0);
                      range.setEnd(node, 3);
                      const selection = window.getSelection();
                      selection.removeAllRanges();
                      selection.addRange(range);
                      span.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
                    }"""
                )
            page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
            state = page.evaluate(
                """() => ({
                  surfaceForm: document.getElementById("toolbar-word-surface-form").value,
                  detailHidden: document.getElementById("toolbar-word-detail").hidden,
                })"""
            )

        assert state == {"surfaceForm": "cat", "detailHidden": True}


def test_double_click_unmarked_word_opens_word_toolbar_with_word_default(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_text(page, 0, "mat")
        page.locator("[data-sentence-id]").first.dispatch_event("dblclick")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        state = page.evaluate(
            """() => ({
              surfaceForm: document.getElementById("toolbar-word-surface-form").value,
              activeType: document.querySelector("[data-word-lexical].active")?.dataset.wordLexical,
            })"""
        )

    assert state == {"surfaceForm": "mat", "activeType": "word"}


def test_w_shortcut_selects_hovered_word_and_opens_word_toolbar(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        point = page.evaluate(
            """() => {
              const sentence = document.querySelector("[data-sentence-id]");
              const walker = document.createTreeWalker(sentence, NodeFilter.SHOW_TEXT);
              let node = walker.nextNode();
              while (node && !node.nodeValue.includes("mat")) {
                node = walker.nextNode();
              }
              const index = node.nodeValue.indexOf("mat");
              const range = document.createRange();
              range.setStart(node, index);
              range.setEnd(node, index + 3);
              const rect = range.getBoundingClientRect();
              return { x: rect.left + (rect.width / 2), y: rect.top + (rect.height / 2) };
            }"""
        )
        page.mouse.move(point["x"], point["y"])
        page.keyboard.press("w")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        state = page.evaluate(
            """() => ({
              selectedText: window.getSelection().toString(),
              surfaceForm: document.getElementById("toolbar-word-surface-form").value,
              activeType: document.querySelector("[data-word-lexical].active")?.dataset.wordLexical,
              statusText: document.getElementById("toolbar-word-status").textContent,
            })"""
        )

    assert state == {
        "selectedText": "mat",
        "surfaceForm": "mat",
        "activeType": "word",
        "statusText": "Using word",
    }


def test_word_type_switch_does_not_resize_the_floating_toolbar(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_text(page, 0, "mat")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        before = page.locator("#selection-toolbar").bounding_box()
        page.locator('#toolbar-word-form button[value="phrase"]').click()
        page.wait_for_function(
            'document.getElementById("toolbar-word-status").textContent === "Using phrase"'
        )
        after = page.locator("#selection-toolbar").bounding_box()

    assert before is not None
    assert after is not None
    assert after["width"] == before["width"]
    assert after["height"] == before["height"]


def test_multi_word_selection_defaults_to_word_until_user_changes_it(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_text(page, 0, "sat on")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        active_type = page.locator("[data-word-lexical].active").get_attribute("data-word-lexical")

    assert active_type == "word"


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


def test_sentence_selection_does_not_render_word_actions_or_duplicate_analysis(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_sentence_contents(page, 1)
        _assert_only_panel(page, "sentence")
        visible_actions = page.locator("#selection-toolbar button:visible").all_inner_texts()

    assert visible_actions == [
        "Mark sentence",
        "Write translation",
        "Write structure",
        "Copy AI prompt",
        "AI analysis",
    ]


def test_translation_editor_does_not_cover_target_sentence(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.set_viewport_size({"width": 900, "height": 520})
        _select_sentence_contents(page, 1)
        page.locator("#toolbar-translation-open").click()
        page.wait_for_function('!document.getElementById("toolbar-translation-editor").hidden')
        page.wait_for_function(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[1];
              const toolbar = document.getElementById("selection-toolbar");
              const sentenceRect = sentence.getBoundingClientRect();
              const toolbarRect = toolbar.getBoundingClientRect();
              return toolbarRect.bottom <= sentenceRect.top || toolbarRect.top >= sentenceRect.bottom;
            }"""
        )
        geometry = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[1];
              const toolbar = document.getElementById("selection-toolbar");
              const sentenceRect = sentence.getBoundingClientRect();
              const toolbarRect = toolbar.getBoundingClientRect();
              const overlaps = !(
                toolbarRect.bottom <= sentenceRect.top
                || toolbarRect.top >= sentenceRect.bottom
                || toolbarRect.right <= sentenceRect.left
                || toolbarRect.left >= sentenceRect.right
              );
              return {
                overlaps,
                sentenceBottom: Math.round(sentenceRect.bottom),
                sentenceTop: Math.round(sentenceRect.top),
                scrollY: Math.round(window.scrollY),
                toolbarBottom: Math.round(toolbarRect.bottom),
                toolbarTop: Math.round(toolbarRect.top),
                viewportHeight: window.innerHeight,
              };
            }"""
        )

    assert geometry["overlaps"] is False, (
        "sentence="
        f"{geometry['sentenceTop']}..{geometry['sentenceBottom']} "
        f"toolbar={geometry['toolbarTop']}..{geometry['toolbarBottom']} "
        f"scrollY={geometry['scrollY']}"
    )
    assert geometry["toolbarTop"] >= 0
    assert geometry["toolbarBottom"] <= geometry["viewportHeight"] + 1


def test_structure_editor_autosaves_and_survives_reader_selection(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_sentence_contents(page, 0)
        page.locator("#toolbar-structure-open").click()
        page.wait_for_function('!document.getElementById("toolbar-structure-editor").hidden')
        initial_value = page.locator("#toolbar-structure-text").input_value()
        page.locator("#toolbar-structure-text").fill(
            "主干：The cat sat\n从句：\n修饰成分：on the mat\n指代逻辑："
        )
        page.wait_for_function(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[0];
              return sentence.dataset.structure.includes("The cat sat")
                && !document.getElementById("selection-toolbar").hidden
                && !document.getElementById("toolbar-structure-editor").hidden;
            }"""
        )

        _select_text(page, 1, "bright")
        state = _visible_panels(page)
        value_after_selection = page.locator("#toolbar-structure-text").input_value()

    assert initial_value == "主干：\n从句：\n修饰成分：\n指代逻辑："
    assert state["toolbar"] is True
    assert state["sentence"] is True
    assert state["structure"] is True
    assert state["word"] is False
    assert value_after_selection.startswith("主干：The cat sat")


def test_saved_translation_underlines_sentence_and_changes_analysis_action(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_sentence_contents(page, 0)
        page.locator("#toolbar-translation-open").click()
        page.locator("#toolbar-translation-text").fill("猫坐在垫子上。")
        page.locator("#toolbar-translation-save").click()
        page.wait_for_function(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[0];
              const toolbar = document.getElementById("selection-toolbar");
              const editor = document.getElementById("toolbar-translation-editor");
              return !toolbar.hidden
                && !editor.hidden
                && sentence.classList.contains("translated")
                && sentence.classList.contains("marked")
                && sentence.dataset.translation === "猫坐在垫子上。"
                && Boolean(sentence.dataset.analysisId)
                && !sentence.classList.contains("analyzed")
                && sentence.classList.contains("analyzed-stale");
            }"""
        )
        page.locator("#toolbar-translation-cancel").click()
        page.wait_for_function('document.getElementById("selection-toolbar").hidden')

        _select_sentence_contents(page, 0)
        page.wait_for_function(
            'document.getElementById("toolbar-analysis-open").textContent === "Check translation"'
        )
        action_text = page.locator("#toolbar-analysis-open").text_content()

    assert action_text == "Check translation"


def test_copy_external_prompt_flushes_pending_translation_and_structure(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    translation = "即时译文：猫坐在垫子上。"
    structure = "主干：The cat sat\n从句：\n修饰成分：on the mat\n指代逻辑："
    for page in _new_page(browser, reader_url):
        page.evaluate(
            """() => {
              window.__copiedText = "";
              Object.defineProperty(navigator, "clipboard", {
                configurable: true,
                value: {
                  writeText: async (text) => {
                    window.__copiedText = text;
                  },
                },
              });
            }"""
        )
        _select_sentence_contents(page, 0)
        sentence_id = int(
            page.locator("[data-sentence-id]").first.get_attribute("data-sentence-id")
            or "0"
        )
        page.locator("#toolbar-translation-open").click()
        page.wait_for_function('!document.getElementById("toolbar-translation-editor").hidden')
        page.locator("#toolbar-translation-text").fill(translation)

        page.locator("#toolbar-structure-open").click()
        page.wait_for_function('!document.getElementById("toolbar-structure-editor").hidden')
        page.locator("#toolbar-structure-text").fill(structure)
        page.locator("#toolbar-external-prompt").click()

        page.wait_for_function(
            """({translation, structure}) => {
              const copied = window.__copiedText || "";
              return copied.includes(translation) && copied.includes(structure);
            }""",
            arg={"translation": translation, "structure": structure},
        )
        copied_text = page.evaluate("window.__copiedText")
        dom_state = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[0];
              return {
                translation: sentence.dataset.translation,
                structure: sentence.dataset.structure,
              };
            }"""
        )

    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT user_translation, user_structure
                 FROM sentence_cards
                WHERE sentence_id = ? AND archived_at IS NULL""",
            (sentence_id,),
        ).fetchone()

    assert translation in copied_text
    assert structure in copied_text
    assert dom_state == {"translation": translation, "structure": structure}
    assert row is not None
    assert row["user_translation"] == translation
    assert row["user_structure"] == structure


def test_word_type_selector_keeps_toolbar_available_for_prompt_copy(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        page.evaluate(
            """() => {
              window.__copiedText = "";
              Object.defineProperty(navigator, "clipboard", {
                configurable: true,
                value: {
                  writeText: async (text) => {
                    window.__copiedText = text;
                  },
                },
              });
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

        page.locator('#toolbar-word-form button[value="phrase"]').click()
        page.locator("#toolbar-word-note").fill("明亮的；此处修饰 day")
        page.wait_for_function(
            """() => {
              const toolbar = document.getElementById("selection-toolbar");
              const wordCard = Array.from(document.querySelectorAll("[data-word-card]"))
                .find((node) => node.textContent === "bright");
              const phrase = document.querySelector('#toolbar-word-form button[value="phrase"]');
              return !toolbar.hidden
                && !wordCard
                && phrase.classList.contains("active")
                && phrase.getAttribute("aria-pressed") === "true"
                && document.getElementById("toolbar-word-status").textContent === "Using phrase";
            }"""
        )
        after = page.evaluate(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[1];
              return {
                sentenceTop: sentence.getBoundingClientRect().top,
                scrollY: window.scrollY,
                toolbarHidden: document.getElementById("selection-toolbar").hidden,
                url: window.location.href,
              };
            }"""
        )
        page.locator("#toolbar-word-copy-prompt").click()
        page.wait_for_function(
            """() => {
              const copied = window.__copiedText || "";
              return copied.includes("目标项：bright（phrase）")
                && copied.includes("lexical_type 必须优先使用：phrase")
                && copied.includes("learner note: 明亮的；此处修饰 day");
            }"""
        )
        copied_text = page.evaluate("window.__copiedText")

    assert before["scrollY"] > 0
    assert after["url"] == before["url"]
    assert abs(after["sentenceTop"] - before["sentenceTop"]) <= 1
    assert after["scrollY"] > 0
    assert after["toolbarHidden"] is False
    assert "目标项：bright（phrase）" in copied_text
    assert "learner note: 明亮的；此处修饰 day" in copied_text


def test_external_word_analysis_enter_saves_and_shift_enter_adds_newline(
    browser: Browser,
    reader_url: str,
) -> None:
    requests: list[dict[str, list[str]]] = []

    def fulfill_external_word_analysis(route) -> None:  # type: ignore[no-untyped-def]
        requests.append(parse_qs(route.request.post_data or ""))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True,
                "card_id": 999,
                "sentence_id": 1,
                "lemma": "bright",
                "surface_form": "bright",
                "lexical_type": "word",
                "analysis": {
                    "meaning_in_context": "giving off plenty of light",
                    "chinese_meaning": "明亮的",
                    "register": "common",
                    "role_in_sentence": "adjective modifying day",
                    "why_this_word": "It describes the day.",
                    "vs_simpler": [],
                    "morphology": {"root": "bright", "family": ["brightness"]},
                    "predicted_error_types": [],
                },
                "prompt_version": "word.v5",
                "model": "external-ai",
                "from_cache": False,
                "is_stale": False,
            }),
        )

    external_result = json.dumps({"lemma": "bright", "lexical_type": "word"})
    for page in _new_page(browser, reader_url):
        page.route(
            "**/analysis/selection/word-external",
            fulfill_external_word_analysis,
        )
        _select_text_until_panel(page, 1, "bright", "toolbar-word-form")
        page.locator("#toolbar-word-copy-prompt").click()
        page.wait_for_function(
            '!document.getElementById("analysis-external-section").hidden'
        )
        textarea = page.locator("#analysis-external-result")
        textarea.fill(external_result)
        textarea.press("Shift+Enter")
        assert requests == []
        assert textarea.input_value() == f"{external_result}\n"

        textarea.fill(external_result)
        textarea.evaluate(
            """(element) => {
              const event = new KeyboardEvent("keydown", {
                key: "Enter",
                code: "Enter",
                bubbles: true,
                cancelable: true,
              });
              Object.defineProperty(event, "keyCode", { value: 229 });
              element.dispatchEvent(event);
            }"""
        )
        page.wait_for_function(
            'document.getElementById("analysis-external-status").textContent === "Saved"'
        )

    assert len(requests) == 1
    assert requests[0]["external_result"] == [external_result]


def test_quick_note_saves_collocation_directly_to_review(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_text(page, 0, "sat on")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        page.locator('#toolbar-word-form button[value="collocation"]').click()
        page.locator("#toolbar-word-note").fill("坐在……上；常与具体位置连用")
        page.locator("#toolbar-word-save").click()
        page.wait_for_function(
            """() => {
              const span = Array.from(document.querySelectorAll('[data-word-card]'))
                .find((element) => element.textContent === 'sat on');
              return span
                && span.dataset.lexicalType === 'collocation'
                && span.dataset.note === '坐在……上；常与具体位置连用';
            }"""
        )

    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT id, lexical_type, user_note, due_at
                 FROM word_cards
                WHERE surface_form = 'sat on' AND archived_at IS NULL"""
        ).fetchone()

    assert row is not None
    assert row["lexical_type"] == "collocation"
    assert row["user_note"] == "坐在……上；常与具体位置连用"
    assert row["due_at"] is not None


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


def test_removed_word_can_be_resaved_as_phrase_with_phrase_color(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    for page in _new_page(browser, reader_url):
        page.locator('[data-word-card][data-lexical-type="word"]').click()
        page.locator("#toolbar-word-detail-remove").click()
        page.wait_for_function('document.querySelectorAll("[data-word-card]").length === 0')

        _select_text(page, 0, "cat")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')
        page.locator('#toolbar-word-form button[value="phrase"]').click()
        page.locator("#toolbar-word-note").fill("此处按 phrase 复习")
        page.locator("#toolbar-word-save").click()
        page.wait_for_function(
            """() => {
              const span = document.querySelector('[data-word-card]');
              return span && span.dataset.lexicalType === 'phrase';
            }"""
        )
        visual_state = page.locator('[data-word-card][data-lexical-type="phrase"]').evaluate(
            """element => ({
              lexicalType: element.dataset.lexicalType,
              backgroundImage: getComputedStyle(element).backgroundImage,
              decorationColor: getComputedStyle(element).textDecorationColor,
            })"""
        )

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT lexical_type FROM word_cards WHERE lemma = 'cat'"
        ).fetchone()

    assert row is not None
    assert row["lexical_type"] == "phrase"
    assert visual_state["lexicalType"] == "phrase"
    assert "168, 85, 247" in visual_state["backgroundImage"]
    assert visual_state["decorationColor"] == "rgba(126, 34, 206, 0.74)"


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


def test_click_marked_sentence_without_analysis_shows_sentence_actions(
    browser: Browser,
    reader_url: str,
) -> None:
    for page in _new_page(browser, reader_url):
        _select_sentence_contents(page, 1)
        page.locator("#toolbar-sentence-submit").click()
        page.wait_for_function(
            """() => {
              const sentence = document.querySelectorAll("[data-sentence-id]")[1];
              return document.getElementById("selection-toolbar").hidden
                && sentence.dataset.marked === "1"
                && !sentence.dataset.analysisId;
            }"""
        )

        page.locator("[data-sentence-id]").nth(1).click()
        page.wait_for_function('!document.getElementById("toolbar-sentence-form").hidden')
        state = page.evaluate(
            """() => ({
              analysisHidden: document.getElementById("toolbar-analysis-open").hidden,
              deleteHidden: document.getElementById("toolbar-sentence-delete").hidden,
              submitHidden: document.getElementById("toolbar-sentence-submit").hidden,
              toolbarHidden: document.getElementById("selection-toolbar").hidden,
            })"""
        )

    assert state == {
        "analysisHidden": False,
        "deleteHidden": False,
        "submitHidden": True,
        "toolbarHidden": False,
    }


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


def test_w_shortcut_replaces_analysis_word_toolbar_with_reader_word_toolbar(
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
        point = page.evaluate(
            """() => {
              const sentence = document.querySelector("[data-sentence-id]");
              const walker = document.createTreeWalker(sentence, NodeFilter.SHOW_TEXT);
              let node = walker.nextNode();
              while (node && !node.nodeValue.includes("mat")) {
                node = walker.nextNode();
              }
              const index = node.nodeValue.indexOf("mat");
              const range = document.createRange();
              range.setStart(node, index);
              range.setEnd(node, index + 3);
              const rect = range.getBoundingClientRect();
              return { x: rect.left + (rect.width / 2), y: rect.top + (rect.height / 2) };
            }"""
        )
        page.mouse.move(point["x"], point["y"])
        page.keyboard.press("w")
        page.wait_for_function('!document.getElementById("toolbar-word-form").hidden')

        _assert_only_panel(page, "word")
        assert page.locator("#toolbar-word-status").text_content() == "Using word"


def test_analysis_panel_mark_phrase_keeps_current_analysis(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
) -> None:
    word_analysis_requests: list[dict[str, list[str]]] = []

    def fulfill_word_analysis(route) -> None:  # type: ignore[no-untyped-def]
        word_analysis_requests.append(parse_qs(route.request.post_data or ""))
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
                "lexical_type": "phrase",
                "analysis": {
                    "meaning_in_context": "catlike animal",
                    "chinese_meaning": "猫科动物",
                    "register": "neutral",
                    "why_this_word": "It names the animal precisely.",
                    "vs_simpler": [],
                    "morphology": {"root": "felis", "family": ["feline"]},
                    "predicted_error_types": ["L01"],
                },
                "prompt_version": "v2",
                "active_prompt_version": "v2",
                "model": "test",
                "from_cache": False,
                "is_stale": False,
            }),
        )

    for page in _new_page(browser, reader_url):
        page.route("**/analysis/word/*", fulfill_word_analysis)
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
            'document.getElementById("analysis-word-meaning").textContent === "catlike animal"'
        )
        state = page.evaluate(
            """() => ({
              url: window.location.href,
              panelHidden: document.getElementById("analysis-panel").hidden,
              simplified: document.getElementById("analysis-simplified").textContent,
              wordSectionsHidden: document.getElementById("analysis-word-sections").hidden,
              previousHidden: document.getElementById("analysis-panel-previous").hidden,
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
        "wordSectionsHidden": False,
        "previousHidden": False,
        "highlighted": True,
    }
    assert word_analysis_requests[0]["context_text"] == ["The feline rested."]
    assert row is not None
    assert row["lexical_type"] == "phrase"


def test_analysis_panel_new_selection_survives_previous_word_analysis(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
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
                "lemma": "selection",
                "surface_form": "selection",
                "lexical_type": "word",
                "analysis": {
                    "meaning_in_context": "selected text",
                    "chinese_meaning": "选中文本",
                    "register": "neutral",
                    "why_this_word": "It is the current selection.",
                    "vs_simpler": [],
                    "morphology": {"root": "", "family": []},
                    "predicted_error_types": [],
                },
                "prompt_version": "v2",
                "active_prompt_version": "v2",
                "model": "test",
                "from_cache": False,
                "is_stale": False,
            }),
        )

    for page in _new_page(browser, reader_url):
        page.route("**/analysis/word/*", fulfill_word_analysis)
        page.locator("[data-sentence-id]").first.click()
        page.wait_for_function('!document.getElementById("analysis-panel").hidden')
        _select_analysis_text(page, "#analysis-simplified", "feline")
        page.wait_for_function('!document.getElementById("toolbar-analysis-word-form").hidden')
        page.locator('[data-analysis-mark="phrase"]').click()
        page.wait_for_function(
            '!document.getElementById("analysis-word-sections").hidden'
        )
        page.locator("#analysis-panel-previous").click()
        page.wait_for_function('!document.getElementById("analysis-sentence-sections").hidden')

        _select_analysis_text(page, "#analysis-simplified", "rested")
        page.wait_for_timeout(800)
        state = page.evaluate(
            """() => ({
              toolbarHidden: document.getElementById("selection-toolbar").hidden,
              analysisWordHidden: document.getElementById("toolbar-analysis-word-form").hidden,
              buttonsDisabled: Array.from(
                document.querySelectorAll("#toolbar-analysis-word-form button")
              ).some((button) => button.disabled),
              surfaceForm: document.getElementById("toolbar-analysis-word-surface-form").value,
            })"""
        )
        page.locator('[data-analysis-mark="collocation"]').click()
        page.wait_for_function(
            '!document.getElementById("analysis-word-sections").hidden'
        )

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT lemma, lexical_type
               FROM word_cards
               WHERE lemma IN ('feline', 'rested') AND archived_at IS NULL
               ORDER BY lemma"""
        ).fetchall()

    assert state == {
        "toolbarHidden": False,
        "analysisWordHidden": False,
        "buttonsDisabled": False,
        "surfaceForm": "rested",
    }
    assert [(row["lemma"], row["lexical_type"]) for row in rows] == [
        ("feline", "phrase"),
        ("rested", "collocation"),
    ]


def test_analysis_panel_ai_analysis_marks_then_returns_to_previous_analysis(
    browser: Browser,
    reader_url: str,
) -> None:
    word_analysis_requests: list[dict[str, list[str]]] = []

    def fulfill_word_analysis(route) -> None:  # type: ignore[no-untyped-def]
        word_analysis_requests.append(parse_qs(route.request.post_data or ""))
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
                "active_prompt_version": "v4",
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
    assert word_analysis_requests[0]["context_text"] == ["The feline rested."]
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
            "active_prompt_version": "v4",
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
                "active_prompt_version": "v4",
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


def test_word_detail_explain_saves_pending_note_before_analysis(
    browser: Browser,
    reader_url: str,
    db: DatabaseConnection,
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
                "active_prompt_version": "v4",
                "from_cache": False,
                "is_stale": False,
            }),
        )

    for page in _new_page(browser, reader_url):
        page.route("**/analysis/word/*", fulfill_word_analysis)
        page.locator("[data-word-card]").click()
        page.wait_for_function('!document.getElementById("toolbar-word-detail").hidden')
        page.locator("#toolbar-word-detail-note").fill("content A")
        page.locator("#toolbar-word-detail-explain").click()
        page.wait_for_function(
            'document.getElementById("word-panel-note").value === "content A"'
        )
        notes_state = page.evaluate(
            """() => ({
              panelNote: document.getElementById("word-panel-note").value,
              spanNote: document.querySelector("[data-word-card]").dataset.note,
            })"""
        )

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT user_note FROM word_cards WHERE lemma = ?",
            ("cat",),
        ).fetchone()

    assert notes_state == {
        "panelNote": "content A",
        "spanNote": "content A",
    }
    assert row["user_note"] == "content A"
