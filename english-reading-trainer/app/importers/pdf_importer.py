"""
PDF importer that normalizes extractable PDF text into the standard reader
hierarchy used by TXT and EPUB imports.

The first implementation intentionally prioritizes trainable reflowed text
over PDF visual fidelity. It does not run OCR and raises a clear ValueError
when a PDF has no extractable words.
"""

from __future__ import annotations

import hashlib
import statistics
import string
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any

import pdfplumber
from pdfminer.pdftypes import resolve1

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.importers.epub_importer import EpubAssetSource, TextBlock, _insert
from app.importers.txt_importer import ImportResult


_HEADER_BAND_RATIO = 0.08
_FOOTER_BAND_RATIO = 0.08
_PAGES_PER_CHAPTER = 10
_MIN_LINE_TOLERANCE = 3.0
_LINE_TOLERANCE_RATIO = 0.6
_PARAGRAPH_GAP_RATIO = 1.8
_FIGURE_PADDING = 6.0
_FIGURE_MERGE_GAP = 18.0
_MIN_FIGURE_WIDTH = 36.0
_MIN_FIGURE_HEIGHT = 24.0
_FULL_WIDTH_RULE_RATIO = 0.75
_HAIRLINE_THICKNESS = 2.0
_MARGIN_DECORATION_BAND_RATIO = 0.18
_MARGIN_DECORATION_MAX_WIDTH_RATIO = 0.18
_MARGIN_DECORATION_MAX_HEIGHT_RATIO = 0.14
_MARGIN_DECORATION_MIN_WORD_HEIGHT_RATIO = 0.02
_PDF_FIGURE_MEDIA_TYPE = "image/png"
_PDF_FIGURE_RENDER_DPI = 150
_NONPROSE_CLUSTER_GAP = 22.0
_PROOF_LINE_X_TOLERANCE = 8.0
_PROOF_CONTINUATION_INDENT = 24.0
_PROOF_LINE_GAP_MULTIPLIER = 1.75
_PROOF_LINE_MAX_GAP = 18.0

_CODE_SYMBOLS = frozenset("{}[]();#=+-*/<>")
_MATH_SYMBOLS = frozenset("=<>+-*/^()[]{}∑∏∫∞≤≥≠±√⋅−λ")
_MONOSPACE_FONT_RE = re.compile(r"(?:courier|mono|consolas|menlo)", re.I)
_SYMBOL_FONT_RE = re.compile(r"(?:symbol|math)", re.I)
_PROOF_LINE_RE = re.compile(r"^\s*(?P<number>\d{1,3})\.\s+(?P<body>\S.*)$")
_PROOF_RULE_CITATION_RE = re.compile(
    r"\b\d+\s*,\s*\d+(?:\s*,\s*\d+)?\s*,?\s*"
    r"(?:MP|MT|HS|DS|CD|SIMP|CONJ|ADD|DN|COMM|ASSOC|DIST|DEM)\b",
    re.I,
)

_PAGE_NUMBER_RE = re.compile(r"^(?:page\s+)?\d+$", re.I)
_REPEATED_WHITESPACE_RE = re.compile(r"\s+")
_PDF_HEADING_MAX_LENGTH = 140
_PDF_NUMBER_TOKEN_RE = (
    r"\d+|[ivxlcdm]+|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty(?:[-\s]+one|[-\s]+two|[-\s]+three|"
    r"[-\s]+four|[-\s]+five|[-\s]+six|[-\s]+seven|[-\s]+eight|"
    r"[-\s]+nine)?|thirty"
)
_PDF_PART_HEADING_RE = re.compile(
    rf"^\s*part\s+(?:{_PDF_NUMBER_TOKEN_RE})(?:[\s.:)-]+.+)?$",
    re.I,
)
_PDF_CHAPTER_HEADING_RE = re.compile(
    rf"^\s*chapter\s+(?P<number>{_PDF_NUMBER_TOKEN_RE})(?:[\s.:)-]+.+)?$",
    re.I,
)
_PDF_NUMERIC_CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?P<number>\d{1,3})\.\s+[A-Z][A-Za-z0-9 ,:'’&-]{2,}$"
)
_PDF_OUTLINE_CHAPTER_HEADING_RE = re.compile(
    rf"^\s*(?:ch\.?|chapter)\s+(?P<number>{_PDF_NUMBER_TOKEN_RE})"
    r"(?:[\s.:)-]+(?P<title>.+))?$",
    re.I,
)
_PDF_BACKMATTER_OUTLINE_RE = re.compile(
    r"^\s*(?:answers?\b|glossary\b|index\b|glossary\s*/\s*index\b|"
    r"bibliography\b|references\b|notes\b)",
    re.I,
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
}
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


@dataclass(frozen=True)
class PdfLine:
    """One reconstructed text line from PDF word coordinates."""

    page_number: int
    top: float
    bottom: float
    text: str


@dataclass(frozen=True)
class PdfWordLine:
    """One PDF text line retaining word geometry and font metadata."""

    page_number: int
    x0: float
    top: float
    x1: float
    bottom: float
    text: str
    words: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PdfPageText:
    """Extracted reader blocks for a single PDF page."""

    page_number: int
    blocks: tuple["PdfPageBlock", ...]
    heading_text: str = ""


@dataclass(frozen=True)
class PdfParagraph:
    """One reconstructed paragraph with its page position."""

    top: float
    text: str


@dataclass(frozen=True)
class PdfFigureRegion:
    """A PDF visual region that should be preserved as a reader figure."""

    page_number: int
    x0: float
    top: float
    x1: float
    bottom: float
    contains_image: bool = False
    force_preserve: bool = False


@dataclass(frozen=True)
class PdfPageBlock:
    """A reader block plus its source top coordinate on the PDF page."""

    top: float
    block: TextBlock


@dataclass(frozen=True)
class PdfSectionMarker:
    """A detected PDF section heading at the start of a page."""

    title: str
    section_kind: str
    chapter_number: int | None = None


@dataclass(frozen=True)
class PdfOutlineItem:
    """One usable PDF outline/bookmark item."""

    title: str
    page_number: int
    level: int


def calculate_pdf_file_hash(file_path: str | Path) -> str:
    """Return the duplicate-detection hash import_pdf() will store."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_pdf(
    db: DatabaseConnection,
    file_path: str | Path,
    title: str | None = None,
    author: str | None = None,
    language: str = "en",
) -> ImportResult:
    """
    Parse *file_path* (PDF) and insert the full hierarchy into the DB.

    Raises:
        FileNotFoundError: if the file does not exist.
        DuplicateBookError: if file_hash already exists in books table.
        ValueError: if the PDF is unreadable or has no extractable text.
    """
    path = Path(file_path)
    file_hash = calculate_pdf_file_hash(path)

    try:
        with pdfplumber.open(path) as pdf:
            metadata = pdf.metadata or {}
            resolved_title = title or _metadata_value(metadata, "Title") or path.stem
            resolved_author = author or _metadata_value(metadata, "Author") or ""
            outline_items = _extract_pdf_outline(pdf)
            pages, asset_sources = _extract_pdf_pages(pdf.pages)
    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read PDF: {path}") from exc

    chapters_raw = _build_chapters(pages, outline_items)
    if not chapters_raw:
        raise ValueError(f"PDF contains no extractable text: {path}")

    return _insert(
        db,
        resolved_title,
        resolved_author,
        language,
        file_hash,
        SourceFormat.PDF,
        chapters_raw,
        asset_sources=asset_sources,
    )


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    """Return a stripped metadata value, accepting common case variations."""
    for candidate in (key, key.lower(), key.upper()):
        value = metadata.get(candidate)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _extract_pdf_outline(pdf: Any) -> tuple[PdfOutlineItem, ...]:
    """Return bookmark/outline entries with resolved physical page numbers."""
    try:
        raw_items = list(pdf.doc.get_outlines())
    except Exception:
        return ()

    page_numbers_by_objid = {
        page.page_obj.pageid: page.page_number
        for page in getattr(pdf, "pages", [])
        if getattr(getattr(page, "page_obj", None), "pageid", None) is not None
    }
    if not page_numbers_by_objid:
        return ()

    outline_items: list[PdfOutlineItem] = []
    seen: set[tuple[int, str, int]] = set()
    for raw_item in raw_items:
        if len(raw_item) < 5:
            continue
        level, title, dest, action, _se = raw_item
        clean_title = _clean_outline_title(title)
        page_number = _outline_destination_page_number(
            dest,
            action,
            page_numbers_by_objid,
        )
        if not clean_title or page_number is None:
            continue
        item_level = _safe_int(level) or 1
        key = (item_level, clean_title, page_number)
        if key in seen:
            continue
        seen.add(key)
        outline_items.append(PdfOutlineItem(clean_title, page_number, item_level))
    return tuple(outline_items)


def _outline_destination_page_number(
    dest: Any,
    action: Any,
    page_numbers_by_objid: dict[int, int],
) -> int | None:
    """Resolve a PDF outline destination/action to a 1-based physical page."""
    target = dest
    if target is None and action is not None:
        try:
            resolved_action = resolve1(action)
        except Exception:
            resolved_action = None
        if isinstance(resolved_action, dict):
            target = resolved_action.get("D")

    try:
        resolved_target = resolve1(target)
    except Exception:
        return None
    if isinstance(resolved_target, list) and resolved_target:
        page_ref = resolved_target[0]
    else:
        page_ref = resolved_target
    objid = getattr(page_ref, "objid", None)
    if objid is None:
        return None
    return page_numbers_by_objid.get(objid)


def _clean_outline_title(title: Any) -> str:
    """Normalize PDF bookmark titles, including NUL-padded titles."""
    if isinstance(title, bytes):
        text = title.decode("utf-8", errors="replace")
    else:
        text = str(title)
    return _clean_line_text(text.replace("\x00", ""))


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_pdf_pages(
    pages: list[Any],
) -> tuple[list[PdfPageText], dict[str, EpubAssetSource]]:
    """Extract page reader blocks and rendered figure assets from PDF pages."""
    extracted: list[PdfPageText] = []
    asset_sources: dict[str, EpubAssetSource] = {}
    for index, page in enumerate(pages, start=1):
        figure_regions = _figure_regions(page, page_number=index)
        nonprose_regions = _nonprose_regions(
            page,
            page_number=index,
            excluded_regions=figure_regions,
        )
        regions = tuple(
            _merge_figure_regions(list(figure_regions) + list(nonprose_regions))
        )
        all_body_words = _body_words(page, figure_regions=())
        figure_blocks = _figure_blocks_for_page(
            page,
            page_number=index,
            regions=regions,
            body_words=all_body_words,
            asset_sources=asset_sources,
        )
        words = _body_words(page, figure_regions=regions)
        lines = _words_to_lines(words, page_number=index)
        heading_text = lines[0].text if lines else ""
        paragraph_blocks = [
            PdfPageBlock(paragraph.top, TextBlock(paragraph.text, "prose"))
            for paragraph in _lines_to_paragraphs(lines, separator_regions=regions)
        ]
        page_blocks = tuple(
            sorted(
                paragraph_blocks + figure_blocks,
                key=lambda block: (block.top, block.block.kind),
            )
        )
        extracted.append(PdfPageText(index, page_blocks, heading_text))
    return extracted, asset_sources


def _body_words(
    page: Any,
    figure_regions: tuple[PdfFigureRegion, ...],
) -> list[dict[str, Any]]:
    """Return words outside margin bands and detected figure regions."""
    page_width = float(getattr(page, "width", 0) or 0)
    page_height = float(getattr(page, "height", 0) or 0)
    header_cutoff = page_height * _HEADER_BAND_RATIO
    footer_cutoff = page_height * (1 - _FOOTER_BAND_RATIO)
    words = page.extract_words() or []
    body_words: list[dict[str, Any]] = []

    for word in words:
        text = _clean_line_text(str(word.get("text", "")))
        top = _float_value(word.get("top"))
        if not text or top is None:
            continue
        if page_height and not (header_cutoff < top < footer_cutoff):
            continue
        if _is_margin_decoration_word(word, text, page_width, page_height):
            continue
        if _word_inside_any_region(word, figure_regions):
            continue
        body_words.append(word)
    return body_words


def _words_to_lines(words: list[dict[str, Any]], *, page_number: int) -> list[PdfLine]:
    """Group sorted PDF words into visual lines."""
    return [
        PdfLine(
            page_number=line.page_number,
            top=line.top,
            bottom=line.bottom,
            text=line.text,
        )
        for line in _words_to_word_lines(words, page_number=page_number)
    ]


def _words_to_word_lines(
    words: list[dict[str, Any]],
    *,
    page_number: int,
) -> list[PdfWordLine]:
    """Group sorted PDF words into visual lines with geometry and metadata."""
    if not words:
        return []

    sorted_words = sorted(
        words,
        key=lambda word: (
            _float_value(word.get("top")) or 0.0,
            _float_value(word.get("x0")) or 0.0,
        ),
    )
    tolerance = _line_tolerance(sorted_words)
    groups: list[list[dict[str, Any]]] = []
    group_top: float | None = None

    for word in sorted_words:
        top = _float_value(word.get("top")) or 0.0
        if group_top is None or abs(top - group_top) > tolerance:
            groups.append([word])
            group_top = top
        else:
            groups[-1].append(word)
            group_top = statistics.mean(
                _float_value(item.get("top")) or 0.0 for item in groups[-1]
            )

    lines: list[PdfWordLine] = []
    for group in groups:
        ordered_group = sorted(group, key=lambda item: _float_value(item.get("x0")) or 0.0)
        text = _clean_line_text(" ".join(str(item.get("text", "")) for item in ordered_group))
        if not text or _is_page_number_line(text):
            continue
        x0_values = [_float_value(item.get("x0")) or 0.0 for item in ordered_group]
        x1_values = [_float_value(item.get("x1")) or x0 for item, x0 in zip(ordered_group, x0_values)]
        tops = [_float_value(item.get("top")) or 0.0 for item in ordered_group]
        bottoms = [_float_value(item.get("bottom")) or top for item, top in zip(ordered_group, tops)]
        lines.append(
            PdfWordLine(
                page_number=page_number,
                x0=min(x0_values),
                top=min(tops),
                x1=max(x1_values),
                bottom=max(bottoms),
                text=text,
                words=tuple(ordered_group),
            )
        )
    return lines


def _line_tolerance(words: list[dict[str, Any]]) -> float:
    """Return a y-coordinate tolerance for grouping words into lines."""
    heights = [
        bottom - top
        for word in words
        if (top := _float_value(word.get("top"))) is not None
        and (bottom := _float_value(word.get("bottom"))) is not None
        and bottom > top
    ]
    if not heights:
        return _MIN_LINE_TOLERANCE
    return max(_MIN_LINE_TOLERANCE, statistics.median(heights) * _LINE_TOLERANCE_RATIO)


def _lines_to_paragraphs(
    lines: list[PdfLine],
    separator_regions: tuple[PdfFigureRegion, ...] = (),
) -> list[PdfParagraph]:
    """Join reconstructed lines into paragraphs, fixing hyphenated line breaks."""
    if not lines:
        return []

    sorted_lines = sorted(lines, key=lambda line: (line.page_number, line.top))
    gap_threshold = _paragraph_gap_threshold(sorted_lines)
    paragraphs: list[str] = []
    paragraph_tops: list[float] = []
    current = sorted_lines[0].text
    current_top = sorted_lines[0].top
    previous = sorted_lines[0]

    for line in sorted_lines[1:]:
        gap = line.top - previous.bottom if line.page_number == previous.page_number else 0.0
        has_separator = _has_region_between(previous, line, separator_regions)
        if (gap > gap_threshold or has_separator) and not _ends_with_hyphenated_word(current):
            paragraphs.append(current)
            paragraph_tops.append(current_top)
            current = line.text
            current_top = line.top
        else:
            current = _join_reflowed_lines(current, line.text)
        previous = line

    paragraphs.append(current)
    paragraph_tops.append(current_top)
    return [
        PdfParagraph(top, cleaned)
        for top, text in zip(paragraph_tops, paragraphs)
        if (cleaned := _clean_paragraph(text))
    ]


def _has_region_between(
    previous: PdfLine,
    line: PdfLine,
    regions: tuple[PdfFigureRegion, ...],
) -> bool:
    if previous.page_number != line.page_number:
        return False
    return any(
        region.page_number == line.page_number
        and previous.bottom <= region.top
        and region.bottom <= line.top
        for region in regions
    )


def _figure_regions(page: Any, *, page_number: int) -> tuple[PdfFigureRegion, ...]:
    """Detect coarse visual figure regions from PDF vector/image primitives."""
    page_width = float(getattr(page, "width", 0) or 0)
    page_height = float(getattr(page, "height", 0) or 0)
    candidates: list[PdfFigureRegion] = []

    for obj in (
        list(getattr(page, "lines", []) or [])
        + list(getattr(page, "curves", []) or [])
        + list(getattr(page, "rects", []) or [])
    ):
        region = _region_from_pdf_object(
            obj,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            contains_image=False,
        )
        if region is not None:
            candidates.append(region)

    for image in getattr(page, "images", []) or []:
        region = _region_from_pdf_object(
            image,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            contains_image=True,
        )
        if region is not None:
            candidates.append(region)

    return tuple(_merge_figure_regions(candidates))


def _nonprose_regions(
    page: Any,
    *,
    page_number: int,
    excluded_regions: tuple[PdfFigureRegion, ...],
) -> tuple[PdfFigureRegion, ...]:
    """Detect math/code text clusters that should render as figures."""
    page_width = float(getattr(page, "width", 0) or 0)
    page_height = float(getattr(page, "height", 0) or 0)
    words = _body_words_with_font_metadata(page, excluded_regions=excluded_regions)
    lines = _words_to_word_lines(words, page_number=page_number)
    if not lines:
        return ()

    flags = [_is_nonprose_line(line) for line in lines]
    flags = _include_numbered_proof_blocks(lines, flags)
    flags = _include_neighboring_formula_fragments(lines, flags)
    clusters: list[list[PdfWordLine]] = []
    current: list[PdfWordLine] = []
    for line, is_nonprose in zip(lines, flags):
        if is_nonprose:
            if current and line.top - current[-1].bottom > _NONPROSE_CLUSTER_GAP:
                clusters.append(current)
                current = []
            current.append(line)
            continue
        if current:
            clusters.append(current)
            current = []
    if current:
        clusters.append(current)

    regions = [
        _region_from_word_lines(
            cluster,
            page_width=page_width,
            page_height=page_height,
        )
        for cluster in clusters
    ]
    return tuple(_merge_figure_regions([region for region in regions if region is not None]))


def _body_words_with_font_metadata(
    page: Any,
    *,
    excluded_regions: tuple[PdfFigureRegion, ...],
) -> list[dict[str, Any]]:
    """Return body words with font metadata for non-prose classification."""
    page_width = float(getattr(page, "width", 0) or 0)
    page_height = float(getattr(page, "height", 0) or 0)
    header_cutoff = page_height * _HEADER_BAND_RATIO
    footer_cutoff = page_height * (1 - _FOOTER_BAND_RATIO)
    words = page.extract_words(extra_attrs=["fontname", "size"]) or []
    body_words: list[dict[str, Any]] = []

    for word in words:
        text = _clean_line_text(str(word.get("text", "")))
        top = _float_value(word.get("top"))
        if not text or top is None:
            continue
        if page_height and not (header_cutoff < top < footer_cutoff):
            continue
        if _is_margin_decoration_word(word, text, page_width, page_height):
            continue
        if _word_inside_any_region(word, excluded_regions):
            continue
        body_words.append(word)
    return body_words


def _is_nonprose_line(line: PdfWordLine) -> bool:
    text = line.text.strip()
    if not text:
        return False
    if _has_monospace_font(line):
        return True
    math_ratio = _math_symbol_ratio(text)
    alpha_ratio = _alpha_ratio(text)
    if _has_math_font(line) and math_ratio >= 0.10 and alpha_ratio <= 0.65:
        return True
    if math_ratio >= 0.22 and alpha_ratio <= 0.45:
        return True
    if _code_symbol_ratio(text) >= 0.22 and alpha_ratio <= 0.65:
        return True
    if _font_size_spread(line) >= 3.0 and alpha_ratio <= 0.55:
        return True
    return False


def _include_numbered_proof_blocks(
    lines: list[PdfWordLine],
    flags: list[bool],
) -> list[bool]:
    """Expand non-prose detection to full numbered proof/inference examples."""
    expanded = list(flags)
    index = 0
    while index < len(lines):
        if _proof_line_match(lines[index]) is None:
            index += 1
            continue

        block_indices = _numbered_proof_candidate_indices(lines, index)
        if len(block_indices) < 2:
            index += 1
            continue

        if any(flags[item] or _has_strong_proof_signal(lines[item]) for item in block_indices):
            for item in block_indices:
                expanded[item] = True
            next_index = _include_proof_continuations(lines, expanded, block_indices)
            index = max(next_index, block_indices[-1] + 1)
            continue

        index = block_indices[-1] + 1
    return expanded


def _numbered_proof_candidate_indices(
    lines: list[PdfWordLine],
    start_index: int,
) -> list[int]:
    base_line = lines[start_index]
    base_match = _proof_line_match(base_line)
    if base_match is None:
        return []

    indices = [start_index]
    previous_line = base_line
    previous_number = _safe_int(base_match.group("number"))
    for candidate_index in range(start_index + 1, len(lines)):
        candidate = lines[candidate_index]
        if not _is_close_vertical_neighbor(previous_line, candidate):
            break
        match = _proof_line_match(candidate)
        if match is None:
            break
        if abs(candidate.x0 - base_line.x0) > _PROOF_LINE_X_TOLERANCE:
            break
        number = _safe_int(match.group("number"))
        if (
            previous_number is not None
            and number is not None
            and number not in {previous_number, previous_number + 1}
        ):
            break
        indices.append(candidate_index)
        previous_line = candidate
        previous_number = number
    return indices


def _include_proof_continuations(
    lines: list[PdfWordLine],
    flags: list[bool],
    block_indices: list[int],
) -> int:
    base_x = lines[block_indices[0]].x0
    previous_index = block_indices[-1]
    candidate_index = previous_index + 1
    while candidate_index < len(lines):
        candidate = lines[candidate_index]
        if _proof_line_match(candidate) is not None:
            break
        if not _is_close_vertical_neighbor(lines[previous_index], candidate):
            break
        if candidate.x0 < base_x + _PROOF_CONTINUATION_INDENT:
            break
        flags[candidate_index] = True
        previous_index = candidate_index
        candidate_index += 1
    return candidate_index


def _is_close_vertical_neighbor(previous: PdfWordLine, candidate: PdfWordLine) -> bool:
    if previous.page_number != candidate.page_number:
        return False
    gap = candidate.top - previous.bottom
    if gap < -1.0:
        return False
    line_height = max(1.0, previous.bottom - previous.top)
    return gap <= min(_PROOF_LINE_MAX_GAP, line_height * _PROOF_LINE_GAP_MULTIPLIER)


def _has_strong_proof_signal(line: PdfWordLine) -> bool:
    match = _proof_line_match(line)
    if match is None:
        return False
    body = match.group("body")
    if _PROOF_RULE_CITATION_RE.search(body):
        return True
    if _math_symbol_ratio(body) >= 0.12 and _alpha_ratio(body) <= 0.75:
        return True
    if _code_symbol_ratio(body) >= 0.18 and _alpha_ratio(body) <= 0.75:
        return True
    return bool(_is_nonprose_line(line) and len(body.split()) <= 8)


def _proof_line_match(line: PdfWordLine) -> re.Match[str] | None:
    return _PROOF_LINE_RE.match(line.text.strip())


def _include_neighboring_formula_fragments(
    lines: list[PdfWordLine],
    flags: list[bool],
) -> list[bool]:
    expanded = list(flags)
    for index, line in enumerate(lines):
        if flags[index] or not _is_formula_fragment_line(line):
            continue
        previous_is_nonprose = index > 0 and flags[index - 1]
        next_is_nonprose = index + 1 < len(flags) and flags[index + 1]
        if previous_is_nonprose or next_is_nonprose:
            expanded[index] = True
    return expanded


def _is_formula_fragment_line(line: PdfWordLine) -> bool:
    text = line.text.strip()
    if len(text) > 16:
        return False
    return bool(text) and all(
        char.isalnum() or char.isspace() or char in _MATH_SYMBOLS
        for char in text
    )


def _has_monospace_font(line: PdfWordLine) -> bool:
    return any(
        _MONOSPACE_FONT_RE.search(str(word.get("fontname") or ""))
        for word in line.words
    )


def _has_math_font(line: PdfWordLine) -> bool:
    return any(
        _SYMBOL_FONT_RE.search(str(word.get("fontname") or ""))
        for word in line.words
    )


def _font_size_spread(line: PdfWordLine) -> float:
    sizes = [
        size
        for word in line.words
        if (size := _float_value(word.get("size"))) is not None
    ]
    if len(sizes) < 2:
        return 0.0
    return max(sizes) - min(sizes)


def _alpha_ratio(text: str) -> float:
    significant = [char for char in text if not char.isspace()]
    if not significant:
        return 0.0
    return sum(char.isalpha() for char in significant) / len(significant)


def _math_symbol_ratio(text: str) -> float:
    significant = [char for char in text if not char.isspace()]
    if not significant:
        return 0.0
    count = sum(
        char in _MATH_SYMBOLS
        or ord(char) > 127
        or (char in string.punctuation and char not in {".", ",", "'", '"'})
        for char in significant
    )
    return count / len(significant)


def _code_symbol_ratio(text: str) -> float:
    significant = [char for char in text if not char.isspace()]
    if not significant:
        return 0.0
    return sum(char in _CODE_SYMBOLS for char in significant) / len(significant)


def _region_from_word_lines(
    lines: list[PdfWordLine],
    *,
    page_width: float,
    page_height: float,
) -> PdfFigureRegion | None:
    if not lines:
        return None
    region = PdfFigureRegion(
        lines[0].page_number,
        min(line.x0 for line in lines),
        min(line.top for line in lines),
        max(line.x1 for line in lines),
        max(line.bottom for line in lines),
        force_preserve=True,
    )
    return _padded_region(region, page_width=page_width, page_height=page_height)


def _region_from_pdf_object(
    obj: dict[str, Any],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    contains_image: bool,
) -> PdfFigureRegion | None:
    bbox = _object_bbox(obj)
    if bbox is None:
        return None
    x0, top, x1, bottom = bbox
    if not _is_body_bbox(top, bottom, page_height):
        return None
    if _is_full_width_hairline(x0, top, x1, bottom, page_width):
        return None
    if (
        not contains_image
        and _is_margin_decoration_bbox(x0, top, x1, bottom, page_width, page_height)
    ):
        return None
    return _padded_region(
        PdfFigureRegion(page_number, x0, top, x1, bottom, contains_image),
        page_width=page_width,
        page_height=page_height,
    )


def _object_bbox(obj: dict[str, Any]) -> tuple[float, float, float, float] | None:
    values = (
        _float_value(obj.get("x0")),
        _float_value(obj.get("top")),
        _float_value(obj.get("x1")),
        _float_value(obj.get("bottom")),
    )
    if any(value is None for value in values):
        return None
    x0, top, x1, bottom = values
    left, right = sorted((x0, x1))
    upper, lower = sorted((top, bottom))
    if right <= left and lower <= upper:
        return None
    return left, upper, right, lower


def _is_body_bbox(top: float, bottom: float, page_height: float) -> bool:
    if not page_height:
        return True
    center = (top + bottom) / 2
    return page_height * _HEADER_BAND_RATIO < center < page_height * (1 - _FOOTER_BAND_RATIO)


def _is_full_width_hairline(
    x0: float,
    top: float,
    x1: float,
    bottom: float,
    page_width: float,
) -> bool:
    if not page_width:
        return False
    width = x1 - x0
    height = bottom - top
    return width >= page_width * _FULL_WIDTH_RULE_RATIO and height <= _HAIRLINE_THICKNESS


def _is_margin_decoration_bbox(
    x0: float,
    top: float,
    x1: float,
    bottom: float,
    page_width: float,
    page_height: float,
) -> bool:
    if not page_width or not page_height:
        return False
    width = x1 - x0
    height = bottom - top
    in_outer_margin = (
        x1 <= page_width * _MARGIN_DECORATION_BAND_RATIO
        or x0 >= page_width * (1 - _MARGIN_DECORATION_BAND_RATIO)
    )
    return (
        in_outer_margin
        and width <= page_width * _MARGIN_DECORATION_MAX_WIDTH_RATIO
        and height <= page_height * _MARGIN_DECORATION_MAX_HEIGHT_RATIO
    )


def _is_margin_decoration_object(
    obj: dict[str, Any],
    page_width: float,
    page_height: float,
) -> bool:
    bbox = _object_bbox(obj)
    if bbox is None:
        return False
    return _is_margin_decoration_bbox(*bbox, page_width, page_height)


def _is_margin_decoration_word(
    word: dict[str, Any],
    text: str,
    page_width: float,
    page_height: float,
) -> bool:
    if not re.fullmatch(r"[A-Z]?\d{1,3}[A-Z]?", text.strip()):
        return False
    bbox = _object_bbox(word)
    if bbox is None:
        return False
    _x0, top, _x1, bottom = bbox
    return (
        page_height > 0
        and bottom - top >= page_height * _MARGIN_DECORATION_MIN_WORD_HEIGHT_RATIO
        and _is_margin_decoration_bbox(*bbox, page_width, page_height)
    )


def _padded_region(
    region: PdfFigureRegion,
    *,
    page_width: float,
    page_height: float,
) -> PdfFigureRegion:
    return PdfFigureRegion(
        region.page_number,
        max(0.0, region.x0 - _FIGURE_PADDING),
        max(0.0, region.top - _FIGURE_PADDING),
        min(page_width, region.x1 + _FIGURE_PADDING) if page_width else region.x1 + _FIGURE_PADDING,
        min(page_height, region.bottom + _FIGURE_PADDING)
        if page_height
        else region.bottom + _FIGURE_PADDING,
        region.contains_image,
        region.force_preserve,
    )


def _merge_figure_regions(regions: list[PdfFigureRegion]) -> list[PdfFigureRegion]:
    merged = list(regions)

    changed = True
    while changed:
        changed = False
        next_regions: list[PdfFigureRegion] = []
        while merged:
            current = merged.pop(0)
            index = _nearby_region_index(current, merged)
            if index is None:
                next_regions.append(current)
                continue
            other = merged.pop(index)
            merged.append(_union_region(current, other))
            changed = True
        merged = next_regions
    return sorted(
        (region for region in merged if _is_substantial_region(region)),
        key=lambda item: (item.page_number, item.top, item.x0),
    )


def _is_substantial_region(region: PdfFigureRegion) -> bool:
    return (
        region.force_preserve
        or region.contains_image
        or (region.x1 - region.x0 >= _MIN_FIGURE_WIDTH)
        and (region.bottom - region.top >= _MIN_FIGURE_HEIGHT)
    )


def _nearby_region_index(
    region: PdfFigureRegion,
    candidates: list[PdfFigureRegion],
) -> int | None:
    for index, candidate in enumerate(candidates):
        if _regions_are_near(region, candidate):
            return index
    return None


def _regions_are_near(left: PdfFigureRegion, right: PdfFigureRegion) -> bool:
    horizontal_gap = max(0.0, max(left.x0, right.x0) - min(left.x1, right.x1))
    vertical_gap = max(0.0, max(left.top, right.top) - min(left.bottom, right.bottom))
    return horizontal_gap <= _FIGURE_MERGE_GAP and vertical_gap <= _FIGURE_MERGE_GAP


def _union_region(left: PdfFigureRegion, right: PdfFigureRegion) -> PdfFigureRegion:
    return PdfFigureRegion(
        left.page_number,
        min(left.x0, right.x0),
        min(left.top, right.top),
        max(left.x1, right.x1),
        max(left.bottom, right.bottom),
        left.contains_image or right.contains_image,
        left.force_preserve or right.force_preserve,
    )


def _figure_blocks_for_page(
    page: Any,
    *,
    page_number: int,
    regions: tuple[PdfFigureRegion, ...],
    body_words: list[dict[str, Any]],
    asset_sources: dict[str, EpubAssetSource],
) -> list[PdfPageBlock]:
    blocks: list[PdfPageBlock] = []
    for index, region in enumerate(regions, start=1):
        words = _words_inside_region(body_words, region)
        if not words and not (region.contains_image or region.force_preserve):
            continue
        asset_href = f"pdf/page-{page_number:04d}-figure-{index:02d}.png"
        asset_sources[asset_href] = EpubAssetSource(
            source_href=asset_href,
            media_type=_PDF_FIGURE_MEDIA_TYPE,
            content=_render_region_png(page, region),
        )
        label = f"PDF page {page_number} figure {index}"
        blocks.append(
            PdfPageBlock(
                region.top,
                TextBlock(
                    text="",
                    kind="figure",
                    asset_href=asset_href,
                    media_type=_PDF_FIGURE_MEDIA_TYPE,
                    alt_text=label,
                ),
            )
        )
    return blocks


def _render_region_png(page: Any, region: PdfFigureRegion) -> bytes:
    cropped = page.crop((region.x0, region.top, region.x1, region.bottom))
    image = cropped.to_image(resolution=_PDF_FIGURE_RENDER_DPI)
    buffer = BytesIO()
    image.original.save(buffer, format="PNG")
    return buffer.getvalue()


def _word_inside_any_region(
    word: dict[str, Any],
    regions: tuple[PdfFigureRegion, ...],
) -> bool:
    return any(_word_inside_region(word, region) for region in regions)


def _words_inside_region(
    words: list[dict[str, Any]],
    region: PdfFigureRegion,
) -> list[dict[str, Any]]:
    return [word for word in words if _word_inside_region(word, region)]


def _word_inside_region(word: dict[str, Any], region: PdfFigureRegion) -> bool:
    bbox = _object_bbox(word)
    if bbox is None:
        return False
    x0, top, x1, bottom = bbox
    return (
        x0 >= region.x0
        and x1 <= region.x1
        and top >= region.top
        and bottom <= region.bottom
    )


def _paragraph_gap_threshold(lines: list[PdfLine]) -> float:
    gaps = [
        line.top - previous.bottom
        for previous, line in zip(lines, lines[1:])
        if line.page_number == previous.page_number and line.top > previous.bottom
    ]
    if not gaps:
        return 12.0
    return max(8.0, statistics.median(gaps) * _PARAGRAPH_GAP_RATIO)


def _join_reflowed_lines(left: str, right: str) -> str:
    """Join two physical PDF lines into one paragraph."""
    left = left.rstrip()
    right = right.lstrip()
    if _ends_with_hyphenated_word(left) and right[:1].isalpha():
        return left[:-1] + right
    return f"{left} {right}"


def _ends_with_hyphenated_word(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]-$", text.rstrip()))


def _build_chapters(
    pages: list[PdfPageText],
    outline_items: tuple[PdfOutlineItem, ...] = (),
) -> list[dict[str, Any]]:
    """Group extracted page paragraphs into virtual reading chapters."""
    nonempty_pages = [page for page in pages if page.blocks]
    outline_chapters = _build_outline_chapters(nonempty_pages, outline_items)
    if outline_chapters is not None:
        return outline_chapters
    detected_chapters = _build_heading_chapters(nonempty_pages)
    if detected_chapters is not None:
        return detected_chapters
    return _build_virtual_chapters(nonempty_pages)


def _build_outline_chapters(
    nonempty_pages: list[PdfPageText],
    outline_items: tuple[PdfOutlineItem, ...],
) -> list[dict[str, Any]] | None:
    """Build chapters from PDF outline/bookmark boundaries when available."""
    if not nonempty_pages or not outline_items:
        return None

    boundary_items = _outline_boundary_items(outline_items)
    chapter_markers = [
        (item, marker)
        for item in boundary_items
        if (marker := _pdf_outline_section_marker(item.title)) is not None
        and marker.section_kind == "chapter"
    ]
    chapter_markers.sort(key=lambda item: item[0].page_number)
    if not chapter_markers:
        return None

    page_numbers = [page.page_number for page in nonempty_pages]
    first_page = min(page_numbers)
    last_page = max(page_numbers)
    first_chapter_page = chapter_markers[0][0].page_number
    last_chapter_page = chapter_markers[-1][0].page_number

    sections: list[tuple[int, PdfSectionMarker]] = []
    if first_page < first_chapter_page:
        sections.append((first_page, PdfSectionMarker("Frontmatter", "frontmatter")))

    sections.extend((item.page_number, marker) for item, marker in chapter_markers)
    sections.extend(
        (item.page_number, marker)
        for item in boundary_items
        if item.page_number > last_chapter_page
        and (marker := _pdf_outline_section_marker(item.title)) is not None
        and marker.section_kind == "backmatter"
    )
    sections = _deduplicate_outline_sections(sections)
    if not sections:
        return None

    chapters: list[dict[str, Any]] = []
    for index, (start_page, marker) in enumerate(sections):
        end_page = sections[index + 1][0] if index + 1 < len(sections) else last_page + 1
        blocks = _page_blocks_in_range(nonempty_pages, start_page, end_page)
        if marker.section_kind == "chapter":
            blocks = _trim_leading_outline_title_blocks(blocks, marker)
        text_blocks = [page_block.block for page_block in blocks]
        if not text_blocks:
            continue
        chapters.append(
            {
                "title": marker.title,
                "section_kind": marker.section_kind,
                "chapter_number": marker.chapter_number,
                "blocks": text_blocks,
            }
        )

    if not any(ch["section_kind"] == "chapter" for ch in chapters):
        return None
    return chapters


def _outline_boundary_items(
    outline_items: tuple[PdfOutlineItem, ...],
) -> tuple[PdfOutlineItem, ...]:
    """Return outline items to use as section boundaries."""
    min_level = min(item.level for item in outline_items)
    top_level_items = tuple(item for item in outline_items if item.level == min_level)
    if any(
        (marker := _pdf_outline_section_marker(item.title)) is not None
        and marker.section_kind == "chapter"
        for item in top_level_items
    ):
        return top_level_items
    return outline_items


def _deduplicate_outline_sections(
    sections: list[tuple[int, PdfSectionMarker]],
) -> list[tuple[int, PdfSectionMarker]]:
    """Sort outline sections and drop duplicates on the same page/kind/number."""
    result: list[tuple[int, PdfSectionMarker]] = []
    seen: set[tuple[int, str, int | None]] = set()
    for page_number, marker in sorted(sections, key=lambda item: item[0]):
        key = (page_number, marker.section_kind, marker.chapter_number)
        if key in seen:
            continue
        seen.add(key)
        result.append((page_number, marker))
    return result


def _page_blocks_in_range(
    pages: list[PdfPageText],
    start_page: int,
    end_page: int,
) -> list[PdfPageBlock]:
    return [
        page_block
        for page in pages
        if start_page <= page.page_number < end_page
        for page_block in page.blocks
    ]


def _trim_leading_outline_title_blocks(
    blocks: list[PdfPageBlock],
    marker: PdfSectionMarker,
) -> list[PdfPageBlock]:
    """Remove a duplicated title block from an outline-delimited chapter."""
    if not blocks:
        return []
    leading = blocks[0]
    if leading.block.kind != "prose":
        return blocks
    leading_text = _clean_line_text(leading.block.text)
    if not leading_text:
        return blocks[1:]
    variants = _outline_title_variants(marker)
    if _normalized_heading_text(leading_text) in variants:
        return blocks[1:]
    trimmed = _remove_title_from_block(leading, marker.title)
    if trimmed is not None:
        return [trimmed, *blocks[1:]]
    return blocks


def _outline_title_variants(marker: PdfSectionMarker) -> set[str]:
    title = _clean_line_text(marker.title)
    variants = {_normalized_heading_text(title)}
    if marker.section_kind == "chapter" and marker.chapter_number is not None:
        variants.add(_normalized_heading_text(f"Chapter {marker.chapter_number}"))
        variants.add(_normalized_heading_text(f"Ch {marker.chapter_number}"))
        stripped = _strip_pdf_chapter_ordinal(title)
        if stripped:
            variants.add(_normalized_heading_text(stripped))
    return {variant for variant in variants if variant}


def _strip_pdf_chapter_ordinal(title: str) -> str:
    chapter_match = _PDF_CHAPTER_HEADING_RE.match(title)
    if chapter_match:
        return title[chapter_match.end("number"):].lstrip(" \t\r\n.:)-")
    outline_match = _PDF_OUTLINE_CHAPTER_HEADING_RE.match(title)
    if outline_match:
        return (outline_match.group("title") or "").strip()
    numeric_match = _PDF_NUMERIC_CHAPTER_HEADING_RE.match(title)
    if numeric_match:
        return title[numeric_match.end("number"):].lstrip(" \t\r\n.:)-")
    return title


def _normalized_heading_text(text: str) -> str:
    return _clean_line_text(text).casefold()


def _build_virtual_chapters(nonempty_pages: list[PdfPageText]) -> list[dict[str, Any]]:
    """Group pages into fixed-size fallback chapters when no headings are found."""
    chapters: list[dict[str, Any]] = []

    for start in range(0, len(nonempty_pages), _PAGES_PER_CHAPTER):
        chunk = nonempty_pages[start:start + _PAGES_PER_CHAPTER]
        blocks = [
            page_block.block
            for page in chunk
            for page_block in page.blocks
        ]
        if not blocks:
            continue
        first_page = chunk[0].page_number
        last_page = chunk[-1].page_number
        title = f"Pages {first_page}-{last_page}" if first_page != last_page else f"Page {first_page}"
        chapters.append(
            {
                "title": title,
                "section_kind": "chapter",
                "chapter_number": len(chapters) + 1,
                "blocks": blocks,
            }
        )
    return chapters


def _build_heading_chapters(
    nonempty_pages: list[PdfPageText],
) -> list[dict[str, Any]] | None:
    """Build chapters from page-leading Part/Chapter headings, if present."""
    chapters: list[dict[str, Any]] = []
    frontmatter_blocks: list[TextBlock] = []
    current: dict[str, Any] | None = None
    saw_marker = False
    next_chapter_number = 1

    for page in nonempty_pages:
        title_block = _leading_prose_block(page.blocks)
        marker_text = page.heading_text or (title_block.block.text if title_block else "")
        marker = _pdf_section_marker(marker_text)
        if marker is None:
            if current is not None:
                current["blocks"].extend(page_block.block for page_block in page.blocks)
            else:
                frontmatter_blocks.extend(page_block.block for page_block in page.blocks)
            continue

        saw_marker = True
        if current is not None:
            chapters.append(current)
            current = None
        elif frontmatter_blocks:
            chapters.append(
                {
                    "title": "Frontmatter",
                    "section_kind": "frontmatter",
                    "chapter_number": None,
                    "blocks": frontmatter_blocks,
                }
            )
            frontmatter_blocks = []

        remaining_blocks = [
            page_block.block
            for page_block in _page_blocks_after_title(
                page.blocks,
                title_block,
                marker.title,
            )
        ]
        if marker.section_kind != "chapter":
            chapters.append(
                {
                    "title": marker.title,
                    "section_kind": marker.section_kind,
                    "chapter_number": None,
                    "blocks": remaining_blocks,
                }
            )
            continue

        chapter_number = marker.chapter_number or next_chapter_number
        next_chapter_number = max(next_chapter_number, chapter_number + 1)
        current = {
            "title": marker.title,
            "section_kind": "chapter",
            "chapter_number": chapter_number,
            "blocks": remaining_blocks,
        }

    if current is not None:
        chapters.append(current)
    elif saw_marker and frontmatter_blocks:
        chapters.append(
            {
                "title": "Frontmatter",
                "section_kind": "frontmatter",
                "chapter_number": None,
                "blocks": frontmatter_blocks,
            }
        )

    if not saw_marker or not any(ch["section_kind"] == "chapter" for ch in chapters):
        return None
    return chapters


def _leading_prose_block(blocks: tuple[PdfPageBlock, ...]) -> PdfPageBlock | None:
    for block in blocks:
        if block.block.kind == "prose" and block.block.text.strip():
            return block
    return None


def _page_blocks_after_title(
    blocks: tuple[PdfPageBlock, ...],
    title_block: PdfPageBlock | None,
    title_text: str,
) -> list[PdfPageBlock]:
    if title_block is None:
        return list(blocks)
    skipped = False
    result: list[PdfPageBlock] = []
    for block in blocks:
        if not skipped and block is title_block:
            skipped = True
            trimmed_block = _remove_title_from_block(block, title_text)
            if trimmed_block is not None:
                result.append(trimmed_block)
            continue
        result.append(block)
    return result


def _remove_title_from_block(
    block: PdfPageBlock,
    title_text: str,
) -> PdfPageBlock | None:
    text = block.block.text.strip()
    title = title_text.strip()
    if not text.startswith(title):
        return None
    remaining = text[len(title):].lstrip(" \t\r\n.:)-")
    if not remaining:
        return None
    return PdfPageBlock(block.top, TextBlock(remaining, block.block.kind))


def _pdf_section_marker(text: str) -> PdfSectionMarker | None:
    clean_text = _clean_line_text(text)
    if not clean_text or len(clean_text) > _PDF_HEADING_MAX_LENGTH:
        return None
    if _PDF_PART_HEADING_RE.match(clean_text):
        return PdfSectionMarker(clean_text, "frontmatter")

    chapter_match = _PDF_CHAPTER_HEADING_RE.match(clean_text)
    if chapter_match:
        return PdfSectionMarker(
            clean_text,
            "chapter",
            _number_token_to_int(chapter_match.group("number")),
        )

    numeric_match = _PDF_NUMERIC_CHAPTER_HEADING_RE.match(clean_text)
    if numeric_match and not clean_text.endswith((".", "!", "?")):
        return PdfSectionMarker(
            clean_text,
            "chapter",
            _number_token_to_int(numeric_match.group("number")),
        )
    return None


def _pdf_outline_section_marker(text: str) -> PdfSectionMarker | None:
    clean_text = _clean_line_text(text)
    if not clean_text or len(clean_text) > _PDF_HEADING_MAX_LENGTH:
        return None

    chapter_match = _PDF_OUTLINE_CHAPTER_HEADING_RE.match(clean_text)
    if chapter_match:
        chapter_number = _number_token_to_int(chapter_match.group("number"))
        title_text = _clean_line_text(chapter_match.group("title") or "")
        if chapter_number is not None:
            title = (
                f"Chapter {chapter_number}: {title_text}"
                if title_text
                else f"Chapter {chapter_number}"
            )
            return PdfSectionMarker(title, "chapter", chapter_number)

    marker = _pdf_section_marker(clean_text)
    if marker is not None:
        return marker

    if _PDF_BACKMATTER_OUTLINE_RE.match(clean_text):
        return PdfSectionMarker(clean_text, "backmatter")

    return None


def _number_token_to_int(token: str) -> int | None:
    normalized = _clean_line_text(token).lower().replace("-", " ")
    if normalized.isdigit():
        return int(normalized)
    if normalized in _NUMBER_WORDS:
        return _NUMBER_WORDS[normalized]

    parts = normalized.split()
    if len(parts) == 2 and parts[0] in {"twenty", "thirty"}:
        ones = _NUMBER_WORDS.get(parts[1])
        if ones is not None and ones < 10:
            return _NUMBER_WORDS[parts[0]] + ones

    return _roman_to_int(normalized)


def _roman_to_int(token: str) -> int | None:
    if not token or not re.fullmatch(r"[ivxlcdm]+", token):
        return None
    total = 0
    previous = 0
    for char in reversed(token):
        value = _ROMAN_VALUES[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total if total > 0 else None


def _clean_line_text(text: str) -> str:
    return _REPEATED_WHITESPACE_RE.sub(" ", text).strip()


def _clean_paragraph(text: str) -> str:
    return _REPEATED_WHITESPACE_RE.sub(" ", text).strip()


def _is_page_number_line(text: str) -> bool:
    return bool(_PAGE_NUMBER_RE.fullmatch(text.strip()))


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
