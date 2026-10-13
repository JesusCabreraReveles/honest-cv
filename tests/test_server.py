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


def answer(action: str, value: str | None = "sí", per: dict | None = None):
    """An elicitation callback. On accept it answers every field with `value`, or with
    `per[skill]` for the skill a field asks about; `value=None` sends no answers."""
    asked, schemas = [], []

    async def callback(ctx, params):
        asked.append(params.message)
        schemas.append(params.requested_schema)
        content = None
        if action == "accept":
            props = params.requested_schema["properties"]
            content = {} if value is None else {
                k: (per or {}).get(f["title"].split(":")[0], value) for k, f in props.items()
            }
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
                     "set_skills", "checklist_apply", "checklist_list", "checklist_new",
                     "check_claims", "build_letter", "import_profile",
                     "remove_skill", "remove_bullet", "remove_role"}


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
    assert len(cb.asked) == 1
    # One field per upgrade, shown by every client, with "no" first.
    assert cb.schemas[0]["required"] == ["u1"]
    field = cb.schemas[0]["properties"]["u1"]
    assert field["title"] == "Rust: F → L — CLI tool" and field["enum"] == ["no", "sí"]
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
    assert not err and out["saved"] == ["Java", "Rust", "NATS"] and out["upgrades_confirmed"] == ["Rust", "NATS"]
    assert len(cb.asked) == 1
    titles = [f["title"] for f in cb.schemas[0]["properties"].values()]
    assert titles == ["Rust: F → L — CLI tool on GitHub", "NATS: X → F — Read the docs, ran the demo"]
    inv = load(profile).inventory
    assert (inv.get("Rust").level, inv.get("NATS").level, inv.get("Java").level) == (
        Level.LAB, Level.FAMILIARITY, Level.FAMILIARITY
    )


@pytest.mark.parametrize("reply", ["decline", "cancel"])
async def test_set_skills_saves_nothing_when_declined(profile, reply):
    async with Client(server, elicitation_callback=answer(reply)) as c:
        err, msg = await call(c, "set_skills", profile=profile, skills=GROUP)
    assert err and "declined" in msg
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
    # Scala was already X: a line that changes nothing saves nothing.
    assert not err and out["saved"] == 1 and len(cb.asked) == 1 and out["upgrades_confirmed"] == ["Rust"]
    assert [p["name"] for p in out["pending_evidence"]] == ["Elixir"]
    assert load(profile).inventory.get("Rust").level is Level.LAB



def test_not_asked_never_counts_as_a_yes():
    # The SDK wraps a resolver's plain return value as an accepted elicitation.
    # Found when checklist_apply saved an upgrade without asking: "not asked" must
    # never read as the person's confirmation.
    from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

    from honest_cv.server import NotAsked, _approved, _confirm_form
    from honest_cv.store import SkillChange

    upgrades = [(SkillChange("Rust", Level.LAB, "CLI"), Level.FAMILIARITY)]
    form = _confirm_form(upgrades)
    assert _approved(AcceptedElicitation(data=form(u1="sí")), upgrades) == upgrades
    assert _approved(AcceptedElicitation(data=form(u1="no")), upgrades) == []
    assert _approved(AcceptedElicitation(data=NotAsked()), upgrades) == []
    assert _approved(DeclinedElicitation(), upgrades) == []


@pytest.mark.parametrize("value", [None, "", "yes", "ok", "true"])
async def test_accept_without_a_valid_answer_saves_nothing(profile, value):
    # Found in Claude Code: an empty form came back "accept" with {} while the
    # person saw no question. Every field needs an explicit "sí" or "no".
    async with Client(server, elicitation_callback=answer("accept", value)) as c:
        err, _ = await call(c, "set_skill", profile=profile, name="Rust", level="L", evidence="CLI tool")
        err2, _ = await call(c, "set_skills", profile=profile, skills=GROUP)
    assert err and err2
    inv = load(profile).inventory
    assert inv.get("Rust").level is Level.FAMILIARITY and inv.get("Java").level is Level.PRODUCTION


async def test_no_saves_nothing_for_that_skill(profile):
    async with Client(server, elicitation_callback=answer("accept", "no")) as c:
        err, msg = await call(c, "set_skill", profile=profile, name="Rust", level="L", evidence="CLI tool")
    assert err and "did not confirm" in msg
    assert load(profile).inventory.get("Rust").level is Level.FAMILIARITY


async def test_each_upgrade_is_answered_on_its_own(profile):
    # Found in Claude Code: a list in the message showed only its last line. Each
    # upgrade is now its own field, and only the ones answered "sí" are saved.
    cb = answer("accept", per={"Rust": "sí", "NATS": "no"})
    async with Client(server, elicitation_callback=cb) as c:
        err, out = await call(c, "set_skills", profile=profile, skills=GROUP)
    assert not err and out["upgrades_confirmed"] == ["Rust"] and out["upgrades_refused"] == ["NATS"]
    inv = load(profile).inventory
    assert inv.get("Rust").level is Level.LAB and inv.get("NATS") is None
    assert inv.get("Java").level is Level.FAMILIARITY  # the downgrade needs no answer


async def test_long_lists_are_asked_ten_at_a_time(profile):
    many = [{"name": f"Tool{n:02}", "level": "F", "evidence": "Tried it"} for n in range(12)]
    cb = answer("accept")
    async with Client(server, elicitation_callback=cb) as c:
        _, first = await call(c, "set_skills", profile=profile, skills=many)
        _, second = await call(c, "set_skills", profile=profile, skills=many)
    assert len(cb.schemas[0]["properties"]) == 10 and "2 more" in cb.asked[0]
    assert first["upgrades_not_asked_yet"] == ["Tool10", "Tool11"]
    assert len(cb.schemas[1]["properties"]) == 2 and second["upgrades_confirmed"] == ["Tool10", "Tool11"]


async def test_build_letter_refuses_unsupported_claims_and_builds_honest_ones(profile, tmp_path):
    async with Client(server) as c:
        _, claims = await call(c, "check_claims", profile=profile, text="I use Scala and Terraform daily.")
        err, msg = await call(c, "build_letter", profile=profile, company="Acme", role="SRE",
                              paragraphs=["I have used Scala daily."], out_dir=str(tmp_path / "x"))
        ok_err, out = await call(c, "build_letter", profile=profile, company="Acme", role="SRE", lang="es",
                                 paragraphs=["Lideré la migración de 40 servicios a Kubernetes.",
                                             "También trabajé con Terraform."], out_dir=str(tmp_path / "o"))
    assert not claims["ok"] and [p["term"] for p in claims["problems"]] == ["Scala"]
    assert [w["term"] for w in claims["warnings"]] == ["Terraform"]
    assert err and "Scala (not_held)" in msg and not (tmp_path / "x").exists()
    pdf = next(f for f in out["files"] if f["format"] == "pdf")
    assert not ok_err and pdf["ats_ok"] and pdf["pages"] == 1
    assert [w["term"] for w in out["warnings"]] == ["Terraform"]


async def test_import_profile(tmp_path):
    resume = Path(__file__).parent / "fixtures" / "resume.json"
    async with Client(server) as c:
        err, dry = await call(c, "import_profile", profile=str(tmp_path / "p"), path=str(resume), dry_run=True)
        assert not err and dry["dry_run"] and not (tmp_path / "p").exists()
        err, out = await call(c, "import_profile", profile=str(tmp_path / "p"), path=str(resume))
        _, built = await call(c, "build_cv", profile=str(tmp_path / "p"), variant="main", out_dir=str(tmp_path / "o"))
        pdf = next(f["path"] for f in built["files"] if f["format"] == "pdf")
        err2, text = await call(c, "import_profile", profile=str(tmp_path / "p"), path=pdf)
    assert not err and out["skills"] == 3 and out["added"]["variants"] == ["main"]
    # A PDF is read, never parsed into the profile: the client organizes it with the person.
    assert not err2 and text["format"] == "pdf" and "Grace Sample" in text["text"]


async def test_remove_tools_are_marked_destructive(profile):
    async with Client(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        err, msg = await call(c, "remove_role", profile=profile, id="bank")
    for name in ("remove_skill", "remove_bullet", "remove_role"):
        assert tools[name].annotations.destructive_hint is True, name
    assert err and "with_bullets" in msg

