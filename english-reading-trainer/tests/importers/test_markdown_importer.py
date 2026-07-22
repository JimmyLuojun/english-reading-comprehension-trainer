"""Tests for app.importers.markdown_importer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db_connection import DatabaseConnection
from app.importers import markdown_importer
from app.importers.markdown_importer import (
    _MarkdownImageRegistry,
    _MarkdownInlineImage,
    _clean_inline_markdown,
    _clean_markdown_line,
    _data_image_references,
    _decode_data_image,
    _final_inline_image_token,
    _inline_image_storage_path,
    _markdown_blocks,
    _split_markdown_chapters,
    import_markdown,
    import_markdown_bytes,
)
from app.importers.txt_importer import DuplicateBookError


MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
TINY_JPEG_DATA_URL = "data:image/jpeg;base64,/9j/2Q=="


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

    assert result.chapter_count == 1
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
        blocks = conn.execute(
            """SELECT kind, text, payload_json
                 FROM chapter_blocks
                WHERE book_id = ?
                ORDER BY idx""",
            (result.book_id,),
        ).fetchall()
    assert book["title"] == "Markdown Book"
    assert book["author"] == "Author"
    assert book["source_format"] == "md"
    assert [row["title"] for row in chapters] == ["Chapter 1"]
    text = " ".join(_sentences_for_book(db, result.book_id))
    assert "First Chapter" not in text
    assert "Second Chapter" not in text
    assert "first paragraph has a useful link for reading" in text
    assert "quoted sentence remains readable" in text
    assert "The list item becomes plain prose" in text
    assert "Code should not become" not in text
    assert "**" not in text
    assert "https://example.com" not in text
    assert [row["kind"] for row in blocks] == [
        "heading",
        "prose",
        "prose",
        "heading",
        "list_item",
        "list_item",
    ]
    assert blocks[0]["text"] == "First Chapter"
    assert '"level": 1' in blocks[0]["payload_json"]
    assert '"quote_depth": 1' in blocks[2]["payload_json"]
    assert blocks[3]["text"] == "Second Chapter"
    assert '"level": 2' in blocks[3]["payload_json"]
    assert blocks[4]["text"] == ""
    assert '"ordered": false' in blocks[4]["payload_json"]


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


def test_import_markdown_preserves_inline_data_images_as_assets(
    db: DatabaseConnection,
) -> None:
    result = import_markdown_bytes(
        db,
        f"If ![]({TINY_PNG_DATA_URL}) is true, continue.".encode("utf-8"),
        title="Inline Formula",
    )

    with db.get_connection() as conn:
        asset = conn.execute(
            """SELECT id, media_type, storage_path, byte_size
                 FROM book_assets
                WHERE book_id = ?""",
            (result.book_id,),
        ).fetchone()
        sentence = conn.execute(
            "SELECT text FROM sentences WHERE book_id = ?",
            (result.book_id,),
        ).fetchone()

    assert asset is not None
    assert asset["media_type"] == "image/png"
    assert asset["byte_size"] > 0
    assert sentence["text"] == f"If [[md-image:{asset['id']}]] is true, continue."

    asset_path = Path(db._db_path).parent / "assets" / asset["storage_path"]
    assert asset_path.exists()


def test_import_markdown_reuses_duplicate_inline_data_image_tokens() -> None:
    registry = _MarkdownImageRegistry()

    first = registry.token_for(TINY_PNG_DATA_URL, "first")
    second = registry.token_for(f" {TINY_PNG_DATA_URL} ", "second")

    assert first == second
    assert len(registry.images) == 1


def test_import_markdown_rolls_back_book_when_inline_image_storage_fails(
    db: DatabaseConnection,
    monkeypatch,
) -> None:
    def fail_store(db_arg, book_id, images):
        raise RuntimeError("disk full")

    monkeypatch.setattr(markdown_importer, "_store_inline_images", fail_store)

    with pytest.raises(RuntimeError, match="disk full"):
        import_markdown_bytes(
            db,
            f"If ![]({TINY_PNG_DATA_URL}) is true, continue.".encode("utf-8"),
            title="Rollback",
        )

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0


def test_markdown_blocks_preserve_headings_paragraphs_and_lists() -> None:
    blocks = _markdown_blocks(
        """# Title

Intro wraps
across lines.

1. Ordered item sentence.
2. Another item.

## Subheading

- Bullet item.
"""
    )

    assert [(block.kind, block.text) for block in blocks] == [
        ("heading", "Title"),
        ("prose", "Intro wraps across lines."),
        ("list_item", "Ordered item sentence."),
        ("list_item", "Another item."),
        ("heading", "Subheading"),
        ("list_item", "Bullet item."),
    ]
    assert '"level": 1' in blocks[0].payload_json
    assert '"ordered": true' in blocks[2].payload_json
    assert '"level": 2' in blocks[4].payload_json
    assert '"ordered": false' in blocks[5].payload_json


def test_markdown_blocks_preserve_quote_depth_and_task_state() -> None:
    blocks = _markdown_blocks(
        """> First quoted line
> wraps in the same quote.
>
>> Nested quote.

- [ ] Pending practice item.
- [x] Completed practice item.
> - [x] Completed quoted item.

Plain paragraph.
"""
    )

    assert [(block.kind, block.text) for block in blocks] == [
        ("prose", "First quoted line wraps in the same quote."),
        ("prose", "Nested quote."),
        ("list_item", "Pending practice item."),
        ("list_item", "Completed practice item."),
        ("list_item", "Completed quoted item."),
        ("prose", "Plain paragraph."),
    ]
    assert json.loads(blocks[0].payload_json) == {"quote_depth": 1}
    assert json.loads(blocks[1].payload_json) == {"quote_depth": 2}
    assert json.loads(blocks[2].payload_json) == {
        "ordered": False,
        "marker": "-",
        "task": True,
        "checked": False,
    }
    assert json.loads(blocks[3].payload_json)["checked"] is True
    assert json.loads(blocks[4].payload_json) == {
        "ordered": False,
        "marker": "-",
        "quote_depth": 1,
        "task": True,
        "checked": True,
    }
    assert blocks[5].payload_json == ""


def test_markdown_blocks_split_when_quote_depth_changes_without_blank_line() -> None:
    blocks = _markdown_blocks("> Quoted sentence.\nPlain sentence.\n>>>>>>>>> Deep quote.")

    assert [block.text for block in blocks] == [
        "Quoted sentence.",
        "Plain sentence.",
        "Deep quote.",
    ]
    assert [json.loads(block.payload_json or "{}") for block in blocks] == [
        {"quote_depth": 1},
        {},
        {"quote_depth": 6},
    ]


def test_markdown_blocks_preserve_safe_whole_block_emphasis() -> None:
    blocks = _markdown_blocks(
        "**You:**\n\n*Read this carefully.*\n\n**Only** part is strong.\n\n**Mismatched__"
    )

    assert [block.text for block in blocks] == [
        "You:",
        "Read this carefully.",
        "Only part is strong.",
        "**Mismatched__",
    ]
    assert [json.loads(block.payload_json or "{}") for block in blocks] == [
        {"block_style": "strong"},
        {"block_style": "emphasis"},
        {},
        {},
    ]


def test_markdown_blocks_register_reference_data_images() -> None:
    registry = _MarkdownImageRegistry()

    blocks = _markdown_blocks(
        f"Text before ![formula][img].\n\n[img]: {TINY_PNG_DATA_URL}",
        image_registry=registry,
    )

    assert len(registry.images) == 1
    assert "[[md-image-token:0]]" in blocks[0].text


def test_markdown_blocks_update_heading_inline_image_tokens(
    db: DatabaseConnection,
) -> None:
    result = import_markdown_bytes(
        db,
        f"# Formula ![]({TINY_PNG_DATA_URL})\n\nReadable sentence.".encode("utf-8"),
        title="Heading Image",
    )

    with db.get_connection() as conn:
        asset_id = conn.execute(
            "SELECT id FROM book_assets WHERE book_id = ?",
            (result.book_id,),
        ).fetchone()["id"]
        heading = conn.execute(
            "SELECT text FROM chapter_blocks WHERE book_id = ? AND kind = 'heading'",
            (result.book_id,),
        ).fetchone()["text"]

    assert heading == f"Formula [[md-image:{asset_id}]]"


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


def test_split_markdown_chapters_skips_setext_headings_in_one_chapter() -> None:
    chapters = _split_markdown_chapters(
        "Opening\n=======\n\nThe opening sentence is readable.\n\nNext\n----\n\nThe next sentence is readable."
    )

    assert [chapter["title"] for chapter in chapters] == ["Chapter 1"]
    assert "Opening" not in chapters[0]["body"]
    assert "The opening sentence is readable." in chapters[0]["body"]
    assert "Next" not in chapters[0]["body"]
    assert "The next sentence is readable." in chapters[0]["body"]


def test_split_markdown_chapters_returns_empty_for_heading_only() -> None:
    assert _split_markdown_chapters("# Empty Heading") == []


def test_split_markdown_chapters_does_not_split_numbered_sections() -> None:
    chapters = _split_markdown_chapters(
        """# Logic Notes

Introductory overview sentence.

## Part 1

Part context sentence.

### 7.1: Rules of Implication I

First rule section sentence.

### 7.2: Rules of Implication II

Second rule section sentence.
"""
    )

    assert len(chapters) == 1
    assert chapters[0]["title"] == "Chapter 1"
    assert "Logic Notes" not in chapters[0]["body"]
    assert "Part 1" not in chapters[0]["body"]
    assert "7.1: Rules of Implication I" not in chapters[0]["body"]
    assert "7.2: Rules of Implication II" not in chapters[0]["body"]
    assert "Introductory overview sentence." in chapters[0]["body"]
    assert "Part context sentence." in chapters[0]["body"]
    assert "First rule section sentence." in chapters[0]["body"]
    assert "Second rule section sentence." in chapters[0]["body"]


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


def test_clean_markdown_line_handles_empty_reference_table_and_rule() -> None:
    assert _clean_markdown_line("   ") == ""
    assert _clean_markdown_line("[ref]: https://example.com") is None
    assert _clean_markdown_line("| --- | --- |") is None
    assert _clean_markdown_line("***") == ""


def test_clean_inline_markdown_handles_images_links_html_and_escapes() -> None:
    assert (
        _clean_inline_markdown(
            r"![Alt text](image.png) <span>**bold**</span> [link](https://x.test) \*literal\*"
        )
        == "Alt text bold link *literal*"
    )


def test_clean_inline_markdown_falls_back_to_alt_for_invalid_data_image() -> None:
    registry = _MarkdownImageRegistry()

    assert (
        _clean_inline_markdown(
            "![Alt text](data:image/png;base64,not-valid)",
            image_registry=registry,
        )
        == "Alt text"
    )
    assert registry.images == []


def test_data_image_helpers_validate_payloads_and_storage_paths(monkeypatch) -> None:
    assert _data_image_references([f"[img]: {TINY_PNG_DATA_URL}"]) == {
        "img": TINY_PNG_DATA_URL
    }
    with pytest.raises(ValueError, match="Unsupported"):
        _decode_data_image("https://example.com/image.png")
    with pytest.raises(ValueError, match="Invalid"):
        _decode_data_image("data:image/png;base64,abcd=")
    with pytest.raises(ValueError, match="Unsupported"):
        _decode_data_image("data:image/png;base64,")
    assert _final_inline_image_token({0: 42}, 0) == "[[md-image:42]]"
    assert _final_inline_image_token({}, 0) == ""

    monkeypatch.setattr(markdown_importer.mimetypes, "guess_extension", lambda media_type: ".jpe")
    image = _MarkdownInlineImage(
        token_index=3,
        data_url=TINY_JPEG_DATA_URL,
        media_type="image/jpeg",
        content=b"jpeg",
        alt_text="Alt",
    )

    assert _inline_image_storage_path(9, image, "abcdef1234567890").endswith(
        "markdown-inline-3-abcdef123456.jpg"
    )
