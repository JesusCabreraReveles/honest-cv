"""The MCP server, driven in-process through the SDK client."""

import json
import shutil

import mcp.types as t
import pytest
from mcp import Client

from honest_cv.model import Level, load
from honest_cv.server import mcp as server
from tests.conftest import ADA

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def profile(tmp_path):
    shutil.copytree(ADA, tmp_path / "ada")
    return str(tmp_path / "ada")


def answer(confirm: bool | None):
    """An elicitation callback: None declines, a bool accepts with that value."""
    asked = []

    async def callback(ctx, params):
        asked.append(params.message)
        if confirm is None:
            return t.ElicitResult(action="decline")
        return t.ElicitResult(action="accept", content={"confirm": confirm})

    callback.asked = asked
    return callback


async def call(client, tool, **args):
    r = await client.call_tool(tool, args)
    text = r.content[0].text
    return r.is_error, (text if r.is_error else json.loads(text))


async def test_lists_the_planned_tools():
    async with Client(server) as c:
        names = {tool.name for tool in (await c.list_tools()).tools}
    assert names == {"init_profile", "get_inventory", "set_skill", "add_bullet", "list_variants",
                     "build_cv", "verify_pdf", "score_job", "gap_report"}


async def test_confirmation_is_not_a_model_argument():
    async with Client(server) as c:
        tool = next(x for x in (await c.list_tools()).tools if x.name == "set_skill")
    assert "confirmation" not in tool.input_schema["properties"]


async def test_upgrade_asks_the_person(profile):
    cb = answer(True)
    async with Client(server, elicitation_callback=cb) as c:
        err, out = await call(c, "set_skill", profile=profile, name="Rust", level="L", evidence="CLI tool")
    assert not err and out["previous_level"] == "F"
    assert len(cb.asked) == 1 and "Rust F -> L" in cb.asked[0]
    assert load(profile).inventory.get("Rust").level is Level.LAB


@pytest.mark.parametrize("reply", [False, None])
async def test_upgrade_refused_when_person_says_no(profile, reply):
    async with Client(server, elicitation_callback=answer(reply)) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Rust", level="P", evidence="x")
    assert err and "did not confirm" in msg
    assert load(profile).inventory.get("Rust").level is Level.FAMILIARITY


async def test_upgrade_without_evidence_never_asks(profile):
    cb = answer(True)
    async with Client(server, elicitation_callback=cb) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Scala", level="P")
    assert err and "needs evidence" in msg and cb.asked == []


async def test_upgrade_without_elicitation_points_to_cli(profile):
    async with Client(server) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Scala", level="P", evidence="Akka at Example Bank")
    # A command the person can paste as is: their evidence, not a placeholder.
    assert err and f'honest-cv skill "{profile}" "Scala" P --evidence "Akka at Example Bank"' in msg
    assert load(profile).inventory.get("Scala").level is Level.NONE


async def test_downgrade_never_asks(profile):
    cb = answer(True)
    async with Client(server, elicitation_callback=cb) as c:
        err, _ = await call(c, "set_skill", profile=profile, name="Java", level="F")
    assert not err and cb.asked == []


async def test_read_tools(profile):
    async with Client(server) as c:
        _, inv = await call(c, "get_inventory", profile=profile)
        _, variants = await call(c, "list_variants", profile=profile)
    assert [s["name"] for s in inv["skills"]["X"]] == ["Scala"]
    assert variants["variants"]["platform"]["extends"] == "backend"
    assert variants["unused_bullets"] == []


async def test_add_bullet_and_errors_reach_the_model(profile):
    async with Client(server) as c:
        err, _ = await call(c, "add_bullet", profile=profile, id="ft_x", text_en="Did X.", role="fintech")
        assert not err
        err, msg = await call(c, "add_bullet", profile=profile, id="y", text_en="Y.", role="nope")
    assert err and "unknown role 'nope'" in msg
    # The reason only, not pydantic's dump of the whole profile.
    assert "input_value" not in msg and "errors.pydantic.dev" not in msg


async def test_build_verify_and_score(profile, tmp_path):
    async with Client(server) as c:
        err, built = await call(c, "build_cv", profile=profile, variant="backend", lang="es", out_dir=str(tmp_path / "o"))
        assert not err
        pdf = next(f for f in built["files"] if f["format"] == "pdf")
        assert pdf["ats_ok"] and pdf["failed_checks"] == []
        _, report = await call(c, "verify_pdf", path=pdf["path"], max_pages=1)
        assert report["ok"] and "Ada Example" in report["text"]
        _, scores = await call(c, "score_job", profile=profile, keywords=["k8s", "Scala"], preferred=["Rust"])
        assert {s["variant"] for s in scores["scores"]} == {"backend", "platform", "leadership"}
        _, gaps = await call(c, "gap_report", profile=profile, variant="backend", keywords=["Scala", "Rust"])
    assert [g["keyword"] for g in gaps["not_in_inventory"]] == ["Scala"]
    assert [g["keyword"] for g in gaps["familiarity_only"]] == ["Rust"]


async def test_profile_from_environment(profile, monkeypatch):
    monkeypatch.setenv("HONEST_CV_PROFILE", profile)
    async with Client(server) as c:
        err, inv = await call(c, "get_inventory")
    assert not err and inv["skills"]["P"]


async def test_missing_profile_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("HONEST_CV_PROFILE", raising=False)
    async with Client(server) as c:
        err, msg = await call(c, "get_inventory")
    assert err and "HONEST_CV_PROFILE" in msg
