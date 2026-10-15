"""Tracking job applications in <profile>/applications.yaml."""

import shutil
from datetime import date

import pytest
from mcp import Client

from honest_cv import applications, cli
from honest_cv.server import mcp as server
from tests.conftest import ADA
from tests.test_server import call

SEP_1, SEP_10, OCT_1 = date(2026, 9, 1), date(2026, 9, 10), date(2026, 10, 1)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def profile(tmp_path):
    shutil.copytree(ADA, tmp_path / "ada")
    return tmp_path / "ada"


def test_logging_the_same_job_again_updates_it(profile):
    applications.log(profile, "Acme", "Backend Engineer", status="applied", when=SEP_1,
                     variant="backend", lang="en", files=["out/cv.pdf"])
    app = applications.log(profile, "Acme", "Backend Engineer", status="interview", when=SEP_10,
                           files=["out/cv.pdf", "out/letter.pdf"], notes="Call with the CTO")
    assert [(c.status, c.date) for c in app.history] == [("applied", SEP_1), ("interview", SEP_10)]
    assert (app.variant, app.files, app.notes) == ("backend", ["out/cv.pdf", "out/letter.pdf"], "Call with the CTO")
    assert len(applications.read(profile).applications) == 1


def test_the_same_status_again_adds_no_history(profile):
    applications.log(profile, "Acme", "SRE", status="applied", when=SEP_1)
    app = applications.log(profile, "Acme", "SRE", status="applied", when=SEP_10, url="https://acme.example/jobs/1")
    assert len(app.history) == 1 and app.url == "https://acme.example/jobs/1"


def test_notes_add_up(profile):
    applications.log(profile, "Acme", "SRE", notes="Salary range 60-70k")
    app = applications.log(profile, "Acme", "SRE", notes="Call with the CTO")
    assert app.notes == "Salary range 60-70k\nCall with the CTO"
    assert applications.log(profile, "Acme", "SRE", notes="Call with the CTO").notes == app.notes


def test_a_backdated_status_keeps_the_history_in_order(profile):
    applications.log(profile, "Acme", "SRE", status="interview", when=SEP_10)
    app = applications.log(profile, "Acme", "SRE", status="applied", when=SEP_1)
    assert [c.status for c in app.history] == ["applied", "interview"] and app.status == "interview"


def test_an_unknown_variant_is_refused(profile):
    with pytest.raises(ValueError, match="unknown variant 'mobile'"):
        applications.log(profile, "Acme", "SRE", variant="mobile")
    assert not (profile / applications.FILE).exists()


def test_listing_latest_first_with_counts_and_waiting(profile):
    applications.log(profile, "Acme", "Backend Engineer", status="applied", when=SEP_1)
    applications.log(profile, "Beta", "SRE", status="interview", when=SEP_10)
    applications.log(profile, "Gamma", "Lead", status="rejected", when=SEP_1)
    applications.log(profile, "Delta", "Platform Engineer", status="applied", when=date(2026, 9, 25))
    data = applications.listing(profile, today=OCT_1)
    assert [a["company"] for a in data["applications"]] == ["Delta", "Beta", "Acme", "Gamma"]
    assert data["applications"][0]["days_since_update"] == 6
    assert data["counts"] == {"applied": 2, "interview": 1, "rejected": 1}
    # Open and quiet for 14+ days; a rejection is closed, not waiting.
    assert data["waiting"] == ["acme_backend_engineer", "beta_sre"]
    only = applications.listing(profile, ["interview"], today=OCT_1)["applications"]
    assert [a["company"] for a in only] == ["Beta"]


@pytest.mark.anyio
async def test_tools(profile):
    async with Client(server) as c:
        err, out = await call(c, "log_application", profile=str(profile), company="Acme", role="SRE",
                              status="applied", date="2026-09-01", variant="platform")
        assert not err and out["application"]["status"] == "applied"
        err, msg = await call(c, "log_application", profile=str(profile), company="Acme", role="SRE",
                              date="1st of September")
        assert err
        err, out = await call(c, "list_applications", profile=str(profile))
    assert not err and out["counts"] == {"applied": 1}


def test_cli(profile, capsys):
    assert cli.main(["apps", "log", str(profile), "--company", "Acme", "--role", "SRE", "-s", "applied",
                     "--date", "2026-09-01", "-v", "platform", "--file", "out/cv.pdf"]) == 0
    assert cli.main(["apps", "list", str(profile)]) == 0
    out = capsys.readouterr().out
    assert "acme_sre: applied (2026-09-01)" in out and "Acme — SRE" in out and "1 applied" in out
    assert cli.main(["apps", "log", str(profile), "--company", "Acme", "--role", "SRE", "--date", "sept 1"]) == 1
