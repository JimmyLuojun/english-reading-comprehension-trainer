"""Small reportlab PDF fixtures for importer and web tests."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def make_text_pdf(
    tmp_path: Path,
    name: str = "sample.pdf",
    *,
    title: str = "PDF Book",
    author: str = "PDF Author",
    pages: list[list[str]] | None = None,
    header: str = "",
    footer: str = "",
) -> Path:
    """Create a PDF containing selectable text."""
    path = tmp_path / name
    page_lines = pages or [
        [
            "The first PDF sentence is readable.",
            "The second PDF sentence is useful for training.",
        ]
    ]
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle(title)
    pdf.setAuthor(author)
    width, height = letter

    for lines in page_lines:
        pdf.setFont("Helvetica", 10)
        if header:
            pdf.drawString(72, height - 30, header)
        if footer:
            pdf.drawString(72, 24, footer)
        pdf.setFont("Helvetica", 12)
        y = height - 96
        for line in lines:
            pdf.drawString(72, y, line)
            y -= 18
        pdf.showPage()

    pdf.save()
    return path


def make_chapter_heading_pdf(
    tmp_path: Path,
    name: str = "chapter-headings.pdf",
    *,
    sections: list[dict[str, list[str] | str]],
    title: str = "Chaptered PDF Book",
    author: str = "PDF Author",
) -> Path:
    """Create a PDF whose pages start with Part/Chapter style headings."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle(title)
    pdf.setAuthor(author)
    _width, height = letter

    for section in sections:
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(72, height - 96, str(section["heading"]))
        pdf.setFont("Helvetica", 12)
        y = height - 150
        for line in section.get("body", []):
            pdf.drawString(72, y, str(line))
            y -= 18
        pdf.showPage()

    pdf.save()
    return path


def make_outline_chapter_pdf(tmp_path: Path, name: str = "outline-chapters.pdf") -> Path:
    """Create a PDF with bookmark chapters and misleading TOC-like text."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle("Outline PDF Book")
    pdf.setAuthor("PDF Author")
    _width, height = letter

    pdf.bookmarkPage("contents")
    pdf.addOutlineEntry("Contents", "contents", level=0)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, height - 96, "Contents")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 132, "10 Fake TOC Entry 500")
    pdf.drawString(72, height - 150, "11 Another Fake TOC Entry 520")
    pdf.drawString(72, height - 190, "The contents page should remain frontmatter.")
    pdf.showPage()

    pdf.bookmarkPage("chapter-1")
    pdf.addOutlineEntry("Ch 1: Real Beginning", "chapter-1", level=0)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(72, height - 96, "1")
    pdf.drawString(72, height - 132, "Real Beginning")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 190, "The first outline chapter sentence is readable.")
    pdf.showPage()

    pdf.bookmarkPage("chapter-2")
    pdf.addOutlineEntry("Ch 2: Second Topic", "chapter-2", level=0)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(72, height - 96, "2")
    pdf.drawString(72, height - 132, "Second Topic")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 190, "The second outline chapter sentence is readable.")
    pdf.showPage()

    pdf.bookmarkPage("answers")
    pdf.addOutlineEntry("Answers to Selected Exercises", "answers", level=0)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, height - 96, "Answers to Selected Exercises")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 150, "The answers page should be backmatter.")
    pdf.showPage()

    pdf.save()
    return path


def make_empty_pdf(tmp_path: Path, name: str = "empty.pdf") -> Path:
    """Create a PDF page with no extractable text."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.rect(72, 500, 120, 80, stroke=1, fill=0)
    pdf.showPage()
    pdf.save()
    return path


def make_vector_figure_pdf(tmp_path: Path, name: str = "vector-figure.pdf") -> Path:
    """Create a PDF with a vector diagram and selectable labels."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter

    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 96, "Before the diagram sentence remains readable.")

    pdf.rect(180, 450, 250, 120, stroke=1, fill=0)
    pdf.rect(205, 510, 70, 35, stroke=1, fill=0)
    pdf.rect(335, 510, 70, 35, stroke=1, fill=0)
    pdf.line(275, 528, 335, 528)
    pdf.line(320, 532, 335, 528)
    pdf.line(320, 524, 335, 528)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(210, 525, "Hash Label")
    pdf.drawString(343, 525, "Block Label")

    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 390, "After the diagram sentence remains readable.")
    pdf.showPage()
    pdf.save()
    return path


def make_nonprose_text_pdf(tmp_path: Path, name: str = "nonprose-text.pdf") -> Path:
    """Create a PDF with math/code text that should render as figures."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    _width, height = letter

    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 96, "Before the formula sentence remains readable.")

    pdf.setFont("Helvetica", 11)
    pdf.drawString(120, height - 150, "p = z * (q / p) <= 1.0")

    pdf.setFont("Courier", 8)
    y = height - 210
    for line in [
        "#include <math.h>",
        "double AttackerSuccessProbability(double q, int z)",
        "{",
        "    double p = 1.0 - q;",
        "    return p;",
        "}",
    ]:
        pdf.drawString(120, y, line)
        y -= 10

    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 315, "After the code sentence remains readable.")
    pdf.showPage()
    pdf.save()
    return path


def make_logic_proof_pdf(tmp_path: Path, name: str = "logic-proof.pdf") -> Path:
    """Create a PDF with a numbered logic proof that should render as one figure."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    _width, height = letter

    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 96, "Before the proof sentence remains readable.")

    pdf.setFillColorRGB(0.72, 0.08, 0.04)
    pdf.setFont("Helvetica", 11)
    y = height - 150
    for line in [
        "1. A -> B",
        "2. B",
        "3. A 1, 2, MP (invalid-line 2 must assert the antecedent)",
    ]:
        pdf.drawString(120, y, line)
        y -= 14

    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 235, "After the proof sentence remains readable.")
    pdf.showPage()
    pdf.save()
    return path


def make_margin_decoration_pdf(
    tmp_path: Path,
    name: str = "margin-decoration.pdf",
) -> Path:
    """Create a PDF with a decorative margin chapter box beside readable text."""
    path = tmp_path / name
    pdf = canvas.Canvas(str(path), pagesize=letter)
    _width, height = letter

    pdf.setFillColorRGB(0.30, 0.18, 0.45)
    pdf.rect(18, height - 330, 60, 45, stroke=0, fill=1)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(46, height - 318, "7")

    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(140, height - 300, "The body sentence beside the margin art remains readable.")
    pdf.showPage()
    pdf.save()
    return path
