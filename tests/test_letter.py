"""Cover letters: the honesty check on the text, and the rendered files."""

import io
from datetime import date

import pytest
from pdfminer.high_level import extract_text

from honest_cv import cli, letter


def kinds(claims):
    return {(f.kind, f.term) for f in claims.problems}, {(f.kind, f.term) for f in claims.warnings}


def test_x_skill_is_a_problem(ada):
    problems, _ = kinds(letter.check_claims("I have built services in Scala for years.", ada))
    assert problems == {("not_held", "Scala")}


@pytest.mark.parametrize("text", [
    "I write Rust in production every day.",
    "Uso Rust a diario en producción.",
])
def test_familiarity_as_experience_is_a_problem(ada, text):
    problems, _ = kinds(letter.check_claims(text, ada))
    assert problems == {("familiarity_as_experience", "Rust")}


@pytest.mark.parametrize("text", [
    "I am also familiar with Rust from personal study.",
    "Tengo nociones de Rust y sigo aprendiendo.",
    "Tengo familiaridad con Rust.",
])
def test_familiarity_said_as_such_is_fine(ada, text):
    assert letter.check_claims(text, ada).ok


def test_held_skills_and_bullet_pool_are_fine(ada):
    # Kubernetes and AWS are P; CI/CD is in no skill but Ada's bullets show it.
    claims = letter.check_claims("I led a 40-service migration to Kubernetes on AWS and rebuilt CI/CD.", ada)
    assert claims.ok and claims.warnings == []


def test_unknown_technology_and_number_are_warnings(ada):
    problems, warnings = kinds(letter.check_claims("I cut costs by 73% with Terraform.", ada))
    assert problems == set()
    assert warnings == {("not_in_inventory", "Terraform"), ("number_not_in_profile", "73%")}


# Found drafting a real letter.


def test_a_name_inside_a_longer_one_is_not_a_mention(ada):
    # "Spring" is a synonym of Spring Framework; here it is part of "Spring Boot", which Ada has.
    claims = letter.check_claims("I have production experience with Java and Spring Boot.", ada)
    assert claims.ok and claims.warnings == []


def test_every_mention_of_a_familiarity_skill_is_checked(ada):
    text = "I am familiar with Rust from personal study. Last year I shipped two Rust services."
    problems = letter.check_claims(text, ada).problems
    assert [(p.kind, p.sentence) for p in problems] == [
        ("familiarity_as_experience", "Last year I shipped two Rust services.")
    ]


def test_practices_are_not_technologies(ada):
    assert letter.check_claims("I enjoy mentoring and hiring, and I care about code review.", ada).warnings == []


def test_other_professions_are_not_technologies(ada):
    # Built-in templates for sales, finance or HR don't turn ordinary words into claims.
    text = "I led negotiation with vendors, owned budgeting and onboarding, and ran user research."
    assert letter.check_claims(text, ada).warnings == []
    # The technical ones still do.
    _, warnings = kinds(letter.check_claims("I shipped apps in Flutter.", ada))
    assert ("not_in_inventory", "Flutter") in warnings


def test_job_keywords_are_checked_too(ada):
    _, warnings = kinds(letter.check_claims("I have run OpenStack clusters.", ada, keywords=["OpenStack"]))
    assert ("not_in_inventory", "OpenStack") in warnings


def test_dates_do_not_follow_the_system_locale(ada):
    when = date(2026, 3, 5)
    assert letter.make(ada, "en", "Acme", "SRE", ["Hi."], when=when).date == "March 5, 2026"
    assert letter.make(ada, "es", "Acme", "SRE", ["Hola."], when=when).date == "5 de marzo de 2026"


def test_a_letter_needs_paragraphs(ada):
    with pytest.raises(ValueError, match="no paragraphs"):
        letter.make(ada, "en", "Acme", "SRE", ["  ", ""])


PARAGRAPHS = [
    "I am applying for the Platform Engineer role at Acme Cloud, whose work on payments matches mine.",
    "At Fictional Fintech I led a 40-service migration to Kubernetes on AWS, moving from UDP to TCP, "
    "then to HTTP/2, with CI/CD rebuilt on GitHub Actions.",
    "Costs $5 #set text(red) *bold* _x_ @ref <label> = heading // c",
]


@pytest.mark.parametrize("lang", ["en", "es"])
def test_rendered_letter_passes_the_ats_checks(ada, lang, tmp_path):
    draft = letter.make(ada, lang, "Acme Cloud", "Platform Engineer", PARAGRAPHS, recipient="Dana Lee")
    built = letter.build(draft, tmp_path)
    pdf = next(b for b in built if b.format == "pdf")
    assert pdf.report.ok, pdf.report.failures
    text = extract_text(io.BytesIO(pdf.path.read_bytes()))
    assert PARAGRAPHS[2] in text  # markup in the text stays literal
    assert {b.format for b in built} == {"pdf", "docx"}
    assert pdf.path.name == f"Ada_Example_Cover_Letter_Acme_Cloud_{lang.upper()}.pdf"


def test_cli_check_and_build(tmp_path):
    from tests.conftest import ADA as ada_path

    path = tmp_path / "letter.txt"
    path.write_text("I am applying.\n\nI have used Scala daily.\n", encoding="utf-8")
    assert cli.main(["letter", "check", str(ada_path), str(path)]) == 1
    assert cli.main(["letter", "build", str(ada_path), str(path), "--company", "Acme", "--role", "SRE",
                     "-o", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()
    path.write_text("I am applying.\n\nI led a migration to Kubernetes.\n", encoding="utf-8")
    assert cli.main(["letter", "build", str(ada_path), str(path), "--company", "Acme", "--role", "SRE",
                     "-o", str(tmp_path / "out")]) == 0
    assert len(list((tmp_path / "out").iterdir())) == 2
