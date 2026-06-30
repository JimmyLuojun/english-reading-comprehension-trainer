"""Tests for app.importers.markdown_importer."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.importers.markdown_importer import (
    _clean_inline_markdown,
    _split_markdown_chapters,
    import_markdown,
    import_markdown_bytes,
)
from app.importers.txt_importer import DuplicateBookError


MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


def _write_md(tmp_path: Path, content: str, name: str = "article.md") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _sentences_for_book(db: DatabaseConnection, book_id: int) -> list[str]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT text FROM sentences WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()
    return [row["text"] for row in rows]


def test_import_markdown_inserts_md_book_and_clean_sentences(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    path = _write_md(
        tmp_path,
        """---
title: Ignored Front Matter
---

# First Chapter

This **first** paragraph has [a useful link](https://example.com) for reading.

> A quoted sentence remains readable.

```python
print("Code should not become a sentence.")
```

## Second Chapter

- [x] The list item becomes plain prose.
- Another item has `inline code` but still reads well.
""",
    )

    result = import_markdown(db, path, title="Markdown Book", author="Author")

    assert result.chapter_count == 2
    assert result.sentence_count >= 4
    with db.get_connection() as conn:
        book = conn.execute(
            "SELECT title, author, source_format FROM books WHERE id = ?",
            (result.book_id,),
        ).fetchone()
        chapters = conn.execute(
            "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
            (result.book_id,),
        ).fetchall()
    assert book["title"] == "Markdown Book"
    assert book["author"] == "Author"
    assert book["source_format"] == "md"
    assert [row["title"] for row in chapters] == ["First Chapter", "Second Chapter"]
    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "first paragraph has a useful link for reading" in text
    assert "quoted sentence remains readable" in text
    assert "The list item becomes plain prose" in text
    assert "Code should not become" not in text
    assert "**" not in text
    assert "https://example.com" not in text


def test_import_markdown_without_headings_uses_single_chapter(
    db: DatabaseConnection,
) -> None:
    result = import_markdown_bytes(
        db,
        b"Plain **Markdown** text. It has another sentence.",
        title="No Headings",
    )

    assert result.chapter_count == 1
    assert result.sentence_count == 2
    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "Plain Markdown text" in text


def test_import_markdown_deduplicates_on_original_bytes(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    path = _write_md(tmp_path, "# Title\n\nUnique Markdown sentence.")

    import_markdown(db, path, title="First")

    with pytest.raises(DuplicateBookError):
        import_markdown(db, path, title="Second")


def test_import_markdown_empty_or_code_only_rejected(db: DatabaseConnection) -> None:
    with pytest.raises(ValueError, match="no usable text"):
        import_markdown_bytes(db, b"```python\nprint('x')\n```", title="Code")


def test_import_markdown_missing_file_raises_file_not_found(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        import_markdown(db, tmp_path / "missing.md", title="Missing")


def test_import_markdown_directory_rejected(
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="not a file"):
        import_markdown(db, tmp_path, title="Directory")


def test_split_markdown_chapters_supports_setext_headings() -> None:
    chapters = _split_markdown_chapters(
        "Opening\n=======\n\nThe opening sentence is readable.\n\nNext\n----\n\nThe next sentence is readable."
    )

    assert [chapter["title"] for chapter in chapters] == ["Opening", "Next"]


def test_split_markdown_chapters_returns_empty_for_heading_only() -> None:
    assert _split_markdown_chapters("# Empty Heading") == []


def test_markdown_cleaning_preserves_unclosed_front_matter_and_skips_rules(
    db: DatabaseConnection,
) -> None:
    result = import_markdown_bytes(
        db,
        b"""+++
title: Not actually front matter without a closing delimiter.

# Notes

Intro sentence stays readable.

[ref]: https://example.com
| --- | --- |
***

> > Nested quote sentence stays readable.
1. Numbered item sentence stays readable.
* Bullet item sentence stays readable.
""",
        title="Rules",
    )

    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "Intro sentence stays readable" in text
    assert "Nested quote sentence stays readable" in text
    assert "Numbered item sentence stays readable" in text
    assert "Bullet item sentence stays readable" in text
    assert "https://example.com" not in text
    assert "***" not in text


def test_clean_inline_markdown_handles_images_links_html_and_escapes() -> None:
    assert (
        _clean_inline_markdown(
            r"![Alt text](image.png) <span>**bold**</span> [link](https://x.test) \*literal\*"
        )
        == "Alt text bold link *literal*"
    )
