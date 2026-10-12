import typst
import pytest

from honest_cv import document
from honest_cv.document import RoleEntry
from honest_cv.render.pdf import FONTS, render_pdf
from honest_cv.verify import verify_pdf


def failed(report):
    return {c.name for c in report.failures}


@pytest.mark.parametrize("lang", ["en", "es"])
def test_example_passes_every_check(ada, lang):
    doc = document.build(ada, "backend", lang)
    report = verify_pdf(render_pdf(doc), max_pages=1, doc=doc)
    assert report.ok, report.failures
    assert {c.name for c in report.checks} >= {
        "text_extractable", "no_ligatures", "single_column", "fonts_embedded", "no_images",
        "page_count", "bullets_extracted", "role_dates_inline", "reading_order", "familiarity_labeled",
    }


def compile_typst(tmp_path, body: str, ligatures: bool = False) -> bytes:
    src = tmp_path / "t.typ"
    src.write_text(f'#set page(paper: "us-letter")\n#set text(font: "Carlito", ligatures: {str(ligatures).lower()})\n{body}', encoding="utf-8")
    return typst.compile(str(src), font_paths=[str(FONTS)], ignore_system_fonts=True)


FILLER = "Backend engineer building reliable payment systems with Java and Kafka. " * 6


def test_right_aligned_dates_are_flagged(tmp_path):
    pdf = compile_typst(tmp_path, f"{FILLER}\n\n*Staff Engineer — Example* #h(1fr) 2020 – 2024\n")
    report = verify_pdf(pdf)
    assert "single_column" in failed(report)


def test_two_columns_are_flagged(tmp_path):
    pdf = compile_typst(tmp_path, f"#columns(2)[{FILLER} #colbreak() Skills: Java, Kafka, Kubernetes]")
    assert "single_column" in failed(verify_pdf(pdf))


def test_page_count_over_budget(tmp_path):
    pdf = compile_typst(tmp_path, FILLER + "\n#pagebreak()\n" + FILLER)
    assert "page_count" in failed(verify_pdf(pdf, max_pages=1))
    assert verify_pdf(pdf, max_pages=2).ok


def test_image_only_pdf_is_flagged(tmp_path):
    pdf = compile_typst(tmp_path, '#rect(width: 5cm, height: 5cm, fill: black)')
    assert "text_extractable" in failed(verify_pdf(pdf))


def test_detached_role_date_is_flagged(ada):
    doc = document.build(ada, "backend", "en")
    pdf = render_pdf(doc)
    doc.roles[0] = RoleEntry(doc.roles[0].heading, "1999 – 2001", None, doc.roles[0].bullets)
    assert "role_dates_inline" in failed(verify_pdf(pdf, doc=doc))


def test_missing_bullet_is_flagged(ada):
    doc = document.build(ada, "backend", "en")
    pdf = render_pdf(doc)
    doc.impact.append("A bullet that was never rendered.")
    assert "bullets_extracted" in failed(verify_pdf(pdf, doc=doc))


def test_unlabeled_familiarity_skill_is_flagged(ada):
    doc = document.build(ada, "backend", "en")
    doc.skills[0].skills.append("Rust")  # an F skill smuggled into a normal line
    pdf = render_pdf(doc)
    assert "familiarity_labeled" in failed(verify_pdf(pdf, doc=doc))
