"""Interview prep for a logged application: what the person can honestly back up.

The client's LLM writes the questions and the STAR stories. This module only lays out,
for each keyword of the job post, the person's level, evidence and the bullets that
show it, and where they stand: strong, without an achievement, marked but pending,
familiarity only, or lacking. Every story must come from those bullets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from honest_cv import applications, checklist
from honest_cv.model import Lang, Level, Source
from honest_cv.score import Keyword, _bullet_mentions, find_skill, score_job, spellings

PREP = "prep"  # the prep notes: <profile>/prep/<application id>.md


class Standing:
    STRONG = "strong"  # P/L, or bullets show it: tell a story from those bullets
    NO_ACHIEVEMENT = "no_achievement"  # P/L but no bullet shows it: find a real example
    MARKED_PENDING = "marked_pending"  # marked in the checklist, no evidence yet
    FAMILIARITY = "familiarity"  # F: say it is familiarity
    LACKING = "lacking"  # X or never recorded: say so, and how they would close the gap


@dataclass
class Story:
    id: str
    role: str
    text: str
    in_cv: bool  # the CV that was sent shows this bullet


@dataclass
class Point:
    keyword: str
    required: bool
    standing: str
    skill: str | None = None
    level: str | None = None
    evidence: str | None = None
    years: float | None = None
    last_used_year: int | None = None
    stories: list[Story] = field(default_factory=list)


def find(folder: str | Path, application: str) -> applications.Application:
    apps = applications.read(folder).applications
    for a in apps:
        if a.id == application:
            return a
    known = ", ".join(a.id for a in apps) or "none yet"
    raise ValueError(f"unknown application '{application}'; known: {known}")


def post_text(folder: str | Path, app: applications.Application) -> str | None:
    if app.post and (path := Path(folder) / app.post).is_file():
        return path.read_text(encoding="utf-8")
    return None


def _text(bullet, lang: Lang) -> str:
    if isinstance(bullet.text, str):
        return bullet.text
    return bullet.text.get(lang) or next(iter(bullet.text.values()))


def points(source: Source, app: applications.Application, keywords: list[Keyword]) -> list[Point]:
    lang: Lang = app.lang or "en"
    variant = app.variant or score_job(source, keywords, lang)[0].variant
    resolved = source.resolve(variant)
    sent = set(resolved.impact).union(*resolved.roles.values())
    marked = {m["keyword"] for m in checklist.marked_pending(source, [k.term for k in keywords])}
    out = []
    for kw in keywords:
        names = spellings(kw.term, source)
        skill = find_skill(kw.term, source)
        stories = [Story(b.id, b.role, _text(b, lang), b.id in sent)
                   for b in source.bullets if _bullet_mentions(b, names, lang)]
        stories.sort(key=lambda s: not s.in_cv)  # what they sent first: it is what they'll be asked about
        p = Point(kw.term, kw.required, Standing.LACKING, stories=stories)
        if skill is not None:
            p.skill, p.level, p.evidence = skill.name, skill.level.value, skill.evidence
            p.years, p.last_used_year = skill.years, skill.last_used_year
        if kw.term in marked:
            p.standing = Standing.MARKED_PENDING
        elif skill is not None and skill.level is Level.NONE:
            p.standing, p.stories = Standing.LACKING, []
        elif skill is not None and skill.level is Level.FAMILIARITY:
            p.standing = Standing.FAMILIARITY
        elif stories:
            p.standing = Standing.STRONG
        elif skill is not None:
            p.standing = Standing.NO_ACHIEVEMENT
        out.append(p)
    return out


def summary(source: Source, app: applications.Application, keywords: list[Keyword]) -> dict:
    found = points(source, app, keywords)
    folder = source.folder
    notes = folder / PREP / f"{app.id}.md" if folder else None
    return {
        "application": {**app.model_dump(mode="json", exclude_defaults=True, exclude={"history"}),
                        "status": app.status.value},
        "post_text": post_text(folder, app) if folder else None,
        "notes_file": str(notes) if notes and notes.is_file() else None,
        "points": [asdict(p) for p in found],
        "by_standing": {s: [p.keyword for p in found if p.standing == s]
                        for s in (Standing.STRONG, Standing.NO_ACHIEVEMENT, Standing.MARKED_PENDING,
                                  Standing.FAMILIARITY, Standing.LACKING)},
    }


def save(folder: str | Path, app: applications.Application, notes: str) -> Path:
    """Write the prep notes the person approved; saving again replaces them."""
    if not notes.strip():
        raise ValueError("the notes are empty")
    path = Path(folder) / PREP / f"{app.id}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(notes.strip() + "\n", encoding="utf-8")
    return path
