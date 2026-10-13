"""Importing a profile from JSON Resume and from a LinkedIn data export."""

import io
import shutil
import zipfile
from pathlib import Path

import pytest

from honest_cv import checklist, cli, importer
from honest_cv.model import load
from tests.conftest import ADA

RESUME = Path(__file__).parent / "fixtures" / "resume.json"

POSITIONS = """\
Company Name,Title,Description,Location,Started On,Finished On
Nimbus Freight,Platform Engineer,"• Moved 30 services to Kubernetes.
• Wrote the on-call runbook.",Bogotá,abr. 2022,
Nimbus Freight,Backend Engineer,Built the routing API.,Bogotá,Jan 2019,Mar 2022
"""


def linkedin_zip() -> bytes:
    files = {
        "Profile.csv": "First Name,Last Name,Headline,Summary,Geo Location,Websites\n"
                       "Lin,Example,Platform Engineer,I keep freight software running.,\"Bogotá, Colombia\","
                       "\"[PERSONAL:https://lin.example.com]\"\n",
        "Email Addresses.csv": "Email Address,Confirmed,Primary\nold@example.com,Yes,No\nlin@example.com,Yes,Yes\n",
        # Some exports put notes above the header.
        "Positions.csv": "Notes:\nThis file lists your positions.\n\n" + POSITIONS,
        "Education.csv": "School Name,Start Date,End Date,Notes,Degree Name,Activities\n"
                         "Universidad Ejemplo,2012,2017,,Ingeniería de Sistemas,\n",
        "Skills.csv": "Name\nKubernetes\nGo\nkubernetes\n",
        "Languages.csv": "Name,Proficiency\nEnglish,Professional working proficiency\n",
        "Certifications.csv": "Name,Url,Authority,Started On,Finished On,License Number\nCKA,,CNCF,,,\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(f"Basic_LinkedInDataExport/{name}", "﻿" + text)
    return buf.getvalue()


@pytest.mark.parametrize("raw, expected", [
    ("2016-03-01", "2016-03"), ("2016-3", "2016-03"), ("2016", "2016"), ("Mar 2016", "2016-03"),
    ("abr. 2022", "2022-04"), ("septiembre de 2019", "2019-09"), ("", None), ("Present", None),
])
def test_dates(raw, expected):
    assert importer.norm_date(raw) == expected


def test_json_resume_builds_a_new_profile(tmp_path):
    report = importer.merge(tmp_path / "p", importer.read(RESUME))
    source = load(tmp_path / "p")
    assert source.profile.contact.name == "Grace Sample"
    assert [(r.id, r.start, r.end) for r in source.profile.roles] == [
        ("imaginary_payments", "2021-04", None), ("sample_retail", "2017-02", "2021-03")
    ]
    # Highlights and list items in a summary become bullets, in the person's words.
    assert [b.text for b in source.bullets if b.role == "sample_retail"] == [
        "Built the inventory API in Python.", "Wrote the CI pipeline in GitHub Actions."
    ]
    assert all("imported" in b.tags for b in source.bullets)
    assert source.profile.languages == "Spanish (Native), English (C1)"
    assert "variants" in report.added and source.resolve("main").title == "Backend Engineer"


def test_skills_go_to_a_checklist_never_to_the_inventory(tmp_path):
    report = importer.merge(tmp_path / "p", importer.read(RESUME))
    assert load(tmp_path / "p").inventory.skills == []
    names = [i.name for i in checklist.read(report.skills_checklist).items]
    assert names == ["Python", "Kafka", "PostgreSQL"]  # "Backend" is a category, not a skill
    assert {i.mark for i in checklist.read(report.skills_checklist).items} == {""}


def test_linkedin_export(tmp_path):
    path = tmp_path / "export.zip"
    path.write_bytes(linkedin_zip())
    report = importer.merge(tmp_path / "p", importer.read(path))
    source = load(tmp_path / "p")
    c = source.profile.contact
    assert (c.name, c.email, c.location) == ("Lin Example", "lin@example.com", "Bogotá, Colombia")
    assert [(r.id, r.title, r.start, r.end) for r in source.profile.roles] == [
        ("nimbus_freight", "Platform Engineer", "2022-04", None),
        ("nimbus_freight_2019", "Backend Engineer", "2019-01", "2022-03"),
    ]
    assert [b.text for b in source.bullets if b.role == "nimbus_freight"] == [
        "Moved 30 services to Kubernetes.", "Wrote the on-call runbook."
    ]
    assert source.profile.certifications == ["CKA, CNCF"]
    assert [i.name for i in checklist.read(report.skills_checklist).items] == ["Kubernetes", "Go"]


def test_merge_into_an_existing_profile_only_adds(tmp_path):
    shutil.copytree(ADA, tmp_path / "ada")
    before = load(tmp_path / "ada")
    report = importer.merge(tmp_path / "ada", importer.read(RESUME))
    after = load(tmp_path / "ada")
    assert after.profile.contact.name == "Ada Example"  # never overwritten
    assert "name (kept yours)" in report.skipped["contact"]
    assert [r.id for r in after.profile.roles][:3] == ["imaginary_payments", "fintech", "sample_retail"]
    assert after.variants.keys() == before.variants.keys()  # no "main": Ada has variants
    assert after.inventory == before.inventory


def test_import_is_idempotent_and_keeps_a_marked_checklist(tmp_path):
    importer.merge(tmp_path / "p", importer.read(RESUME))
    marked = tmp_path / "p" / "imported-skills.md"
    marked.write_text(marked.read_text().replace("- [ ] Python", "- [P] Python — inventory API"))
    again = importer.merge(tmp_path / "p", importer.read(RESUME))
    assert "roles" not in again.added and again.skills_checklist_kept
    assert "[P] Python" in marked.read_text()


def test_dry_run_writes_nothing(tmp_path):
    report = importer.merge(tmp_path / "p", importer.read(RESUME), dry_run=True)
    assert report.added["roles"] and not (tmp_path / "p").exists()


def test_other_formats_are_refused(tmp_path):
    path = tmp_path / "cv.docx"
    path.write_bytes(b"x")
    with pytest.raises(ValueError, match="JSON Resume"):
        importer.read(path)


def test_cli_import(tmp_path, capsys):
    assert cli.main(["import", str(tmp_path / "p"), str(RESUME), "--dry-run"]) == 0
    assert "Would add:" in capsys.readouterr().out and not (tmp_path / "p").exists()
    assert cli.main(["import", str(tmp_path / "p"), str(RESUME)]) == 0
    assert cli.main(["build", str(tmp_path / "p"), "-o", str(tmp_path / "out")]) == 0


def test_checklist_with_extra_skills(ada):
    text = checklist.compose([], ada, extra=["Kubernetes", "Elixir"])
    items = {i.name: i for i in checklist.parse(text).items}
    assert items["Elixir"].section == "Found in your imported profile" and items["Elixir"].mark == ""
    assert items["Kubernetes"].mark == "P"  # prefilled from the inventory
