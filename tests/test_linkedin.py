"""LinkedIn texts from a variant."""

import pytest

from honest_cv import cli, linkedin


@pytest.fixture
def s(ada):
    return linkedin.suggest(ada, "platform", "en")


def test_headline_is_the_title_and_a_few_production_skills(s):
    assert s.headline.text == "Senior Platform Engineer | Kubernetes · Docker · AWS · GitHub Actions · OpenTelemetry"
    assert s.headline.chars <= linkedin.HEADLINE


def test_about_is_the_summary_and_the_impact_bullets(ada, s):
    v = ada.resolve("platform")
    assert s.about.text.startswith(v.summary["en"] + "\n\n• ")


def test_positions_follow_the_variant(ada, s):
    v = ada.resolve("platform")
    assert [p.company for p in s.positions] == [r.company for r in ada.profile.roles if v.roles.get(r.id)]
    first = s.positions[0]
    assert first.description.text.startswith("Payments platform processing 2M")
    assert first.description.text.count("\n• ") == len(v.roles["fintech"])


def test_skills_are_p_and_l_never_f_or_x(s):
    assert s.skills[:2] == ["Java", "PostgreSQL"]  # P first, most years first
    assert "gRPC" in s.skills  # L
    assert "Rust" not in s.skills and "Scala" not in s.skills


def test_bullets_that_do_not_fit_are_named(ada, monkeypatch):
    monkeypatch.setattr(linkedin, "POSITION", 200)
    first = linkedin.suggest(ada, "platform", "en").positions[0]
    assert first.description.chars <= 200 and first.left_out
    assert first.left_out[0] in ada.resolve("platform").roles["fintech"]


def test_every_text_fits(ada):
    for variant in ada.variants:
        for lang in ("en", "es"):
            s = linkedin.suggest(ada, variant, lang)
            assert s.headline.chars <= 220 and s.about.chars <= 2600
            assert all(p.description.chars <= 2000 for p in s.positions)


def test_cli(tmp_path, capsys):
    assert cli.main(["linkedin", "examples/ada", "-v", "backend", "-l", "es", "-o", str(tmp_path)]) == 0
    assert "## Headline" in capsys.readouterr().out
    assert (tmp_path / "Ada_Example_LinkedIn_backend_ES.md").exists()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_an_approved_polish_is_checked_and_saved(tmp_path):
    import shutil

    from mcp import Client

    from honest_cv.server import mcp as server
    from tests.conftest import ADA
    from tests.test_server import call

    shutil.copytree(ADA, tmp_path / "ada")
    profile = str(tmp_path / "ada")
    async with Client(server) as c:
        err, out = await call(c, "linkedin_profile", profile=profile, variant="backend",
                              headline="Backend engineer · payments and ledgers",
                              about="I build payment systems that keep their books straight.")
        assert not err and out["headline"]["text"] == "Backend engineer · payments and ledgers"
        saved = (tmp_path / "ada" / "out").glob("*LinkedIn*.md").__next__().read_text(encoding="utf-8")
        assert "I build payment systems that keep their books straight." in saved
        # Scala is X in Ada's inventory: claiming it saves nothing.
        err, msg = await call(c, "linkedin_profile", profile=profile, variant="backend",
                              about="Years of Scala in production.")
        assert err and "Scala" in msg and "nothing was saved" in msg
        err, msg = await call(c, "linkedin_profile", profile=profile, variant="backend", headline="x" * 221)
        assert err and "221 characters" in msg
