"""
Minimal programmatic EPUB builder for tests.

Wraps ebooklib to create valid .epub files in tmp_path without
requiring real EPUB fixtures on disk.
"""

from pathlib import Path

from ebooklib import epub


def make_epub(
    tmp_path: Path,
    filename: str,
    title: str = "Test Book",
    author: str = "Test Author",
    chapters: list[dict] | None = None,
    language: str = "en",
) -> Path:
    """
    Build a minimal but valid EPUB file.

    chapters: list of {"title": str, "paragraphs": [str, ...]}
    If None, a single default chapter is used.
    Returns the Path to the written .epub file.
    """
    if chapters is None:
        chapters = [
            {
                "title": "Chapter 1",
                "paragraphs": [
                    "This is the first paragraph of chapter one. "
                    "It contains two sentences.",
                    "This is the second paragraph. Another sentence follows here.",
                ],
            }
        ]

    book = epub.EpubBook()
    book.set_identifier("test-id-001")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    spine_items: list = ["nav"]
    toc_links: list = []

    for idx, ch in enumerate(chapters, start=1):
        ch_id   = f"chap_{idx:03d}"
        ch_file = f"{ch_id}.xhtml"

        # Build HTML content
        paras_html = "\n".join(
            f"<p>{p}</p>" for p in ch["paragraphs"]
        )
        html_content = (
            f'<?xml version="1.0" encoding="utf-8"?>'
            f'<!DOCTYPE html>'
            f'<html xmlns="http://www.w3.org/1999/xhtml">'
            f'<head><title>{ch["title"]}</title></head>'
            f'<body>'
            f'<h1>{ch["title"]}</h1>'
            f'{paras_html}'
            f'</body></html>'
        )

        item = epub.EpubHtml(
            title=ch["title"],
            file_name=ch_file,
            lang=language,
        )
        item.content = html_content.encode("utf-8")
        book.add_item(item)
        spine_items.append(item)
        toc_links.append(epub.Link(ch_file, ch["title"], ch_id))

    # Navigation
    book.toc = toc_links
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    out_path = tmp_path / filename
    epub.write_epub(str(out_path), book)
    return out_path


def make_epub_no_toc(
    tmp_path: Path,
    filename: str,
    chapters: list[dict],
) -> Path:
    """EPUB with chapters but TOC entries have no titles (tests heading fallback)."""
    book = epub.EpubBook()
    book.set_identifier("no-toc-001")
    book.set_title("No TOC Book")
    book.set_language("en")

    spine_items: list = ["nav"]

    for idx, ch in enumerate(chapters, start=1):
        ch_id   = f"chap_{idx:03d}"
        ch_file = f"{ch_id}.xhtml"
        paras_html = "\n".join(f"<p>{p}</p>" for p in ch["paragraphs"])
        html_content = (
            f'<html><head><title></title></head>'
            f'<body><h2>{ch["title"]}</h2>{paras_html}</body></html>'
        )
        item = epub.EpubHtml(title="", file_name=ch_file, lang="en")
        item.content = html_content.encode("utf-8")
        book.add_item(item)
        spine_items.append(item)

    # Intentionally empty TOC
    book.toc = []
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    out_path = tmp_path / filename
    epub.write_epub(str(out_path), book)
    return out_path


def make_epub_no_paragraphs(tmp_path: Path, filename: str) -> Path:
    """EPUB where body has no <p> tags — tests block-level fallback."""
    book = epub.EpubBook()
    book.set_identifier("no-p-001")
    book.set_title("No P Tags")
    book.set_language("en")

    html_content = (
        "<html><body>"
        "<div>First block with enough text to count as a paragraph here.</div>"
        "<div>Second block with enough text to count as a paragraph too here.</div>"
        "</body></html>"
    )
    item = epub.EpubHtml(title="Chapter 1", file_name="chap_001.xhtml", lang="en")
    item.content = html_content.encode("utf-8")
    book.add_item(item)

    book.toc = [epub.Link("chap_001.xhtml", "Chapter 1", "c1")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", item]

    out_path = tmp_path / filename
    epub.write_epub(str(out_path), book)
    return out_path
