"""Reader page rendering helpers and browser interaction script."""

from __future__ import annotations

import json
from typing import Any

from app.web.views.books import _section_label
from app.web.views.layout import _escape
from app.web.views.reader_script import _selection_script

def _reader_view(
    rows: list[dict[str, Any]],
    return_to: str,
    chapter_id: int,
    word_cards: list[dict[str, Any]],
    book_id: int,
    book_title: str,
    chapter_idx: int,
    chapter_title: str,
    section_kind: str,
    chapter_number: int | None,
    restore_progress: bool,
    previous_chapter: dict[str, Any] | None = None,
    next_chapter: dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> str:
    cards_by_sentence = _word_cards_by_sentence(word_cards)
    content = _reader_content_blocks(
        rows=rows,
        blocks=blocks or [],
        chapter_id=chapter_id,
        cards_by_sentence=cards_by_sentence,
        book_id=book_id,
    )
    restore_flag = "1" if restore_progress else "0"
    section_label = _section_label(
        {
            "idx": chapter_idx,
            "title": chapter_title,
            "section_kind": section_kind,
            "chapter_number": chapter_number,
        }
    )
    return f"""
    <article class="reader" data-reader data-book-id="{book_id}"
      data-chapter-idx="{chapter_idx}" data-return-to="{_escape(return_to)}"
      data-restore-progress="{restore_flag}">
      <header class="reader-header">
        <div class="reader-header-actions" aria-label="Reader navigation">
          <a class="button small" href="/books">All books</a>
          <a class="button small" href="/books/{book_id}">Chapters</a>
        </div>
        <h1 class="reader-title">{_escape(book_title)}</h1>
        <h2 class="reader-chapter">{_escape(section_label)}</h2>
      </header>
      <div id="chapter-start" class="reader-anchor" aria-hidden="true"></div>
      {_reader_boundary_link(book_id, previous_chapter, "previous")}
      {content}
      <div id="chapter-end" class="reader-anchor" aria-hidden="true"></div>
      {_reader_boundary_link(book_id, next_chapter, "next")}
    </article>
    {_analysis_panel()}
    {_selection_toolbar(return_to, word_cards)}
    """

def _reader_content_blocks(
    *,
    rows: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    chapter_id: int,
    cards_by_sentence: dict[int, list[dict[str, Any]]],
    book_id: int,
) -> str:
    if not blocks:
        paragraphs = _group_sentence_paragraphs(rows)
        if not paragraphs:
            return '<p class="empty">No sentences in this chapter.</p>'
        return "\n".join(
            _reader_paragraph(paragraph_rows, chapter_id, cards_by_sentence)
            for paragraph_rows in paragraphs
        )

    rows_by_paragraph = {
        paragraph_rows[0]["paragraph_id"]: paragraph_rows
        for paragraph_rows in _group_sentence_paragraphs(rows)
        if paragraph_rows
    }
    parts: list[str] = []
    for block in blocks:
        paragraph_id = block.get("paragraph_id")
        if paragraph_id:
            paragraph_rows = rows_by_paragraph.get(paragraph_id, [])
            if paragraph_rows:
                parts.append(
                    _reader_paragraph(paragraph_rows, chapter_id, cards_by_sentence)
                )
            continue
        if block["kind"] in {"image", "figure", "missing_asset"}:
            parts.append(_reader_media_block(block, book_id))
    return "\n".join(parts) if parts else '<p class="empty">No sentences in this chapter.</p>'

def _reader_boundary_link(
    book_id: int,
    chapter: dict[str, Any] | None,
    direction: str,
) -> str:
    if chapter is None:
        return ""
    if direction == "previous":
        anchor = "chapter-end"
        label = "Previous section"
        class_name = "reader-section-nav-prev"
    else:
        anchor = "chapter-start"
        label = "Next section"
        class_name = "reader-section-nav-next"
    section_label = _section_label(chapter)
    return (
        f'<p class="reader-section-nav {class_name}" role="navigation">'
        f'<a href="/read/{book_id}?chapter={chapter["idx"]}#{anchor}">'
        f'{label}: {_escape(section_label)}</a>'
        "</p>"
    )

def _group_sentence_paragraphs(
    rows: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    paragraphs: list[list[dict[str, Any]]] = []
    current_id: int | None = None
    for row in rows:
        paragraph_id = int(row["paragraph_id"])
        if paragraph_id != current_id:
            paragraphs.append([])
            current_id = paragraph_id
        paragraphs[-1].append(row)
    return paragraphs

def _reader_paragraph(
    rows: list[dict[str, Any]],
    chapter_id: int,
    cards_by_sentence: dict[int, list[dict[str, Any]]],
) -> str:
    sentence_spans = " ".join(
        _reader_sentence_span(row, chapter_id, cards_by_sentence.get(row["id"], []))
        for row in rows
    )
    return f'<p class="reader-para">{sentence_spans}</p>'

def _reader_media_block(block: dict[str, Any], book_id: int) -> str:
    caption = str(block.get("text") or "")
    alt_text = str(block.get("asset_alt_text") or caption)
    if block["kind"] == "missing_asset" or block.get("asset_is_missing"):
        label = caption or str(block.get("asset_source_href") or "Missing EPUB asset")
        return (
            '<figure class="reader-figure reader-figure-missing">'
            f'<div class="reader-missing-asset">{_escape(label)}</div>'
            "</figure>"
        )

    asset_id = block.get("asset_id")
    if not asset_id:
        return ""
    figcaption = (
        f"<figcaption>{_escape(caption)}</figcaption>"
        if caption
        else ""
    )
    return (
        '<figure class="reader-figure">'
        f'<img src="/assets/books/{book_id}/{asset_id}" alt="{_escape(alt_text)}" '
        'loading="lazy">'
        f"{figcaption}"
        "</figure>"
    )

def _word_cards_by_sentence(
    word_cards: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for card in word_cards:
        grouped.setdefault(int(card["first_sentence_id"]), []).append(card)
    return grouped

def _reader_sentence_span(
    row: dict[str, Any],
    chapter_id: int,
    word_cards: list[dict[str, Any]],
) -> str:
    marked = "1" if row["has_card"] else "0"
    classes = ["reader-sentence"]
    if row["has_card"]:
        classes.append("marked")
    if (row.get("user_translation") or "").strip():
        classes.append("translated")
    if row.get("has_analysis"):
        classes.append("analyzed-stale" if row.get("analysis_is_stale") else "analyzed")
    analysis_id = row.get("ai_analysis_id") if row.get("has_analysis") else ""
    text = _highlight_word_cards(row["text"], word_cards)
    title_attr = ' title="Translation saved"' if "translated" in classes else ""
    return (
        f'<span id="sentence-{row["id"]}" class="{" ".join(classes)}"{title_attr} '
        f'data-sentence-id="{row["id"]}" '
        f'data-chapter-id="{chapter_id}" data-marked="{marked}" '
        f'data-translation="{_escape(row.get("user_translation", ""))}" '
        f'data-note="{_escape(row.get("user_note", ""))}" '
        f'data-analysis-id="{_escape(analysis_id or "")}" '
        f'data-analysis-stale="{int(row.get("analysis_is_stale") or 0)}">'
        f'{text}</span>'
    )

def _highlight_word_cards(text: str, word_cards: list[dict[str, Any]]) -> str:
    if not word_cards:
        return _escape(text)

    lower_text = text.lower()
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for card in word_cards:
        surface = str(card.get("surface_form") or card.get("lemma") or "").strip()
        if not surface:
            continue
        start = lower_text.find(surface.lower())
        if start >= 0:
            matches.append((start, start + len(surface), card))

    selected: list[tuple[int, int, dict[str, Any]]] = []
    occupied_until = -1
    for start, end, card in sorted(
        matches,
        key=lambda item: (item[0], -(item[1] - item[0])),
    ):
        if start < occupied_until:
            continue
        selected.append((start, end, card))
        occupied_until = end

    if not selected:
        return _escape(text)

    pieces: list[str] = []
    cursor = 0
    for start, end, card in selected:
        pieces.append(_escape(text[cursor:start]))
        meaning = _escape(str(card.get("current_meaning") or ""))
        note = _escape(str(card.get("user_note") or ""))
        lexical_type = _escape(str(card.get("lexical_type") or ""))
        pieces.append(
            f'<span data-word-card="{card["id"]}"'
            f' data-lexical-type="{lexical_type}"'
            f' data-meaning="{meaning}" data-note="{note}"'
            f'>{_escape(text[start:end])}</span>'
        )
        cursor = end
    pieces.append(_escape(text[cursor:]))
    return "".join(pieces)

def _selection_toolbar(return_to: str, word_cards: list[dict[str, Any]]) -> str:
    word_index = {
        card["lemma"]: {
            "id": card["id"],
            "surface_form": card["surface_form"],
            "lexical_type": card.get("lexical_type") or "",
            "current_meaning": card.get("current_meaning") or "",
            "user_note": card.get("user_note") or "",
        }
        for card in word_cards
    }
    return f"""
    <div id="selection-toolbar" class="selection-toolbar" hidden>
      <form id="toolbar-sentence-form" method="post" class="toolbar-group" hidden>
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
        <button id="toolbar-sentence-submit" type="submit">Mark sentence</button>
        <button id="toolbar-sentence-delete" type="button" class="danger" hidden>Unmark sentence</button>
        <button id="toolbar-translation-open" type="button">Write translation</button>
        <button id="toolbar-translation-delete" type="button" class="danger" hidden>Delete translation</button>
      </form>
      <form id="toolbar-translation-form" method="post" class="toolbar-group" hidden>
        <input id="toolbar-translation-value" type="hidden" name="user_translation">
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
      </form>
      <div id="toolbar-translation-editor" class="translation-editor" hidden>
        <label for="toolbar-translation-text">Your understanding</label>
        <textarea id="toolbar-translation-text" rows="4" placeholder="Write your Chinese understanding"></textarea>
        <div class="translation-actions">
          <button id="toolbar-translation-cancel" type="button">Cancel</button>
          <button id="toolbar-translation-save" type="button">Save only</button>
          <button id="toolbar-translation-analyze" type="button">Save and AI analyze</button>
        </div>
        <p id="toolbar-translation-status" class="toolbar-status" aria-live="polite"></p>
      </div>
      <form id="toolbar-word-form" method="post" action="/mark/word" class="toolbar-group" hidden>
        <input id="toolbar-word-sentence-id" type="hidden" name="sentence_id">
        <input id="toolbar-word-surface-form" type="hidden" name="surface_form">
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
        <button type="submit" name="lexical_type" value="word">Mark word</button>
        <button type="submit" name="lexical_type" value="phrase">Mark phrase</button>
        <button type="submit" name="lexical_type" value="collocation">Mark collocation</button>
      </form>
      <form id="toolbar-analysis-word-form" method="post" action="/mark/word" class="toolbar-group" hidden>
        <input id="toolbar-analysis-word-sentence-id" type="hidden" name="sentence_id">
        <input id="toolbar-analysis-word-surface-form" type="hidden" name="surface_form">
        <input type="hidden" name="return_to" value="{_escape(return_to)}">
        <button type="button" name="lexical_type" value="word" data-analysis-mark="word">Mark word</button>
        <button type="button" name="lexical_type" value="phrase" data-analysis-mark="phrase">Mark phrase</button>
        <button type="button" name="lexical_type" value="collocation" data-analysis-mark="collocation">Mark collocation</button>
        <button type="button" name="lexical_type" value="word" data-analysis-analyze="word">AI analysis</button>
        <span id="toolbar-analysis-word-status" class="toolbar-status" aria-live="polite"></span>
      </form>
      <div id="toolbar-word-detail" class="toolbar-group word-detail-panel" hidden>
        <strong id="toolbar-word-detail-surface" class="word-detail-surface"></strong>
        <div class="word-detail-fields">
          <label class="word-detail-label">Meaning
            <input id="toolbar-word-detail-meaning" type="text" placeholder="Definition…">
          </label>
          <label class="word-detail-label">Takeaway
            <input id="toolbar-word-detail-note" type="text" placeholder="What I should remember…">
          </label>
        </div>
        <div class="word-detail-actions">
          <button id="toolbar-word-detail-save" type="button">Save</button>
          <button id="toolbar-word-detail-explain" type="button">Explain word</button>
          <button id="toolbar-word-detail-view-card" type="button">View card</button>
          <button id="toolbar-word-detail-remove" type="button" class="danger">Remove from cards</button>
        </div>
      </div>
      <div id="toolbar-cross-sentence" class="toolbar-group" hidden>
        <span class="toolbar-status">Selection spans sentences</span>
        <button id="toolbar-cross-sentence-delete" type="button" class="danger" hidden>Unmark sentences</button>
        <button id="toolbar-dismiss" type="button">Dismiss</button>
      </div>
      <button id="toolbar-analysis-open" type="button" hidden>AI analysis</button>
    </div>
    <script id="word-card-index" type="application/json">{_json_script(word_index)}</script>
    <script>{_selection_script()}</script>
    """

def _analysis_panel() -> str:
    return """
    <button id="analysis-panel-tab" class="analysis-panel-tab" type="button" aria-controls="analysis-panel">
      Analysis
    </button>
    <aside id="analysis-panel" class="analysis-panel" hidden aria-live="polite">
      <header class="analysis-panel-header">
        <div>
          <p id="analysis-panel-kicker" class="panel-kicker">Sentence analysis</p>
          <div class="analysis-title-row">
            <h2 id="analysis-panel-title">AI Analysis</h2>
            <button
              id="analysis-word-pronunciation"
              class="speak-button"
              type="button"
              data-speak-text=""
              title="Play pronunciation"
              aria-label="Play pronunciation"
              hidden>▶</button>
          </div>
          <p id="analysis-panel-meta" class="muted"></p>
        </div>
        <button id="analysis-panel-close" type="button">Close panel</button>
      </header>
      <div id="analysis-panel-status" class="analysis-status"></div>
      <div id="analysis-sentence-sections">
        <section class="analysis-section">
          <h3><span class="section-label-zh">简化英文</span><span class="section-label-en">Simplified English</span></h3>
          <p id="analysis-simplified" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3><span class="section-label-zh">中文释义</span><span class="section-label-en">Chinese meaning</span></h3>
          <p id="analysis-gloss" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3><span class="section-label-zh">阅读卡点</span><span class="section-label-en">Blocking point</span></h3>
          <p id="analysis-blocking-point" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3><span class="section-label-zh">句子结构</span><span class="section-label-en">Structure</span></h3>
          <h4><span class="section-label-zh">主干骨架</span><span class="section-label-en">Subject skeleton</span></h4>
          <p id="analysis-skeleton" class="analysis-text"></p>
          <h4><span class="section-label-zh">从句</span><span class="section-label-en">Clauses</span></h4>
          <div id="analysis-clauses"></div>
          <h4><span class="section-label-zh">修饰成分</span><span class="section-label-en">Modifiers</span></h4>
          <div id="analysis-modifiers"></div>
          <h4><span class="section-label-zh">逻辑连接词</span><span class="section-label-en">Logic markers</span></h4>
          <div id="analysis-logic-markers"></div>
          <h4><span class="section-label-zh">指代关系</span><span class="section-label-en">Anaphora</span></h4>
          <div id="analysis-anaphora"></div>
        </section>
        <section class="analysis-section">
          <h3><span class="section-label-zh">问题诊断</span><span class="section-label-en">Diagnosis</span></h3>
          <div id="analysis-diagnosis"></div>
        </section>
        <section class="analysis-section">
          <h3><span class="section-label-zh">回到整句</span><span class="section-label-en">Back to whole sentence</span></h3>
          <p id="analysis-back-to-whole" class="analysis-text"></p>
        </section>
        <section class="analysis-section sentence-study-section">
          <h3><span class="section-label-zh">我的翻译</span><span class="section-label-en">Your translation</span></h3>
          <textarea id="sentence-panel-translation" rows="4" placeholder="Edit your Chinese understanding"></textarea>
          <div class="word-notes-actions">
            <button id="sentence-panel-translation-save" type="button">Save translation</button>
            <span id="sentence-panel-translation-status" class="toolbar-status" aria-live="polite"></span>
          </div>
        </section>
        <section class="analysis-section sentence-study-section">
          <h3><span class="section-label-zh">收获</span><span class="section-label-en">Takeaway</span></h3>
          <p id="sentence-panel-note-suggestion" class="analysis-text"></p>
          <button id="sentence-panel-note-accept" type="button">Accept suggestion</button>
          <textarea id="sentence-panel-note" rows="3" placeholder="What did I learn from this sentence?"></textarea>
          <div class="word-notes-actions">
            <button id="sentence-panel-note-save" type="button">Save takeaway</button>
            <span id="sentence-panel-note-status" class="toolbar-status" aria-live="polite"></span>
          </div>
        </section>
      </div>
      <div id="analysis-word-sections" hidden>
        <section class="analysis-section">
          <h3>In this sentence</h3>
          <p id="analysis-word-role" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Meaning in context</h3>
          <p id="analysis-word-meaning" class="analysis-text"></p>
          <p id="analysis-word-meaning-zh" class="analysis-text analysis-translation"></p>
        </section>
        <section class="analysis-section">
          <h3>Register</h3>
          <p id="analysis-word-register" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Why this word</h3>
          <p id="analysis-word-why" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>vs. simpler alternatives</h3>
          <div id="analysis-word-vs-simpler"></div>
        </section>
        <section id="analysis-word-note-check-section" class="analysis-section" hidden>
          <h3>Takeaway check</h3>
          <p id="analysis-word-note-check" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Morphology</h3>
          <p id="analysis-word-morphology" class="analysis-text"></p>
        </section>
        <section class="analysis-section">
          <h3>Predicted error types</h3>
          <p id="analysis-word-errors" class="analysis-text analysis-codes"></p>
        </section>
        <section id="word-panel-notes" class="analysis-section">
          <h3>My word card</h3>
          <div class="word-notes-fields">
            <label class="word-notes-label">Definition
              <input id="word-panel-meaning" type="text" placeholder="My definition…">
            </label>
            <label class="word-notes-label">Takeaway
              <input id="word-panel-note" type="text" placeholder="What I should remember…">
            </label>
          </div>
          <div class="word-notes-actions">
            <button id="word-panel-save" type="button">Save</button>
            <span id="word-panel-save-status" class="toolbar-status" aria-live="polite"></span>
          </div>
        </section>
      </div>
      <footer class="analysis-panel-actions">
        <button id="analysis-panel-retry" type="button">Reanalyze</button>
        <button id="analysis-panel-retry-pro" type="button">Reanalyze with Pro</button>
        <button id="analysis-panel-previous" type="button" hidden>Back to previous analysis</button>
        <button id="analysis-panel-unmark" type="button" class="danger" hidden>Unmark sentence</button>
        <button id="analysis-panel-return" type="button">Back to reading</button>
      </footer>
    </aside>
    """

def _json_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c")
