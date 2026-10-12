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
from typing import Annotated, Literal

from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ValidationError

from honest_cv import __version__, store
from honest_cv import build as build_mod
from honest_cv import score as score_mod
from honest_cv.model import LEVEL_RANK, Bullet, Lang, Level, Source, load
from honest_cv.verify import verify_pdf as verify

INSTRUCTIONS = """\
honest-cv turns a person's real experience into ATS-safe CVs, one variant per type of role.

Honesty rules, enforced by this server:
- Skill levels: P (production), L (own project/lab), F (familiarity, always labeled), X (never shown).
- Raising a skill's level needs written evidence and the person's own confirmation, which the
  server asks for directly. Never invent experience, metrics or skills.

Typical flow: get_inventory and list_variants to learn the profile; for a job post, extract its
keywords yourself, call score_job, then gap_report on the best variant; propose edits the person
approves; build_cv, which also verifies the PDF.
"""

mcp = MCPServer("honest-cv", version=__version__, instructions=INSTRUCTIONS)

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def _profile_dir(profile: str | None) -> Path:
    value = profile or os.environ.get("HONEST_CV_PROFILE")
    if not value:
        raise ToolError("no profile folder given and HONEST_CV_PROFILE is not set")
    return Path(value).expanduser().resolve()


def _load(profile: str | None) -> Source:
    return load(_profile_dir(profile))


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
            raise ToolError(str(e)) from e

    return wrapper


@mcp.tool(annotations=WRITE)
@_tool_errors
def init_profile(profile: str) -> dict:
    """Create a profile folder with empty, commented YAML templates. Refuses to overwrite."""
    created = store.init_profile(_profile_dir(profile))
    return {"created": [str(p) for p in created]}


@mcp.tool(annotations=READ)
@_tool_errors
def get_inventory(profile: str | None = None) -> dict:
    """The skill inventory: level (P/L/F/X), years, last use, evidence and aliases."""
    inv = _load(profile).inventory
    by_level = {lvl.value: [] for lvl in sorted(Level, key=LEVEL_RANK.get, reverse=True)}
    for s in inv.skills:
        by_level[s.level.value].append(s.model_dump(mode="json", exclude_none=True, exclude_defaults=True))
    return {"levels": {"P": "production", "L": "own project or lab", "F": "familiarity", "X": "does not have it"},
            "skills": by_level}


class ConfirmUpgrade(BaseModel):
    confirm: bool


def _upgrade(profile: str | None, name: str, level: str) -> tuple[Path, Level, Level]:
    folder = _profile_dir(profile)
    current = load(folder).inventory.get(name)
    return folder, current.level if current else Level.NONE, Level(level)


def _can_ask(ctx: Context) -> bool:
    caps = ctx.client_capabilities
    return caps is not None and caps.elicitation is not None


def confirm_upgrade(
    ctx: Context, name: str, level: str, evidence: str | None, profile: str | None
) -> Elicit[ConfirmUpgrade] | ConfirmUpgrade:
    """Ask the person, not the model, to confirm a level upgrade."""
    try:
        _, old, new = _upgrade(profile, name, level)
    except (ToolError, ValueError):
        return ConfirmUpgrade(confirm=False)  # set_skill reports the real error
    if LEVEL_RANK[new] <= LEVEL_RANK[old] or not (evidence and evidence.strip()) or not _can_ask(ctx):
        return ConfirmUpgrade(confirm=False)  # nothing to ask, or set_skill refuses
    return Elicit(
        f"Confirm skill upgrade: {name} {old} -> {new}.\nEvidence: {evidence}\n"
        "Only confirm if this is true and you can defend it in an interview.",
        ConfirmUpgrade,
    )


@mcp.tool(annotations=WRITE)
@_tool_errors
def set_skill(
    ctx: Context,
    name: str,
    level: Literal["P", "L", "F", "X"],
    confirmation: Annotated[ElicitationResult[ConfirmUpgrade], Resolve(confirm_upgrade)],
    profile: str | None = None,
    evidence: str | None = None,
    years: float | None = None,
    last_used: int | None = None,
    aliases: list[str] | None = None,
    notes: str | None = None,
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
                f'Ask them to run: honest-cv skill {folder} "{name}" {new} --evidence "..."'
            )
        if not (isinstance(confirmation, AcceptedElicitation) and confirmation.data.confirm):
            raise ToolError(f"{name}: the person did not confirm the upgrade; nothing was saved")
        confirmed = True
    skill = store.upsert_skill(
        folder, name, new, evidence=evidence, confirmed=confirmed,
        years=years, last_used=last_used, aliases=aliases, notes=notes,
    )
    return {"saved": skill.model_dump(mode="json", exclude_none=True, exclude_defaults=True), "previous_level": old.value}


@mcp.tool(annotations=WRITE)
@_tool_errors
def add_bullet(
    id: str,
    text_en: str,
    profile: str | None = None,
    text_es: str | None = None,
    role: str | None = None,
    tags: list[str] | None = None,
    metrics: list[str] | None = None,
) -> dict:
    """Add an achievement to the bullet pool. `role` is a role id from profile.yaml; leave it
    out for bullets used only in the Selected Impact section. Use only facts the person stated."""
    text = {"en": text_en, **({"es": text_es} if text_es else {})}
    bullet = Bullet(id=id, role=role, tags=tags or [], metrics=metrics or [], text=text)
    store.add_bullet(_profile_dir(profile), bullet)
    return {"saved": bullet.model_dump(mode="json", exclude_defaults=True)}


@mcp.tool(annotations=READ)
@_tool_errors
def list_variants(profile: str | None = None) -> dict:
    """Variants after `extends:` is applied, with the bullet texts each one uses."""
    source = _load(profile)
    out = {}
    for vid, raw in source.variants.items():
        v = source.resolve(vid)
        out[vid] = {
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
    variant: str,
    lang: Lang = "en",
    profile: str | None = None,
    formats: list[Literal["pdf", "docx"]] | None = None,
    out_dir: str | None = None,
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
def verify_pdf(path: str, max_pages: int | None = None) -> dict:
    """Check that any PDF is ATS-safe and return the text an ATS would extract."""
    report = verify(Path(path).expanduser(), max_pages=max_pages)
    return {
        "ok": report.ok,
        "pages": report.pages,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks],
        "text": report.text,
    }


def _keywords(keywords: list[str], preferred: list[str] | None) -> list[score_mod.Keyword]:
    return [score_mod.Keyword(k) for k in keywords] + [score_mod.Keyword(k, False) for k in preferred or []]


@mcp.tool(annotations=READ)
@_tool_errors
def score_job(
    keywords: list[str],
    profile: str | None = None,
    preferred: list[str] | None = None,
    lang: Lang = "en",
    variants: list[str] | None = None,
) -> dict:
    """Keyword coverage of each variant, best first. Extract the job post's keywords yourself:
    `keywords` are the required ones, `preferred` the nice-to-haves. Use the post's own wording."""
    scores = score_mod.score_job(_load(profile), _keywords(keywords, preferred), lang, variants)
    return {"scores": [s.to_dict() for s in scores]}


@mcp.tool(annotations=READ)
@_tool_errors
def gap_report(
    variant: str,
    keywords: list[str],
    profile: str | None = None,
    preferred: list[str] | None = None,
    lang: Lang = "en",
) -> dict:
    """Missing keywords grouped by what can honestly be done:
    in_inventory_not_in_cv (the person has it at P/L: add it, see unused_bullets),
    familiarity_only (only claim it as familiarity), not_in_inventory (do not claim it)."""
    groups = score_mod.gap_report(_load(profile), variant, lang, _keywords(keywords, preferred))
    return {k: [r.__dict__ for r in v] for k, v in groups.items()}


def main() -> None:
    mcp.run("stdio")
