"""LinkedIn profile texts from a variant, within LinkedIn's limits.

Deterministic, like the CV: the headline, the About section and each position's
description come from the variant's title, summary and bullets, in the person's own
words. The skills are P and L only: LinkedIn has no way to label familiarity, so F
skills stay out, like X ones. A client may polish the wording, but the result goes
through `letter.check_claims` before the person uses it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from honest_cv.build import file_stem
from honest_cv.document import date_range
from honest_cv.model import LEVEL_RANK, Lang, Level, Source, localize

HEADLINE, ABOUT, POSITION, SKILLS = 220, 2600, 2000, 100
HEADLINE_SKILLS = 5  # more reads as keyword stuffing
BULLET = "• "


@dataclass
class Text:
    text: str
    limit: int

    @property
    def chars(self) -> int:
        return len(self.text)

    def to_dict(self) -> dict:
        return {"text": self.text, "chars": self.chars, "limit": self.limit}


@dataclass
class Position:
    title: str
    company: str
    dates: str
    description: Text
    left_out: list[str] = field(default_factory=list)  # bullet ids that did not fit

    def to_dict(self) -> dict:
        return {**asdict(self), "description": self.description.to_dict()}


@dataclass
class Suggestion:
    variant: str
    lang: Lang
    headline: Text
    about: Text
    positions: list[Position]
    skills: list[str]

    def to_dict(self) -> dict:
        return {"variant": self.variant, "lang": self.lang, "headline": self.headline.to_dict(),
                "about": self.about.to_dict(), "positions": [p.to_dict() for p in self.positions],
                "skills": self.skills}

    def markdown(self) -> str:
        out = [f"# LinkedIn — {self.variant} ({self.lang})", "",
               f"## Headline ({self.headline.chars}/{HEADLINE})", "", self.headline.text, "",
               f"## About ({self.about.chars}/{ABOUT})", "", self.about.text, "", "## Experience", ""]
        for p in self.positions:
            out += [f"### {p.title} — {p.company} ({p.dates})", f"({p.description.chars}/{POSITION})", "",
                    p.description.text, ""]
            if p.left_out:
                out += [f"Left out to fit the limit: {', '.join(p.left_out)}", ""]
        out += [f"## Skills ({len(self.skills)}/{SKILLS})", "", ", ".join(self.skills), ""]
        return "\n".join(out)


def _fit(items: list[tuple[str, str]], room: int, sep: str) -> tuple[list[str], list[str]]:
    """As many (id, text) items as fit in `room` characters joined by `sep`, in order;
    returns their texts and the ids of those left out."""
    kept, left, used = [], [], 0
    for item_id, text in items:
        cost = len(text) + (len(sep) if kept else 0)
        if used + cost <= room:
            kept.append(text)
            used += cost
        else:
            left.append(item_id)
    return kept, left


def _join(head: str, items: list[tuple[str, str]], limit: int, gap: str, sep: str) -> tuple[str, list[str]]:
    """`head`, then `gap`, then the items that fit within `limit` joined by `sep`."""
    room = limit - len(head) - (len(gap) if head else 0)
    kept, left = _fit(items, room, sep)
    body = sep.join(kept)
    return (f"{head}{gap}{body}" if head and body else head or body), left


def _shown_skills(source: Source, names: list[str], levels: set[Level]) -> list[str]:
    out = []
    for name in names:
        skill = source.inventory.get(name)
        if skill and skill.level in levels and skill.name not in out:
            out.append(skill.name)
    return out


def suggest(source: Source, variant_id: str, lang: Lang) -> Suggestion:
    v = source.resolve(variant_id)

    def loc(text, where):
        return localize(text, lang, where)

    title = loc(v.title, f"variant {v.id}.title")
    key = _shown_skills(source, [n for g in v.skills for n in g.skills], {Level.PRODUCTION})[:HEADLINE_SKILLS]
    headline, _ = _join(title, [(n, n) for n in key], HEADLINE, " | ", " · ")

    impact = [(b, BULLET + loc(source.bullet(b).text, f"bullet {b}")) for b in v.impact]
    about, _ = _join(loc(v.summary, f"variant {v.id}.summary"), impact, ABOUT, "\n\n", "\n")

    positions = []
    for role in source.profile.roles:
        ids = v.roles.get(role.id)
        if not ids:
            continue
        context = loc(role.context, f"role {role.id}.context") if role.context else ""
        bullets = [(b, BULLET + loc(source.bullet(b).text, f"bullet {b}")) for b in ids]
        text, left = _join(context, bullets, POSITION, "\n\n", "\n")
        positions.append(Position(loc(role.title, f"role {role.id}"), role.company,
                                  date_range(role.start, role.end, lang), Text(text, POSITION), left))

    # Every P and L skill, P first, then by years: LinkedIn shows the first ones.
    ranked = sorted((s for s in source.inventory.skills if s.level in (Level.PRODUCTION, Level.LAB)),
                    key=lambda s: (-LEVEL_RANK[s.level], -(s.years or 0)))
    skills = [s.name for s in ranked][:SKILLS]
    return Suggestion(v.id, lang, Text(headline, HEADLINE), Text(about, ABOUT), positions, skills)


def write(suggestion: Suggestion, name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{file_stem(name, suggestion.variant, suggestion.lang).replace('_CV_', '_LinkedIn_')}.md"
    path.write_text(suggestion.markdown(), encoding="utf-8")
    return path
