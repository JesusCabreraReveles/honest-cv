"""ATS checks on a rendered PDF.

Generic checks work on any PDF. When the source `Document` is given, content
checks also confirm that what an ATS extracts matches what was meant to be sent,
including the honesty rules.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTTextContainer, LTTextLine
from pypdf import PdfReader

from honest_cv.document import FAMILIARITY, Document

LIGATURES = re.compile(r"[ﬀ-ﬆ]")
MIN_TEXT_CHARS = 200
MIN_EXTRACTOR_AGREEMENT = 0.95
# Two text lines on the same row further apart than this (pt) mean a second column
# or a right-aligned field, which parsers split into separate blocks.
ROW_GAP_PT = 24


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    pages: int
    text: str  # as extracted by pdfminer
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


def verify_pdf(
    pdf: bytes | str | Path, *, max_pages: int | None = None, doc: Document | None = None
) -> Report:
    data = Path(pdf).read_bytes() if isinstance(pdf, (str, Path)) else pdf
    reader = PdfReader(io.BytesIO(data))
    pypdf_text = "\n".join(p.extract_text() or "" for p in reader.pages)
    miner_text = extract_text(io.BytesIO(data))
    report = Report(pages=len(reader.pages), text=miner_text)
    add = report.checks.append

    short = [n for n, t in (("pypdf", pypdf_text), ("pdfminer", miner_text)) if len(t.strip()) < MIN_TEXT_CHARS]
    add(Check("text_extractable", not short, f"too little text from {', '.join(short)}" if short else ""))

    a, b = _words(pypdf_text), _words(miner_text)
    agreement = len(a & b) / max(len(a | b), 1)
    add(Check("extractors_agree", agreement >= MIN_EXTRACTOR_AGREEMENT, f"{agreement:.0%} shared words"))

    found = sorted(set(LIGATURES.findall(pypdf_text + miner_text)))
    add(Check("no_ligatures", not found, " ".join(found)))

    add(Check("no_soft_hyphens", "­" not in pypdf_text + miner_text))

    images = sum(len(p.images) for p in reader.pages)
    add(Check("no_images", images == 0, f"{images} image(s)" if images else ""))

    missing = _unembedded_fonts(reader)
    add(Check("fonts_embedded", not missing, ", ".join(missing)))

    split = _split_rows(data)
    add(Check("single_column", not split, "; ".join(split[:3])))

    if max_pages is not None:
        add(Check("page_count", report.pages <= max_pages, f"{report.pages} of max {max_pages}"))

    if doc is not None:
        _content_checks(doc, pypdf_text, miner_text, add)
    return report


def _unembedded_fonts(reader: PdfReader) -> list[str]:
    missing = set()
    for page in reader.pages:
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        for ref in fonts.values():
            font = ref.get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None and "/DescendantFonts" in font:
                descriptor = font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            if descriptor is None:
                missing.add(str(font.get("/BaseFont")))
                continue
            descriptor = descriptor.get_object()
            if not any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                missing.add(str(font.get("/BaseFont")))
    return sorted(missing)


def _split_rows(data: bytes) -> list[str]:
    """Rows where pdfminer sees two text lines side by side with a wide gap."""
    issues = []
    for n, page in enumerate(extract_pages(io.BytesIO(data)), start=1):
        lines = [
            line
            for box in page
            if isinstance(box, LTTextContainer)
            for line in box
            if isinstance(line, LTTextLine) and line.get_text().strip()
        ]
        for i, x in enumerate(lines):
            for y in lines[i + 1 :]:
                overlap = min(x.y1, y.y1) - max(x.y0, y.y0)
                if overlap < 0.5 * min(x.height, y.height):
                    continue
                left, right = (x, y) if x.x0 <= y.x0 else (y, x)
                if right.x0 - left.x1 > ROW_GAP_PT:
                    issues.append(
                        f"page {n}: '{_flat(left.get_text())[:40]}' | '{_flat(right.get_text())[:40]}'"
                    )
    return issues


def _content_checks(doc: Document, pypdf_text: str, miner_text: str, add) -> None:
    flat_a, flat_b = _flat(pypdf_text), _flat(miner_text)

    expected = doc.impact + [b for r in doc.roles for b in r.bullets]
    lost = [b for b in expected if _flat(b) not in flat_a or _flat(b) not in flat_b]
    add(Check("bullets_extracted", not lost, "; ".join(x[:50] for x in lost[:3])))

    miner_lines = [_flat(line) for line in miner_text.splitlines()]
    detached = [r.heading for r in doc.roles if _flat(f"{r.heading} · {r.dates}") not in miner_lines]
    add(Check("role_dates_inline", not detached, "; ".join(detached)))

    h = doc.headings
    anchors = [doc.name, h["summary"]]
    anchors += [h["impact"]] if doc.impact else []
    anchors += [h["experience"], *(r.heading for r in doc.roles)] if doc.roles else []
    anchors += [h["skills"]] if doc.skills else []
    positions = [flat_b.find(_flat(a)) for a in anchors]
    in_order = -1 not in positions and positions == sorted(positions)
    add(Check("reading_order", in_order, "" if in_order else "sections out of order or missing"))

    label = FAMILIARITY[doc.lang]
    familiar = next((s.skills for s in doc.skills if s.label == label), [])
    lines = [_flat(line) for line in pypdf_text.splitlines()]
    skills_lines = [l for l in lines if any(l.startswith(f"{s.label}:") for s in doc.skills)]
    misplaced = [
        name
        for name in familiar
        for line in skills_lines
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", line) and not line.startswith(f"{label}:")
    ]
    add(Check("familiarity_labeled", not misplaced, ", ".join(misplaced)))
