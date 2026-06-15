"""
Minimal programmatic EPUB builder for tests.

Wraps ebooklib to create valid .epub files in tmp_path without
requiring real EPUB fixtures on disk.
"""

from pathlib import Path

from ebooklib import epub


PNG_1X1_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfeA\xe2`\x82\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


def make_epub_with_html(
    tmp_path: Path,
    filename: str,
    *,
    body_html: str,
    title: str = "HTML Fixture",
    author: str = "Fixture Author",
    language: str = "en",
) -> Path:
    """EPUB with one chapter whose body is supplied as raw HTML."""
    book = epub.EpubBook()
    book.set_identifier(f"html-fixture-{filename}")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    html_content = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<!DOCTYPE html>'
        f'<html xmlns="http://www.w3.org/1999/xhtml">'
        f'<head><title>{title}</title></head>'
        f'<body><h1>{title}</h1>{body_html}</body></html>'
    )
    item = epub.EpubHtml(title=title, file_name="chap_001.xhtml", lang=language)
    item.content = html_content.encode("utf-8")
    book.add_item(item)

    book.toc = [epub.Link("chap_001.xhtml", title, "c1")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", item]

    out_path = tmp_path / filename
    epub.write_epub(str(out_path), book)
    return out_path


def make_epub_with_image(
    tmp_path: Path,
    filename: str,
    *,
    body_html: str | None = None,
    title: str = "Image Fixture",
    author: str = "Fixture Author",
    language: str = "en",
    image_path: str = "images/diagram.png",
    image_bytes: bytes = PNG_1X1_BYTES,
) -> Path:
    """EPUB with one chapter and one PNG manifest asset."""
    book = epub.EpubBook()
    book.set_identifier(f"image-fixture-{filename}")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    if body_html is None:
        body_html = (
            "<p>Before image prose with enough words to become sentences.</p>"
            f'<figure><img src="{image_path}" alt="Network diagram"/>'
            "<figcaption>Figure 1. Network diagram caption.</figcaption></figure>"
            "<p>After image prose with enough words to become sentences.</p>"
        )

    html_content = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<!DOCTYPE html>'
        f'<html xmlns="http://www.w3.org/1999/xhtml">'
        f'<head><title>{title}</title></head>'
        f'<body><h1>{title}</h1>{body_html}</body></html>'
    )
    item = epub.EpubHtml(title=title, file_name="chap_001.xhtml", lang=language)
    item.content = html_content.encode("utf-8")
    image = epub.EpubImage(
        uid="diagram",
        file_name=image_path,
        media_type="image/png",
        content=image_bytes,
    )
    book.add_item(item)
    book.add_item(image)

    book.toc = [epub.Link("chap_001.xhtml", title, "c1")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", item]

    out_path = tmp_path / filename
    epub.write_epub(str(out_path), book)
    return out_path


def make_epub_with_sections(
    tmp_path: Path,
    filename: str,
    *,
    sections: list[dict],
    title: str = "Structured Fixture",
    author: str = "Fixture Author",
    language: str = "en",
) -> Path:
    """EPUB with raw section metadata and optional nested TOC entries."""
    book = epub.EpubBook()
    book.set_identifier(f"structured-fixture-{filename}")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    spine_items: list = ["nav"]
    toc_links: list = []

    for idx, section in enumerate(sections, start=1):
        file_name = section.get("file_name", f"section_{idx:03d}.xhtml")
        section_title = section["title"]
        epub_type = section.get("epub_type", "chapter")
        body_html = section["body_html"]
        html_content = (
            f'<?xml version="1.0" encoding="utf-8"?>'
            f'<!DOCTYPE html>'
            f'<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops">'
            f'<head><title>{section_title}</title></head>'
            f'<body><section epub:type="{epub_type}">'
            f'<h1>{section_title}</h1>{body_html}'
            f'</section></body></html>'
        )
        item = epub.EpubHtml(
            title=section_title,
            file_name=file_name,
            lang=language,
        )
        item.content = html_content.encode("utf-8")
        book.add_item(item)
        spine_items.append(item)

        toc_entry = epub.Link(
            file_name,
            section.get("toc_title", section_title),
            f"section-{idx}",
        )
        children = [
            epub.Link(child["href"], child["title"], f"section-{idx}-child-{child_idx}")
            for child_idx, child in enumerate(section.get("toc_children", []), start=1)
        ]
        toc_links.append((toc_entry, children) if children else toc_entry)

    book.toc = toc_links
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    out_path = tmp_path / filename
    epub.write_epub(str(out_path), book)
    return out_path
