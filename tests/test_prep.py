"""Interview prep: what backs each keyword of a post, for one logged application."""

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from honest_cv import applications, cli, prep
from honest_cv.model import load
from honest_cv.score import Keyword
from honest_cv.server import mcp as server

ADA = Path(__file__).parent.parent / "examples" / "ada"
POST = "Platform engineer. Kafka, Redis, Rust, Scala, Terraform and Scrum."


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def profile(tmp_path):
    shutil.copytree(ADA, tmp_path / "ada")
    folder = tmp_path / "ada"
    applications.log(folder, "Acme", "SRE", status="interview", variant="platform", lang="en", post=POST)
    (folder / "checklist.md").write_text("- [P] Scrum\n", encoding="utf-8")
    return folder


def test_each_keyword_gets_its_standing_and_its_stories(profile):
    source = load(profile)
    app = prep.find(profile, "acme_sre")
    points = {p.keyword: p for p in prep.points(source, app, [Keyword(k) for k in
              ("Kafka", "Redis", "Rust", "Scala", "Terraform", "Scrum")])}
    assert {k: p.standing for k, p in points.items()} == {
        "Kafka": "strong", "Redis": "no_achievement", "Rust": "familiarity",
        "Scala": "lacking", "Terraform": "lacking", "Scrum": "marked_pending"}
    kafka = points["Kafka"]
    assert kafka.level == "P" and kafka.evidence and kafka.stories
    # What the CV that was sent shows comes first: the interviewer has it in front of them.
    assert [s.in_cv for s in kafka.stories] == sorted((s.in_cv for s in kafka.stories), reverse=True)
    assert all("Kafka" in s.text for s in kafka.stories)


def test_unknown_application(profile):
    with pytest.raises(ValueError, match="unknown application 'nope'; known: acme_sre"):
        prep.find(profile, "nope")


@pytest.mark.anyio
async def test_tool_returns_the_post_then_the_points_and_saves_the_notes(profile):
    async with Client(server) as c:
        r = await c.call_tool("interview_prep", {"application": "acme_sre", "profile": str(profile)})
        first = json.loads(r.content[0].text)
        assert first["post_text"].strip() == POST and first["points"] == [] and first["notes_file"] is None
        r = await c.call_tool("interview_prep", {"application": "acme_sre", "profile": str(profile),
                                                 "keywords": ["Kafka"], "preferred": ["Scala"],
                                                 "notes": "# Acme\n\n- Kafka: the reconciliation story."})
        out = json.loads(r.content[0].text)
        assert out["by_standing"]["strong"] == ["Kafka"] and out["by_standing"]["lacking"] == ["Scala"]
        assert Path(out["notes_file"]) == profile / "prep" / "acme_sre.md"
        assert (profile / "prep" / "acme_sre.md").read_text(encoding="utf-8").startswith("# Acme")
        r = await c.call_tool("interview_prep", {"application": "acme_sre", "profile": str(profile)})
        assert json.loads(r.content[0].text)["notes_file"] == out["notes_file"]
        r = await c.call_tool("interview_prep", {"application": "nope", "profile": str(profile)})
        assert r.is_error and "unknown application" in r.content[0].text


def test_cli(profile, capsys):
    assert cli.main(["apps", "list", str(profile)]) == 0
    assert "id: acme_sre" in capsys.readouterr().out
    notes = profile / "notes.md"
    notes.write_text("# Acme\n", encoding="utf-8")
    assert cli.main(["apps", "prep", str(profile), "acme_sre", "-k", "Kafka,Scala", "--notes", str(notes)]) == 0
    out = capsys.readouterr().out
    assert "Kafka [P]: strong" in out and "Scala [X]: lacking" in out
    assert str(Path("prep", "acme_sre.md")) in out
