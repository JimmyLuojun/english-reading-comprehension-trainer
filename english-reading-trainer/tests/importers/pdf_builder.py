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
