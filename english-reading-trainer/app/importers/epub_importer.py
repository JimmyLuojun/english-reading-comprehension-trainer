"""
EPUB file importer: reads an EPUB book and inserts the full
Book -> Chapter -> Paragraph -> Sentence hierarchy into the database.

Processing pipeline:
  1. Normalize the source path; iBooks directory packages are converted
     to deterministic temporary EPUB ZIP files.
  2. Read EPUB with ebooklib; extract metadata (title, author).
  3. Build a TOC map (href -> top-level section title) for naming rows.
  4. Walk spine items in reading order; skip navigation documents.
  5. For each content item: parse HTML with BeautifulSoup, classify the
     item as frontmatter/chapter/appendix/backmatter, extract visible text
     blocks in DOM order, segment prose with pysbd.
  6. Insert all rows in a single transaction.

Chapter title resolution (priority):
  1. TOC entry matching the item's href
  2. First <h1> / <h2> / <h3> in the item's HTML
  3. Item filename (stem)
  4. "Chapter N" fallback
"""

from collections.abc import Iterator
from contextlib import contextmanager
import json
import hashlib
import mimetypes
import posixpath
import re
import shutil
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from bs4.element import Tag
from ebooklib import ITEM_DOCUMENT, ITEM_NAVIGATION, epub

from app.db_connection import DatabaseConnection
from app.db_models import SourceFormat
from app.importers.txt_importer import DuplicateBookError, ImportResult
from app.nlp.sentence_segmenter import normalize_for_hash, segment_sentences


@dataclass(frozen=True)
class PreparedEpubSource:
    """Normalized EPUB source path plus the hash used for duplicate detection."""

    path: Path
    file_hash: str
    temporary_path: Path | None = None
    missing_asset_hrefs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TextBlock:
    """A visible EPUB content block in reading order."""

    text: str
    kind: str = "prose"
    asset_href: str = ""
    media_type: str = ""
    alt_text: str = ""
    is_missing: bool = False
    payload_json: str = ""


@dataclass(frozen=True)
class EpubAssetSource:
    """A manifest asset available from the EPUB reader."""

    source_href: str
    media_type: str
    content: bytes
    is_missing: bool = False


@dataclass(frozen=True)
class ChapterClassification:
    """EPUB section kind plus the displayed body chapter number, when any."""

    section_kind: str
    chapter_number: int | None = None


_EPUB_MIMETYPE = "mimetype"
_EPUB_CONTAINER = Path("META-INF") / "container.xml"
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_ZIP_FILE_MODE = 0o644 << 16

_SECTION_FRONTMATTER = "frontmatter"
_SECTION_CHAPTER = "chapter"
_SECTION_APPENDIX = "appendix"
_SECTION_BACKMATTER = "backmatter"

_KIND_PROSE = "prose"
_KIND_PRE = "pre"
_KIND_TABLE = "table"
_KIND_IMAGE = "image"
_KIND_FIGURE = "figure"
_KIND_MISSING_ASSET = "missing_asset"

_FULL_TEXT_TAGS = {"p", "pre", "blockquote", "figcaption", "caption"}
_FALLBACK_BLOCK_TAGS = {"div", "section", "article"}
_LIST_TAGS = {"li"}
_DEFINITION_TAGS = {"dt", "dd"}
_TABLE_TAGS = {"table", "tr"}
_TABLE_CELL_TAGS = {"td", "th"}
_MEDIA_TAGS = {"figure", "img"}
_EXCLUDED_TAGS = {"script", "style", "nav", "aside", "head"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_EXTRACTABLE_DESCENDANT_TAGS = (
    _FULL_TEXT_TAGS
    | _FALLBACK_BLOCK_TAGS
    | _LIST_TAGS
    | _DEFINITION_TAGS
    | _TABLE_TAGS
    | _MEDIA_TAGS
)
_TEXT_BACKED_BLOCK_KINDS = frozenset({_KIND_PROSE, _KIND_PRE, _KIND_TABLE})

_CHAPTER_TITLE_RE = re.compile(r"^\s*(?:chapter\s+)?(\d+)(?:[\s.:)-]+|$)", re.I)
_PART_TITLE_RE = re.compile(
    r"^\s*part\s*(?:"
    r"\d+|[ivxlcdm]+|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty"
    r")(?:[\s.:)-]+|$)",
    re.I,
)
_PART_SEPARATOR_TEXT_RE = re.compile(
    r"\bpart\s+(?:"
    r"\d+|[ivxlcdm]+|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty"
    r")\b",
    re.I,
)
_APPENDIX_TITLE_RE = re.compile(r"^\s*(?:appendix\s+)?([A-Z])(?:[\s.:)-]+|$)")
_FRONTMATTER_TYPES = {
    "acknowledgments",
    "dedication",
    "foreword",
    "frontmatter",
    "cover",
    "glossary",
    "introduction",
    "preface",
    "prologue",
    "titlepage",
}
_BACKMATTER_TYPES = {
    "afterword",
    "backmatter",
    "bibliography",
    "colophon",
    "copyright-page",
    "credits",
    "index",
}
_FRONTMATTER_TITLES = {
    "acknowledgments",
    "cover",
    "dedication",
    "foreword",
    "glossary",
    "preface",
    "prologue",
    "quick glossary",
    "title page",
    "titlepage",
}
_BACKMATTER_TITLES = {"index", "colophon", "copyright"}

_MIN_PARA_LEN = 20

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")


@contextmanager
def _prepare_epub_source(file_path: str | Path) -> Iterator[PreparedEpubSource]:
    """Yield a path ebooklib can read, converting directory packages to ZIPs."""
    source_path = Path(file_path)
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {source_path}")

    if source_path.is_file():
        yield PreparedEpubSource(
            path=source_path,
            file_hash=_sha256_file(source_path),
        )
        return

    if not source_path.is_dir():
        raise ValueError(f"EPUB path is neither a file nor a directory: {source_path}")

    _validate_epub_directory(source_path)
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        missing_assets = _write_epub_directory_zip(source_path, tmp_path)
        yield PreparedEpubSource(
            path=tmp_path,
            file_hash=_sha256_file(tmp_path),
            temporary_path=tmp_path,
            missing_asset_hrefs=_missing_asset_hrefs_from_arcnames(
                source_path,
                missing_assets,
            ),
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _validate_epub_directory(source_dir: Path) -> None:
    """Validate the minimum EPUB directory-package structure."""
    if not (source_dir / _EPUB_MIMETYPE).is_file():
        raise ValueError(f"EPUB directory is missing {_EPUB_MIMETYPE}: {source_dir}")
    if not (source_dir / _EPUB_CONTAINER).is_file():
        raise ValueError(f"EPUB directory is missing {_EPUB_CONTAINER}: {source_dir}")


def _write_epub_directory_zip(source_dir: Path, out_path: Path) -> list[str]:
    """Write a deterministic EPUB ZIP from an expanded directory package."""
    files = sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and _is_epub_payload_file(path.relative_to(source_dir))
    )
    mimetype_path = source_dir / _EPUB_MIMETYPE
    remaining = [path for path in files if path != mimetype_path]
    existing_arcnames = {path.relative_to(source_dir).as_posix() for path in files}
    missing_assets = _missing_manifest_asset_arcnames(source_dir, existing_arcnames)

    with ZipFile(out_path, "w") as archive:
        _write_zip_entry(
            archive,
            _EPUB_MIMETYPE,
            mimetype_path.read_bytes(),
            compression=ZIP_STORED,
        )
        for path in remaining:
            _write_zip_entry(
                archive,
                path.relative_to(source_dir).as_posix(),
                path.read_bytes(),
                compression=ZIP_DEFLATED,
            )
        for arcname in missing_assets:
            _write_zip_entry(
                archive,
                arcname,
                b"",
                compression=ZIP_STORED,
            )
    return missing_assets


def _is_epub_payload_file(relative_path: Path) -> bool:
    """Return False for macOS metadata files that are not part of the EPUB."""
    ignored_names = {"__MACOSX", ".DS_Store"}
    return not any(
        part in ignored_names or part.startswith("._")
        for part in relative_path.parts
    )


def _write_zip_entry(
    archive: ZipFile,
    arcname: str,
    data: bytes,
    *,
    compression: int,
) -> None:
    """Write a ZIP entry with stable metadata."""
    info = ZipInfo(arcname)
    info.date_time = _ZIP_EPOCH
    info.external_attr = _ZIP_FILE_MODE
    info.compress_type = compression
    archive.writestr(info, data)


def _missing_manifest_asset_arcnames(
    source_dir: Path,
    existing_arcnames: set[str],
) -> list[str]:
    """Return missing non-document manifest assets to stub for ebooklib loading."""
    opf_path = _opf_path_from_container(source_dir)
    opf_dir = opf_path.parent
    tree = ET.parse(opf_path)
    missing_assets: list[str] = []

    for item in tree.getroot().iter():
        if _xml_local_name(item.tag) != "item":
            continue
        href = item.attrib.get("href", "")
        if not href:
            continue
        media_type = item.attrib.get("media-type", "")
        href, _fragment = urldefrag(unquote(href))
        arcname = (opf_dir.relative_to(source_dir) / href).as_posix()
        if arcname in existing_arcnames:
            continue
        if _is_required_manifest_document(media_type):
            raise ValueError(f"EPUB directory is missing document resource: {arcname}")
        missing_assets.append(arcname)

    return sorted(set(missing_assets))


def _missing_asset_hrefs_from_arcnames(
    source_dir: Path,
    arcnames: list[str],
) -> frozenset[str]:
    """Return both ZIP arcnames and OPF-relative hrefs for missing assets."""
    if not arcnames:
        return frozenset()

    try:
        opf_dir = _opf_path_from_container(source_dir).parent.relative_to(source_dir)
    except ValueError:
        opf_dir = Path()
    opf_prefix = opf_dir.as_posix().rstrip("/")
    hrefs: set[str] = set()
    for arcname in arcnames:
        normalized = _normalize_epub_path(arcname)
        if not normalized:
            continue
        hrefs.add(normalized)
        if opf_prefix and normalized.startswith(f"{opf_prefix}/"):
            hrefs.add(normalized[len(opf_prefix) + 1 :])
    return frozenset(hrefs)


def _opf_path_from_container(source_dir: Path) -> Path:
    container_path = source_dir / _EPUB_CONTAINER
    tree = ET.parse(container_path)
    for element in tree.getroot().iter():
        if _xml_local_name(element.tag) == "rootfile":
            full_path = element.attrib.get("full-path")
            if full_path:
                opf_path = source_dir / unquote(full_path)
                if not opf_path.is_file():
                    raise ValueError(f"EPUB directory is missing OPF file: {full_path}")
                return opf_path
    raise ValueError(f"EPUB directory container has no rootfile: {container_path}")


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_required_manifest_document(media_type: str) -> bool:
    return media_type in {
        "application/xhtml+xml",
        "text/html",
        "application/x-dtbncx+xml",
    }


def _normalize_epub_path(href: str) -> str:
    """Normalize an EPUB-internal path and reject traversal/remote URLs."""
    clean_href, _fragment = urldefrag(unquote((href or "").strip()))
    if not clean_href:
        return ""
    parsed = urlparse(clean_href)
    if parsed.scheme or parsed.netloc:
        return ""
    normalized = posixpath.normpath(clean_href.lstrip("/"))
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        return ""
    return normalized


def _resolve_epub_href(document_href: str, resource_href: str) -> str:
    """Resolve a resource href relative to an EPUB document href."""
    clean_href = _normalize_epub_path(resource_href)
    if not clean_href:
        return ""
    if not document_href:
        return clean_href
    document_dir = posixpath.dirname(_normalize_epub_path(document_href))
    joined = posixpath.join(document_dir, clean_href) if document_dir else clean_href
    return _normalize_epub_path(joined)


def _sha256_file(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _extract_metadata(book: epub.EpubBook, field: str) -> str:
    """Return the first value for a Dublin Core metadata field, or ''."""
    values = book.get_metadata("DC", field)
    if values:
        val = values[0]
        return (val[0] if isinstance(val, tuple) else val).strip()
    return ""


def _build_toc_map(book: epub.EpubBook) -> dict[str, str]:
    """
    Return a dict mapping document hrefs to top-level section titles.

    Nested TOC entries usually point to fragments inside the same HTML file.
    Those entries must not overwrite the file-level title used for the row.
    """
    result: dict[str, str] = {}

    def _record(href: str, title: str) -> None:
        clean_title = title.strip()
        if not clean_title:
            return
        href, fragment = urldefrag(unquote(href or ""))
        if not href or fragment:
            return
        result.setdefault(href, clean_title)
        result.setdefault(Path(href).name, clean_title)

    def _walk(items) -> None:
        for item in items:
            if isinstance(item, epub.Link):
                _record(item.href, item.title)
            elif isinstance(item, tuple) and len(item) == 2:
                section, children = item
                if isinstance(section, epub.Section) and section.title:
                    _record(section.href or "", section.title)
                _walk(children)
            elif isinstance(item, (list, tuple)):
                _walk(item)

    _walk(book.toc)
    return result


def _build_asset_sources(
    book: epub.EpubBook,
    missing_asset_hrefs: frozenset[str] = frozenset(),
) -> dict[str, EpubAssetSource]:
    """Index image-like EPUB manifest items by normalized href."""
    sources: dict[str, EpubAssetSource] = {}
    for item in book.get_items():
        source_href = _normalize_epub_path(getattr(item, "file_name", ""))
        if not source_href:
            continue
        media_type = getattr(item, "media_type", "") or ""
        if not _is_supported_asset(source_href, media_type):
            continue
        is_missing = source_href in missing_asset_hrefs
        content = b"" if is_missing else (item.get_content() or b"")
        source = EpubAssetSource(
            source_href=source_href,
            media_type=media_type,
            content=content,
            is_missing=is_missing,
        )
        sources.setdefault(source_href, source)
    return sources


def _is_supported_asset(source_href: str, media_type: str) -> bool:
    if media_type.startswith("image/"):
        return True
    guessed, _encoding = mimetypes.guess_type(source_href)
    return bool(guessed and guessed.startswith("image/"))


def _lookup_asset_source(
    asset_sources: dict[str, EpubAssetSource],
    source_href: str,
) -> EpubAssetSource | None:
    source = asset_sources.get(source_href)
    if source is not None:
        return source

    suffix_matches = [
        candidate
        for href, candidate in asset_sources.items()
        if href.endswith(f"/{source_href}") or source_href.endswith(f"/{href}")
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return None


def _extract_chapters(
    book: epub.EpubBook,
    toc_map: dict[str, str],
    asset_sources: dict[str, EpubAssetSource] | None = None,
    missing_asset_hrefs: frozenset[str] = frozenset(),
) -> list[dict]:
    """
    Walk spine in reading order; return list of
    {"title": str, "paragraphs": [TextBlock, ...]} dicts.
    """
    chapters: list[dict] = []
    body_chapter_count = 0

    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        if item.get_type() == ITEM_NAVIGATION:
            continue
        if item.get_type() != ITEM_DOCUMENT:
            continue

        html_bytes = item.get_body_content() or item.get_content()
        if not html_bytes:
            continue

        soup = BeautifulSoup(html_bytes, "lxml")
        bare_name = Path(item.file_name).name
        title = (
            toc_map.get(item.file_name)
            or toc_map.get(bare_name)
            or _heading_from_soup(soup)
            or Path(item.file_name).stem
        )

        blocks = _extract_text_blocks(
            soup,
            document_href=item.file_name,
            asset_sources=asset_sources,
            missing_asset_hrefs=missing_asset_hrefs,
        )
        if not blocks:
            continue
        classification = _classify_chapter(title, soup, body_chapter_count + 1)
        if classification.section_kind == _SECTION_CHAPTER:
            body_chapter_count += 1
        chapters.append(
            {
                "title": title,
                "section_kind": classification.section_kind,
                "chapter_number": classification.chapter_number,
                "paragraphs": [
                    block for block in blocks if _is_text_backed_block(block)
                ],
                "blocks": blocks,
            }
        )

    return chapters


def _heading_from_soup(soup: BeautifulSoup) -> str:
    """Return the text of the first heading tag found, or ''."""
    for tag in _HEADING_TAGS:
        el = soup.find(tag)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _classify_chapter(
    title: str,
    soup: BeautifulSoup,
    next_chapter_number: int,
) -> ChapterClassification:
    """Classify an EPUB spine document for display and chapter numbering."""
    epub_types = _epub_type_tokens(soup)
    parsed_number = _chapter_number_from_title(title)

    if "part" in epub_types or _is_part_separator(title, soup, epub_types):
        return ChapterClassification(_SECTION_FRONTMATTER)
    if "chapter" in epub_types or parsed_number is not None:
        return ChapterClassification(
            _SECTION_CHAPTER,
            parsed_number or next_chapter_number,
        )
    if "appendix" in epub_types or _APPENDIX_TITLE_RE.match(title):
        return ChapterClassification(_SECTION_APPENDIX)
    if epub_types & _BACKMATTER_TYPES or title.strip().lower() in _BACKMATTER_TITLES:
        return ChapterClassification(_SECTION_BACKMATTER)
    if epub_types & _FRONTMATTER_TYPES or _is_frontmatter_title(title):
        return ChapterClassification(_SECTION_FRONTMATTER)
    return ChapterClassification(_SECTION_CHAPTER, next_chapter_number)


def _epub_type_tokens(soup: BeautifulSoup) -> set[str]:
    """Return lowercase tokens from epub:type attributes near the document root."""
    tokens: set[str] = set()
    roots = []
    if soup.body:
        roots.append(soup.body)
        roots.extend(
            child for child in soup.body.find_all(True, recursive=False)
            if isinstance(child, Tag)
        )
    else:
        roots.extend(soup.find_all(True, recursive=False))

    for tag in roots:
        raw = tag.get("epub:type") or tag.get("type") or ""
        if raw:
            tokens.update(part.strip().lower() for part in raw.split() if part.strip())
    return tokens


def _chapter_number_from_title(title: str) -> int | None:
    match = _CHAPTER_TITLE_RE.match(title)
    if not match:
        return None
    return int(match.group(1))


def _is_part_separator(
    title: str,
    soup: BeautifulSoup,
    epub_types: set[str],
) -> bool:
    """Return True for body part divider pages that should not count as chapters."""
    if _is_part_title(title) or _is_part_title(_heading_from_soup(soup)):
        return True
    if "bodymatter" not in epub_types:
        return False

    body_text = " ".join((soup.get_text(" ", strip=True) or "").split())
    if len(body_text) > 180:
        return False
    return bool(_PART_SEPARATOR_TEXT_RE.search(body_text))


def _is_part_title(title: str) -> bool:
    return bool(_PART_TITLE_RE.match(title))


def _is_frontmatter_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in _FRONTMATTER_TITLES or normalized.startswith("praise for ")


def _extract_text_blocks(
    soup: BeautifulSoup,
    *,
    document_href: str = "",
    asset_sources: dict[str, EpubAssetSource] | None = None,
    missing_asset_hrefs: frozenset[str] = frozenset(),
) -> list[TextBlock]:
    """
    Extract visible text blocks in DOM order without duplicating nested blocks.

    Prose blocks are sentence-segmented later. Code and table blocks are stored
    as complete units so examples and tabular rows are not split apart.
    """
    for tag in soup.find_all(_EXCLUDED_TAGS):
        tag.decompose()

    root = soup.body or soup
    blocks: list[TextBlock] = []
    consumed: set[int] = set()
    include_media = bool(document_href or asset_sources)
    asset_sources = asset_sources or {}

    for element in root.find_all(True):
        if not isinstance(element, Tag):
            continue
        if id(element) in consumed or _has_consumed_ancestor(element, consumed):
            continue

        name = element.name.lower()
        if name in _HEADING_TAGS:
            continue

        if include_media and name == "figure":
            block = _figure_block_from_element(
                element,
                document_href=document_href,
                asset_sources=asset_sources,
                missing_asset_hrefs=missing_asset_hrefs,
            )
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if include_media and name == "img":
            block = _image_block_from_element(
                element,
                document_href=document_href,
                asset_sources=asset_sources,
                missing_asset_hrefs=missing_asset_hrefs,
                figure_caption="",
                force_figure=False,
            )
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name == "dt":
            block, nodes = _definition_block_from_dt(element)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids(nodes))
            continue

        if name == "dd":
            block = _text_block_from_element(element, kind=_KIND_PROSE)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name == "pre":
            block = _text_block_from_element(element, kind=_KIND_PRE)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name == "tr":
            block = _table_row_block(element)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name == "table":
            if _has_descendant_named(element, {"tr"}):
                continue
            block = _text_block_from_element(element, kind=_KIND_TABLE)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name in _FULL_TEXT_TAGS:
            if name in {"blockquote", "figcaption", "caption"}:
                has_descendant = _has_extractable_descendant(element)
                if has_descendant:
                    direct = _direct_text(element)
                    if direct and _passes_min_length(direct):
                        blocks.append(TextBlock(direct, _KIND_PROSE))
                    continue
            block = _text_block_from_element(element, kind=_KIND_PROSE)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name in _LIST_TAGS:
            if _has_extractable_descendant(element):
                direct = _direct_text(element)
                if direct and _passes_min_length(direct):
                    blocks.append(TextBlock(direct, _KIND_PROSE))
                continue
            block = _text_block_from_element(element, kind=_KIND_PROSE)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))
            continue

        if name in _FALLBACK_BLOCK_TAGS and not _has_extractable_descendant(element):
            block = _text_block_from_element(element, kind=_KIND_PROSE)
            if block:
                blocks.append(block)
                consumed.update(_descendant_ids([element]))

    return blocks


def _figure_block_from_element(
    figure: Tag,
    *,
    document_href: str,
    asset_sources: dict[str, EpubAssetSource],
    missing_asset_hrefs: frozenset[str],
) -> TextBlock | None:
    """Create one media block from a figure and its caption."""
    image = figure.find(
        lambda tag: isinstance(tag, Tag) and tag.name.lower() == "img"
    )
    if not isinstance(image, Tag):
        return None

    caption_tag = figure.find(
        lambda tag: isinstance(tag, Tag) and tag.name.lower() == "figcaption"
    )
    caption = ""
    if isinstance(caption_tag, Tag):
        caption = _clean_text(caption_tag.get_text(" ", strip=True))

    return _image_block_from_element(
        image,
        document_href=document_href,
        asset_sources=asset_sources,
        missing_asset_hrefs=missing_asset_hrefs,
        figure_caption=caption,
        force_figure=True,
    )


def _image_block_from_element(
    image: Tag,
    *,
    document_href: str,
    asset_sources: dict[str, EpubAssetSource],
    missing_asset_hrefs: frozenset[str],
    figure_caption: str,
    force_figure: bool,
) -> TextBlock | None:
    source_href = _resolve_epub_href(document_href, _image_source(image))
    if not source_href:
        return None

    asset_source = _lookup_asset_source(asset_sources, source_href)
    alt_text = _clean_text(str(image.get("alt") or ""))
    caption = _clean_text(figure_caption)
    media_type = asset_source.media_type if asset_source else ""
    is_missing = (
        source_href in missing_asset_hrefs
        or (asset_source.is_missing if asset_source else True)
    )
    text = caption or alt_text
    kind = _KIND_MISSING_ASSET if is_missing else (
        _KIND_FIGURE if force_figure or caption else _KIND_IMAGE
    )
    payload = {
        "source_href": source_href,
        "alt": alt_text,
        "caption": caption,
    }
    return TextBlock(
        text=text,
        kind=kind,
        asset_href=source_href,
        media_type=media_type,
        alt_text=alt_text,
        is_missing=is_missing,
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def _image_source(image: Tag) -> str:
    return str(
        image.get("src")
        or image.get("href")
        or image.get("xlink:href")
        or image.get("data-src")
        or ""
    )


def _definition_block_from_dt(dt: Tag) -> tuple[TextBlock | None, list[Tag]]:
    """Combine a dt with one or more following dd siblings."""
    nodes = [dt]
    texts = [_clean_text(dt.get_text(" ", strip=True))]

    for sibling in dt.find_next_siblings():
        if not isinstance(sibling, Tag):
            continue
        name = sibling.name.lower()
        if name == "dt":
            break
        if name != "dd":
            continue
        text = _clean_text(sibling.get_text(" ", strip=True))
        if text:
            texts.append(text)
            nodes.append(sibling)

    text = _clean_text(" ".join(part for part in texts if part))
    if not _passes_min_length(text):
        return None, nodes
    return TextBlock(text, _KIND_PROSE), nodes


def _table_row_block(row: Tag) -> TextBlock | None:
    cells = [
        _clean_text(cell.get_text(" ", strip=True))
        for cell in row.find_all(_TABLE_CELL_TAGS, recursive=False)
    ]
    text = _clean_text(" | ".join(cell for cell in cells if cell))
    if not _passes_min_length(text):
        return None
    return TextBlock(text, _KIND_TABLE)


def _text_block_from_element(element: Tag, *, kind: str) -> TextBlock | None:
    text = _clean_text(element.get_text(" ", strip=True))
    if not _passes_min_length(text):
        return None
    return TextBlock(text, kind)


def _direct_text(element: Tag) -> str:
    parts: list[str] = []
    for child in element.children:
        if isinstance(child, Tag):
            child_name = child.name.lower()
            if (
                child_name in _EXTRACTABLE_DESCENDANT_TAGS
                or child_name in _HEADING_TAGS
            ):
                continue
            text = child.get_text(" ", strip=True)
        else:
            text = str(child)
        text = _clean_text(text)
        if text:
            parts.append(text)
    return _clean_text(" ".join(parts))


def _has_extractable_descendant(element: Tag) -> bool:
    return element.find(_is_extractable_descendant) is not None


def _is_extractable_descendant(element: Tag) -> bool:
    if not isinstance(element, Tag):
        return False
    name = element.name.lower()
    return name in _EXTRACTABLE_DESCENDANT_TAGS or name in _HEADING_TAGS


def _has_descendant_named(element: Tag, names: set[str]) -> bool:
    return (
        element.find(
            lambda tag: isinstance(tag, Tag) and tag.name.lower() in names
        )
        is not None
    )


def _has_consumed_ancestor(element: Tag, consumed: set[int]) -> bool:
    return any(
        id(parent) in consumed
        for parent in element.parents
        if isinstance(parent, Tag)
    )


def _descendant_ids(nodes: list[Tag]) -> set[int]:
    result: set[int] = set()
    for node in nodes:
        result.add(id(node))
        result.update(id(descendant) for descendant in node.find_all(True))
    return result


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    """
    Extract non-empty visible text blocks from the HTML.

    Compatibility wrapper for tests and older callers. The importer itself uses
    `_extract_text_blocks()` so non-prose blocks can bypass sentence splitting.
    """
    return [block.text for block in _extract_text_blocks(soup)]


def _passes_min_length(text: str) -> bool:
    return len(text) >= _MIN_PARA_LEN


def _clean_text(text: str) -> str:
    """Normalise whitespace in extracted HTML text."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_hash(sentence_text: str) -> str:
    return _sha256(normalize_for_hash(sentence_text).encode("utf-8"))


def _coerce_text_block(value: TextBlock | str) -> TextBlock:
    if isinstance(value, TextBlock):
        return value
    return TextBlock(str(value), _KIND_PROSE)


def _is_text_backed_block(block: TextBlock) -> bool:
    return block.kind in _TEXT_BACKED_BLOCK_KINDS


def _asset_base_dir_for_db(db: DatabaseConnection) -> Path:
    db_path = Path(getattr(db, "_db_path"))
    return db_path.parent / "assets"


def _insert_asset(
    conn,
    *,
    book_id: int,
    block: TextBlock,
    asset_sources: dict[str, EpubAssetSource],
    asset_cache: dict[str, int],
    staging_root: Path,
) -> int | None:
    if not block.asset_href:
        return None
    cached_id = asset_cache.get(block.asset_href)
    if cached_id is not None:
        return cached_id

    source = _lookup_asset_source(asset_sources, block.asset_href)
    is_missing = block.is_missing or source is None or source.is_missing
    media_type = block.media_type or (source.media_type if source else "")
    storage_path = ""
    digest = ""
    byte_size = 0

    if not is_missing:
        content = source.content if source else b""
        digest = _sha256(content)
        byte_size = len(content)
        storage_path = _stage_asset_file(
            staging_root,
            book_id=book_id,
            source_href=block.asset_href,
            media_type=media_type,
            content=content,
            digest=digest,
        )

    asset_id: int = conn.execute(
        """INSERT INTO book_assets
           (book_id, source_href, media_type, storage_path, sha256,
            byte_size, alt_text, is_missing)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            book_id,
            block.asset_href,
            media_type,
            storage_path,
            digest,
            byte_size,
            block.alt_text,
            1 if is_missing else 0,
        ),
    ).lastrowid
    asset_cache[block.asset_href] = asset_id
    return asset_id


def _stage_asset_file(
    staging_root: Path,
    *,
    book_id: int,
    source_href: str,
    media_type: str,
    content: bytes,
    digest: str,
) -> str:
    filename = _asset_filename(source_href, media_type, digest)
    storage_path = f"books/{book_id}/{filename}"
    target_path = staging_root / storage_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    return storage_path


def _asset_filename(source_href: str, media_type: str, digest: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(source_href).stem)
    stem = stem.strip(".-")[:48] or "asset"
    return f"{stem}-{digest[:12]}{_asset_extension(source_href, media_type)}"


def _asset_extension(source_href: str, media_type: str) -> str:
    suffix = Path(source_href).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    extension = mimetypes.guess_extension(media_type.split(";", 1)[0]) or ".bin"
    return ".jpg" if extension == ".jpe" else extension


def _move_staged_assets(
    staging_root: Path,
    asset_base_dir: Path,
    *,
    book_id: int,
) -> Path | None:
    staging_book_dir = staging_root / "books" / str(book_id)
    if not staging_book_dir.exists():
        return None

    final_book_dir = asset_base_dir / "books" / str(book_id)
    if final_book_dir.exists():
        raise FileExistsError(f"Asset directory already exists: {final_book_dir}")
    final_book_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging_book_dir), str(final_book_dir))
    return final_book_dir


def _insert(
    db: DatabaseConnection,
    title: str,
    author: str,
    language: str,
    file_hash: str,
    source_format: SourceFormat,
    chapters_raw: list[dict],
    asset_sources: dict[str, EpubAssetSource] | None = None,
) -> ImportResult:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    chapter_count = paragraph_count = sentence_count = 0
    global_sentence_idx = 0
    asset_sources = asset_sources or {}
    asset_base_dir = _asset_base_dir_for_db(db)
    staging_root = Path(tempfile.mkdtemp(prefix="epub-assets-"))
    final_book_dir: Path | None = None

    try:
        with db.get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM books WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            if existing:
                raise DuplicateBookError(
                    f"A book with file_hash={file_hash!r} already exists "
                    f"(id={existing['id']})"
                )

            book_id: int = conn.execute(
                """INSERT INTO books
                   (title, author, language, source_format, file_hash, imported_at,
                    total_chapters, total_sentences)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
                (title, author, language, source_format.value, file_hash, now),
            ).lastrowid
            asset_cache: dict[str, int] = {}

            for ch_idx, ch in enumerate(chapters_raw, start=1):
                ch_sentence_start = global_sentence_idx
                section_kind = ch.get("section_kind", _SECTION_CHAPTER)
                chapter_number = ch.get("chapter_number")

                chapter_id: int = conn.execute(
                    """INSERT INTO chapters
                       (book_id, idx, title, sentence_start, sentence_end,
                        section_kind, chapter_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        book_id,
                        ch_idx,
                        ch["title"],
                        ch_sentence_start,
                        ch_sentence_start,
                        section_kind,
                        chapter_number,
                    ),
                ).lastrowid
                if section_kind == _SECTION_CHAPTER:
                    chapter_count += 1

                paragraph_idx = 0
                blocks = ch.get("blocks", ch.get("paragraphs", []))
                for block_idx, raw_block in enumerate(blocks, start=1):
                    block = _coerce_text_block(raw_block)
                    paragraph_id: int | None = None

                    if _is_text_backed_block(block):
                        paragraph_idx += 1
                        par_start = global_sentence_idx
                        paragraph_id = conn.execute(
                            """INSERT INTO paragraphs
                               (chapter_id, idx, sentence_start, sentence_end)
                               VALUES (?, ?, ?, ?)""",
                            (chapter_id, paragraph_idx, par_start, par_start),
                        ).lastrowid
                        paragraph_count += 1

                        if block.kind == _KIND_PROSE:
                            sentence_rows = [
                                (sent.text, sent.char_start, sent.char_end)
                                for sent in segment_sentences(block.text)
                            ]
                        else:
                            sentence_rows = [(block.text, 0, len(block.text))]

                        for sentence_text, char_start, char_end in sentence_rows:
                            conn.execute(
                                """INSERT INTO sentences
                                   (book_id, chapter_id, paragraph_id, idx,
                                    text, text_hash,
                                    char_offset_start, char_offset_end)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    book_id,
                                    chapter_id,
                                    paragraph_id,
                                    global_sentence_idx,
                                    sentence_text,
                                    _text_hash(sentence_text),
                                    char_start,
                                    char_end,
                                ),
                            )
                            global_sentence_idx += 1
                            sentence_count += 1

                        conn.execute(
                            "UPDATE paragraphs SET sentence_end = ? WHERE id = ?",
                            (global_sentence_idx, paragraph_id),
                        )

                    asset_id = _insert_asset(
                        conn,
                        book_id=book_id,
                        block=block,
                        asset_sources=asset_sources,
                        asset_cache=asset_cache,
                        staging_root=staging_root,
                    )
                    conn.execute(
                        """INSERT INTO chapter_blocks
                           (book_id, chapter_id, idx, kind, paragraph_id,
                            asset_id, text, payload_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            book_id,
                            chapter_id,
                            block_idx,
                            block.kind,
                            paragraph_id,
                            asset_id,
                            "" if _is_text_backed_block(block) else block.text,
                            block.payload_json,
                        ),
                    )

                conn.execute(
                    "UPDATE chapters SET sentence_end = ? WHERE id = ?",
                    (global_sentence_idx, chapter_id),
                )

            conn.execute(
                "UPDATE books SET total_chapters = ?, total_sentences = ? WHERE id = ?",
                (chapter_count, sentence_count, book_id),
            )
            final_book_dir = _move_staged_assets(
                staging_root,
                asset_base_dir,
                book_id=book_id,
            )
    except Exception:
        if final_book_dir is not None and final_book_dir.exists():
            shutil.rmtree(final_book_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return ImportResult(
        book_id=book_id,
        chapter_count=chapter_count,
        paragraph_count=paragraph_count,
        sentence_count=sentence_count,
    )


def calculate_epub_file_hash(file_path: str | Path) -> str:
    """Return the duplicate-detection hash import_epub() will store."""
    with _prepare_epub_source(file_path) as prepared:
        return prepared.file_hash


def import_epub(
    db: DatabaseConnection,
    file_path: str | Path,
    title: str | None = None,
    author: str | None = None,
    language: str = "en",
) -> ImportResult:
    """
    Parse *file_path* (EPUB) and insert the full hierarchy into the DB.

    If *title* / *author* are None, values are extracted from EPUB metadata.

    Raises:
        FileNotFoundError: if the file does not exist.
        DuplicateBookError: if file_hash already exists in books table.
        ValueError: if the EPUB contains no usable text.
    """
    original_path = Path(file_path)
    with _prepare_epub_source(original_path) as prepared:
        book = epub.read_epub(str(prepared.path), options={"ignore_ncx": True})

        resolved_title = title or _extract_metadata(book, "title") or original_path.stem
        resolved_author = author or _extract_metadata(book, "creator") or ""

        toc_map = _build_toc_map(book)
        asset_sources = _build_asset_sources(book, prepared.missing_asset_hrefs)
        chapters_raw = _extract_chapters(
            book,
            toc_map,
            asset_sources,
            prepared.missing_asset_hrefs,
        )

        if not chapters_raw:
            raise ValueError(f"EPUB contains no usable text: {original_path}")

        return _insert(
            db,
            resolved_title,
            resolved_author,
            language,
            prepared.file_hash,
            SourceFormat.EPUB,
            chapters_raw,
            asset_sources,
        )
