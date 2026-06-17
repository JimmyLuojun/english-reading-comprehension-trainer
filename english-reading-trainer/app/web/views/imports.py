"""Import page rendering helpers."""

from __future__ import annotations

from fastapi.responses import HTMLResponse

from app.web.views.layout import _html_page

def _import_forms() -> str:
    return """
    <section class="toolbar">
      <div>
        <h1>Import</h1>
        <p class="muted">Add a TXT, EPUB, or PDF file, or paste text directly. You jump straight to the reader after import.</p>
      </div>
    </section>
    <section class="band">
      <h2>Upload file</h2>
      <form method="post" action="/import/file" enctype="multipart/form-data" class="stack-form">
        <label for="file-title">Title (optional)</label>
        <input id="file-title" name="title" placeholder="Leave blank to auto-detect">
        <label for="file-author">Author (optional)</label>
        <input id="file-author" name="author">
        <label for="file-input">TXT, EPUB, or PDF file</label>
        <input id="file-input" type="file" name="file" accept=".txt,.epub,.pdf,text/plain,application/epub+zip,application/pdf" required>
        <button type="submit">Import file</button>
      </form>
    </section>
    <section class="band">
      <h2>Paste text</h2>
      <form method="post" action="/import/paste" class="stack-form">
        <label for="paste-title">Title (optional)</label>
        <input id="paste-title" name="title" placeholder="Leave blank to auto-detect">
        <label for="paste-author">Author (optional)</label>
        <input id="paste-author" name="author">
        <label for="paste-text">Article text</label>
        <textarea id="paste-text" name="text" rows="14" placeholder="Paste an article here..." required></textarea>
        <button type="submit">Import pasted text</button>
      </form>
    </section>
    """

def _duplicate_page(existing_book_id: int | None) -> HTMLResponse:
    if existing_book_id is not None:
        link = (
            f'<a class="button primary" href="/read/{existing_book_id}">Open existing book</a> '
            f'<a class="button" href="/books/{existing_book_id}">View chapters</a>'
        )
    else:
        link = '<a class="button" href="/books">Browse books</a>'
    body = f"""
    <section class="toolbar">
      <div>
        <h1>Already imported</h1>
        <p class="muted">This content has the same hash as a book already in your library.</p>
      </div>
    </section>
    <section class="band">
      <p>No new book was created. Open the existing one to keep reading.</p>
      <p>{link}</p>
    </section>
    """
    return _html_page("Already imported", body, active="import", status_code=409)
