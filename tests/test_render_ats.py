"""ATS invariants, checked on every build of the example profile."""

import io
import re

import pytest
from docx import Document as DocxDocument
from pdfminer.high_level import extract_text
from pypdf import PdfReader

from honest_cv import document
from honest_cv.build import build_cv
from honest_cv.render.docx import render_docx
from honest_cv.render.pdf import DENSITY, fit_pages, page_stats, render_pdf

LIGATURES = re.compile("[ﬀ-ﬆ]")
CASES = [(v, l) for v in ("backend", "platform") for l in ("en", "es")]


@pytest.fixture(scope="module")
def pdfs():
    from honest_cv.model import load
    from tests.conftest import ADA

    source = load(ADA)
    return {(v, l): (document.build(source, v, l), render_pdf(document.build(source, v, l))) for v, l in CASES}


@pytest.mark.parametrize("case", CASES)
def test_text_extractable_without_ligatures(pdfs, case):
    doc, pdf = pdfs[case]
    a = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    b = extract_text(io.BytesIO(pdf))
    for text in (a, b):
        assert doc.name in text
        assert not LIGATURES.search(text)
        assert "­" not in text  # no soft hyphens
        for bullet in doc.impact + [b for r in doc.roles for b in r.bullets]:
            assert " ".join(bullet.split()) in " ".join(text.split())


@pytest.mark.parametrize("case", CASES)
def test_role_heading_keeps_its_dates_in_pdfminer(pdfs, case):
    doc, pdf = pdfs[case]
    lines = extract_text(io.BytesIO(pdf)).splitlines()
    for role in doc.roles:
        assert f"{role.heading} · {role.dates}" in lines


@pytest.mark.parametrize("case", CASES)
def test_reading_order_follows_source(pdfs, case):
    doc, pdf = pdfs[case]
    text = extract_text(io.BytesIO(pdf))
    h = doc.headings
    anchors = [doc.name, h["summary"], h["impact"], h["experience"], *(r.heading for r in doc.roles), h["skills"], h["education"]]
    positions = [text.index(a) for a in anchors]
    assert positions == sorted(positions)


def test_only_bundled_fonts_embedded(pdfs):
    _, pdf = pdfs[("backend", "en")]
    reader = PdfReader(io.BytesIO(pdf))
    fonts = {str(f.get_object()["/BaseFont"]).split("+")[-1] for p in reader.pages for f in p["/Resources"]["/Font"].values()}
    assert fonts and all(f.startswith("Carlito") for f in fonts)


def test_no_images_in_pdf(pdfs):
    _, pdf = pdfs[("backend", "en")]
    assert all(not p.images for p in PdfReader(io.BytesIO(pdf)).pages)


def test_markup_in_user_text_is_literal(ada):
    doc = document.build(ada, "backend", "en")
    nasty = 'Costs $5 #set text(red) *bold* _x_ @ref <label> = heading // c'
    doc.summary = nasty
    text = extract_text(io.BytesIO(render_pdf(doc)))
    assert nasty in text


def test_fit_pages_steps_down_density(ada):
    doc = document.build(ada, "backend", "en")
    doc.max_pages = 1
    filler = doc.roles[0].bullets[0]
    # Grow the CV until the airiest density spills to a second page.
    for n in range(10, 120):
        doc.roles[0].bullets = [filler] * n
        airy, _ = page_stats(render_pdf(doc, DENSITY[0]))
        if airy > 1:
            break
    tight, _ = page_stats(render_pdf(doc, DENSITY[-1]))
    assert airy == 2 and tight == 1
    result = fit_pages(doc)
    assert result.level > 0 and result.pages == 1 and result.fits


def test_fit_pages_reports_overflow(ada):
    doc = document.build(ada, "backend", "en")
    doc.roles[0].bullets = [doc.roles[0].bullets[0]] * 150
    doc.max_pages = 1
    result = fit_pages(doc)
    assert not result.fits and result.pages > 1


def test_docx_is_single_column_without_tables_images_or_header(ada):
    for lang in ("en", "es"):
        d = DocxDocument(io.BytesIO(render_docx(document.build(ada, "backend", lang))))
        assert not d.tables
        assert not d.inline_shapes
        for s in d.sections:
            assert all(not p.text.strip() for p in s.header.paragraphs)
            assert all(not p.text.strip() for p in s.footer.paragraphs)


def test_build_cv_writes_files(ada, tmp_path):
    built = build_cv(ada, "backend", "es", tmp_path)
    assert [b.path.name for b in built] == ["Ada_Example_CV_backend_ES.pdf", "Ada_Example_CV_backend_ES.docx"]
    assert built[0].pages == 1 and built[0].fits
