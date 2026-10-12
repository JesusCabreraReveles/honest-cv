"""Data model: a profile folder holds four YAML files validated with pydantic.

    profile.yaml   contact, roles, education, languages, certifications
    bullets.yaml   pool of achievements, each with an id, role and tags
    skills.yaml    skill inventory with honesty levels (P/L/F/X)
    variants.yaml  per-role-type CV plans, with `extends:` inheritance
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Lang = Literal["en", "es"]
LANGS: tuple[Lang, ...] = ("en", "es")

# A text is either the same string in every language or one string per language.
Text = str | dict[Lang, str]

FILES = ("profile.yaml", "bullets.yaml", "skills.yaml", "variants.yaml")


class MissingTranslation(ValueError):
    pass


def localize(text: Text, lang: Lang, where: str) -> str:
    if isinstance(text, str):
        return text
    try:
        return text[lang]
    except KeyError:
        raise MissingTranslation(f"{where}: no '{lang}' text") from None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- profile.yaml ------------------------------------------------------------


class Contact(Strict):
    name: str
    email: str
    phone: str | None = None
    location: Text | None = None
    links: list[str] = []


class Role(Strict):
    id: str
    title: Text
    company: str
    location: Text | None = None
    start: str
    end: str | None = None  # None means "Present"
    context: Text | None = None


class Education(Strict):
    institution: str
    degree: Text
    start: str | None = None
    end: str | None = None


class Profile(Strict):
    contact: Contact
    roles: list[Role] = []
    education: list[Education] = []
    certifications: list[Text] = []
    languages: Text | None = None

    @model_validator(mode="after")
    def _unique_role_ids(self) -> Profile:
        _check_unique([r.id for r in self.roles], "role id")
        return self


# --- bullets.yaml ------------------------------------------------------------


class Bullet(Strict):
    id: str
    role: str | None = None  # None: not tied to a role, usable only in `impact`
    tags: list[str] = []
    metrics: list[str] = []
    text: Text


# --- skills.yaml -------------------------------------------------------------


class Level(StrEnum):
    PRODUCTION = "P"
    LAB = "L"
    FAMILIARITY = "F"
    NONE = "X"


# Higher rank means stronger evidence. Moving up this ladder is an "upgrade".
LEVEL_RANK = {Level.NONE: 0, Level.FAMILIARITY: 1, Level.LAB: 2, Level.PRODUCTION: 3}


FIRST_YEAR = 1950


class Skill(Strict):
    name: str
    level: Level
    years: float | None = Field(None, ge=0)
    last_used_year: int | None = None  # a calendar year, e.g. 2026
    evidence: str | None = None
    aliases: list[str] = []
    notes: str | None = None

    @field_validator("last_used_year")
    @classmethod
    def _is_a_year(cls, v: int | None) -> int | None:
        if v is not None and not FIRST_YEAR <= v <= date.today().year + 1:
            raise ValueError(f"must be a calendar year like {date.today().year}, not {v}")
        return v


class SkillUpgradeError(ValueError):
    pass


def set_skill_level(
    skill: Skill, level: Level, *, evidence: str | None, confirmed: bool
) -> Skill:
    """Return a copy of `skill` at `level`.

    Upgrades need written evidence and an explicit confirmation from the person.
    Downgrades are always allowed: being more modest is never dishonest.
    """
    if LEVEL_RANK[level] > LEVEL_RANK[skill.level]:
        if not (evidence and evidence.strip()):
            raise SkillUpgradeError(f"{skill.name}: upgrading to {level} requires evidence")
        if not confirmed:
            raise SkillUpgradeError(f"{skill.name}: upgrading to {level} requires human confirmation")
    return skill.model_copy(update={"level": level, "evidence": evidence or skill.evidence})


class Inventory(Strict):
    skills: list[Skill] = []

    @model_validator(mode="after")
    def _unique_names(self) -> Inventory:
        _check_unique([s.name.casefold() for s in self.skills], "skill name")
        return self

    def get(self, name: str) -> Skill | None:
        key = name.casefold()
        return next((s for s in self.skills if s.name.casefold() == key), None)


# --- variants.yaml -----------------------------------------------------------


class SkillGroup(Strict):
    label: Text
    skills: list[str]


class Variant(Strict):
    extends: str | None = None
    title: Text | None = None
    summary: Text | None = None
    competencies: list[str] | None = None
    impact: list[str] | None = None
    roles: dict[str, list[str]] | None = None
    skills: list[SkillGroup] | None = None
    max_pages: int | None = Field(default=None, ge=1)


class ResolvedVariant(Strict):
    """A variant after `extends:` is applied. Every field is set."""

    id: str
    title: Text
    summary: Text
    competencies: list[str] = []
    impact: list[str] = []
    roles: dict[str, list[str]] = {}
    skills: list[SkillGroup] = []
    max_pages: int = 2


# --- the whole folder --------------------------------------------------------


class ProfileError(ValueError):
    pass


class Source(Strict):
    profile: Profile
    bullets: list[Bullet] = []
    inventory: Inventory = Field(default_factory=Inventory)
    variants: dict[str, Variant] = {}

    @model_validator(mode="after")
    def _check_references(self) -> Source:
        _check_unique([b.id for b in self.bullets], "bullet id")
        role_ids = {r.id for r in self.profile.roles}
        for b in self.bullets:
            if b.role is not None and b.role not in role_ids:
                raise ValueError(f"bullet '{b.id}': unknown role '{b.role}'")
        for vid in self.variants:
            self.resolve(vid)  # surfaces broken references and cycles at load time
        return self

    def bullet(self, bid: str) -> Bullet:
        for b in self.bullets:
            if b.id == bid:
                return b
        raise ProfileError(f"unknown bullet '{bid}'")

    def resolve(self, vid: str) -> ResolvedVariant:
        """Flatten the `extends:` chain. A field set in the child replaces the parent's,
        except `roles`, which merges per role id."""
        chain: list[str] = []
        cur: str | None = vid
        while cur is not None:
            if cur in chain:
                raise ProfileError(f"variant cycle: {' -> '.join([*chain, cur])}")
            if cur not in self.variants:
                raise ProfileError(f"unknown variant '{cur}'")
            chain.append(cur)
            cur = self.variants[cur].extends

        merged: dict = {}
        for name in reversed(chain):
            v = self.variants[name]
            for field in v.model_fields_set - {"extends"}:
                value = getattr(v, field)
                if field == "roles":
                    merged["roles"] = {**merged.get("roles", {}), **value}
                else:
                    merged[field] = value
        for field in ("title", "summary"):
            if field not in merged:
                raise ProfileError(f"variant '{vid}': missing '{field}'")
        resolved = ResolvedVariant(id=vid, **merged)
        self._check_variant(resolved)
        return resolved

    def _check_variant(self, v: ResolvedVariant) -> None:
        role_ids = {r.id for r in self.profile.roles}
        for bid in v.impact:
            self.bullet(bid)
        for rid, ids in v.roles.items():
            if rid not in role_ids:
                raise ProfileError(f"variant '{v.id}': unknown role '{rid}'")
            for bid in ids:
                if self.bullet(bid).role != rid:
                    raise ProfileError(f"variant '{v.id}': bullet '{bid}' does not belong to role '{rid}'")
        for group in v.skills:
            for name in group.skills:
                if self.inventory.get(name) is None:
                    raise ProfileError(
                        f"variant '{v.id}': skill '{name}' is not in the inventory"
                    )


def explain(error: Exception) -> str:
    """The error text, plus a hint for the most common YAML slip.

    Validation errors are reduced to "where: what", one per line. pydantic's own
    text repeats the whole input, which buries the reason under the profile."""
    text = str(error)
    if isinstance(error, ValidationError):
        text = "\n".join(
            f"{'.'.join(map(str, e['loc']))}: {_reason(e)}" if e["loc"] else _reason(e) for e in error.errors()
        )
        split = [e for e in error.errors() if e["type"] == "extra_forbidden" and " " in str(e["loc"][-1])]
        if split:
            text += (
                "\nHint: a comma inside {...} splits a value in two. "
                'Put text with commas in quotes, e.g. evidence: "EKS, RDS and MSK".'
            )
    return text


def _reason(error: dict) -> str:
    return error["msg"].removeprefix("Value error, ")


def _check_unique(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for v in values:
        if v in seen:
            raise ValueError(f"duplicate {what} '{v}'")
        seen.add(v)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def load(folder: str | Path) -> Source:
    folder = Path(folder)
    if not (folder / "profile.yaml").exists():
        raise ProfileError(f"{folder}: missing profile.yaml")
    return Source(
        profile=_read_yaml(folder / "profile.yaml"),
        bullets=_read_yaml(folder / "bullets.yaml").get("bullets", []),
        inventory=_read_yaml(folder / "skills.yaml"),
        variants=_read_yaml(folder / "variants.yaml").get("variants", {}),
    )
