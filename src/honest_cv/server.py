"""MCP server over stdio. Deterministic and keyless: the client's LLM extracts
keywords and runs the interview; this server validates, builds, verifies and
measures.

Every tool takes a `profile` folder. When it is omitted, HONEST_CV_PROFILE is used.
"""

from __future__ import annotations

import functools
import inspect
import os
from pathlib import Path
from string import Template
from typing import Annotated, Literal

from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError, create_model

from honest_cv import __version__, checklist, letter, store
from honest_cv import build as build_mod
from honest_cv import score as score_mod
from honest_cv.model import LEVEL_RANK, Bullet, Lang, Level, SkillGroup, Source, Text, Variant, explain, load
from honest_cv.verify import verify_pdf as verify

INSTRUCTIONS = """\
honest-cv turns a person's real experience into ATS-safe CVs, one variant per type of role.
Talk to the person in the language they write in; these tools answer in English.

Honesty rules, enforced by this server:
- Skill levels: P (production), L (own project/lab), F (familiarity, always labeled), X (never shown).
- Raising a skill's level needs written evidence and the person's own confirmation, which the
  server asks for directly. Never invent experience, metrics or skills.

Edit the profile through the tools (set_contact, upsert_role, upsert_education,
set_profile_details, add_bullet, set_skill, save_variant), not by writing its files: the tools
validate every change.

Typical flow: get_inventory and list_variants to learn the profile; for a job post, extract its
keywords yourself, call score_job, then gap_report on the best variant; propose edits the person
approves; build_cv, which also verifies the PDF. If a check fails, never reword the person's
text to pass it: report it, since it is probably a bug in honest-cv.
"""

mcp = MCPServer("honest-cv", version=__version__, instructions=INSTRUCTIONS)

# Parameter descriptions shared by the tools. Clients show them to the model and,
# in tools like the MCP Inspector, to the person.
Profile = Annotated[str | None, Field(description="Profile folder. Defaults to HONEST_CV_PROFILE.")]
LangArg = Annotated[Lang, Field(description="Language of the CV: en or es.")]
VariantId = Annotated[str, Field(description="Variant id from variants.yaml, e.g. backend.")]
Keywords = Annotated[list[str], Field(description="Required keywords from the job post, in its own wording.")]
Preferred = Annotated[list[str] | None, Field(description="Nice-to-have keywords from the job post.")]
TextArg = Annotated[
    Text | None, Field(description='One string, or one per language: {"en": "...", "es": "..."}.')
]
Year = Annotated[str | None, Field(description='A year or year-month, e.g. "2021" or "2021-03".')]

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def _profile_dir(profile: str | None) -> Path:
    value = profile or os.environ.get("HONEST_CV_PROFILE")
    if not value:
        raise ToolError("no profile folder given and HONEST_CV_PROFILE is not set")
    return Path(value).expanduser().resolve()


def _load(profile: str | None) -> Source:
    return load(_profile_dir(profile))


def _quote(value: object) -> str:
    # Double quotes work in POSIX shells, PowerShell and cmd alike.
    return '"' + str(value).replace('"', "'") + '"'


def _tool_errors(fn):
    """Turn expected failures into ToolError so the model sees the reason."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result
        except ToolError:
            raise
        except (ValidationError, ValueError, FileNotFoundError) as e:
            raise ToolError(explain(e)) from e

    return wrapper


@mcp.tool(annotations=WRITE)
@_tool_errors
def init_profile(
    profile: Annotated[str, Field(description="Folder to create. Must not hold a profile yet.")],
) -> dict:
    """Create a profile folder with empty, commented YAML templates. Refuses to overwrite."""
    created = store.init_profile(_profile_dir(profile))
    return {"created": [str(p) for p in created]}


@mcp.tool(annotations=READ)
@_tool_errors
def get_inventory(profile: Profile = None) -> dict:
    """The skill inventory: level (P/L/F/X), years, last use, evidence and aliases."""
    inv = _load(profile).inventory
    by_level = {lvl.value: [] for lvl in sorted(Level, key=LEVEL_RANK.get, reverse=True)}
    for s in inv.skills:
        by_level[s.level.value].append(s.model_dump(mode="json", exclude_none=True, exclude_defaults=True))
    return {"levels": {"P": "production", "L": "own project or lab", "F": "familiarity", "X": "does not have it"},
            "skills": by_level}


class ConfirmUpgrade(BaseModel):
    """The confirmation form: one required "no"/"sí" field per upgrade, built by
    `_confirm_form`. Two things seen in Claude Code shaped it:
    - a form with no fields came back "accept" while the person saw no question;
    - a list inside the message showed only its last line, so the person
      approved upgrades they never saw.
    Fields are always shown, one per upgrade, and "no" comes first in case a
    client preselects an option."""


ASK_AT_ONCE = 10  # upgrades per question; the rest are asked on the next call
NO, YES_ANSWER = "no", "sí"


def _confirm_form(upgrades: list[tuple[store.SkillChange, Level]]) -> type[ConfirmUpgrade]:
    fields = {
        f"u{i}": (
            Literal["no", "sí"],
            Field(
                title=f"{c.name}: {old.value} → {c.level.value} — {c.evidence}",
                description="sí only if it is true and you can defend it in an interview.",
            ),
        )
        for i, (c, old) in enumerate(upgrades[:ASK_AT_ONCE], start=1)
    }
    return create_model("ConfirmUpgrade", __base__=ConfirmUpgrade, **fields)


def _ask(upgrades: list[tuple[store.SkillChange, Level]]) -> Elicit[ConfirmUpgrade]:
    shown = min(len(upgrades), ASK_AT_ONCE)
    more = f" ({len(upgrades) - shown} more next time)" if len(upgrades) > shown else ""
    return Elicit(f"honest-cv: confirm {shown} skill upgrade(s), one per field{more}.", _confirm_form(upgrades))


class NotAsked(BaseModel):
    """What a resolver returns when it does not ask the person.

    The SDK wraps any plain return value as an *accepted* elicitation, so "not
    asked" must be a different type that `_approved` never mistakes for a yes."""


def _approved(confirmation: object, upgrades: list) -> list:
    """The upgrades the person answered "sí" to, in the order they were asked."""
    if not (isinstance(confirmation, AcceptedElicitation) and isinstance(confirmation.data, ConfirmUpgrade)):
        return []
    data = confirmation.data
    return [u for i, u in enumerate(upgrades[:ASK_AT_ONCE], start=1) if getattr(data, f"u{i}", NO) == YES_ANSWER]


def _upgrade(profile: str | None, name: str, level: str) -> tuple[Path, Level, Level]:
    folder = _profile_dir(profile)
    current = load(folder).inventory.get(name)
    return folder, current.level if current else Level.NONE, Level(level)


def _can_ask(ctx: Context) -> bool:
    caps = ctx.client_capabilities
    return caps is not None and caps.elicitation is not None


def _single(name: str, level: str, evidence: str | None, old: Level) -> list[tuple[store.SkillChange, Level]]:
    return [(store.SkillChange(name, Level(level), evidence), old)]


def confirm_upgrade(
    ctx: Context, name: str, level: str, evidence: str | None, profile: str | None
) -> Elicit[ConfirmUpgrade] | NotAsked:
    """Ask the person, not the model, to confirm a level upgrade."""
    try:
        _, old, new = _upgrade(profile, name, level)
    except (ToolError, ValueError):
        return NotAsked()  # set_skill reports the real error
    if LEVEL_RANK[new] <= LEVEL_RANK[old] or not (evidence and evidence.strip()) or not _can_ask(ctx):
        return NotAsked()  # nothing to confirm, or set_skill refuses
    return _ask(_single(name, level, evidence, old))


@mcp.tool(annotations=WRITE)
@_tool_errors
def set_skill(
    ctx: Context,
    name: Annotated[str, Field(description="Skill name, e.g. Kubernetes. Matches existing skills ignoring case.")],
    level: Annotated[
        Literal["P", "L", "F", "X"],
        Field(description="P production at a job, L own project or lab, F familiarity, X does not have it."),
    ],
    confirmation: Annotated[ElicitationResult[ConfirmUpgrade], Resolve(confirm_upgrade)],
    profile: Profile = None,
    evidence: Annotated[
        str | None, Field(description="Where and how the person used it. Required to raise a level.")
    ] = None,
    years: Annotated[float | None, Field(description="Years of use, e.g. 2.5.", ge=0)] = None,
    last_used_year: Annotated[
        int | None, Field(description="Last calendar year the person used it, e.g. 2026.")
    ] = None,
    aliases: Annotated[list[str] | None, Field(description="Other spellings, e.g. k8s for Kubernetes.")] = None,
    notes: Annotated[str | None, Field(description="Private notes; never printed on the CV.")] = None,
) -> dict:
    """Add or change a skill. Raising the level (a new skill counts as coming from X) needs
    `evidence`, and the server then asks the person to confirm. Lowering is always allowed."""
    folder, old, new = _upgrade(profile, name, level)
    confirmed = False
    if LEVEL_RANK[new] > LEVEL_RANK[old]:
        if not (evidence and evidence.strip()):
            raise ToolError(f"{name}: raising {old} -> {new} needs evidence (where and how it was used)")
        if not _can_ask(ctx):
            raise ToolError(
                "this client cannot ask the person directly, so the upgrade was not saved. "
                f"Ask them to run in a terminal: uvx honest-cv skill {_quote(folder)} {_quote(name)} {new} --evidence {_quote(evidence)}"
            )
        if not _approved(confirmation, _single(name, level, evidence, old)):
            raise ToolError(f"{name}: the person did not confirm the upgrade; nothing was saved")
        confirmed = True
    skill = store.upsert_skill(
        folder, name, new, evidence=evidence, confirmed=confirmed,
        years=years, last_used_year=last_used_year, aliases=aliases, notes=notes,
    )
    return {"saved": skill.model_dump(mode="json", exclude_none=True, exclude_defaults=True), "previous_level": old.value}


class SkillInput(BaseModel):
    name: str = Field(description="Skill name, e.g. Kubernetes.")
    level: Literal["P", "L", "F", "X"] = Field(description="P production, L own project or lab, F familiarity, X does not have it.")
    evidence: str | None = Field(None, description="Where and how the person used it. Required to raise a level.")
    years: float | None = Field(None, description="Years of use, e.g. 2.5.", ge=0)
    last_used_year: int | None = Field(None, description="Last calendar year the person used it, e.g. 2026.")
    aliases: list[str] | None = Field(None, description="Other spellings, e.g. k8s.")
    notes: str | None = Field(None, description="Private notes; never printed on the CV.")

    def change(self) -> store.SkillChange:
        return store.SkillChange(**{**self.model_dump(), "level": Level(self.level)})


def _skills_plan(profile: str | None, skills: list) -> checklist.Plan:
    changes = [(s if isinstance(s, SkillInput) else SkillInput.model_validate(s)).change() for s in skills]
    return checklist.classify(_load(profile), changes)


def _checklist_plan(profile: str | None, path: str) -> checklist.Plan:
    return checklist.plan(_load(profile), checklist.read(path))


def _ask_for(ctx: Context, plan: checklist.Plan) -> Elicit[ConfirmUpgrade] | NotAsked:
    if not plan.upgrades or not _can_ask(ctx):
        return NotAsked()  # the tool reports why
    return _ask(plan.upgrades)


def confirm_skills(ctx: Context, skills: list, profile: str | None) -> Elicit[ConfirmUpgrade] | NotAsked:
    try:
        plan = _skills_plan(profile, skills)
    except (ToolError, ValueError):
        return NotAsked()
    # set_skills saves nothing when an upgrade lacks evidence, so don't ask then.
    return NotAsked() if plan.missing_evidence else _ask_for(ctx, plan)


def confirm_checklist(ctx: Context, path: str, profile: str | None) -> Elicit[ConfirmUpgrade] | NotAsked:
    try:
        return _ask_for(ctx, _checklist_plan(profile, path))
    except (ToolError, ValueError, OSError):
        return NotAsked()


def _save_plan(ctx: Context, profile: str | None, plan: checklist.Plan, confirmation) -> dict:
    """Save the updates and the upgrades the person answered "sí" to, one field each.

    Declining or cancelling the form saves nothing at all."""
    folder = _profile_dir(profile)
    approved: list = []
    if plan.upgrades:
        if not _can_ask(ctx):
            pending = checklist.write_pending(folder, [c for c, _ in plan.upgrades])
            raise ToolError(
                "this client cannot ask the person directly, so nothing was saved. The upgrades are in "
                f"{pending}. Ask them to read it and run in a terminal: "
                f"uvx honest-cv checklist apply {_quote(folder)} {_quote(pending)}"
            )
        if not isinstance(confirmation, AcceptedElicitation):
            raise ToolError("the person declined the confirmation; nothing was saved")
        approved = _approved(confirmation, plan.upgrades)
    yes = {id(c) for c, _ in approved}
    changes = [c for c, _ in plan.updates] + [c for c, _ in approved]
    saved = store.upsert_skills(folder, changes, confirmed=bool(approved)) if changes else []
    return {
        "saved": [s.name for s in saved],
        "upgrades_confirmed": [c.name for c, _ in approved],
        "upgrades_refused": [c.name for c, _ in plan.upgrades[:ASK_AT_ONCE] if id(c) not in yes],
        "upgrades_not_asked_yet": [c.name for c, _ in plan.upgrades[ASK_AT_ONCE:]],
    }


@mcp.tool(annotations=WRITE)
@_tool_errors
def set_skills(
    ctx: Context,
    skills: Annotated[list[SkillInput], Field(description="The skills to add or change.")],
    confirmation: Annotated[ElicitationResult[ConfirmUpgrade], Resolve(confirm_skills)],
    profile: Profile = None,
) -> dict:
    """Add or change several skills at once. Every upgrade needs `evidence`; the person answers
    "sí" or "no" for each one, up to 10 per question, and only the "sí" ones are saved. Call it
    again with `upgrades_not_asked_yet`. Use it to record skills in groups."""
    plan = _skills_plan(profile, skills)
    if plan.missing_evidence:
        names = ", ".join(c.name for c in plan.missing_evidence)
        raise ToolError(f"raising a level needs evidence; missing for: {names}. Nothing was saved")
    return _save_plan(ctx, profile, plan, confirmation)


@mcp.tool(annotations=READ)
@_tool_errors
def checklist_list() -> dict:
    """The built-in skill checklists, one per kind of profile, to combine with `checklist_new`."""
    return {"checklists": [b.__dict__ for b in checklist.available()]}


@mcp.tool(annotations=WRITE)
@_tool_errors
def checklist_new(
    lists: Annotated[list[str], Field(description="Checklist ids from checklist_list, e.g. backend-jvm.")],
    profile: Profile = None,
    path: Annotated[str | None, Field(description="File to write. Default: <profile>/checklist.md.")] = None,
    overwrite: Annotated[bool, Field(description="Replace the file if it exists.")] = False,
) -> dict:
    """Merge built-in checklists into one Markdown file, without duplicates and prefilled from the
    inventory. The person marks it in their editor; then call `checklist_apply`."""
    out = Path(path).expanduser() if path else _profile_dir(profile) / "checklist.md"
    if out.exists() and not overwrite:
        raise ToolError(f"{out} exists; ask the person before replacing it (overwrite=true)")
    text = checklist.compose(lists, _load(profile))
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "skills": len(checklist.parse(text).items)}


@mcp.tool(annotations=WRITE)
@_tool_errors
def checklist_apply(
    ctx: Context,
    path: Annotated[str, Field(description="A Markdown checklist marked by the person, e.g. <profile>/checklist.md.")],
    confirmation: Annotated[ElicitationResult[ConfirmUpgrade], Resolve(confirm_checklist)],
    profile: Profile = None,
) -> dict:
    """Save the lines the person marked in a checklist. The person answers "sí" or "no" for each
    upgrade with evidence, up to 10 per question: call it again while `upgrades_not_asked_yet`
    is not empty. Lines without evidence come back as `pending_evidence`: ask where they used
    them, in groups, and record them with `set_skills`. Ask about nothing else: unmarked lines
    are for the person to mark in the file, not to go through in the chat. To resume a checklist,
    call this again rather than reading the file."""
    plan = _checklist_plan(profile, path)
    result = _save_plan(ctx, profile, plan, confirmation) if plan.upgrades or plan.updates else {"saved": []}
    summary = plan.summary()
    del summary["upgrades"], summary["updates"]
    return {**result, "saved": len(result["saved"]), **summary}


@mcp.tool(annotations=WRITE)
@_tool_errors
def add_bullet(
    id: Annotated[str, Field(description="Unique bullet id, e.g. ft_k8s.")],
    text_en: Annotated[str, Field(description="The achievement in English, as the person stated it.")],
    profile: Profile = None,
    text_es: Annotated[str | None, Field(description="The same achievement in Spanish.")] = None,
    role: Annotated[str | None, Field(description="Role id from profile.yaml this bullet belongs to.")] = None,
    tags: Annotated[list[str] | None, Field(description="Skills and topics it shows, e.g. Kubernetes.")] = None,
    metrics: Annotated[list[str] | None, Field(description="Numbers it claims, e.g. 40%, kept for review.")] = None,
) -> dict:
    """Add an achievement to the bullet pool. `role` is a role id from profile.yaml; leave it
    out for bullets used only in the Selected Impact section. Use only facts the person stated."""
    text = {"en": text_en, **({"es": text_es} if text_es else {})}
    bullet = Bullet(id=id, role=role, tags=tags or [], metrics=metrics or [], text=text)
    store.add_bullet(_profile_dir(profile), bullet)
    return {"saved": bullet.model_dump(mode="json", exclude_defaults=True)}


@mcp.tool(annotations=WRITE)
@_tool_errors
def set_contact(
    profile: Profile = None,
    name: Annotated[str | None, Field(description="Full name as it should appear on the CV.")] = None,
    email: Annotated[str | None, Field(description="Email for the CV.")] = None,
    phone: Annotated[str | None, Field(description='Phone, e.g. "+52 442 000 0000".')] = None,
    location: TextArg = None,
    links: Annotated[list[str] | None, Field(description="Full list of links: LinkedIn, GitHub, site.")] = None,
) -> dict:
    """Change the contact details given; the others stay as they are. Pass `"clear"` to remove
    an optional field."""
    contact = store.set_contact(
        _profile_dir(profile), name=name, email=email, phone=phone, location=location, links=links
    )
    return {"contact": contact.model_dump(mode="json", exclude_none=True)}


@mcp.tool(annotations=WRITE)
@_tool_errors
def set_profile_details(
    profile: Profile = None,
    certifications: Annotated[
        list[Text] | None, Field(description="The full list of certifications, replacing the current one.")
    ] = None,
    languages: TextArg = None,
) -> dict:
    """Replace the certifications list and/or the spoken-languages line."""
    return store.set_profile_details(_profile_dir(profile), certifications=certifications, languages=languages)


@mcp.tool(annotations=WRITE)
@_tool_errors
def upsert_role(
    id: Annotated[str, Field(description="Short role id, e.g. acme. Bullets point to it.")],
    profile: Profile = None,
    title: TextArg = None,
    company: Annotated[str | None, Field(description="Company name.")] = None,
    start: Year = None,
    end: Annotated[
        str | None, Field(description='Year it ended, e.g. "2024". "present" marks it as the current role.')
    ] = None,
    location: TextArg = None,
    context: TextArg = None,
) -> dict:
    """Add a role, or change the fields given on an existing one. A new role needs `title`,
    `company` and `start`, and goes in date order, newest first. Keep the person's real title."""
    if end is not None and end.strip().casefold() in {"present", "current", "now"}:
        end = store.CLEAR
    role = store.upsert_role(
        _profile_dir(profile), id, title=title, company=company, start=start, end=end,
        location=location, context=context,
    )
    return {"role": role.model_dump(mode="json", exclude_none=True)}


@mcp.tool(annotations=WRITE)
@_tool_errors
def upsert_education(
    institution: Annotated[str, Field(description="School or university.")],
    profile: Profile = None,
    degree: TextArg = None,
    start: Year = None,
    end: Year = None,
) -> dict:
    """Add an education entry, or change the one with the same institution and degree. Say
    honestly whether the degree was completed, e.g. "B.Sc. (unfinished)"."""
    entry = store.upsert_education(_profile_dir(profile), institution, degree=degree, start=start, end=end)
    return {"education": entry.model_dump(mode="json", exclude_none=True)}


@mcp.tool(annotations=WRITE)
@_tool_errors
def save_variant(
    id: Annotated[str, Field(description="Variant id, e.g. backend.")],
    profile: Profile = None,
    extends: Annotated[str | None, Field(description="Variant to inherit from; set only what differs.")] = None,
    title: TextArg = None,
    summary: TextArg = None,
    competencies: Annotated[list[str] | None, Field(description="Short list of core competencies.")] = None,
    impact: Annotated[list[str] | None, Field(description="Bullet ids for Selected Impact.")] = None,
    roles: Annotated[
        dict[str, list[str]] | None, Field(description="Role id -> bullet ids to show, in order.")
    ] = None,
    skills: Annotated[list[SkillGroup] | None, Field(description="Skill groups: a label and skill names.")] = None,
    max_pages: Annotated[int | None, Field(description="Page limit, usually 1 or 2.", ge=1)] = None,
) -> dict:
    """Add a variant or replace it whole: pass every field it should define. A variant without
    `extends` needs `title` and `summary`. See `list_variants` → `own` for what it defines now."""
    fields = {
        "extends": extends, "title": title, "summary": summary, "competencies": competencies,
        "impact": impact, "roles": roles, "skills": skills, "max_pages": max_pages,
    }
    variant = Variant(**{k: v for k, v in fields.items() if v is not None})
    saved = store.save_variant(_profile_dir(profile), id, variant)
    return {"saved": id, "variant": saved.model_dump(mode="json", exclude_none=True)}


@mcp.tool(annotations=READ)
@_tool_errors
def list_variants(profile: Profile = None) -> dict:
    """Variants after `extends:` is applied, with the bullet texts each one uses."""
    source = _load(profile)
    out = {}
    for vid, raw in source.variants.items():
        v = source.resolve(vid)
        out[vid] = {
            "own": raw.model_dump(mode="json", exclude_none=True),
            "extends": raw.extends,
            "title": v.title,
            "max_pages": v.max_pages,
            "competencies": v.competencies,
            "impact": {b: source.bullet(b).text for b in v.impact},
            "roles": {rid: {b: source.bullet(b).text for b in ids} for rid, ids in v.roles.items()},
            "skills": [g.model_dump(mode="json") for g in v.skills],
        }
    unused = sorted({b.id for b in source.bullets} - {
        b for v in out.values() for b in [*v["impact"], *(x for r in v["roles"].values() for x in r)]
    })
    return {"variants": out, "unused_bullets": unused}


@mcp.tool(annotations=WRITE)
@_tool_errors
def build_cv(
    variant: VariantId,
    lang: LangArg = "en",
    profile: Profile = None,
    formats: Annotated[list[Literal["pdf", "docx"]] | None, Field(description="Default: both.")] = None,
    out_dir: Annotated[str | None, Field(description="Output folder. Default: <profile>/out.")] = None,
) -> dict:
    """Render a variant to PDF and/or DOCX (default both) and verify the PDF for ATS safety.
    Files go to `out_dir`, default <profile>/out."""
    folder = _profile_dir(profile)
    out = Path(out_dir).expanduser() if out_dir else folder / "out"
    built = build_mod.build_cv(load(folder), variant, lang, out, tuple(formats or build_mod.FORMATS))
    files = []
    for b in built:
        entry = {"path": str(b.path), "format": b.format}
        if b.report is not None:
            entry |= {
                "pages": b.pages,
                "within_max_pages": b.fits,
                "ats_ok": b.report.ok,
                "failed_checks": [{"name": c.name, "detail": c.detail} for c in b.report.failures],
            }
        files.append(entry)
    return {"variant": variant, "lang": lang, "files": files}


@mcp.tool(annotations=READ)
@_tool_errors
def verify_pdf(
    path: Annotated[str, Field(description="Path to any PDF, made with honest-cv or not.")],
    max_pages: Annotated[int | None, Field(description="Fail the page_count check above this.")] = None,
) -> dict:
    """Check that any PDF is ATS-safe and return the text an ATS would extract."""
    report = verify(Path(path).expanduser(), max_pages=max_pages)
    return {
        "ok": report.ok,
        "pages": report.pages,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks],
        "text": report.text,
    }


@mcp.tool(annotations=READ)
@_tool_errors
def check_claims(
    text: Annotated[str, Field(description="The draft: a cover letter, a summary, any text about the person.")],
    profile: Profile = None,
    keywords: Annotated[
        list[str] | None, Field(description="Keywords of the job post, so its technologies are checked too.")
    ] = None,
) -> dict:
    """Check a draft against the profile. `problems` must be fixed before `build_letter`: a skill
    the person marked X, or a familiarity (F) skill not called familiarity in its sentence.
    `warnings` are for the person: a technology the profile doesn't show, or a number found
    nowhere in it. Fix them by removing or qualifying the claim, never by adding skills."""
    return letter.check_claims(text, _load(profile), keywords).to_dict()


@mcp.tool(annotations=WRITE)
@_tool_errors
def build_letter(
    company: Annotated[str, Field(description="Company name, as in the job post.")],
    role: Annotated[str, Field(description="Job title, as in the job post.")],
    paragraphs: Annotated[list[str], Field(description="The body, one string per paragraph, approved by the person.")],
    lang: LangArg = "en",
    profile: Profile = None,
    recipient: Annotated[str | None, Field(description="Hiring manager or team, if the post names one.")] = None,
    greeting: Annotated[str | None, Field(description="Default: Dear Hiring Team, / Estimado equipo de selección:")] = None,
    closing: Annotated[str | None, Field(description="Default: Sincerely, / Atentamente,")] = None,
    keywords: Annotated[list[str] | None, Field(description="Keywords of the job post, for check_claims.")] = None,
    formats: Annotated[list[Literal["pdf", "docx"]] | None, Field(description="Default: both.")] = None,
    out_dir: Annotated[str | None, Field(description="Output folder. Default: <profile>/out.")] = None,
) -> dict:
    """Render a cover letter to PDF and/or DOCX, one page, with the CV's ATS checks. It runs
    `check_claims` first and refuses while there are problems."""
    folder = _profile_dir(profile)
    source = load(folder)
    draft = letter.make(source, lang, company, role, paragraphs, recipient=recipient, greeting=greeting, closing=closing)
    claims = letter.check_claims("\n".join([draft.greeting, *draft.paragraphs, draft.closing]), source, keywords)
    if not claims.ok:
        found = "; ".join(f"{p.term} ({p.kind}): {p.sentence}" for p in claims.problems)
        raise ToolError(f"the letter claims what the profile does not support, so it was not built: {found}")
    out = Path(out_dir).expanduser() if out_dir else folder / "out"
    files = []
    for b in letter.build(draft, out, tuple(formats or letter.FORMATS)):
        entry = {"path": str(b.path), "format": b.format}
        if b.report is not None:
            entry |= {"pages": b.report.pages, "ats_ok": b.report.ok,
                      "failed_checks": [{"name": c.name, "detail": c.detail} for c in b.report.failures]}
        files.append(entry)
    return {"files": files, "warnings": claims.to_dict()["warnings"]}


def _keywords(keywords: list[str], preferred: list[str] | None) -> list[score_mod.Keyword]:
    return [score_mod.Keyword(k) for k in keywords] + [score_mod.Keyword(k, False) for k in preferred or []]


@mcp.tool(annotations=READ)
@_tool_errors
def score_job(
    keywords: Keywords,
    profile: Profile = None,
    preferred: Preferred = None,
    lang: LangArg = "en",
    variants: Annotated[list[str] | None, Field(description="Variant ids to score. Default: all.")] = None,
) -> dict:
    """Keyword coverage of each variant, best first. Extract the job post's keywords yourself:
    `keywords` are the required ones, `preferred` the nice-to-haves. Use the post's own wording."""
    scores = score_mod.score_job(_load(profile), _keywords(keywords, preferred), lang, variants)
    return {"scores": [s.to_dict() for s in scores]}


@mcp.tool(annotations=READ)
@_tool_errors
def gap_report(
    variant: VariantId,
    keywords: Keywords,
    profile: Profile = None,
    preferred: Preferred = None,
    lang: LangArg = "en",
) -> dict:
    """Missing keywords grouped by what can honestly be done:
    in_inventory_not_in_cv (a P/L skill or a pool bullet shows it: add it, see unused_bullets;
    if that list is empty, the term only needs to appear in the summary or competencies),
    familiarity_only (only claim it as familiarity), not_in_inventory (do not claim it)."""
    groups = score_mod.gap_report(_load(profile), variant, lang, _keywords(keywords, preferred))
    return {k: [r.__dict__ for r in v] for k, v in groups.items()}


PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str, **values: str) -> str:
    return Template((PROMPTS / f"{name}.md").read_text(encoding="utf-8")).substitute(values)


def _profile_label(profile: str | None) -> str:
    return profile or os.environ.get("HONEST_CV_PROFILE") or "(ask the person where to keep it)"


@mcp.prompt(title="Honest cover letter")
def cover_letter(job_post: str, profile: str | None = None, lang: str = "en") -> str:
    """Write a cover letter for a job post from the person's real bullets and skills."""
    return _prompt("cover_letter", profile=_profile_label(profile), lang=lang, job_post=job_post)


@mcp.prompt(title="Honest CV interview")
def interview(profile: str | None = None, langs: str = "en, es") -> str:
    """Guided interview that fills the skill inventory and the bullet pool, one question at a time."""
    return _prompt("interview", profile=_profile_label(profile), langs=langs)


@mcp.prompt(title="Tailor CV for a job post")
def tailor_for_job(job_post: str, profile: str | None = None, lang: str = "en") -> str:
    """Score the variants against a job post, explain the honest gaps, adjust a variant and rebuild."""
    return _prompt("tailor_for_job", profile=_profile_label(profile), lang=lang, job_post=job_post.strip())


def main() -> None:
    mcp.run("stdio")
