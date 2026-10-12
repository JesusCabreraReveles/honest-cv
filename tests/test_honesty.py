"""Each honesty rule from CLAUDE.md has a test here."""

import io

import pytest
from docx import Document as DocxDocument
from pypdf import PdfReader

from honest_cv import document
from honest_cv.model import Level, Skill, SkillUpgradeError, set_skill_level
from honest_cv.render.docx import render_docx
from honest_cv.render.pdf import render_pdf


def rendered_texts(source, variant, lang):
    doc = document.build(source, variant, lang)
    pdf = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(render_pdf(doc))).pages)
    docx = "\n".join(p.text for p in DocxDocument(io.BytesIO(render_docx(doc))).paragraphs)
    return doc, pdf, docx


@pytest.mark.parametrize("lang", ["en", "es"])
def test_x_skill_is_never_rendered(ada, lang):
    assert ada.inventory.get("Scala").level is Level.NONE
    doc, pdf, docx = rendered_texts(ada, "backend", lang)
    for text in (pdf, docx, str(doc.skills)):
        assert "Scala" not in text


@pytest.mark.parametrize("lang,label", [("en", "Familiarity"), ("es", "Familiaridad")])
def test_f_skill_only_under_familiarity_label(ada, lang, label):
    doc, pdf, docx = rendered_texts(ada, "backend", lang)
    rust_lines = [s for s in doc.skills if "Rust" in s.skills]
    assert [s.label for s in rust_lines] == [label]
    for text in (pdf, docx):
        lines = [line for line in text.splitlines() if "Rust" in line]
        assert lines and all(line.startswith(f"{label}:") for line in lines)


def test_familiarity_line_only_holds_f_skills(ada):
    doc = document.build(ada, "backend", "en")
    familiar = next(s for s in doc.skills if s.label == "Familiarity")
    assert all(ada.inventory.get(n).level is Level.FAMILIARITY for n in familiar.skills)


def test_upgrade_requires_evidence():
    skill = Skill(name="Rust", level=Level.FAMILIARITY)
    with pytest.raises(SkillUpgradeError, match="requires evidence"):
        set_skill_level(skill, Level.PRODUCTION, evidence=None, confirmed=True)
    with pytest.raises(SkillUpgradeError, match="requires evidence"):
        set_skill_level(skill, Level.LAB, evidence="   ", confirmed=True)


def test_upgrade_requires_human_confirmation():
    skill = Skill(name="Rust", level=Level.FAMILIARITY)
    with pytest.raises(SkillUpgradeError, match="requires human confirmation"):
        set_skill_level(skill, Level.LAB, evidence="CLI tool on GitHub", confirmed=False)


def test_upgrade_with_evidence_and_confirmation():
    skill = Skill(name="Rust", level=Level.NONE)
    up = set_skill_level(skill, Level.LAB, evidence="CLI tool on GitHub", confirmed=True)
    assert up.level is Level.LAB and up.evidence == "CLI tool on GitHub"
    assert skill.level is Level.NONE  # original untouched


def test_downgrade_needs_nothing():
    skill = Skill(name="Java", level=Level.PRODUCTION, evidence="Payments API")
    down = set_skill_level(skill, Level.FAMILIARITY, evidence=None, confirmed=False)
    assert down.level is Level.FAMILIARITY and down.evidence == "Payments API"
