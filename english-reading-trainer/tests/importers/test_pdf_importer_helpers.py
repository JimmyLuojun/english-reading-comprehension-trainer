"""Branch-focused helper tests for app.importers.pdf_importer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db_connection import DatabaseConnection
from app.importers import pdf_importer as pdf

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


def _word(
    text: str,
    *,
    x0: float = 72,
    top: float = 100,
    x1: float = 120,
    bottom: float = 112,
    fontname: str = "MinionPro-Regular",
    size: float = 10,
) -> dict[str, object]:
    return {
        "text": text,
        "x0": x0,
        "top": top,
        "x1": x1,
        "bottom": bottom,
        "fontname": fontname,
        "size": size,
    }


def _line(
    text: str,
    *,
    page_number: int = 1,
    x0: float = 72,
    top: float = 100,
    x1: float = 420,
    bottom: float = 112,
    words: tuple[dict[str, object], ...] | None = None,
) -> pdf.PdfWordLine:
    return pdf.PdfWordLine(
        page_number=page_number,
        x0=x0,
        top=top,
        x1=x1,
        bottom=bottom,
        text=text,
        words=words or (_word(text, x0=x0, top=top, x1=x1, bottom=bottom),),
    )


def _page_block(text: str, *, top: float = 100, kind: str = "prose") -> pdf.PdfPageBlock:
    return pdf.PdfPageBlock(top, pdf.TextBlock(text, kind))


class _FakePage:
    width = 600
    height = 800
    lines: list[dict[str, object]] = []
    curves: list[dict[str, object]] = []
    rects: list[dict[str, object]] = []
    images: list[dict[str, object]] = []

    def __init__(self, words: list[dict[str, object]] | None = None) -> None:
        self._words = words or []

    def extract_words(self, **_kwargs):
        return self._words

    def crop(self, bbox):
        self.bbox = bbox
        return self

    def to_image(self, resolution):
        self.resolution = resolution

        class Original:
            def save(self, buffer, format):
                assert format == "PNG"
                buffer.write(b"\x89PNG\r\n\x1a\nfake")

        return SimpleNamespace(original=Original())


def test_calculate_pdf_file_hash_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PDF path is not a file"):
        pdf.calculate_pdf_file_hash(tmp_path)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (FileNotFoundError("gone"), FileNotFoundError),
        (ValueError("bad pdf"), ValueError),
        (RuntimeError("boom"), ValueError),
    ],
)
def test_import_pdf_preserves_expected_read_errors_and_wraps_unknown(
    db: DatabaseConnection,
    tmp_path: Path,
    monkeypatch,
    raised: Exception,
    expected: type[Exception],
) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF fake")

    class FailingOpen:
        def __enter__(self):
            raise raised

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(pdf.pdfplumber, "open", lambda _path: FailingOpen())

    with pytest.raises(expected):
        pdf.import_pdf(db, path)


def test_metadata_value_accepts_case_variants_and_empty_values() -> None:
    assert pdf._metadata_value({"title": "  Name  "}, "Title") == "Name"
    assert pdf._metadata_value({"TITLE": ""}, "Title") == ""
    assert pdf._metadata_value({}, "Author") == ""


def test_extract_pdf_outline_handles_errors_empty_pages_and_filters(monkeypatch) -> None:
    class BadDoc:
        def get_outlines(self):
            raise RuntimeError("bad outline")

    assert pdf._extract_pdf_outline(SimpleNamespace(doc=BadDoc(), pages=[])) == ()

    class EmptyDoc:
        def get_outlines(self):
            return [(1, "Chapter 1", None, None, None)]

    assert pdf._extract_pdf_outline(SimpleNamespace(doc=EmptyDoc(), pages=[])) == ()

    page = SimpleNamespace(page_obj=SimpleNamespace(pageid=10), page_number=3)
    dest = SimpleNamespace(objid=10)

    class GoodDoc:
        def get_outlines(self):
            return [
                (1, "Too short"),
                (1, "", dest, None, None),
                (1, "Chapter 1", dest, None, None),
                (1, "Chapter 1", dest, None, None),
            ]

    monkeypatch.setattr(pdf, "resolve1", lambda value: value)

    assert pdf._extract_pdf_outline(SimpleNamespace(doc=GoodDoc(), pages=[page])) == (
        pdf.PdfOutlineItem("Chapter 1", 3, 1),
    )


def test_outline_destination_page_number_handles_action_and_bad_targets(monkeypatch) -> None:
    page_ref = SimpleNamespace(objid=22)
    monkeypatch.setattr(
        pdf,
        "resolve1",
        lambda value: {"D": [page_ref]} if value == "action" else value,
    )
    assert pdf._outline_destination_page_number(None, "action", {22: 5}) == 5
    assert pdf._outline_destination_page_number(SimpleNamespace(), None, {22: 5}) is None

    def fail_resolve(_value):
        raise RuntimeError("unresolvable")

    monkeypatch.setattr(pdf, "resolve1", fail_resolve)
    assert pdf._outline_destination_page_number(None, "bad-action", {22: 5}) is None
    assert pdf._outline_destination_page_number("bad-target", None, {22: 5}) is None


def test_outline_title_safe_int_and_float_helpers_cover_invalid_inputs() -> None:
    assert pdf._clean_outline_title(b"Ch\x00apter") == "Chapter"
    assert pdf._safe_int("not-int") is None
    assert pdf._safe_int(None) is None
    assert pdf._float_value("bad") is None
    assert pdf._float_value(None) is None


def test_body_words_and_line_grouping_skip_invalid_margin_and_page_numbers() -> None:
    region = pdf.PdfFigureRegion(1, 60, 95, 130, 120)
    words = [
        _word("", top=100),
        _word("NoTop", top="bad"),
        _word("Header", top=10),
        _word("7", x0=5, top=100, x1=30, bottom=180),
        _word("Inside", top=100),
        _word("Body", x0=150, top=140, x1=190, bottom=152),
    ]
    page = _FakePage(words)

    assert pdf._body_words(page, (region,)) == [words[-1]]
    assert pdf._body_words_with_font_metadata(page, excluded_regions=(region,)) == [words[-1]]
    assert pdf._words_to_word_lines([], page_number=1) == []
    assert pdf._words_to_word_lines([_word("12")], page_number=1) == []
    assert pdf._line_tolerance([{"top": "bad", "bottom": None}]) == pdf._MIN_LINE_TOLERANCE


def test_lines_to_paragraphs_separator_page_mismatch_and_cleaning() -> None:
    first = pdf.PdfLine(1, 100, 110, "Hyphen-")
    second = pdf.PdfLine(1, 125, 135, "ated word continues.")
    third = pdf.PdfLine(2, 50, 60, "Next page line.")
    region = pdf.PdfFigureRegion(1, 0, 118, 500, 120)

    paragraphs = pdf._lines_to_paragraphs([first, second, third], (region,))

    assert [item.text for item in paragraphs] == [
        "Hyphenated word continues. Next page line."
    ]
    assert pdf._has_region_between(first, third, (region,)) is False
    assert pdf._paragraph_gap_threshold([first]) == 12.0
    assert pdf._clean_paragraph("  a   b  ") == "a b"


def test_figure_region_detection_covers_images_and_filtered_objects() -> None:
    page = _FakePage()
    page.lines = [
        {"x0": 0, "top": 200, "x1": 600, "bottom": 201},
        {"x0": 10, "top": 200, "x1": 30, "bottom": 230},
        {"x0": 100, "top": 200, "x1": 180, "bottom": 250},
    ]
    page.images = [{"x0": 220, "top": 260, "x1": 300, "bottom": 330}]

    regions = pdf._figure_regions(page, page_number=1)

    assert len(regions) == 2
    assert any(region.contains_image for region in regions)
    assert pdf._region_from_pdf_object(
        {"x0": "bad", "top": 1, "x1": 2, "bottom": 3},
        page_number=1,
        page_width=600,
        page_height=800,
        contains_image=False,
    ) is None
    assert pdf._region_from_pdf_object(
        {"x0": 100, "top": 1, "x1": 200, "bottom": 2},
        page_number=1,
        page_width=600,
        page_height=800,
        contains_image=False,
    ) is None


def test_nonprose_line_classifiers_and_clusters() -> None:
    empty = _line("", words=())
    monospace = _line("if (x) { y(); }", words=(_word("if", fontname="Courier"),))
    math_font = _line(
        "p -> q",
        words=(_word("p", fontname="MathematicalPiLTStd"), _word("->", x0=90),),
    )
    code = _line("#{x}=<y>;", words=(_word("#{x}=<y>;",),))
    code_only = _line("abc#;", words=(_word("abc#;",),))
    spread = _line("x + =", words=(_word("x", size=10), _word("+", x0=90, size=14)))
    spread_only = _line("ab12", words=(_word("ab", size=10), _word("12", x0=90, size=14)))

    assert pdf._is_nonprose_line(empty) is False
    assert pdf._is_nonprose_line(monospace) is True
    assert pdf._is_nonprose_line(math_font) is True
    assert pdf._is_nonprose_line(code) is True
    assert pdf._is_nonprose_line(code_only) is True
    assert pdf._is_nonprose_line(spread) is True
    assert pdf._is_nonprose_line(spread_only) is True
    assert pdf._alpha_ratio("   ") == 0.0
    assert pdf._math_symbol_ratio("   ") == 0.0
    assert pdf._code_symbol_ratio("   ") == 0.0
    assert pdf._font_size_spread(_line("one", words=(_word("one", size="bad"),))) == 0.0

    page = _FakePage([
        _word("p", top=100, x0=100, x1=110, fontname="MathematicalPiLTStd"),
        _word("->", top=100, x0=115, x1=130, fontname="MathematicalPiLTStd"),
        _word("q", top=100, x0=135, x1=145, fontname="MathematicalPiLTStd"),
    ])
    assert pdf._nonprose_regions(page, page_number=1, excluded_regions=())


def test_numbered_logic_and_proof_helpers_cover_break_conditions() -> None:
    assert pdf._numbered_logic_example_candidate_indices([_line("not proof")], 0) == []
    lines = [
        _line("1. Modus Ponens (MP): p -> q", top=100, bottom=110),
        _line("2. Modus Tollens (MT): ~q -> ~p", top=114, bottom=124),
        _line("p -> q", top=128, bottom=138),
        _line("4. Skips a number", top=142, bottom=152),
    ]
    assert pdf._numbered_logic_example_candidate_indices(lines, 0) == [0, 1, 2]
    assert pdf._numbered_logic_example_candidate_indices(lines, 3) == []
    assert pdf._numbered_logic_example_candidate_indices([
        _line("1. Modus Ponens (MP): p -> q", top=100, bottom=110),
        _line("2. Modus Tollens (MT): ~q -> ~p", x0=200, top=114, bottom=124),
    ], 0) == []
    assert pdf._is_logic_example_neighbor(lines[0], _line("2. x", page_number=2)) is False
    assert pdf._has_logic_rule_example_signal("Modus Ponens p -> q") is True
    assert pdf._has_logic_example_continuation_signal("p -> q") is True

    proof_lines = [
        _line("1. p -> q", top=100, bottom=110),
        _line("2. p", top=114, bottom=124),
        _line("3. q 1, 2, MP", top=128, bottom=138),
        _line("p -> q", x0=110, top=142, bottom=152),
        _line("4. New proof starts", top=156, bottom=166),
    ]
    flags = pdf._include_numbered_proof_blocks(proof_lines, [False] * len(proof_lines))
    assert flags[:4] == [True, True, True, True]
    citation_block_flags = pdf._include_numbered_proof_blocks([
        _line("1. premise", top=100, bottom=110),
        _line("2. conclusion 1, 2, MP", top=114, bottom=124),
    ], [False, False])
    assert citation_block_flags == [True, True]
    single_line_flags = pdf._include_numbered_proof_blocks([_line("1. p")], [False])
    assert single_line_flags == [False]
    no_signal_flags = pdf._include_numbered_proof_blocks([
        _line("1. premise", top=100, bottom=110),
        _line("2. conclusion", top=114, bottom=124),
    ], [False, False])
    assert no_signal_flags == [False, False]
    assert pdf._numbered_proof_candidate_indices([_line("not proof")], 0) == []
    assert pdf._numbered_proof_candidate_indices([
        _line("1. p", top=100, bottom=110),
        _line("2. q", top=200, bottom=210),
    ], 0) == [0]
    assert pdf._numbered_proof_candidate_indices([
        _line("1. p", top=100, bottom=110),
        _line("ordinary", top=114, bottom=124),
    ], 0) == [0]
    assert pdf._numbered_proof_candidate_indices([
        _line("1. p", top=100, bottom=110),
        _line("2. q", x0=200, top=114, bottom=124),
    ], 0) == [0]
    assert pdf._numbered_proof_candidate_indices([
        _line("1. p", top=100, bottom=110),
        _line("3. q", top=114, bottom=124),
    ], 0) == [0]
    assert pdf._is_close_vertical_neighbor(proof_lines[0], _line("x", page_number=2)) is False
    assert pdf._is_close_vertical_neighbor(proof_lines[1], _line("x", top=100, bottom=105)) is False
    assert pdf._has_strong_proof_signal(_line("not proof")) is False
    assert pdf._has_strong_proof_signal(_line("1. Modus Ponens p -> q")) is True
    assert pdf._has_strong_proof_signal(_line("1. q 1, 2, MP")) is True
    assert pdf._has_strong_proof_signal(_line("1. p = q")) is True
    assert pdf._has_strong_proof_signal(_line("1. p → q")) is True
    assert pdf._has_strong_proof_signal(_line("1. abc#;")) is True
    assert pdf._has_strong_proof_signal(
        _line("1. plain words", words=(_word("plain", fontname="Courier"),))
    ) is True
    assert pdf._is_proof_continuation_line(_line("")) is False
    assert pdf._is_proof_continuation_line(_line("1, 2, MP")) is True
    assert pdf._is_proof_continuation_line(
        _line("This is a long prose line with enough alphabetic words to be normal prose.")
    ) is False
    assert pdf._is_proof_continuation_line(_line("p -> q")) is True
    assert pdf._looks_like_long_prose_line(
        "This is a long prose line with enough alphabetic words to be normal prose."
    ) is True


def test_proof_continuation_helper_break_conditions() -> None:
    base = _line("1. p", top=100, bottom=110)
    proof = _line("2. q 1, 2, MP", top=114, bottom=124)
    continuation = _line("p -> q", x0=110, top=128, bottom=138)
    flags = [True, True, False]
    assert pdf._include_proof_continuations([base, proof, continuation], flags, [0, 1]) == 3
    assert flags == [True, True, True]
    assert pdf._include_proof_continuations([
        base,
        proof,
        _line("3. starts", top=128, bottom=138),
    ], [True, True, False], [0, 1]) == 2
    assert pdf._include_proof_continuations([
        base,
        proof,
        _line("far", top=200, bottom=210),
    ], [True, True, False], [0, 1]) == 2
    assert pdf._include_proof_continuations([
        base,
        proof,
        _line("not indented", x0=80, top=128, bottom=138),
    ], [True, True, False], [0, 1]) == 2
    assert pdf._include_proof_continuations([
        base,
        proof,
        _line("ordinary prose", x0=110, top=128, bottom=138),
    ], [True, True, False], [0, 1]) == 2


def test_formula_fragment_neighbor_expansion_and_region_helpers() -> None:
    lines = [
        _line("p -> q", top=100, bottom=110),
        _line("r", top=114, bottom=124),
        _line("ordinary prose", top=128, bottom=138),
    ]
    assert pdf._include_neighboring_formula_fragments(lines, [True, False, False]) == [
        True,
        True,
        False,
    ]
    assert pdf._is_formula_fragment_line(_line("this is a long non formula line")) is False
    assert pdf._region_from_word_lines([], page_width=600, page_height=800) is None
    region = pdf._region_from_word_lines(lines[:2], page_width=600, page_height=800)
    assert region is not None
    assert region.force_preserve is True


def test_object_bbox_margin_and_word_region_helpers() -> None:
    assert pdf._object_bbox({"x0": 2, "top": 4, "x1": 1, "bottom": 3}) == (1, 3, 2, 4)
    assert pdf._object_bbox({"x0": 2, "top": 4, "x1": 2, "bottom": 4}) is None
    assert pdf._is_body_bbox(0, 10, 0) is True
    assert pdf._is_full_width_hairline(0, 1, 500, 2, 0) is False
    assert pdf._is_margin_decoration_bbox(0, 100, 20, 150, 0, 800) is False
    assert pdf._is_margin_decoration_object({"x0": "bad"}, 600, 800) is False
    assert pdf._is_margin_decoration_object(
        {"x0": 0, "top": 100, "x1": 20, "bottom": 150},
        600,
        800,
    ) is True
    assert pdf._is_margin_decoration_word({"x0": "bad"}, "7", 600, 800) is False

    region = pdf.PdfFigureRegion(1, 10, 10, 100, 100)
    assert pdf._word_inside_region({"x0": "bad"}, region) is False
    assert pdf._word_inside_any_region(_word("x", x0=20, top=20, x1=30, bottom=30), (region,))
    assert pdf._words_inside_region([
        _word("in", x0=20, top=20, x1=30, bottom=30),
        _word("out", x0=200, top=20, x1=230, bottom=30),
    ], region)[0]["text"] == "in"


def test_figure_block_rendering_skips_empty_nonforced_regions() -> None:
    page = _FakePage()
    asset_sources: dict[str, pdf.EpubAssetSource] = {}
    skipped = pdf.PdfFigureRegion(1, 100, 100, 180, 160)
    forced = pdf.PdfFigureRegion(1, 200, 200, 260, 260, force_preserve=True)

    blocks = pdf._figure_blocks_for_page(
        page,
        page_number=1,
        regions=(skipped, forced),
        body_words=[],
        asset_sources=asset_sources,
    )

    assert len(blocks) == 1
    assert blocks[0].block.kind == "figure"
    assert next(iter(asset_sources.values())).content.startswith(b"\x89PNG")


def test_chapter_outline_and_heading_helpers_cover_empty_and_trimmed_cases() -> None:
    prose = _page_block("Chapter 1: Start The first sentence remains.", top=10)
    figure = _page_block("", top=5, kind="figure")
    pages = [
        pdf.PdfPageText(1, (prose,), "Chapter 1: Start"),
        pdf.PdfPageText(2, (_page_block("Body page."),), ""),
    ]
    outline = (
        pdf.PdfOutlineItem("Preface", 1, 2),
        pdf.PdfOutlineItem("Chapter 1: Start", 1, 2),
    )

    assert pdf._build_outline_chapters([], outline) is None
    assert pdf._build_outline_chapters(pages, ()) is None
    assert pdf._build_outline_chapters(pages, (pdf.PdfOutlineItem("Preface", 1, 1),)) is None
    chapters = pdf._build_outline_chapters(pages, outline)
    assert chapters is not None
    assert chapters[0]["title"] == "Chapter 1: Start"
    assert chapters[0]["blocks"][0].text == "The first sentence remains."
    assert pdf._outline_boundary_items(outline) == outline
    assert pdf._deduplicate_outline_sections([
        (1, pdf.PdfSectionMarker("Chapter 1", "chapter", 1)),
        (1, pdf.PdfSectionMarker("Chapter 1 duplicate", "chapter", 1)),
    ]) == [(1, pdf.PdfSectionMarker("Chapter 1", "chapter", 1))]
    assert pdf._trim_leading_outline_title_blocks([], pdf.PdfSectionMarker("x", "chapter", 1)) == []
    assert pdf._trim_leading_outline_title_blocks(
        [figure],
        pdf.PdfSectionMarker("x", "chapter", 1),
    ) == [figure]
    assert pdf._trim_leading_outline_title_blocks(
        [_page_block("   ")],
        pdf.PdfSectionMarker("x", "chapter", 1),
    ) == []
    assert pdf._trim_leading_outline_title_blocks(
        [_page_block("Chapter 1")],
        pdf.PdfSectionMarker("Chapter 1", "chapter", 1),
    ) == []


def test_outline_chapter_builder_covers_defensive_empty_sections(monkeypatch) -> None:
    pages = [pdf.PdfPageText(1, (_page_block("Chapter 1"),), "")]
    outline = (pdf.PdfOutlineItem("Chapter 1", 1, 1),)
    monkeypatch.setattr(pdf, "_deduplicate_outline_sections", lambda _sections: [])

    assert pdf._build_outline_chapters(pages, outline) is None


def test_outline_chapter_builder_skips_empty_chapter_and_rejects_backmatter_only() -> None:
    pages = [
        pdf.PdfPageText(1, (_page_block("Chapter 1"),), ""),
        pdf.PdfPageText(2, (_page_block("Glossary body"),), ""),
    ]
    outline = (
        pdf.PdfOutlineItem("Chapter 1", 1, 1),
        pdf.PdfOutlineItem("Glossary", 2, 1),
    )

    assert pdf._build_outline_chapters(pages, outline) is None


def test_virtual_and_heading_chapter_helpers_cover_frontmatter_and_nonmarkers() -> None:
    empty_page = pdf.PdfPageText(1, (), "")
    assert pdf._build_virtual_chapters([empty_page]) == []
    front = pdf.PdfPageText(1, (_page_block("Intro text."),), "")
    part = pdf.PdfPageText(2, (_page_block("PART I: Setup"),), "PART I: Setup")
    chapter = pdf.PdfPageText(
        3,
        (_page_block("Chapter Two: Argument Body begins."),),
        "",
    )
    trailing = pdf.PdfPageText(4, (_page_block("Trailing body."),), "")
    chapters = pdf._build_heading_chapters([front, part, chapter, trailing])

    assert chapters is not None
    assert [chapter["section_kind"] for chapter in chapters] == [
        "frontmatter",
        "frontmatter",
        "chapter",
    ]
    assert chapters[-1]["chapter_number"] == 2
    assert pdf._build_heading_chapters([front]) is None
    assert pdf._build_heading_chapters([
        pdf.PdfPageText(1, (_page_block("PART I: Setup"),), ""),
        pdf.PdfPageText(2, (_page_block("Loose frontmatter after part."),), ""),
    ]) is None
    assert pdf._leading_prose_block((pdf.PdfPageBlock(1, pdf.TextBlock("", "figure")),)) is None
    assert pdf._page_blocks_after_title((_page_block("Body only."),), None, "Title")[0].block.text == "Body only."
    title = _page_block("Title")
    other = _page_block("Other", top=20)
    assert [block.block.text for block in pdf._page_blocks_after_title((title, other), title, "Title")] == ["Other"]
    assert pdf._remove_title_from_block(_page_block("Body only."), "Title") is None
    assert pdf._remove_title_from_block(_page_block("Title"), "Title") is None


def test_section_marker_number_and_cleanup_helpers_cover_edges() -> None:
    assert pdf._pdf_section_marker("") is None
    assert pdf._pdf_section_marker("x" * 200) is None
    assert pdf._pdf_section_marker("PART II: Setup") == pdf.PdfSectionMarker(
        "PART II: Setup",
        "frontmatter",
    )
    assert pdf._pdf_section_marker("Chapter Twenty-One: Middle").chapter_number == 21
    assert pdf._pdf_section_marker("1. A Real Heading").chapter_number == 1
    assert pdf._pdf_section_marker("1. Not a heading.") is None
    assert pdf._pdf_outline_section_marker("") is None
    assert pdf._pdf_outline_section_marker("x" * 200) is None
    assert pdf._pdf_outline_section_marker("Chapter 3") == pdf.PdfSectionMarker(
        "Chapter 3",
        "chapter",
        3,
    )
    assert pdf._pdf_outline_section_marker("Glossary") == pdf.PdfSectionMarker(
        "Glossary",
        "backmatter",
    )
    assert pdf._pdf_outline_section_marker("PART I: Setup") == pdf.PdfSectionMarker(
        "PART I: Setup",
        "frontmatter",
    )
    assert pdf._pdf_outline_section_marker("ordinary section") is None
    assert pdf._strip_pdf_chapter_ordinal("Chapter 2: Start") == "Start"
    assert pdf._strip_pdf_chapter_ordinal("Ch. 2: Start") == "Start"
    assert pdf._strip_pdf_chapter_ordinal("2. Start") == "Start"
    assert pdf._strip_pdf_chapter_ordinal("Start") == "Start"
    assert pdf._number_token_to_int("twenty-one") == 21
    assert pdf._number_token_to_int("bad") is None
    assert pdf._roman_to_int("") is None
    assert pdf._roman_to_int("bad") is None
    assert pdf._roman_to_int("iv") == 4
