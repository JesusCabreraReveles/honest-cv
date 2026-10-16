"""MCP server over stdio. Deterministic and keyless: the client's LLM extracts
keywords and runs the interview; this server validates, builds, verifies and
measures.

Every tool takes a `profile` folder. When it is omitted, HONEST_CV_PROFILE is used.
"""

from __future__ import annotations

import datetime
import functools
import inspect
import json
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

from honest_cv import __version__, applications, checklist, export, importer, letter, linkedin, store
from honest_cv import build as build_mod
from honest_cv import prep as prep_mod
from honest_cv import score as score_mod
from honest_cv.model import LEVEL_RANK, Bullet, Lang, Level, SkillGroup, Source, Text, Variant, explain, load
from honest_cv.verify import verify_pdf as verify

INSTRUCTIONS = """\
honest-cv turns a person's real experience into ATS-safe CVs, one variant per type of role.
Talk to the person in the language they write in, for the whole conversation. These tools answer
in English and CVs may be in English: neither is a reason to switch. Only the person can change it.

Honesty rules, enforced by this server:
- Skill levels: P (production), L (own project/lab), F (familiarity, always labeled), X (never shown).
- Raising a skill's level needs written evidence and the person's own confirmation, which the
  server asks for directly. Never invent experience, metrics or skills.
- If every role has an end date, the person is not working now: summaries, letters and LinkedIn
  texts speak of that work in the past tense ("led", not "I lead").
- Evidence is where and how, in the person's words. A bare "yes, I used them" to a list is not
  evidence: ask where and how for each one before recording it, and never fill the gap with a
  guess like their current employer or "(confirmed by the person)".

Edit the profile through the tools (set_contact, upsert_role, upsert_education,
set_profile_details, add_bullet, set_skill, save_variant), not by writing its files: the tools
validate every change.

Typical flow: get_inventory and list_variants to learn the profile; for a job post, extract its
keywords yourself, call score_job, then gap_report on the best variant; propose edits the person
approves; build_cv, which also verifies the PDF. If a check fails, never reword the person's
text to pass it: report it, since it is probably a bug in honest-cv.

Skills: for many at once, use a checklist (checklist_list, checklist_new, checklist_apply), in
the person's language (lang). Any profession works: the person's own templates in <profile>/checklists/ are listed too, with
their synonyms. Then ask for their biggest achievements, which usually cover several skills, and
after that for one real achievement for each of `key_skills_without_achievements`.

The person may dictate: before saving, read back technology and company names and every
number as you understood them, and let them correct you.

Applications: after build_cv or build_letter, offer log_application; record news (interview,
offer, rejection) the same way. list_applications shows the ones waiting for an answer.
When one gets an interview, offer interview_prep: STAR answers only from the stories it returns.

Also: linkedin_profile for LinkedIn texts (check any rewording with check_claims), and
export_json_resume for other CV tools.

Cover letters: draft only the body paragraphs; build_letter adds the name, contact details,
date, greeting and closing from the profile, so never ask for them or leave placeholders. Run
check_claims on the draft and show its findings before showing the letter: a claim the person
cannot back goes into the profile first, or out of the letter.
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

REMOVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
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


def _confirm_form(
    upgrades: list[tuple[store.SkillChange, Level]], new: frozenset[str] = frozenset(),
    notes: dict[str, str] | None = None,
) -> type[ConfirmUpgrade]:
    """`new`: see `checklist.new_skills`. `notes`: the person's own notes on these skills,
    shown first, since one may say why they lowered it. Clients cut long titles, so the
    evidence goes in the description."""
    notes = notes or {}

    def description(c: store.SkillChange) -> str:
        note = f"Your note: {notes[c.name]}. " if notes.get(c.name) else ""
        return f"{note}{c.evidence} — sí only if it is true and you can defend it in an interview."

    fields = {
        f"u{i}": (
            Literal["no", "sí"],
            Field(
                title=f"{c.name}: {'new' if c.name in new else old.value} → {c.level.value}",
                description=description(c),
            ),
        )
        for i, (c, old) in enumerate(upgrades[:ASK_AT_ONCE], start=1)
    }
    return create_model("ConfirmUpgrade", __base__=ConfirmUpgrade, **fields)


def _ask(upgrades: list[tuple[store.SkillChange, Level]], source: Source) -> Elicit[ConfirmUpgrade]:
    shown = min(len(upgrades), ASK_AT_ONCE)
    more = f" ({len(upgrades) - shown} more next time)" if len(upgrades) > shown else ""
    notes = {c.name: s.notes for c, _ in upgrades if (s := source.inventory.get(c.name)) and s.notes}
    form = _confirm_form(upgrades, checklist.new_skills(upgrades, source), notes)
    return Elicit(f"honest-cv: confirm {shown} skill upgrade(s), one per field{more}.", form)


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
    return _ask(_single(name, level, evidence, old), _load(profile))


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


def _ask_for(ctx: Context, plan: checklist.Plan, profile: str | None) -> Elicit[ConfirmUpgrade] | NotAsked:
    if not plan.upgrades or not _can_ask(ctx):
        return NotAsked()  # the tool reports why
    return _ask(plan.upgrades, _load(profile))


def confirm_skills(ctx: Context, skills: list, profile: str | None) -> Elicit[ConfirmUpgrade] | NotAsked:
    try:
        plan = _skills_plan(profile, skills)
    except (ToolError, ValueError):
        return NotAsked()
    # set_skills saves nothing when an upgrade lacks evidence, so don't ask then.
    return NotAsked() if plan.missing_evidence else _ask_for(ctx, plan, profile)


def confirm_checklist(ctx: Context, path: str, profile: str | None) -> Elicit[ConfirmUpgrade] | NotAsked:
    try:
        return _ask_for(ctx, _checklist_plan(profile, path), profile)
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


@mcp.tool(annotations=WRITE)
@_tool_errors
def import_profile(
    path: Annotated[str, Field(description="A JSON Resume (.json), a LinkedIn data export (.zip) or a LinkedIn profile PDF.")],
    profile: Profile = None,
    dry_run: Annotated[bool, Field(description="Report what would be added without writing.")] = False,
) -> dict:
    """Import contact, roles with their achievements, education, certifications and languages.
    Only what the profile lacks is added; nothing is overwritten. Skills come without a level, so
    they go to <profile>/imported-skills.md, a checklist for the person to mark, never to the
    inventory. Imported bullets are tagged `imported`: review them with the person. `path` may be
    the folder of an unzipped LinkedIn export. Tell the person the result's `note` if there is one.

    For a PDF nothing is written: its text comes back for you to organize with the editing tools
    (see the import_linkedin_pdf prompt)."""
    file = Path(path).expanduser()
    if file.suffix.lower() == ".pdf":
        from pdfminer.high_level import extract_text

        return {"format": "pdf", "text": extract_text(str(file)),
                "next": "Propose contact, roles, education and achievements from this text; save what the person "
                        "approves with set_contact, upsert_role, upsert_education, set_profile_details and "
                        "add_bullet; pass the skills to checklist_new as extra."}
    report = importer.merge(_profile_dir(profile), importer.read(file), dry_run=dry_run)
    return {"dry_run": dry_run, **report.__dict__}


@mcp.tool(annotations=READ)
@_tool_errors
def checklist_list(
    profile: Profile = None,
    lang: Annotated[Lang, Field(description="The person's language: the built-in templates in it, where translated.")] = "en",
) -> dict:
    """The skill checklist templates to combine with `checklist_new`: the built-in ones, one per
    kind of profile, and the person's own in <profile>/checklists/ (origin "yours"). Any
    profession works: a template is a Markdown list in the same format."""
    try:
        folder = _profile_dir(profile)
    except ToolError:
        folder = None
    return {"checklists": [b.__dict__ for b in checklist.available(folder, lang)]}


@mcp.tool(annotations=WRITE)
@_tool_errors
def checklist_new(
    lists: Annotated[
        list[str], Field(description="Ids from checklist_list, e.g. backend-jvm, or paths to .md templates.")
    ],
    profile: Profile = None,
    path: Annotated[str | None, Field(description="File to write. Default: <profile>/checklist.md.")] = None,
    overwrite: Annotated[bool, Field(description="Replace the file if it exists.")] = False,
    extra: Annotated[
        list[str] | None, Field(description="More skill names to ask about, e.g. found in an imported profile.")
    ] = None,
    lang: Annotated[
        Lang, Field(description="The person's language: the file's headings and the built-in templates in it.")
    ] = "en",
) -> dict:
    """Merge checklist templates into one Markdown file, without duplicates and prefilled from the
    inventory. The person marks it in their editor; then call `checklist_apply`. `lists` may be
    empty when `extra` names the skills. Use the person's language: skill names in another
    language still match job posts in English, through their synonyms."""
    out = Path(path).expanduser() if path else _profile_dir(profile) / "checklist.md"
    if out.exists() and not overwrite:
        raise ToolError(f"{out} exists; ask the person before replacing it (overwrite=true)")
    folder = _profile_dir(profile)
    text = checklist.compose(lists, load(folder), extra, folder, lang)
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
    call this again rather than reading the file.

    `skills_without_achievements` are P and L skills from this checklist that no bullet shows;
    `key_skills_without_achievements` are the P ones among the ★ section and the skills a variant
    shows. Once the checklist is done, ask for the person's biggest achievements first: one
    usually covers several skills. Then ask about the key skills still uncovered. The rest wait
    for a job post that asks for them (`gap_report` → `no_achievement`). Save each with
    `add_bullet`. If there is none, leave it; never write one for them."""
    plan = _checklist_plan(profile, path)
    result = _save_plan(ctx, profile, plan, confirmation) if plan.upgrades or plan.updates else {"saved": []}
    summary = plan.summary()
    del summary["upgrades"], summary["updates"]
    items = checklist.read(path).items
    source = _load(profile)
    missing = checklist.unbacked(source, [i.name for i in items])
    key = set(checklist.unbacked(source, checklist.key_skills(source, items), levels=(Level.PRODUCTION,)))
    return {**result, "saved": len(result["saved"]), **summary,
            "key_skills_without_achievements": [n for n in missing if n in key],
            "skills_without_achievements": missing}


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
    courses: Annotated[
        list[Text] | None,
        Field(description="The full list of courses and trainings without an exam, replacing the current one. "
                          "A course is never a certification."),
    ] = None,
    languages: TextArg = None,
) -> dict:
    """Replace the certifications list, the courses list and/or the spoken-languages line."""
    return store.set_profile_details(
        _profile_dir(profile), certifications=certifications, courses=courses, languages=languages
    )


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
def upsert_publication(
    id: Annotated[str, Field(description="Short id, e.g. book_adr_kit. Variants list these ids.")],
    profile: Profile = None,
    title: Annotated[str | None, Field(description="The title as published.")] = None,
    venue: Annotated[
        str | None,
        Field(description='Where it is published, e.g. "Amazon (self-published)" or "Medium". '
                          "Never a publisher it did not have."),
    ] = None,
    year: Year = None,
    url: Annotated[str | None, Field(description="A link to it.")] = None,
) -> dict:
    """Add a book, article or paper the person wrote, or change the fields given of the one with
    this id. Every variant shows all publications unless it lists the ones it wants."""
    entry = store.upsert_publication(_profile_dir(profile), id, title=title, venue=venue, year=year, url=url)
    return {"publication": entry.model_dump(mode="json", exclude_none=True)}


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
    publications: Annotated[
        list[str] | None,
        Field(description="Publication ids to show, in order; [] shows none. Not set: all of them."),
    ] = None,
    max_pages: Annotated[int | None, Field(description="Page limit, usually 1 or 2.", ge=1)] = None,
) -> dict:
    """Add a variant or replace it whole: pass every field it should define. A variant without
    `extends` needs `title` and `summary`. See `list_variants` → `own` for what it defines now."""
    fields = {
        "extends": extends, "title": title, "summary": summary, "competencies": competencies,
        "impact": impact, "roles": roles, "skills": skills, "publications": publications,
        "max_pages": max_pages,
    }
    variant = Variant(**{k: v for k, v in fields.items() if v is not None})
    saved = store.save_variant(_profile_dir(profile), id, variant)
    return {"saved": id, "variant": saved.model_dump(mode="json", exclude_none=True)}


@mcp.tool(annotations=REMOVE)
@_tool_errors
def remove_skill(
    name: Annotated[str, Field(description="Skill name as in the inventory.")],
    profile: Profile = None,
) -> dict:
    """Delete a skill from the inventory, e.g. a duplicate or a misspelling. It also leaves the
    variants' skill groups and same-named competencies. To say the person doesn't have a skill,
    prefer set_skill with level X: it keeps gap reports honest. Ask the person first."""
    return store.remove_skill(_profile_dir(profile), name)


@mcp.tool(annotations=REMOVE)
@_tool_errors
def remove_bullet(
    id: Annotated[str, Field(description="Bullet id.")],
    profile: Profile = None,
) -> dict:
    """Delete an achievement from the pool and from every variant that uses it. Ask the person first."""
    return store.remove_bullet(_profile_dir(profile), id)


@mcp.tool(annotations=REMOVE)
@_tool_errors
def remove_publication(
    id: Annotated[str, Field(description="Publication id from profile.yaml.")],
    profile: Profile = None,
) -> dict:
    """Delete a publication and its place in every variant. Ask the person first."""
    return store.remove_publication(_profile_dir(profile), id)


@mcp.tool(annotations=REMOVE)
@_tool_errors
def remove_role(
    id: Annotated[str, Field(description="Role id from profile.yaml.")],
    profile: Profile = None,
    with_bullets: Annotated[
        bool, Field(description="Also delete the role's bullets. Only if the person agreed to lose them.")
    ] = False,
) -> dict:
    """Delete a role and its place in every variant. A role with bullets is refused unless
    `with_bullets` is true. Ask the person first."""
    return store.remove_role(_profile_dir(profile), id, with_bullets=with_bullets)


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
            "publications": [p.id for p in source.publications(v)],
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


@mcp.tool(annotations=WRITE)
@_tool_errors
def export_json_resume(
    variant: VariantId,
    lang: LangArg = "en",
    profile: Profile = None,
    out_dir: Annotated[str | None, Field(description="Output folder. Default: <profile>/out.")] = None,
) -> dict:
    """Export a variant as JSON Resume, for other CV tools and sites. Same rules as the CV:
    X skills never appear and F skills only in a "Familiarity" group with that level."""
    folder = _profile_dir(profile)
    out = Path(out_dir).expanduser() if out_dir else folder / "out"
    return {"path": str(export.export(load(folder), variant, lang, out))}


@mcp.tool(annotations=WRITE)
@_tool_errors
def linkedin_profile(
    variant: VariantId,
    lang: LangArg = "en",
    profile: Profile = None,
    out_dir: Annotated[str | None, Field(description="Output folder. Default: <profile>/out.")] = None,
    headline: Annotated[
        str | None, Field(description="A polished headline the person approved, to save instead of the draft.")
    ] = None,
    about: Annotated[
        str | None, Field(description="A polished About the person approved, to save instead of the draft.")
    ] = None,
) -> dict:
    """LinkedIn texts from a variant, within LinkedIn's limits: headline, About, each position's
    description from its bullets, and the skills (P and L only: LinkedIn can't label
    familiarity). Also writes them to a Markdown file to copy from. Once the person approves a
    polished headline or About, call it again with them: they are checked like a letter and
    saved in that file, so the person keeps the final version."""
    folder = _profile_dir(profile)
    source = load(folder)
    suggestion = linkedin.suggest(source, variant, lang)
    warnings = []
    for name, text, limit in (("headline", headline, linkedin.HEADLINE), ("about", about, linkedin.ABOUT)):
        if text is None:
            continue
        text = text.strip()
        if len(text) > limit:
            raise ToolError(f"{name} has {len(text)} characters; LinkedIn allows {limit}. Nothing was saved.")
        claims = letter.check_claims(text, source)
        if not claims.ok:
            raise ToolError(f"{name} makes claims the profile does not support; nothing was saved: "
                            + json.dumps(claims.to_dict()["problems"], ensure_ascii=False))
        warnings += [{**w, "text": name} for w in claims.to_dict()["warnings"]]
        setattr(suggestion, name, linkedin.Text(text, limit))
    path = linkedin.write(suggestion, source.profile.contact.name,
                          Path(out_dir).expanduser() if out_dir else folder / "out")
    return {**suggestion.to_dict(), "path": str(path), **({"warnings": warnings} if warnings else {})}


StatusArg = Literal["draft", "applied", "interview", "offer", "rejected", "withdrawn"]


@mcp.tool(annotations=WRITE)
@_tool_errors
def log_application(
    company: Annotated[str, Field(description="Company name, as in the job post.")],
    role: Annotated[str, Field(description="Job title, as in the job post.")],
    profile: Profile = None,
    status: Annotated[StatusArg | None, Field(description="New status. A change is kept in the history.")] = None,
    date: Annotated[str | None, Field(description="Date of this status, YYYY-MM-DD. Default: today.")] = None,
    url: Annotated[str | None, Field(description="Link to the job post.")] = None,
    variant: Annotated[str | None, Field(description="Variant id of the CV sent.")] = None,
    lang: Annotated[Lang | None, Field(description="Language of the CV sent.")] = None,
    files: Annotated[list[str] | None, Field(description="Paths of the CV and letter sent. A copy is kept in <profile>/sent/.")] = None,
    notes: Annotated[str | None, Field(description="Contact person, salary range, next step... Added to the notes already there.")] = None,
    post: Annotated[
        str | None, Field(description="The job post's full text, as the person gave it. Saved to <profile>/posts/.")
    ] = None,
    prep: Annotated[
        list[str] | None,
        Field(description="What to prepare for the interview: skills to back with an example, gaps to "
                          "explain, questions to ask. Replaces the list."),
    ] = None,
) -> dict:
    """Record a job application, or update the one for the same company and role. Fields not
    given keep their value. Use it after build_cv or build_letter when the person sends them,
    and when they tell you what happened (interview, offer, rejection). Save the post's text,
    since links expire, and any advice you gave for the interview as `prep`, so the person
    can find both later. Each file is copied to <profile>/sent/<id>/, so the record keeps what
    was sent even after the next build; `not_found` lists the paths it could not copy."""
    try:
        when = datetime.date.fromisoformat(date) if date else None
    except ValueError:
        raise ToolError(f"date must be YYYY-MM-DD, e.g. 2026-10-14; got {date!r}") from None
    folder = _profile_dir(profile)
    app = applications.log(folder, company, role, status=status, when=when, url=url,
                           variant=variant, lang=lang, files=files, notes=notes, post=post, prep=prep)
    out: dict = {"application": app.model_dump(mode="json", exclude_defaults=True)}
    if missing := [f for f in app.files if not (folder / f).is_file()]:
        out["not_found"] = missing
    return out


@mcp.tool(annotations=READ)
@_tool_errors
def list_applications(
    profile: Profile = None,
    status: Annotated[list[StatusArg] | None, Field(description="Only these statuses. Default: all.")] = None,
) -> dict:
    """The person's applications, most recently updated first, with `days_since_update`, a count
    per status, and `waiting`: open applications with no news for 14 days or more."""
    return applications.listing(_profile_dir(profile), status)


@mcp.tool(annotations=WRITE)
@_tool_errors
def interview_prep(
    application: Annotated[str, Field(description="Application id, from list_applications.")],
    profile: Profile = None,
    keywords: Annotated[
        list[str] | None,
        Field(description="Required keywords from the job post, in its own wording. Leave out on the "
                          "first call to get the saved post's text."),
    ] = None,
    preferred: Preferred = None,
    notes: Annotated[
        str | None,
        Field(description="The prep notes the person approved, in Markdown. Saved to "
                          "<profile>/prep/<application>.md, replacing earlier notes."),
    ] = None,
) -> dict:
    """What the person can honestly say in the interview for one application. Returns the
    application, the saved job post's text and, for each keyword, their level, evidence and
    `stories`: the bullets that show it, the ones in the CV they sent first. `standing` says
    how to prepare it: strong (tell a story from those bullets), no_achievement (find a real
    example), marked_pending (marked in their checklist, ask for the evidence), familiarity
    (say it is familiarity), lacking (say so honestly). Every story must come from `stories`."""
    folder = _profile_dir(profile)
    source = _load(profile)
    app = prep_mod.find(folder, application)
    out = prep_mod.summary(source, app, _keywords(keywords or [], preferred))
    if notes is not None:
        out["notes_file"] = str(prep_mod.save(folder, app, notes))
    return out


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
    familiarity_only (only claim it as familiarity), not_in_inventory (do not claim it).
    `no_achievement`: skills the post asks for that the person has at P or L but no bullet
    shows; this is the moment to ask for one real achievement each.
    `marked_in_checklist`: keywords the person already marked in <profile>/checklist.md, still
    pending evidence, so they appear above as missing or familiarity. Ask where they used each
    one instead of treating it as new; it is saved only with evidence and their confirmation."""
    source = _load(profile)
    groups = score_mod.gap_report(source, variant, lang, _keywords(keywords, preferred))
    out = {k: [r.__dict__ for r in v] for k, v in groups.items()}
    names = [*keywords, *(preferred or [])]
    return {**out, "no_achievement": checklist.unbacked(source, names),
            "marked_in_checklist": checklist.marked_pending(source, names)}


PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str, **values: str) -> str:
    return Template((PROMPTS / f"{name}.md").read_text(encoding="utf-8")).substitute(values)


def _profile_label(profile: str | None) -> str:
    return profile or os.environ.get("HONEST_CV_PROFILE") or "(ask the person where to keep it)"


@mcp.prompt(title="Honest cover letter")
def cover_letter(job_post: str, profile: str | None = None, lang: str = "en") -> str:
    """Write a cover letter for a job post from the person's real bullets and skills."""
    return _prompt("cover_letter", profile=_profile_label(profile), lang=lang, job_post=job_post)


@mcp.prompt(title="Import a LinkedIn profile PDF")
def import_linkedin_pdf(path: str, profile: str | None = None) -> str:
    """Turn the PDF from LinkedIn's "Save to PDF" into a profile, with the person's approval."""
    return _prompt("import_linkedin_pdf", profile=_profile_label(profile), path=path)


@mcp.prompt(name="linkedin_profile", title="LinkedIn profile from a variant")
def linkedin_profile_prompt(variant: str, profile: str | None = None, lang: str = "en") -> str:
    """Headline, About, positions and skills for LinkedIn, from a variant, without adding claims."""
    return _prompt("linkedin_profile", profile=_profile_label(profile), lang=lang, variant=variant)


@mcp.prompt(name="interview_prep", title="Prepare a job interview")
def interview_prep_prompt(application: str, profile: str | None = None) -> str:
    """Likely questions, STAR stories from the person's own achievements and honest answers for
    the gaps, for an application they logged."""
    return _prompt("interview_prep", profile=_profile_label(profile), application=application)


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
