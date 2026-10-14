"""The person's own templates: any profession, with their own synonyms."""

import shutil
from pathlib import Path

import pytest

from honest_cv import checklist, letter
from honest_cv.model import TEMPLATES, load, synonym_line
from honest_cv.score import Keyword, Status, score_job
from tests.conftest import ADA

EXAMPLES = sorted((Path(__file__).parent.parent / "examples" / "checklists").glob("*.md"))
ACCOUNTING = """\
# Accounting
same: Certified Public Accountant = CPA = Contador Público
same: Service Level Objectives = SLOs
- [ ] SAP FI
- [ ] Month-end close
"""


@pytest.fixture
def profile(tmp_path):
    shutil.copytree(ADA, tmp_path / "ada")
    (tmp_path / "ada" / TEMPLATES).mkdir()
    (tmp_path / "ada" / TEMPLATES / "accounting.md").write_text(ACCOUNTING, encoding="utf-8")
    return tmp_path / "ada"


def test_synonym_lines():
    assert synonym_line("same: Work Breakdown Structure = WBS = EDT") == ["Work Breakdown Structure", "WBS", "EDT"]
    assert synonym_line("Same:  PMP =  ") is None  # one name is not a group
    assert synonym_line("- [ ] same: as above") is None


def test_own_synonyms_count_in_the_job_score(profile):
    keywords = [Keyword("Service Level Objectives")]
    before = score_job(load(ADA), keywords, "en", ["platform"])[0].keywords[0]
    after = score_job(load(profile), keywords, "en", ["platform"])[0].keywords[0]
    assert (before.status, after.status) == (Status.MISSING, Status.FOUND)


def test_letter_check_knows_the_persons_own_templates(profile):
    text = "I run the month-end close in SAP FI."
    assert letter.check_claims(text, load(ADA)).warnings == []  # not a technology it knew
    terms = {w.term for w in letter.check_claims(text, load(profile)).warnings}
    assert terms == {"SAP FI", "Month-end close"}


def test_two_names_from_own_synonyms_merge_in_a_checklist(profile):
    plan = checklist.plan(load(profile), checklist.parse("- [P] CPA — licensed 2015\n- [L] Contador Público\n"))
    # One skill, at the lower level, under that line's name: the same rule as the built-in synonyms.
    assert [(c.name, c.level.value) for c in plan.changes] == [("Contador Público", "L")]
    assert "using the lower" in plan.problems[0]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_templates_are_well_formed(path):
    # The same contract as the built-in checklists, so they can be copied as they are.
    text = path.read_text(encoding="utf-8")
    parsed = checklist.parse(text)
    assert text.startswith("# ") and parsed.problems == []
    assert any("★" in i.section for i in parsed.items) and {i.mark for i in parsed.items} == {""}
    groups = [g for line in text.splitlines() if (g := synonym_line(line))]
    assert groups, "an example shows how to declare synonyms"
    canonical = {n.casefold(): g[0] for g in groups for n in g}
    names = [canonical.get(i.name.casefold(), i.name) for i in parsed.items]
    assert names == [i.name for i in parsed.items], "use the main name of a synonym group"
    assert len({n.casefold() for n in names}) == len(names), "a skill is listed twice"
