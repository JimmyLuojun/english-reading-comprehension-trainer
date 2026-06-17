"""
Integration tests for app/importers/epub_importer.py.

Uses real SQLite (tmp_path) and programmatically built EPUB fixtures
from epub_builder.py. No mocking.

Covers: metadata extraction, TOC-based chapter titles, heading fallback,
paragraph / sentence counts, text_hash / file_hash, duplicate detection,
missing file, empty EPUB, no-<p>-tag fallback, DB hierarchy integrity,
cascade queries, ImportResult ↔ DB consistency.
"""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.importers.epub_importer import (
    EpubAssetSource,
    TextBlock,
    _SECTION_APPENDIX,
    _SECTION_BACKMATTER,
    _SECTION_CHAPTER,
    _SECTION_FRONTMATTER,
    _asset_extension,
    _build_toc_map,
    _build_asset_sources,
    _classify_chapter,
    _coerce_text_block,
    _definition_block_from_dt,
    _direct_text,
    _extract_chapters,
    _extract_paragraphs,
    _extract_text_blocks,
    _heading_from_soup,
    _image_block_from_element,
    _is_extractable_descendant,
    _is_supported_asset,
    _lookup_asset_source,
    _missing_asset_hrefs_from_arcnames,
    _missing_manifest_asset_arcnames,
    _move_staged_assets,
    _normalize_epub_path,
    _opf_path_from_container,
    _prepare_epub_source,
    _resolve_epub_href,
    _table_row_block,
    _text_hash,
    _validate_epub_directory,
    _figure_block_from_element,
    _insert,
    calculate_epub_file_hash,
    import_epub,
)
from app.importers.txt_importer import DuplicateBookError, ImportResult
from app.nlp.sentence_segmenter import normalize_for_hash
from bs4 import BeautifulSoup
from bs4.element import Tag
from ebooklib import ITEM_DOCUMENT, ITEM_NAVIGATION
from ebooklib import epub

from tests.importers.epub_builder import (
    PNG_1X1_BYTES,
    make_epub,
    make_epub_with_html,
    make_epub_with_image,
    make_epub_with_sections,
    make_epub_no_paragraphs,
    make_epub_no_toc,
)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


@pytest.fixture()
def simple_epub(tmp_path: Path) -> Path:
    return make_epub(
        tmp_path,
        "simple.epub",
        title="My Test Book",
        author="Jane Doe",
        chapters=[
            {
                "title": "Chapter 1",
                "paragraphs": [
                    "The economy grew rapidly last year. Analysts were surprised.",
                    "Inflation remained a concern for many households.",
                ],
            },
            {
                "title": "Chapter 2",
                "paragraphs": [
                    "The second chapter begins here. It has two sentences.",
                    "A longer paragraph appears in this section. More details follow. "
                    "This is the third sentence.",
                ],
            },
        ],
    )


def explode_epub(epub_path: Path, target_dir: Path) -> Path:
    target_dir.mkdir()
    with ZipFile(epub_path) as archive:
        archive.extractall(target_dir)
    return target_dir


def write_minimal_epub_directory(package_path: Path, opf_body: str) -> Path:
    (package_path / "META-INF").mkdir(parents=True)
    (package_path / "OEBPS").mkdir()
    (package_path / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (package_path / "META-INF" / "container.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <container version="1.0"
          xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
          <rootfiles>
            <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
          </rootfiles>
        </container>""",
        encoding="utf-8",
    )
    (package_path / "OEBPS" / "content.opf").write_text(opf_body, encoding="utf-8")
    return package_path


def minimal_opf(manifest: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Fixture</dc:title>
      </metadata>
      <manifest>{manifest}</manifest>
      <spine/>
    </package>"""


class FakeEpubItem:
    def __init__(
        self,
        item_type: int,
        *,
        body: bytes | None = b"",
        content: bytes | None = b"",
        file_name: str = "fake.xhtml",
    ) -> None:
        self._item_type = item_type
        self._body = body
        self._content = content
        self.file_name = file_name

    def get_type(self) -> int:
        return self._item_type

    def get_body_content(self) -> bytes | None:
        return self._body

    def get_content(self) -> bytes | None:
        return self._content


class FakeEpubBook:
    def __init__(self, items: dict[str, FakeEpubItem | None]) -> None:
        self.spine = [(item_id, "yes") for item_id in items]
        self._items = items

    def get_item_with_id(self, item_id: str) -> FakeEpubItem | None:
        return self._items[item_id]


# ---------------------------------------------------------------------------
# Unit tests: _heading_from_soup
# ---------------------------------------------------------------------------

class TestHeadingFromSoup:
    def test_finds_h1(self) -> None:
        soup = BeautifulSoup("<html><body><h1>My Title</h1><p>text</p></body></html>", "lxml")
        assert _heading_from_soup(soup) == "My Title"

    def test_finds_h2_when_no_h1(self) -> None:
        soup = BeautifulSoup("<html><body><h2>Sub Title</h2><p>text</p></body></html>", "lxml")
        assert _heading_from_soup(soup) == "Sub Title"

    def test_returns_empty_when_no_heading(self) -> None:
        soup = BeautifulSoup("<html><body><p>Just a paragraph.</p></body></html>", "lxml")
        assert _heading_from_soup(soup) == ""

    def test_strips_heading_whitespace(self) -> None:
        soup = BeautifulSoup("<html><body><h1>  Padded  </h1></body></html>", "lxml")
        assert _heading_from_soup(soup) == "Padded"


# ---------------------------------------------------------------------------
# Unit tests: TOC and chapter classification
# ---------------------------------------------------------------------------

class TestTocAndChapterClassification:
    def test_toc_map_ignores_empty_titles_and_walks_nested_lists(self) -> None:
        toc = [
            epub.Link("empty.xhtml", "", "empty"),
            [
                epub.Link("nested.xhtml", "Nested Top Title", "nested"),
                epub.Link("nested.xhtml#child", "Nested Child Title", "child"),
            ],
        ]
        book = SimpleNamespace(toc=toc)

        toc_map = _build_toc_map(book)

        assert "empty.xhtml" not in toc_map
        assert toc_map["nested.xhtml"] == "Nested Top Title"
        assert toc_map["nested.xhtml"] != "Nested Child Title"

    def test_classifies_appendix_from_title(self) -> None:
        soup = BeautifulSoup("<html><body><section></section></body></html>", "lxml")

        classification = _classify_chapter("A. Useful Appendix", soup, 3)

        assert classification.section_kind == _SECTION_APPENDIX
        assert classification.chapter_number is None

    def test_classifies_backmatter_from_title(self) -> None:
        soup = BeautifulSoup("<html><body><section></section></body></html>", "lxml")

        classification = _classify_chapter("Index", soup, 3)

        assert classification.section_kind == _SECTION_BACKMATTER
        assert classification.chapter_number is None

    def test_classifies_cover_and_titlepage_as_frontmatter(self) -> None:
        soup = BeautifulSoup("<html><body><section></section></body></html>", "lxml")

        cover = _classify_chapter("cover", soup, 1)
        titlepage = _classify_chapter("Title Page", soup, 1)

        assert cover.section_kind == "frontmatter"
        assert cover.chapter_number is None
        assert titlepage.section_kind == "frontmatter"
        assert titlepage.chapter_number is None

    def test_classifies_part_title_as_non_counted_section(self) -> None:
        soup = BeautifulSoup("<html><body><section></section></body></html>", "lxml")

        classification = _classify_chapter("Part One: The Language of Money", soup, 1)

        assert classification.section_kind == _SECTION_FRONTMATTER
        assert classification.chapter_number is None

    def test_classifies_short_bodymatter_part_page_as_non_counted_section(
        self,
    ) -> None:
        soup = BeautifulSoup(
            """
            <html><body>
              <section epub:type="bodymatter">
                <p>Rich Dad Poor Dad for Teens PART TWO RICH DAD'S MONEY SECRETS</p>
              </section>
            </body></html>
            """,
            "lxml",
        )

        classification = _classify_chapter("Part002", soup, 2)

        assert classification.section_kind == _SECTION_FRONTMATTER
        assert classification.chapter_number is None

    def test_classifies_chapter_from_fallback_when_no_semantics(self) -> None:
        soup = BeautifulSoup("<html><body><section></section></body></html>", "lxml")

        classification = _classify_chapter("Unnumbered Body Section", soup, 7)

        assert classification.section_kind == _SECTION_CHAPTER
        assert classification.chapter_number == 7

    def test_epub_type_tokens_reads_root_without_body(self) -> None:
        soup = BeautifulSoup('<section type="appendix"></section>', "xml")

        classification = _classify_chapter("Untitled Appendix", soup, 1)

        assert classification.section_kind == _SECTION_APPENDIX

    def test_extract_chapters_skips_missing_navigation_non_document_and_empty_items(
        self,
    ) -> None:
        book = FakeEpubBook(
            {
                "missing": None,
                "nav": FakeEpubItem(ITEM_NAVIGATION),
                "style": FakeEpubItem(999),
                "empty": FakeEpubItem(ITEM_DOCUMENT, body=b"", content=b""),
            }
        )

        assert _extract_chapters(book, {}) == []


# ---------------------------------------------------------------------------
# Unit tests: _extract_paragraphs
# ---------------------------------------------------------------------------

class TestExtractParagraphs:
    def test_extracts_p_tags(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<p>First paragraph with enough text here.</p>"
            "<p>Second paragraph with enough text here.</p>"
            "</body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert len(paras) == 2

    def test_skips_short_paragraphs(self) -> None:
        soup = BeautifulSoup(
            "<html><body><p>Hi.</p><p>Long enough paragraph to pass the filter.</p></body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert len(paras) == 1
        assert "Long enough" in paras[0]

    def test_strips_script_and_style(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<script>alert('x')</script>"
            "<style>body{color:red}</style>"
            "<p>Valid paragraph text that is long enough.</p>"
            "</body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert all("alert" not in p for p in paras)
        assert all("color" not in p for p in paras)

    def test_falls_back_to_div_when_no_p(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<div>First div block with enough text to pass the length filter.</div>"
            "<div>Second div block also long enough to pass the length filter.</div>"
            "</body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert len(paras) >= 1

    def test_empty_html_returns_empty(self) -> None:
        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        paras = _extract_paragraphs(soup)
        assert paras == []

    def test_collapses_whitespace_in_paragraph(self) -> None:
        soup = BeautifulSoup(
            "<html><body><p>Word   with   extra    spaces   here.</p></body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        if paras:
            assert "  " not in paras[0]

    def test_returns_list_of_strings(self) -> None:
        soup = BeautifulSoup(
            "<html><body><p>A paragraph with sufficient length to pass.</p></body></html>",
            "lxml",
        )
        paras = _extract_paragraphs(soup)
        assert isinstance(paras, list)
        assert all(isinstance(p, str) for p in paras)

    def test_extracts_mixed_visible_blocks_in_order(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<p>First paragraph with enough text here.</p>"
            "<ul><li>List item text with enough words to be imported too.</li></ul>"
            "<dl>"
            "<dt>Full client</dt>"
            "<dd>Stores the complete blockchain history for validation.</dd>"
            "<dd>Runs independently without relying on third party servers.</dd>"
            "</dl>"
            "<pre>bitcoin-cli getnewaddress --verbose\n"
            "bitcoin-cli dumpprivkey exampleaddress</pre>"
            "<table><tr><td>Command name</td>"
            "<td>Creates a new receiving address for the wallet.</td></tr></table>"
            "<figcaption>Figure caption text with enough details for import.</figcaption>"
            "</body></html>",
            "lxml",
        )

        paras = _extract_paragraphs(soup)

        assert paras == [
            "First paragraph with enough text here.",
            "List item text with enough words to be imported too.",
            "Full client Stores the complete blockchain history for validation. "
            "Runs independently without relying on third party servers.",
            "bitcoin-cli getnewaddress --verbose bitcoin-cli dumpprivkey exampleaddress",
            "Command name | Creates a new receiving address for the wallet.",
            "Figure caption text with enough details for import.",
        ]

    def test_nested_parent_and_child_blocks_are_not_duplicated(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<div><p>Nested paragraph with enough text to be imported.</p></div>"
            "</body></html>",
            "lxml",
        )

        paras = _extract_paragraphs(soup)

        assert paras == ["Nested paragraph with enough text to be imported."]

    def test_extracts_standalone_definition_description(self) -> None:
        soup = BeautifulSoup(
            "<html><body><dl>"
            "<dd>Standalone definition description long enough to import.</dd>"
            "</dl></body></html>",
            "lxml",
        )

        paras = _extract_paragraphs(soup)

        assert paras == ["Standalone definition description long enough to import."]

    def test_extracts_table_without_row_children_as_whole_block(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<table>Table direct text with enough details to import as one block.</table>"
            "</body></html>",
            "lxml",
        )

        paras = _extract_paragraphs(soup)

        assert paras == ["Table direct text with enough details to import as one block."]

    def test_extracts_direct_text_from_container_with_nested_blocks(self) -> None:
        soup = BeautifulSoup(
            "<html><body>"
            "<blockquote>Direct quote wrapper text long enough."
            "<p>Nested quote paragraph long enough to import too.</p></blockquote>"
            "<ul><li>Direct list wrapper text long enough."
            "<p>Nested list paragraph long enough to import too.</p></li></ul>"
            "</body></html>",
            "lxml",
        )

        paras = _extract_paragraphs(soup)

        assert paras == [
            "Direct quote wrapper text long enough.",
            "Nested quote paragraph long enough to import too.",
            "Direct list wrapper text long enough.",
            "Nested list paragraph long enough to import too.",
        ]

    def test_extract_text_blocks_skips_non_tag_entries_from_custom_root(self) -> None:
        class FakeRoot:
            def find_all(self, _all: bool) -> list[str]:
                return ["not-a-tag"]

        class FakeSoup:
            body = FakeRoot()

            def find_all(self, _tags: set[str]) -> list:
                return []

        assert _extract_text_blocks(FakeSoup()) == []

    def test_definition_block_handles_non_dd_siblings_and_next_dt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        soup = BeautifulSoup(
            "<dl><dt>Definition term with enough words</dt>"
            "<span>ignored sibling</span>"
            "<dd>Definition description with enough words.</dd>"
            "<dt>Next definition term with enough words</dt></dl>",
            "lxml",
        )
        dt = soup.find("dt")
        span = soup.find("span")
        dd = soup.find("dd")
        next_dt = soup.find_all("dt")[1]

        def fake_siblings(self: Tag) -> list:
            return ["raw text sibling", span, dd, next_dt]

        monkeypatch.setattr(Tag, "find_next_siblings", fake_siblings)

        block, nodes = _definition_block_from_dt(dt)

        assert block is not None
        assert block.text == (
            "Definition term with enough words "
            "Definition description with enough words."
        )
        assert nodes == [dt, dd]

    def test_definition_block_returns_none_when_combined_text_is_short(self) -> None:
        soup = BeautifulSoup("<dl><dt>Short</dt></dl>", "lxml")

        block, nodes = _definition_block_from_dt(soup.find("dt"))

        assert block is None
        assert nodes == [soup.find("dt")]

    def test_short_table_row_returns_none(self) -> None:
        soup = BeautifulSoup("<table><tr><td>tiny</td></tr></table>", "lxml")

        assert _table_row_block(soup.find("tr")) is None

    def test_direct_text_skips_extractable_children_and_headings(self) -> None:
        soup = BeautifulSoup(
            "<li>Leading text"
            "<span>inline child text</span>"
            "<p>paragraph child skipped</p>"
            "<h2>heading skipped</h2>"
            "trailing text</li>",
            "lxml",
        )

        assert _direct_text(soup.find("li")) == (
            "Leading text inline child text trailing text"
        )

    def test_non_tag_is_not_extractable_descendant(self) -> None:
        assert _is_extractable_descendant("plain text") is False

    def test_string_value_coerces_to_prose_text_block(self) -> None:
        block = _coerce_text_block("plain string paragraph")

        assert block.text == "plain string paragraph"
        assert block.kind == "prose"


# ---------------------------------------------------------------------------
# Unit tests: media assets and EPUB href helpers
# ---------------------------------------------------------------------------

class TestEpubMediaHelpers:
    def test_missing_asset_hrefs_handles_empty_and_invalid_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_path = tmp_path / "Broken.epub"

        assert _missing_asset_hrefs_from_arcnames(package_path, []) == frozenset()

        def raise_value_error(_source_dir: Path) -> Path:
            raise ValueError("broken container")

        monkeypatch.setattr(
            "app.importers.epub_importer._opf_path_from_container",
            raise_value_error,
        )

        hrefs = _missing_asset_hrefs_from_arcnames(
            package_path,
            ["OEBPS/images/missing.png", "http://example.test/remote.png"],
        )

        assert hrefs == frozenset({"OEBPS/images/missing.png"})

    def test_path_normalization_rejects_empty_remote_and_traversal(self) -> None:
        assert _normalize_epub_path("") == ""
        assert _normalize_epub_path("https://example.test/image.png") == ""
        assert _normalize_epub_path("../image.png") == ""
        assert _normalize_epub_path("images/a%20b.png#frag") == "images/a b.png"
        assert _resolve_epub_href("", "images/a.png") == "images/a.png"
        assert _resolve_epub_href("chapters/ch1.xhtml", "") == ""

    def test_asset_source_index_skips_empty_and_unsupported_items(self) -> None:
        empty = FakeEpubItem(999, file_name="", content=b"ignored")
        css = FakeEpubItem(999, file_name="styles/book.css", content=b"body{}")
        png = FakeEpubItem(
            999,
            file_name="images/pic.png",
            content=PNG_1X1_BYTES,
        )
        missing = FakeEpubItem(
            999,
            file_name="images/missing.png",
            content=b"placeholder",
        )
        book = SimpleNamespace(get_items=lambda: [empty, css, png, missing])

        sources = _build_asset_sources(book, frozenset({"images/missing.png"}))

        assert set(sources) == {"images/pic.png", "images/missing.png"}
        assert sources["images/pic.png"].content == PNG_1X1_BYTES
        assert sources["images/missing.png"].content == b""
        assert sources["images/missing.png"].is_missing is True
        assert _is_supported_asset("images/cover.jpg", "") is True

    def test_lookup_asset_source_uses_unique_suffix_only(self) -> None:
        source = EpubAssetSource("OEBPS/images/pic.png", "image/png", b"1")
        duplicate = EpubAssetSource("OPS/images/pic.png", "image/png", b"2")

        assert _lookup_asset_source({"OEBPS/images/pic.png": source}, "images/pic.png") == source
        assert _lookup_asset_source(
            {
                "OEBPS/images/pic.png": source,
                "OPS/images/pic.png": duplicate,
            },
            "images/pic.png",
        ) is None

    def test_extracts_standalone_images_and_reuses_asset_rows(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_image(
            tmp_path,
            "standalone-images.epub",
            body_html=(
                "<p>Before standalone image text with enough words.</p>"
                '<img src="images/diagram.png" alt="Standalone diagram"/>'
                '<img src="images/diagram.png" alt="Repeated diagram"/>'
                "<p>After standalone image text with enough words.</p>"
            ),
        )

        result = import_epub(db, ep)

        with db.get_connection() as conn:
            asset_count = conn.execute(
                "SELECT COUNT(*) FROM book_assets WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
            image_blocks = conn.execute(
                "SELECT kind, asset_id FROM chapter_blocks "
                "WHERE book_id = ? AND kind = 'image' ORDER BY idx",
                (result.book_id,),
            ).fetchall()

        assert asset_count == 1
        assert len(image_blocks) == 2
        assert image_blocks[0]["asset_id"] == image_blocks[1]["asset_id"]

    def test_figure_without_image_and_image_without_source_return_none(self) -> None:
        soup = BeautifulSoup(
            "<figure><figcaption>Caption without image.</figcaption></figure>"
            "<img alt='No source'>",
            "lxml",
        )
        figure = soup.find("figure")
        image = soup.find("img")

        assert _figure_block_from_element(
            figure,
            document_href="chap.xhtml",
            asset_sources={},
            missing_asset_hrefs=frozenset(),
        ) is None
        assert _image_block_from_element(
            image,
            document_href="chap.xhtml",
            asset_sources={},
            missing_asset_hrefs=frozenset(),
            figure_caption="",
            force_figure=False,
        ) is None

    def test_asset_extension_falls_back_to_media_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.importers.epub_importer.mimetypes.guess_extension",
            lambda _media_type: ".jpe",
        )

        assert _asset_extension("images/no-extension", "image/jpeg") == ".jpg"

    def test_move_staged_assets_handles_empty_and_existing_destination(
        self, tmp_path: Path
    ) -> None:
        staging_root = tmp_path / "stage"
        asset_base = tmp_path / "assets"
        staging_root.mkdir()

        assert _move_staged_assets(staging_root, asset_base, book_id=1) is None

        (staging_root / "books" / "1").mkdir(parents=True)
        (asset_base / "books" / "1").mkdir(parents=True)

        with pytest.raises(FileExistsError):
            _move_staged_assets(staging_root, asset_base, book_id=1)

    def test_insert_cleans_final_asset_dir_when_error_follows_move(
        self, tmp_path: Path
    ) -> None:
        real_db = DatabaseConnection(tmp_path / "test.db")
        real_db.apply_migrations(MIGRATIONS_DIR)

        class RaisingAfterCommitDb:
            _db_path = tmp_path / "test.db"

            @contextmanager
            def get_connection(self):
                with real_db.get_connection() as conn:
                    yield conn
                raise RuntimeError("simulated post-move failure")

        block = TextBlock(
            text="Figure caption",
            kind="figure",
            asset_href="images/pic.png",
            media_type="image/png",
            alt_text="Picture",
        )
        source = EpubAssetSource("images/pic.png", "image/png", PNG_1X1_BYTES)

        with pytest.raises(RuntimeError, match="post-move failure"):
            _insert(
                RaisingAfterCommitDb(),
                "Title",
                "Author",
                "en",
                "hash-cleanup",
                SourceFormat.EPUB,
                [
                    {
                        "title": "Chapter 1",
                        "section_kind": "chapter",
                        "chapter_number": 1,
                        "blocks": [block],
                    }
                ],
                {"images/pic.png": source},
            )

        assert not (tmp_path / "assets" / "books" / "1").exists()


# ---------------------------------------------------------------------------
# Unit tests: _text_hash
# ---------------------------------------------------------------------------

class TestTextHash:
    def test_hash_is_64_char_hex(self) -> None:
        h = _text_hash("Hello world.")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_case_insensitive(self) -> None:
        assert _text_hash("Hello World.") == _text_hash("hello world.")

    def test_whitespace_collapse(self) -> None:
        assert _text_hash("Hello  world.") == _text_hash("Hello world.")

    def test_matches_manual_sha256(self) -> None:
        text = "The quick brown fox."
        expected = hashlib.sha256(
            normalize_for_hash(text).encode("utf-8")
        ).hexdigest()
        assert _text_hash(text) == expected


# ---------------------------------------------------------------------------
# Integration: import_epub basic
# ---------------------------------------------------------------------------

class TestImportEpubBasic:
    def test_returns_import_result(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert isinstance(result, ImportResult)

    def test_book_row_inserted(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row is not None
        assert row["source_format"] == "epub"

    def test_metadata_extracted_from_epub(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT title, author FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["title"] == "My Test Book"
        assert row["author"] == "Jane Doe"

    def test_explicit_title_overrides_metadata(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub, title="Override Title")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT title FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["title"] == "Override Title"

    def test_explicit_author_overrides_metadata(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub, author="Override Author")
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT author FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["author"] == "Override Author"

    def test_book_totals_correct(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT total_chapters, total_sentences FROM books WHERE id = ?",
                (result.book_id,),
            ).fetchone()
        assert row["total_chapters"] == result.chapter_count
        assert row["total_sentences"] == result.sentence_count


# ---------------------------------------------------------------------------
# Integration: chapters
# ---------------------------------------------------------------------------

class TestImportEpubChapters:
    def test_two_chapters_imported(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert result.chapter_count == 2

    def test_chapter_titles_stored(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
                (result.book_id,),
            ).fetchall()
        titles = [r["title"] for r in rows]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles

    def test_heading_fallback_when_no_toc(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_no_toc(
            tmp_path,
            "no_toc.epub",
            chapters=[
                {"title": "The Beginning", "paragraphs": [
                    "A long enough paragraph for the beginning of the book here."
                ]},
                {"title": "The End", "paragraphs": [
                    "A long enough paragraph for the end of the book here."
                ]},
            ],
        )
        result = import_epub(db, ep)
        assert result.chapter_count == 2
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT title FROM chapters WHERE book_id = ? ORDER BY idx",
                (result.book_id,),
            ).fetchall()
        titles = [r["title"] for r in rows]
        # Titles come from <h2> tags in the HTML
        assert any("Beginning" in t for t in titles)

    def test_single_chapter_epub(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub(
            tmp_path,
            "single.epub",
            chapters=[{"title": "Only Chapter",
                        "paragraphs": ["A single paragraph with enough text."]}],
        )
        result = import_epub(db, ep)
        assert result.chapter_count == 1

    def test_three_chapter_epub(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        chapters = [
            {"title": f"Chapter {i}",
             "paragraphs": [f"Paragraph for chapter {i} with enough text here."]}
            for i in range(1, 4)
        ]
        ep = make_epub(tmp_path, "three.epub", chapters=chapters)
        result = import_epub(db, ep)
        assert result.chapter_count == 3

    def test_frontmatter_does_not_consume_body_chapter_number(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_sections(
            tmp_path,
            "frontmatter.epub",
            sections=[
                {
                    "title": "Praise for Mastering Bitcoin",
                    "file_name": "praise.xhtml",
                    "epub_type": "preface",
                    "body_html": (
                        "<p>Useful praise text with enough words to import here.</p>"
                    ),
                },
                {
                    "title": "1. Introduction",
                    "file_name": "ch01.xhtml",
                    "epub_type": "chapter",
                    "body_html": (
                        "<p>Body chapter text with enough words to import here.</p>"
                    ),
                },
            ],
        )

        result = import_epub(db, ep)

        assert result.chapter_count == 1
        with db.get_connection() as conn:
            rows = conn.execute(
                """SELECT idx, title, section_kind, chapter_number
                     FROM chapters
                    WHERE book_id = ?
                    ORDER BY idx""",
                (result.book_id,),
            ).fetchall()
            total_chapters = conn.execute(
                "SELECT total_chapters FROM books WHERE id = ?",
                (result.book_id,),
            ).fetchone()["total_chapters"]

        assert total_chapters == 1
        assert [row["idx"] for row in rows] == [1, 2]
        assert rows[0]["section_kind"] == "frontmatter"
        assert rows[0]["chapter_number"] is None
        assert rows[1]["section_kind"] == "chapter"
        assert rows[1]["chapter_number"] == 1

    def test_part_page_does_not_consume_body_chapter_number(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_sections(
            tmp_path,
            "part-page.epub",
            sections=[
                {
                    "title": "Part One: The Language of Money",
                    "file_name": "Part001.xhtml",
                    "epub_type": "bodymatter",
                    "body_html": (
                        "<p>Part One divider text with enough words to import here.</p>"
                    ),
                },
                {
                    "title": "Chapter One: A New Way of Learning",
                    "file_name": "Chapter001.xhtml",
                    "epub_type": "chapter",
                    "body_html": (
                        "<p>Body chapter text with enough words to import here.</p>"
                    ),
                },
            ],
        )

        result = import_epub(db, ep)

        assert result.chapter_count == 1
        with db.get_connection() as conn:
            rows = conn.execute(
                """SELECT idx, title, section_kind, chapter_number
                     FROM chapters
                    WHERE book_id = ?
                    ORDER BY idx""",
                (result.book_id,),
            ).fetchall()
            total_chapters = conn.execute(
                "SELECT total_chapters FROM books WHERE id = ?",
                (result.book_id,),
            ).fetchone()["total_chapters"]

        assert total_chapters == 1
        assert [row["idx"] for row in rows] == [1, 2]
        assert rows[0]["title"] == "Part One: The Language of Money"
        assert rows[0]["section_kind"] == _SECTION_FRONTMATTER
        assert rows[0]["chapter_number"] is None
        assert rows[1]["title"] == "Chapter One: A New Way of Learning"
        assert rows[1]["section_kind"] == _SECTION_CHAPTER
        assert rows[1]["chapter_number"] == 1

    def test_nested_toc_entries_do_not_overwrite_document_title(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_sections(
            tmp_path,
            "nested_toc.epub",
            sections=[
                {
                    "title": "1. Introduction",
                    "file_name": "ch01.xhtml",
                    "epub_type": "chapter",
                    "body_html": (
                        "<p>Body chapter text with enough words to import here.</p>"
                    ),
                    "toc_children": [
                        {"href": "ch01.xhtml#sending", "title": "Sending Bitcoins"}
                    ],
                },
            ],
        )

        result = import_epub(db, ep)

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT title, chapter_number FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()

        assert row["title"] == "1. Introduction"
        assert row["chapter_number"] == 1


# ---------------------------------------------------------------------------
# Integration: paragraphs & sentences
# ---------------------------------------------------------------------------

class TestImportEpubParagraphsAndSentences:
    def test_paragraphs_imported(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert result.paragraph_count >= 2

    def test_sentences_imported(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        assert result.sentence_count >= 4

    def test_sentences_stored_in_db(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
        assert count == result.sentence_count

    def test_no_p_tag_fallback_produces_sentences(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_no_paragraphs(tmp_path, "no_p.epub")
        result = import_epub(db, ep)
        assert result.sentence_count >= 1

    def test_sentence_text_is_non_empty(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT text FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchall()
        assert all(r["text"].strip() for r in rows)

    def test_pre_and_table_blocks_are_not_sentence_split(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_html(
            tmp_path,
            "blocks.epub",
            body_html=(
                "<p>Plain prose sentence one. Plain prose sentence two.</p>"
                "<pre>function one() { return 1. }\n"
                "function two() { return 2. }</pre>"
                "<table><tr><td>Command name</td>"
                "<td>Creates a new receiving address for the wallet.</td></tr></table>"
            ),
        )

        result = import_epub(db, ep)

        with db.get_connection() as conn:
            code_rows = conn.execute(
                "SELECT text FROM sentences WHERE book_id = ? AND text LIKE ?",
                (result.book_id, "%function one%"),
            ).fetchall()
            table_rows = conn.execute(
                "SELECT text FROM sentences WHERE book_id = ? AND text LIKE ?",
                (result.book_id, "%Command name%"),
            ).fetchall()
        assert len(code_rows) == 1
        assert "function two()" in code_rows[0]["text"]
        assert len(table_rows) == 1
        assert table_rows[0]["text"] == (
            "Command name | Creates a new receiving address for the wallet."
        )

    def test_image_figure_is_stored_as_asset_and_chapter_block(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_image(tmp_path, "image.epub")

        result = import_epub(db, ep)

        with db.get_connection() as conn:
            blocks = conn.execute(
                """SELECT kind, paragraph_id, asset_id, text
                     FROM chapter_blocks
                    WHERE book_id = ?
                    ORDER BY idx""",
                (result.book_id,),
            ).fetchall()
            asset = conn.execute(
                "SELECT * FROM book_assets WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()
            sentence_text = " ".join(
                row["text"]
                for row in conn.execute(
                    "SELECT text FROM sentences WHERE book_id = ? ORDER BY idx",
                    (result.book_id,),
                ).fetchall()
            )

        assert [row["kind"] for row in blocks] == ["prose", "figure", "prose"]
        assert blocks[0]["paragraph_id"] is not None
        assert blocks[1]["paragraph_id"] is None
        assert blocks[1]["asset_id"] == asset["id"]
        assert blocks[1]["text"] == "Figure 1. Network diagram caption."
        assert asset["source_href"] == "images/diagram.png"
        assert asset["media_type"] == "image/png"
        assert asset["byte_size"] == len(PNG_1X1_BYTES)
        assert asset["sha256"] == hashlib.sha256(PNG_1X1_BYTES).hexdigest()
        assert asset["is_missing"] == 0
        assert (tmp_path / "assets" / asset["storage_path"]).read_bytes() == PNG_1X1_BYTES
        assert "Figure 1. Network diagram caption." not in sentence_text

    def test_missing_directory_image_asset_records_placeholder_block(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_image(tmp_path, "missing-image-source.epub")
        package_path = explode_epub(ep, tmp_path / "Missing Image Package.epub")
        image_path = next(package_path.rglob("diagram.png"))
        image_path.unlink()

        result = import_epub(db, package_path)

        with db.get_connection() as conn:
            asset = conn.execute(
                "SELECT * FROM book_assets WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()
            block = conn.execute(
                "SELECT kind, paragraph_id, asset_id, text FROM chapter_blocks "
                "WHERE book_id = ? AND kind = 'missing_asset'",
                (result.book_id,),
            ).fetchone()

        assert asset["source_href"] == "images/diagram.png"
        assert asset["is_missing"] == 1
        assert asset["storage_path"] == ""
        assert asset["byte_size"] == 0
        assert block["paragraph_id"] is None
        assert block["asset_id"] == asset["id"]
        assert block["text"] == "Figure 1. Network diagram caption."
        assert not (tmp_path / "assets" / "books" / str(result.book_id)).exists()


# ---------------------------------------------------------------------------
# Integration: hashes
# ---------------------------------------------------------------------------

class TestImportEpubHashes:
    def test_file_hash_is_sha256_of_bytes(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        raw = simple_epub.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_hash FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["file_hash"] == expected

    def test_text_hash_case_insensitive(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub(
            tmp_path, "hash_test.epub",
            chapters=[{"title": "Ch1", "paragraphs": ["Hello World. One sentence."]}],
        )
        result = import_epub(db, ep)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT text, text_hash FROM sentences WHERE book_id = ? LIMIT 1",
                (result.book_id,),
            ).fetchone()
        expected = _text_hash(row["text"])
        assert row["text_hash"] == expected

    def test_same_sentence_cross_book_same_hash(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        sentence = "The quick brown fox jumps over the lazy dog."
        for i in range(1, 3):
            # Give each book a unique extra sentence so file_hash differs
            extra = f"This is unique filler sentence number {i} to differentiate books."
            ep = make_epub(
                tmp_path, f"book{i}.epub",
                chapters=[{"title": "Ch", "paragraphs": [sentence + " " + extra]}],
            )
            import_epub(db, ep, title=f"Book {i}")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT text_hash FROM sentences WHERE text = ?",
                (sentence,),
            ).fetchall()
        assert len(rows) == 1

    def test_directory_package_hash_is_stable(
        self, db: DatabaseConnection, simple_epub: Path, tmp_path: Path
    ) -> None:
        package_path = explode_epub(simple_epub, tmp_path / "Simple Package.epub")
        expected_hash = calculate_epub_file_hash(package_path)

        result = import_epub(db, package_path)

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_hash FROM books WHERE id = ?", (result.book_id,)
            ).fetchone()
        assert row["file_hash"] == expected_hash
        assert calculate_epub_file_hash(package_path) == expected_hash


# ---------------------------------------------------------------------------
# Integration: error handling
# ---------------------------------------------------------------------------

class TestImportEpubErrors:
    def test_existing_path_that_is_not_file_or_directory_raises(
        self, tmp_path: Path
    ) -> None:
        if not hasattr(os, "mkfifo"):
            pytest.skip("mkfifo is not available on this platform")
        fifo_path = tmp_path / "source.epub"
        os.mkfifo(fifo_path)

        with pytest.raises(ValueError, match="neither a file nor a directory"):
            with _prepare_epub_source(fifo_path):
                pass

    def test_directory_package_cleanup_ignores_unlink_error(
        self, simple_epub: Path, tmp_path: Path
    ) -> None:
        package_path = explode_epub(simple_epub, tmp_path / "Cleanup Package.epub")
        captured_temp_paths: list[Path] = []

        with pytest.MonkeyPatch.context() as monkeypatch:
            original_unlink = Path.unlink

            def raising_unlink(path: Path, *args, **kwargs) -> None:
                captured_temp_paths.append(path)
                raise OSError("simulated cleanup failure")

            monkeypatch.setattr(Path, "unlink", raising_unlink)
            with _prepare_epub_source(package_path) as prepared:
                assert prepared.temporary_path is not None
                captured_temp_paths.append(prepared.temporary_path)

        for path in captured_temp_paths:
            if path.exists() and path.is_file():
                original_unlink(path)

    def test_validate_epub_directory_requires_mimetype(
        self, tmp_path: Path
    ) -> None:
        package_path = tmp_path / "No Mimetype.epub"
        (package_path / "META-INF").mkdir(parents=True)
        (package_path / "META-INF" / "container.xml").write_text(
            "<container/>", encoding="utf-8"
        )

        with pytest.raises(ValueError, match="missing mimetype"):
            _validate_epub_directory(package_path)

    def test_validate_epub_directory_requires_container(
        self, tmp_path: Path
    ) -> None:
        package_path = tmp_path / "No Container.epub"
        package_path.mkdir()
        (package_path / "mimetype").write_text("application/epub+zip", encoding="utf-8")

        with pytest.raises(ValueError, match="missing META-INF/container.xml"):
            _validate_epub_directory(package_path)

    def test_manifest_item_without_href_is_ignored(self, tmp_path: Path) -> None:
        package_path = write_minimal_epub_directory(
            tmp_path / "No Href.epub",
            minimal_opf('<item id="no-href" media-type="image/png"/>'),
        )

        missing = _missing_manifest_asset_arcnames(package_path, set())

        assert missing == []

    def test_missing_manifest_document_resource_raises(self, tmp_path: Path) -> None:
        package_path = write_minimal_epub_directory(
            tmp_path / "Missing Document.epub",
            minimal_opf(
                '<item href="missing.xhtml" id="missing" '
                'media-type="application/xhtml+xml"/>'
            ),
        )

        with pytest.raises(ValueError, match="missing document resource"):
            _missing_manifest_asset_arcnames(package_path, set())

    def test_container_rootfile_must_exist(self, tmp_path: Path) -> None:
        package_path = tmp_path / "Missing Opf.epub"
        (package_path / "META-INF").mkdir(parents=True)
        (package_path / "mimetype").write_text("application/epub+zip", encoding="utf-8")
        (package_path / "META-INF" / "container.xml").write_text(
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OEBPS/missing.opf"/></rootfiles>
            </container>""",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="missing OPF file"):
            _opf_path_from_container(package_path)

    def test_container_requires_rootfile(self, tmp_path: Path) -> None:
        package_path = tmp_path / "No Rootfile.epub"
        (package_path / "META-INF").mkdir(parents=True)
        (package_path / "mimetype").write_text("application/epub+zip", encoding="utf-8")
        (package_path / "META-INF" / "container.xml").write_text(
            "<container/>", encoding="utf-8"
        )

        with pytest.raises(ValueError, match="has no rootfile"):
            _opf_path_from_container(package_path)

    def test_file_not_found_raises(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            import_epub(db, tmp_path / "missing.epub")

    def test_duplicate_file_hash_raises(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        import_epub(db, simple_epub)
        with pytest.raises(DuplicateBookError):
            import_epub(db, simple_epub)

    def test_duplicate_does_not_insert_extra_book(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        import_epub(db, simple_epub)
        with pytest.raises(DuplicateBookError):
            import_epub(db, simple_epub)
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        assert count == 1

    def test_directory_package_duplicate_raises(
        self, db: DatabaseConnection, simple_epub: Path, tmp_path: Path
    ) -> None:
        package_path = explode_epub(simple_epub, tmp_path / "Duplicate Package.epub")
        import_epub(db, package_path)

        with pytest.raises(DuplicateBookError):
            import_epub(db, package_path)

    def test_directory_package_missing_non_document_asset_is_stubbed(
        self, db: DatabaseConnection, simple_epub: Path, tmp_path: Path
    ) -> None:
        package_path = explode_epub(simple_epub, tmp_path / "Missing Asset.epub")
        opf_path = next(package_path.rglob("*.opf"))
        opf_text = opf_path.read_text(encoding="utf-8")
        opf_text = opf_text.replace(
            "</manifest>",
            '<item href="missing-image.png" id="missing-image" '
            'media-type="image/png"/></manifest>',
        )
        opf_path.write_text(opf_text, encoding="utf-8")

        result = import_epub(db, package_path)

        assert result.sentence_count >= 1

    def test_epub_with_no_usable_text_raises(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        ep = make_epub_with_html(
            tmp_path,
            "empty.epub",
            body_html="<p>tiny</p>",
        )

        with pytest.raises(ValueError, match="contains no usable text"):
            import_epub(db, ep)


# ---------------------------------------------------------------------------
# Integration: DB hierarchy integrity
# ---------------------------------------------------------------------------

class TestImportEpubHierarchyIntegrity:
    def test_all_sentences_have_valid_paragraph(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM sentences s "
                "LEFT JOIN paragraphs p ON s.paragraph_id = p.id "
                "WHERE s.book_id = ? AND p.id IS NULL",
                (result.book_id,),
            ).fetchone()[0]
        assert orphans == 0

    def test_all_paragraphs_have_valid_chapter(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM paragraphs p "
                "JOIN chapters c ON p.chapter_id = c.id "
                "LEFT JOIN books b ON c.book_id = b.id "
                "WHERE c.book_id = ? AND b.id IS NULL",
                (result.book_id,),
            ).fetchone()[0]
        assert orphans == 0

    def test_import_result_matches_db_counts(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            ch  = conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
            par = conn.execute(
                "SELECT COUNT(*) FROM paragraphs p "
                "JOIN chapters c ON p.chapter_id = c.id WHERE c.book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
            sent = conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0]
        assert ch   == result.chapter_count
        assert par  == result.paragraph_count
        assert sent == result.sentence_count

    def test_chapter_sentence_ranges_are_valid(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT sentence_start, sentence_end FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchall()
        for row in rows:
            assert row["sentence_end"] >= row["sentence_start"]

    def test_sentence_idx_monotonically_increases(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT idx FROM sentences WHERE book_id = ? ORDER BY id",
                (result.book_id,),
            ).fetchall()
        indices = [r["idx"] for r in rows]
        assert indices == sorted(indices)

    def test_cascade_delete_removes_all_children(
        self, db: DatabaseConnection, simple_epub: Path
    ) -> None:
        result = import_epub(db, simple_epub)
        with db.get_connection() as conn:
            conn.execute("DELETE FROM books WHERE id = ?", (result.book_id,))
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM sentences WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id = ?",
                (result.book_id,),
            ).fetchone()[0] == 0
