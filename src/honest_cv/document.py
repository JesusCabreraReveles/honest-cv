"""Build the language-specific document that every renderer consumes.

The honesty rules live here, so PDF and DOCX cannot disagree:
- an `X` skill is never emitted;
- `F` skills are only emitted under the "Familiarity" label.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from honest_cv.model import Lang, Level, Source, localize

HEADINGS: dict[Lang, dict[str, str]] = {
    "en": {
        "summary": "Summary",
        "competencies": "Core Competencies",
        "impact": "Selected Impact",
        "experience": "Experience",
        "skills": "Skills",
        "education": "Education",
        "certifications": "Certifications",
        "courses": "Courses",
        "languages": "Languages",
    },
    "es": {
        "summary": "Resumen",
        "competencies": "Competencias clave",
        "impact": "Impacto destacado",
        "experience": "Experiencia",
        "skills": "Habilidades",
        "education": "Educación",
        "certifications": "Certificaciones",
        "courses": "Cursos",
        "languages": "Idiomas",
    },
}

FAMILIARITY: dict[Lang, str] = {"en": "Familiarity", "es": "Familiaridad"}
PRESENT: dict[Lang, str] = {"en": "Present", "es": "Presente"}


@dataclass
class RoleEntry:
    # The company goes in the heading line of every role: some parsers only
    # attach the company to the first role of a block.
    heading: str
    dates: str
    context: str | None
    bullets: list[str]


@dataclass
class SkillLine:
    label: str
    skills: list[str]


@dataclass
class Document:
    lang: Lang
    name: str
    title: str
    contact: list[str]
    summary: str
    competencies: list[str]
    impact: list[str]
    roles: list[RoleEntry]
    skills: list[SkillLine]
    education: list[str]
    certifications: list[str]
    courses: list[str]
    languages: str | None
    headings: dict[str, str] = field(default_factory=dict)
    max_pages: int = 2

    def to_dict(self) -> dict:
        return asdict(self)


def date_range(start: str | None, end: str | None, lang: Lang) -> str:
    if start is None:
        return end or ""
    return f"{start} – {end or PRESENT[lang]}"


def contact_items(source: Source, lang: Lang) -> list[str]:
    """Location, email, phone and links, in that order: the CV's and the letter's contact line."""
    c = source.profile.contact
    location = localize(c.location, lang, "contact.location") if c.location else None
    return [x for x in (location, c.email, c.phone) if x] + c.links


def build(source: Source, variant_id: str, lang: Lang) -> Document:
    v = source.resolve(variant_id)
    p = source.profile
    c = p.contact

    def loc(text, where):
        return localize(text, lang, where)

    contact = contact_items(source, lang)

    roles = []
    for role in p.roles:
        ids = v.roles.get(role.id)
        if not ids:
            continue
        heading = f"{loc(role.title, f'role {role.id}')} — {role.company}"
        if role.location:
            heading += f", {loc(role.location, f'role {role.id}.location')}"
        roles.append(
            RoleEntry(
                heading=heading,
                dates=date_range(role.start, role.end, lang),
                context=loc(role.context, f"role {role.id}.context") if role.context else None,
                bullets=[loc(source.bullet(b).text, f"bullet {b}") for b in ids],
            )
        )

    return Document(
        lang=lang,
        name=c.name,
        title=loc(v.title, f"variant {v.id}.title"),
        contact=contact,
        summary=loc(v.summary, f"variant {v.id}.summary"),
        competencies=list(v.competencies),
        impact=[loc(source.bullet(b).text, f"bullet {b}") for b in v.impact],
        roles=roles,
        skills=skill_lines(source, v.skills, lang),
        education=[
            " · ".join(
                x
                for x in (loc(e.degree, "education.degree"), e.institution, date_range(e.start, e.end, lang))
                if x
            )
            for e in p.education
        ],
        certifications=[loc(x, "certifications") for x in p.certifications],
        courses=[loc(x, "courses") for x in p.courses],
        languages=loc(p.languages, "languages") if p.languages else None,
        headings=HEADINGS[lang],
        max_pages=v.max_pages,
    )


def skill_lines(source: Source, groups, lang: Lang) -> list[SkillLine]:
    lines: list[SkillLine] = []
    familiar: list[str] = []
    for group in groups:
        shown = []
        for name in group.skills:
            skill = source.inventory.get(name)
            if skill.level is Level.NONE:
                continue
            if skill.level is Level.FAMILIARITY:
                if skill.name not in familiar:
                    familiar.append(skill.name)
                continue
            shown.append(skill.name)
        if shown:
            lines.append(SkillLine(localize(group.label, lang, "skill group label"), shown))
    if familiar:
        lines.append(SkillLine(FAMILIARITY[lang], familiar))
    return lines
