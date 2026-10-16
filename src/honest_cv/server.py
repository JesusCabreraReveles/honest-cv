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
Profile = Annotated[str | None, Field(description="Path of the profile folder. Leave it out to use the server's default (--profile or HONEST_CV_PROFILE).")]
LangArg = Annotated[Lang, Field(description="Language of the output: en (English) or es (Spanish).")]
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
    """Create a new profile folder with empty, commented YAML templates (profile, bullets,
    skills, variants). Use it once, before anything else, when the person has no profile; to start
    from LinkedIn or a JSON Resume, call import_profile afterwards. Refuses an existing profile and
    overwrites nothing. Returns `created`: the files written."""
    created = store.init_profile(_profile_dir(profile))
    return {"created": [str(p) for p in created]}


@mcp.tool(annotations=READ)
@_tool_errors
def get_inventory(profile: Profile = None) -> dict:
    """Read the person's skill inventory. Use it at the start of a session and before
    proposing skill changes; for CV content (roles, bullets, variants) use list_variants instead.
    Returns `levels` (what P, L, F and X mean) and `skills` grouped by level, each with its
    years, last_used_year, evidence, aliases and notes. Read-only."""
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
    """Add or change one skill in the inventory. Use it for a single skill; for several at
    once use set_skills, and for a whole marked list use checklist_apply. Raising a level (a new skill
    counts as rising from X) needs `evidence`, and the server asks the person to confirm before saving;
    lowering is always allowed. Returns `saved` (the stored skill) and `previous_level`."""
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
    """Add or change several skills in one call, for example a group the person just told
    you about. Use set_skill for one skill and checklist_apply for a marked checklist. Every upgrade
    needs `evidence`; the person confirms upgrades in a form, up to 10 per call, and only those they
    answer "sí" are saved. Returns `saved`, `upgrades_confirmed`, `upgrades_refused` and
    `upgrades_not_asked_yet`: when that list is not empty, call set_skills again with those skills."""
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
    """Import an existing CV into the profile: a JSON Resume (.json), a LinkedIn data export
    (.zip or its unzipped folder) or a LinkedIn profile PDF. Use it at the start, right after
    init_profile, instead of typing everything; run it first with `dry_run`. Adds contact, roles with
    their achievements, education, certifications, courses, publications and languages; only what the
    profile lacks, never overwriting. Skills arrive without a level, so they go to
    <profile>/imported-skills.md for the person to mark, never to the inventory. Imported bullets are
    tagged `imported`: review them with the person. Returns what was added and an optional `note` to
    pass on. For a PDF nothing is written: it returns the `text`, to organize with the editing tools
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
    """List the skill checklist templates the person can combine. Use it before
    checklist_new, to let the person pick the ones that fit their profession. Returns `checklists`:
    each with its `id`, `title`, `description`, number of `skills` and `origin` ("built-in", or
    "yours" for templates in <profile>/checklists/). Any profession works. Pass `lang` in the
    person's language to get the translated templates. Read-only."""
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
    """Write a checklist file for the person to mark in their editor, merged from the
    templates picked in checklist_list, without duplicates and prefilled from the inventory. Use it
    when the person has many skills: it is much faster than asking one by one. Next step: once they
    have marked it, call checklist_apply. Refuses to replace an existing file unless `overwrite`.
    `lists` may be empty when `extra` names the skills. Returns the file's `path` and its number of
    `skills`."""
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
    """Save the skills the person marked in a checklist file. Use it after checklist_new,
    once the person says they are done, and again to resume. Lines that keep or lower a level are
    saved at once; upgrades with evidence are confirmed in a form, up to 10 per call: call again while
    `upgrades_not_asked_yet` is not empty. Returns the counts saved, `pending_evidence` (marked lines
    without evidence: ask where they used them, in groups, and save with set_skills),
    `skills_without_achievements` and `key_skills_without_achievements`.

    Ask about nothing else: unmarked lines are for the person to mark in the file. After the
    checklist, ask for the person's biggest achievements first, since one usually covers several
    skills, then for the key skills still without one; save each with add_bullet. The rest wait for a
    job post that asks for them (gap_report → `no_achievement`). Never write an achievement for
    them."""
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
    """Add one achievement to the bullet pool, the material every CV variant picks from. Use it
    after the person approves the wording, one bullet per call; to change which bullets a CV shows,
    use save_variant. `role` is a role id from upsert_role; leave it out for bullets used only in
    Selected Impact. Use only facts the person stated, never invented numbers. Returns `saved`."""
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
    links: Annotated[list[str] | None, Field(description="All the links to show, e.g. LinkedIn, GitHub, a site. Replaces the current list.")] = None,
) -> dict:
    """Update the person's contact details on the CV. Use it for name, email, phone,
    location and links; roles, education and the rest have their own tools. Only the fields given
    change; pass "clear" to remove an optional one. `links` replaces the whole list. Returns the
    `contact` as saved in profile.yaml."""
    contact = store.set_contact(
        _profile_dir(profile), name=name, email=email, phone=phone, location=location, links=links
    )
    return {"contact": contact.model_dump(mode="json", exclude_none=True)}


@mcp.tool(annotations=WRITE)
@_tool_errors
def set_profile_details(
    profile: Profile = None,
    certifications: Annotated[
        list[Text] | None, Field(description="All the certifications, replacing the current list. Leave out to keep it.")
    ] = None,
    courses: Annotated[
        list[Text] | None,
        Field(description="All the courses and trainings without an exam, replacing the current list; leave out to keep it. "
                          "A course is never a certification."),
    ] = None,
    languages: TextArg = None,
) -> dict:
    """Replace the certifications, courses or spoken-languages line of the profile.
    Use it for those three lists only; roles, education and publications have their own tools. Each
    list you pass replaces the current one in full; leave a field out to keep it. A course or
    training without an exam goes in `courses`, never in `certifications`. Returns the saved
    values."""
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
    """Add a job role, or change some fields of an existing one by its `id`. Use it while
    interviewing the person about their work history; their achievements go in with add_bullet,
    pointing to this id. A new role needs `title`, `company` and `start`; roles stay in date order,
    newest first. Keep the person's real title. Returns the `role` as saved."""
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
    """Add an education entry, or change the one with the same institution and degree.
    Use it for degrees and formal studies; courses and certifications go in set_profile_details. Say
    honestly whether the degree was completed, e.g. "B.Sc. (unfinished)". Returns the `education`
    entry as saved."""
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
    """Add a book, article or paper the person wrote, or change some fields of the one
    with this `id`. Use it when the person mentions something they published; courses and
    certifications go in set_profile_details. Every variant shows all publications unless it lists the
    ones it wants (save_variant → `publications`). Returns the `publication` as saved."""
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
    """Create or replace a CV variant: the plan for one kind of role (title, summary, which
    bullets and skills to show). Use it to set up a variant or tailor one to a job post; read the
    current ones with list_variants first. It replaces the variant whole, so pass every field it
    should define (list_variants → `own` shows them). A variant without `extends` needs `title` and
    `summary`. Every reference is checked before saving. Returns `saved` and the `variant`."""
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
    """Delete a skill from the inventory, e.g. a duplicate or a misspelling, and from the
    variants' skill groups and competencies. Use it only for mistakes: to record that the person
    doesn't have a skill, use set_skill with level X instead, which keeps gap reports honest. Ask the
    person first; it cannot be undone. Returns what was removed and `variants_updated`."""
    return store.remove_skill(_profile_dir(profile), name)


@mcp.tool(annotations=REMOVE)
@_tool_errors
def remove_bullet(
    id: Annotated[str, Field(description="Bullet id.")],
    profile: Profile = None,
) -> dict:
    """Delete an achievement from the pool and from every variant that uses it. Use it when
    the person wants it gone; to stop showing it in one CV, change that variant with save_variant
    instead. Ask the person first; it cannot be undone. Returns what was removed and `variants_updated`."""
    return store.remove_bullet(_profile_dir(profile), id)


@mcp.tool(annotations=REMOVE)
@_tool_errors
def remove_publication(
    id: Annotated[str, Field(description="Publication id from profile.yaml.")],
    profile: Profile = None,
) -> dict:
    """Delete a publication from the profile and from every variant that lists it. To
    hide it from one CV only, change that variant's `publications` with save_variant instead. Ask the
    person first; it cannot be undone. Returns what was removed and `variants_updated`."""
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
    """Delete a role from the profile and from every variant. A role that still has bullets
    is refused unless `with_bullets` is true, which deletes them too. To hide a role from one CV, edit
    that variant with save_variant instead. Ask the person first; it cannot be undone. Returns what was
    removed and `variants_updated`."""
    return store.remove_role(_profile_dir(profile), id, with_bullets=with_bullets)


@mcp.tool(annotations=READ)
@_tool_errors
def list_variants(profile: Profile = None) -> dict:
    """Read every CV variant, with `extends` already applied and the text of each bullet
    it uses. Use it before save_variant, build_cv or score_job, to know what each CV contains.
    Returns `variants` (with `own`: the fields each one defines itself) and `unused_bullets`:
    achievements no variant shows yet. Read-only."""
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
    formats: Annotated[list[Literal["pdf", "docx"]] | None, Field(description="Formats to write: pdf, docx or both. Default: both.")] = None,
    out_dir: Annotated[str | None, Field(description="Output folder. Default: <profile>/out.")] = None,
) -> dict:
    """Render a CV variant to PDF and/or DOCX, then verify the PDF for ATS safety. Use it when
    the person wants the files; for a cover letter use build_letter, and to check a PDF made
    elsewhere use verify_pdf. Files go to `out_dir`, default <profile>/out, replacing earlier builds
    of the same variant and language. Returns the `files`, each PDF with its pages, `ats_ok` and
    failed checks. A failed check is probably a bug in honest-cv: report it, never reword the
    person's text to pass it."""
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
    max_pages: Annotated[int | None, Field(description="Most pages allowed; the page_count check fails above it. Default: no limit.")] = None,
) -> dict:
    """Check whether any PDF is ATS-safe: one column, no ligatures, dates on their role's line,
    text extractable, and the page count. Use it on a CV from any tool, e.g. the person's current
    one; build_cv already runs it on the CVs it renders. Returns `ok`, `pages`, `checks` (each with
    `name`, `ok`, `detail`) and `text`: what an ATS reads. Read-only."""
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
    """Check any text about the person against their profile before it goes anywhere: a
    cover letter, a summary, a LinkedIn text. build_letter and linkedin_profile run it too. Returns
    `problems`, which must be fixed (a skill marked X, or a familiarity skill not called familiarity
    in its sentence), and `warnings` for the person (a technology the profile doesn't show, or a
    number found nowhere in it). Fix them by removing or qualifying the claim, never by adding
    skills. Read-only."""
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
    greeting: Annotated[str | None, Field(description="Opening line. Default: Dear Hiring Team, / Estimado equipo de selección:")] = None,
    closing: Annotated[str | None, Field(description="Closing line. Default: Sincerely, / Atentamente,")] = None,
    keywords: Annotated[list[str] | None, Field(description="Keywords of the job post, for check_claims.")] = None,
    formats: Annotated[list[Literal["pdf", "docx"]] | None, Field(description="Formats to write: pdf, docx or both. Default: both.")] = None,
    out_dir: Annotated[str | None, Field(description="Output folder. Default: <profile>/out.")] = None,
) -> dict:
    """Render an approved cover letter to a one-page PDF and/or DOCX with the CV's ATS
    checks. Use it after drafting the letter with the person and running check_claims; for the CV
    itself use build_cv. It runs check_claims again and refuses while there are problems. Returns the
    `files` and any `warnings` to show the person."""
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
    """Export a CV variant as a JSON Resume file, for other CV tools and sites that
    import that format. Use build_cv for a PDF or DOCX instead. Same honesty rules as the CV: X skills
    never appear, and F skills only in a "Familiarity" group. Writes to `out_dir`, default
    <profile>/out, and returns its `path`."""
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
    """Write the LinkedIn texts for a variant, each within LinkedIn's limit: headline,
    About, one description per position from its bullets, and the skills (P and L only, since
    LinkedIn can't label familiarity). Use it when the person updates their LinkedIn profile. Writes
    them to a Markdown file to copy from and returns them with their `path`, plus `left_out`: bullets
    that didn't fit. After the person approves a polished headline or About, call it again with them:
    they are checked like a letter and saved in that file."""
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
    status: Annotated[StatusArg | None, Field(description="New status: draft, applied, interview, offer, rejected or withdrawn. Each change is kept in the history with its date.")] = None,
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
    """Record a job application, or update the one for the same company and role. Use it
    when the person sends a CV or letter, and whenever they tell you what happened (interview, offer,
    rejection); list_applications reads them back. Fields not given keep their value. Save the post's
    full text in `post`, since links expire, and your interview advice in `prep`. Each file in `files`
    is copied to <profile>/sent/<id>/, so the record keeps what was sent. Returns the `application`
    and `not_found`: paths it could not copy."""
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
    status: Annotated[list[StatusArg] | None, Field(description="Only applications in these statuses. Default: all.")] = None,
) -> dict:
    """List the person's job applications, most recently updated first. Use it when
    they ask how their search is going or which application to follow up; log_application records
    changes. Returns `applications` (each with its id, status and `days_since_update`), a count per
    status and `waiting`: open applications with no news for 14 days or more. Read-only."""
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
    """Prepare the interview for one logged application from what the person can honestly
    back up. Call it first with only `application` to get the saved job post (`post_text`), then again
    with the post's keywords. For each keyword it returns their level, evidence, `stories` (the
    bullets that show it, those in the CV they sent first) and a `standing`: strong (tell a story
    from those bullets), no_achievement (ask for a real example), marked_pending (ask for evidence),
    familiarity (say it is familiarity) or lacking (say so honestly). Every story must come from
    `stories`. With `notes`, saves the approved prep to <profile>/prep/<id>.md."""
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
    variants: Annotated[list[str] | None, Field(description="Variant ids to score, from list_variants. Default: all.")] = None,
) -> dict:
    """Measure how well each CV variant covers a job post's keywords, best first. Use it first
    when the person shares a post, to pick a variant; then call gap_report on that variant to see
    what is missing and why. Extract the keywords yourself in the post's own wording: `keywords` are
    the required ones, `preferred` the nice-to-haves. Returns `scores`: per variant, the required and
    overall coverage and each keyword found, found only as familiarity, or missing. Read-only."""
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
    """Explain the keywords a job post asks for that one variant doesn't show, grouped by what
    can honestly be done. Use it after score_job picked the variant, before editing it with
    save_variant. Returns: `in_inventory_not_in_cv` (the person has it: add it, using
    `unused_bullets`, or name it in the summary or competencies), `familiarity_only` (only as
    familiarity), `not_in_inventory` (do not claim it), `no_achievement` (P or L skills no bullet
    shows: ask for one real achievement each) and `marked_in_checklist` (marked in their checklist,
    still without evidence: ask where they used it). Read-only."""
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
