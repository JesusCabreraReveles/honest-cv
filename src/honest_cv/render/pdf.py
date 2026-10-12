"""PDF rendering with Typst, plus `fit_pages` to meet a variant's page budget."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import typst
from pypdf import PdfReader

from honest_cv.document import Document

HERE = Path(__file__).parent
TEMPLATE = HERE / "templates" / "classic.typ"
FONTS = HERE / "fonts"


@dataclass(frozen=True)
class Density:
    size: float  # body size in pt
    leading: float  # space between lines, in em
    section_gap: float  # mm above a section heading or a role
    item_gap: float  # extra mm between bullets


# From most to least airy. The last level is the legibility floor.
# Spanish needs roughly 15% more space than English for the same content.
DENSITY = [
    Density(9.5, 0.55, 2.9, 0.60),
    Density(9.2, 0.50, 2.5, 0.50),
    Density(9.0, 0.46, 2.2, 0.45),
    Density(8.8, 0.42, 2.0, 0.40),
]

# A last page with only a few lines reads as filler, not depth.
MIN_TAIL_WORDS = 150


def render_pdf(doc: Document, density: Density = DENSITY[0]) -> bytes:
    return typst.compile(
        str(TEMPLATE),
        font_paths=[str(FONTS)],
        ignore_system_fonts=True,  # same output on every machine
        sys_inputs={
            "data": json.dumps(doc.to_dict(), ensure_ascii=False),
            "size": str(density.size),
            "leading": str(density.leading),
            "section_gap": str(density.section_gap),
            "item_gap": str(density.item_gap),
        },
    )


def page_stats(pdf: bytes) -> tuple[int, int]:
    """(page count, words on the last page)."""
    pages = PdfReader(io.BytesIO(pdf)).pages
    return len(pages), len(pages[-1].extract_text().split())


@dataclass
class FitResult:
    pdf: bytes
    pages: int
    level: int
    fits: bool


def fit_pages(doc: Document) -> FitResult:
    """Step down the density until the CV fits `doc.max_pages` without a near-empty
    last page. Content is never cut. If no level gives a clean result, keep the one
    with the fewest pages."""
    best: FitResult | None = None
    for level, density in enumerate(DENSITY):
        pdf = render_pdf(doc, density)
        pages, tail_words = page_stats(pdf)
        fits = pages <= doc.max_pages
        result = FitResult(pdf, pages, level, fits)
        if fits and (pages == 1 or tail_words >= MIN_TAIL_WORDS):
            return result
        if best is None or pages < best.pages:
            best = result
    return best
