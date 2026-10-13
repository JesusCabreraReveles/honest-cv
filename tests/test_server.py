"""The MCP server, driven in-process through the SDK client."""

import json
import shutil
from pathlib import Path

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


def answer(action: str, typed: str | None = "yes"):
    """An elicitation callback: accept (typing `typed` in the form), decline or cancel."""
    asked, schemas = [], []

    async def callback(ctx, params):
        asked.append(params.message)
        schemas.append(params.requested_schema)
        content = ({} if typed is None else {"confirm": typed}) if action == "accept" else None
        return t.ElicitResult(action=action, content=content)

    callback.asked, callback.schemas = asked, schemas
    return callback


async def call(client, tool, **args):
    r = await client.call_tool(tool, args)
    text = r.content[0].text
    return r.is_error, (text if r.is_error else json.loads(text))


async def test_lists_the_planned_tools():
    async with Client(server) as c:
        names = {tool.name for tool in (await c.list_tools()).tools}
    assert names == {"init_profile", "get_inventory", "set_skill", "add_bullet", "list_variants",
                     "build_cv", "verify_pdf", "score_job", "gap_report", "set_contact",
                     "set_profile_details", "upsert_role", "upsert_education", "save_variant",
                     "set_skills", "checklist_apply", "checklist_list", "checklist_new"}


async def test_every_tool_argument_is_described():
    async with Client(server) as c:
        tools = (await c.list_tools()).tools
    missing = [f"{x.name}.{k}" for x in tools for k, v in x.input_schema["properties"].items() if "description" not in v]
    assert missing == []


async def test_confirmation_is_not_a_model_argument():
    async with Client(server) as c:
        tool = next(x for x in (await c.list_tools()).tools if x.name == "set_skill")
    assert "confirmation" not in tool.input_schema["properties"]


async def test_upgrade_asks_the_person(profile):
    cb = answer("accept")
    async with Client(server, elicitation_callback=cb) as c:
        err, out = await call(c, "set_skill", profile=profile, name="Rust", level="L", evidence="CLI tool")
    assert not err and out["previous_level"] == "F"
    assert len(cb.asked) == 1 and "Rust F -> L" in cb.asked[0]
    # The person must type the answer: a form with no fields can be accepted by the
    # client without them deciding.
    assert cb.schemas[0]["required"] == ["confirm"]
    assert load(profile).inventory.get("Rust").level is Level.LAB


@pytest.mark.parametrize("reply", ["decline", "cancel"])
async def test_upgrade_refused_when_person_says_no(profile, reply):
    async with Client(server, elicitation_callback=answer(reply)) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Rust", level="P", evidence="x")
    assert err and "did not confirm" in msg
    assert load(profile).inventory.get("Rust").level is Level.FAMILIARITY


async def test_upgrade_without_evidence_never_asks(profile):
    cb = answer("accept")
    async with Client(server, elicitation_callback=cb) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Scala", level="P")
    assert err and "needs evidence" in msg and cb.asked == []


async def test_upgrade_without_elicitation_points_to_cli(profile):
    async with Client(server) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Scala", level="P", evidence="Akka at Example Bank")
    # A command the person can paste as is: their evidence, not a placeholder.
    assert err and f'uvx honest-cv skill "{profile}" "Scala" P --evidence "Akka at Example Bank"' in msg
    assert load(profile).inventory.get("Scala").level is Level.NONE


async def test_downgrade_never_asks(profile):
    cb = answer("accept")
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


async def test_profile_editing_tools(profile):
    async with Client(server) as c:
        err, _ = await call(c, "set_contact", profile=profile, location={"en": "Remote", "es": "Remoto"})
        assert not err
        err, out = await call(c, "upsert_role", profile=profile, id="fintech", end="2025")
        assert not err and out["role"]["end"] == "2025"
        err, out = await call(c, "upsert_role", profile=profile, id="fintech", end="present")
        assert not err and "end" not in out["role"]
        err, msg = await call(c, "upsert_role", profile=profile, id="new", title="Engineer", start="2024")
        assert err and "company" in msg
        err, _ = await call(c, "save_variant", profile=profile, id="sre", extends="platform",
                            title={"en": "SRE", "es": "SRE"},
                            skills=[{"label": "Cloud", "skills": ["AWS", "Kubernetes"]}])
        assert not err
        _, variants = await call(c, "list_variants", profile=profile)
    source = load(profile)
    assert source.profile.contact.location == {"en": "Remote", "es": "Remoto"}
    assert source.resolve("sre").skills[0].skills == ["AWS", "Kubernetes"]
    assert variants["variants"]["sre"]["own"]["extends"] == "platform"


GROUP = [
    {"name": "Rust", "level": "L", "evidence": "CLI tool on GitHub"},
    {"name": "NATS", "level": "F", "evidence": "Read the docs, ran the demo"},
    {"name": "Java", "level": "F"},  # a downgrade needs nothing
]


async def test_set_skills_asks_once_for_every_upgrade(profile):
    cb = answer("accept")
    async with Client(server, elicitation_callback=cb) as c:
        err, out = await call(c, "set_skills", profile=profile, skills=GROUP)
    assert not err and out == {"saved": ["Java", "Rust", "NATS"], "upgrades": 2}
    assert len(cb.asked) == 1
    assert "Rust: F -> L. Evidence: CLI tool on GitHub" in cb.asked[0] and "NATS: X -> F" in cb.asked[0]
    inv = load(profile).inventory
    assert (inv.get("Rust").level, inv.get("NATS").level, inv.get("Java").level) == (
        Level.LAB, Level.FAMILIARITY, Level.FAMILIARITY
    )


@pytest.mark.parametrize("reply", ["decline", "cancel"])
async def test_set_skills_saves_nothing_when_declined(profile, reply):
    async with Client(server, elicitation_callback=answer(reply)) as c:
        err, msg = await call(c, "set_skills", profile=profile, skills=GROUP)
    assert err and "did not confirm" in msg
    assert load(profile).inventory.get("Java").level is Level.PRODUCTION  # not even the downgrade


async def test_set_skills_needs_evidence_for_every_upgrade(profile):
    cb = answer("accept")
    async with Client(server, elicitation_callback=cb) as c:
        err, msg = await call(c, "set_skills", profile=profile, skills=[*GROUP, {"name": "Elixir", "level": "P"}])
    assert err and "missing for: Elixir" in msg and cb.asked == []
    assert load(profile).inventory.get("Rust").level is Level.FAMILIARITY


async def test_set_skills_without_elicitation_leaves_a_checklist_for_the_cli(profile):
    async with Client(server) as c:
        err, msg = await call(c, "set_skills", profile=profile, skills=GROUP)
    pending = Path(profile) / "pending-upgrades.md"
    assert err and "uvx honest-cv checklist apply" in msg and str(pending) in msg
    assert "- [L] Rust — CLI tool on GitHub" in pending.read_text(encoding="utf-8")
    assert load(profile).inventory.get("Rust").level is Level.FAMILIARITY


async def test_checklist_apply_returns_pending_lines(profile, tmp_path):
    path = tmp_path / "checklist.md"
    path.write_text("## Data\n- [L] Rust — CLI tool\n- [P] Elixir\n- [X] Scala\n", encoding="utf-8")
    cb = answer("accept")
    async with Client(server, elicitation_callback=cb) as c:
        err, out = await call(c, "checklist_apply", profile=profile, path=str(path))
    assert not err and out["saved"] == 2 and len(cb.asked) == 1
    assert [p["name"] for p in out["pending_evidence"]] == ["Elixir"]
    assert load(profile).inventory.get("Rust").level is Level.LAB



def test_not_asked_never_counts_as_a_yes():
    # The SDK wraps a resolver's plain return value as an accepted elicitation.
    # Found when checklist_apply saved an upgrade without asking: "not asked" must
    # never read as the person's confirmation.
    from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

    from honest_cv.server import ConfirmUpgrade, NotAsked, _confirmed

    assert _confirmed(AcceptedElicitation(data=ConfirmUpgrade(confirm="sí")))
    assert not _confirmed(AcceptedElicitation(data=ConfirmUpgrade(confirm="no")))
    assert not _confirmed(AcceptedElicitation(data=NotAsked()))
    assert not _confirmed(DeclinedElicitation())


async def test_checklist_new_and_list(profile):
    async with Client(server) as c:
        _, listed = await call(c, "checklist_list")
        err, out = await call(c, "checklist_new", profile=profile, lists=["data"])
        again, msg = await call(c, "checklist_new", profile=profile, lists=["data"])
    assert "data" in {b["id"] for b in listed["checklists"]}
    assert not err and Path(out["path"]).exists() and out["skills"] > 40
    assert again and "exists" in msg


@pytest.mark.parametrize("typed", [None, "", "no", "ok", "true"])
async def test_accept_without_typing_yes_saves_nothing(profile, typed):
    # Found in Claude Code: an empty form came back "accept" with {} while the
    # person saw no question. Only a typed yes/sí counts.
    async with Client(server, elicitation_callback=answer("accept", typed)) as c:
        err, _ = await call(c, "set_skill", profile=profile, name="Rust", level="L", evidence="CLI tool")
        err2, _ = await call(c, "set_skills", profile=profile, skills=GROUP)
    assert err and err2
    assert load(profile).inventory.get("Rust").level is Level.FAMILIARITY


@pytest.mark.parametrize("typed", ["yes", "Y", " sí ", "Si", "s"])
async def test_typed_yes_in_either_language_confirms(profile, typed):
    async with Client(server, elicitation_callback=answer("accept", typed)) as c:
        err, _ = await call(c, "set_skill", profile=profile, name="Rust", level="L", evidence="CLI tool")
    assert not err and load(profile).inventory.get("Rust").level is Level.LAB

