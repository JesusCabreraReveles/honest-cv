"""Exporting a variant as JSON Resume."""

import json

import pytest

from honest_cv import cli, export, importer
from honest_cv.model import load


@pytest.fixture
def resume(ada):
    return export.json_resume(ada, "backend", "en")


def test_x_never_appears_and_f_is_labeled(resume):
    groups = {g["name"]: g for g in resume["skills"]}
    assert "Scala" not in json.dumps(resume)
    assert groups["Familiarity"] == {"name": "Familiarity", "level": "Familiarity", "keywords": ["Rust"]}
    assert all("level" not in g for name, g in groups.items() if name != "Familiarity")


def test_the_variant_picks_roles_and_bullets(ada, resume):
    v = ada.resolve("backend")
    assert [w["name"] for w in resume["work"]] == [r.company for r in ada.profile.roles if v.roles.get(r.id)]
    assert sum(len(w["highlights"]) for w in resume["work"]) == sum(len(ids) for ids in v.roles.values())


def test_basics(resume):
    b = resume["basics"]
    assert (b["name"], b["label"]) == ("Ada Example", "Senior Backend Engineer")
    # The schema wants URIs.
    assert {p["network"]: p["url"] for p in b["profiles"]} == {
        "LinkedIn": "https://linkedin.com/in/ada-example", "GitHub": "https://github.com/ada-example"
    }


def test_languages_are_split(ada):
    assert export.json_resume(ada, "backend", "es")["languages"] == [
        {"language": "Español", "fluency": "nativo"}, {"language": "inglés", "fluency": "C1"}
    ]


@pytest.mark.parametrize("lang", ["en", "es"])
def test_importing_the_export_gives_the_same_profile(ada, lang, tmp_path):
    path = export.export(ada, "backend", lang, tmp_path / "out")
    importer.merge(tmp_path / "p", importer.read(path))
    back = load(tmp_path / "p")
    v = ada.resolve("backend")

    def text(t):
        return t if isinstance(t, str) else t[lang]

    exported = [r for r in ada.profile.roles if v.roles.get(r.id)]
    assert [(r.company, text(r.title), r.start, r.end) for r in back.profile.roles] == [
        (r.company, text(r.title), r.start, r.end) for r in exported
    ]
    assert sorted(text(b.text) for b in back.bullets) == sorted(
        text(ada.bullet(b).text) for ids in v.roles.values() for b in ids
    )
    c, d = back.profile.contact, ada.profile.contact
    assert (c.name, c.email, c.phone) == (d.name, d.email, d.phone)
    assert [text(e.degree) for e in back.profile.education] == [text(e.degree) for e in ada.profile.education]
    assert back.profile.certifications == [text(x) for x in ada.profile.certifications]


def test_cli_export(tmp_path, capsys):
    assert cli.main(["export", "examples/ada", "-v", "platform", "-l", "es", "-o", str(tmp_path)]) == 0
    path = tmp_path / "Ada_Example_CV_platform_ES.resume.json"
    assert str(path) in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))["meta"]["variant"] == "platform"
