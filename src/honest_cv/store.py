"""Writes to a profile folder. Every write validates the whole profile first and
replaces the file atomically, so a bad edit never leaves a broken profile behind.

PyYAML does not keep comments: a file rewritten here loses them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from honest_cv.model import FILES, Bullet, Contact, Education, Level, Role, Skill, Source, Variant, set_skill_level

TEMPLATES = Path(__file__).parent / "templates" / "profile"


class StoreError(ValueError):
    pass


def init_profile(folder: str | Path) -> list[Path]:
    folder = Path(folder).expanduser()
    existing = [f for f in FILES if (folder / f).exists()]
    if existing:
        raise StoreError(f"{folder}: already has {', '.join(existing)}; not overwriting")
    folder.mkdir(parents=True, exist_ok=True)
    created = []
    for name in FILES:
        shutil.copyfile(TEMPLATES / name, folder / name)
        created.append(folder / name)
    return created


def _read(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _raw(folder: Path) -> dict[str, dict]:
    return {name: _read(folder, name) for name in FILES}


def _validate(raw: dict[str, dict]) -> Source:
    return Source(
        profile=raw["profile.yaml"],
        bullets=raw["bullets.yaml"].get("bullets", []),
        inventory=raw["skills.yaml"],
        variants=raw["variants.yaml"].get("variants", {}),
    )


def _write(folder: Path, name: str, data: dict) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, folder / name)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _dump_model(model) -> dict:
    return model.model_dump(mode="json", exclude_defaults=True)


@dataclass
class SkillChange:
    """One skill to add or change. Fields left as None keep their current value."""

    name: str
    level: Level
    evidence: str | None = None
    years: float | None = None
    last_used_year: int | None = None
    aliases: list[str] | None = None
    notes: str | None = None


def upsert_skills(folder: str | Path, changes: list[SkillChange], *, confirmed: bool = False) -> list[Skill]:
    """Add or change several skills in one write: all of them are saved, or none.

    A new skill counts as moving up from `X`. Every upgrade needs evidence, and
    `confirmed` must say the person approved the whole list."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    skills = raw["skills.yaml"].setdefault("skills", [])
    saved = []
    for change in changes:
        index = next((i for i, s in enumerate(skills) if s["name"].casefold() == change.name.casefold()), None)
        current = Skill(**skills[index]) if index is not None else Skill(name=change.name, level=Level.NONE)
        updated = set_skill_level(current, change.level, evidence=change.evidence, confirmed=confirmed)
        fields = {k: getattr(change, k) for k in ("years", "last_used_year", "aliases", "notes")}
        updated = Skill(**{**updated.model_dump(), **{k: v for k, v in fields.items() if v is not None}})
        if index is None:
            skills.append(_dump_model(updated))
        else:
            skills[index] = _dump_model(updated)
        saved.append(updated)
    _validate(raw)
    _write(folder, "skills.yaml", raw["skills.yaml"])
    return saved


def upsert_skill(
    folder: str | Path,
    name: str,
    level: Level,
    *,
    evidence: str | None = None,
    confirmed: bool = False,
    **fields,
) -> Skill:
    """Add or change one skill. See `upsert_skills`."""
    return upsert_skills(folder, [SkillChange(name, level, evidence, **fields)], confirmed=confirmed)[0]


def add_bullet(folder: str | Path, bullet: Bullet) -> Bullet:
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    raw["bullets.yaml"].setdefault("bullets", []).append(_dump_model(bullet))
    _validate(raw)
    _write(folder, "bullets.yaml", raw["bullets.yaml"])
    return bullet


# Passed for an optional field to remove it, e.g. a role's `end` when it is current again.
CLEAR = "clear"


def _merge(current: dict, changes: dict) -> dict:
    """Fields given as None stay as they are; CLEAR removes them."""
    merged = dict(current)
    for key, value in changes.items():
        if value is None:
            continue
        if value == CLEAR:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _save_profile(folder: Path, raw: dict[str, dict]) -> Source:
    source = _validate(raw)
    _write(folder, "profile.yaml", raw["profile.yaml"])
    return source


def set_contact(folder: str | Path, **fields) -> Contact:
    """Change the contact fields given; the rest stay as they are."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    profile = raw["profile.yaml"]
    profile["contact"] = _merge(profile.get("contact") or {}, fields)
    return _save_profile(folder, raw).profile.contact


def set_profile_details(folder: str | Path, *, certifications=None, languages=None) -> dict:
    """Replace the certifications list and/or the languages line."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    raw["profile.yaml"] = _merge(raw["profile.yaml"], {"certifications": certifications, "languages": languages})
    profile = _save_profile(folder, raw).profile
    return {"certifications": profile.certifications, "languages": profile.languages}


def upsert_role(folder: str | Path, id: str, **fields) -> Role:
    """Add a role, or change the fields given on an existing one.

    A new role is placed by its start date, newest first, because the CV lists
    roles in file order."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    roles = raw["profile.yaml"].setdefault("roles", [])
    index = next((i for i, r in enumerate(roles) if r.get("id") == id), None)
    if index is not None:
        roles[index] = _merge(roles[index], fields)
    else:
        new = _merge({"id": id}, fields)
        start = str(new.get("start", ""))
        at = next((i for i, r in enumerate(roles) if str(r.get("start", "")) < start), len(roles))
        roles.insert(at, new)
    source = _save_profile(folder, raw)
    return next(r for r in source.profile.roles if r.id == id)


def upsert_education(folder: str | Path, institution: str, **fields) -> Education:
    """Add an education entry, or change the one with the same institution and degree."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    entries = raw["profile.yaml"].setdefault("education", [])
    degree = fields.get("degree")
    index = next(
        (
            i
            for i, e in enumerate(entries)
            if e.get("institution", "").casefold() == institution.casefold()
            and (degree is None or e.get("degree") == degree)
        ),
        None,
    )
    if index is not None:
        entries[index] = _merge(entries[index], fields)
    else:
        entries.append(_merge({"institution": institution}, fields))
        index = len(entries) - 1
    return _save_profile(folder, raw).profile.education[index]


def save_variant(folder: str | Path, id: str, variant: Variant) -> Variant:
    """Add a variant, or replace it whole."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    variants = raw["variants.yaml"].get("variants") or {}
    variants[id] = variant.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    raw["variants.yaml"]["variants"] = variants
    source = _validate(raw)  # resolves every variant, including those that extend this one
    _write(folder, "variants.yaml", raw["variants.yaml"])
    return source.variants[id]

