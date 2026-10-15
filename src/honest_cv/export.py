"""Export a variant as JSON Resume (https://jsonresume.org/schema), in one language.

The same rules as the CV apply: the variant picks the roles and bullets, X skills
never appear, and F skills only appear in their own "Familiarity" group. Importing
the file back (importer.from_json_resume) gives the same profile.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from honest_cv import __version__
from honest_cv.build import file_stem
from honest_cv.document import FAMILIARITY, skill_lines
from honest_cv.model import Lang, Source, localize

SCHEMA = "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json"
NETWORKS = {"github.com": "GitHub", "linkedin.com": "LinkedIn", "gitlab.com": "GitLab",
            "x.com": "X", "twitter.com": "X", "stackoverflow.com": "Stack Overflow"}
LANGUAGE = re.compile(r"^(?P<language>[^()]+?)\s*(?:\((?P<fluency>[^()]*)\))?$")


def _network(url: str) -> str:
    host = urlparse(url if "//" in url else f"https://{url}").netloc.lower().removeprefix("www.")
    return NETWORKS.get(host, host)


def _url(link: str) -> str:
    """The schema wants a URI: "github.com/ada" becomes "https://github.com/ada"."""
    return link if "://" in link else f"https://{link}"


def _split(text: str) -> list[str]:
    """Split "a, b (c, d), e" on the commas outside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [x for x in [*parts, cur.strip()] if x]


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def json_resume(source: Source, variant_id: str, lang: Lang) -> dict:
    v = source.resolve(variant_id)
    p = source.profile
    c = p.contact

    def loc(text, where):
        return localize(text, lang, where) if text else None

    place = loc(c.location, "contact.location")
    city, _, region = (place or "").partition(", ")
    basics = _clean({
        "name": c.name,
        "label": loc(v.title, f"variant {v.id}.title"),
        "email": c.email,
        "phone": c.phone,
        "summary": loc(v.summary, f"variant {v.id}.summary"),
        "location": _clean({"city": city, "region": region}),
        "profiles": [{"network": _network(u), "url": _url(u)} for u in c.links],
    })
    work = [
        _clean({
            "name": role.company,
            "position": loc(role.title, f"role {role.id}"),
            "location": loc(role.location, f"role {role.id}.location"),
            "startDate": role.start,
            "endDate": role.end,
            "summary": loc(role.context, f"role {role.id}.context"),
            "highlights": [loc(source.bullet(b).text, f"bullet {b}") for b in v.roles[role.id]],
        })
        for role in p.roles if v.roles.get(role.id)
    ]
    education = [
        _clean({"institution": e.institution, "studyType": loc(e.degree, "education.degree"),
                "startDate": e.start, "endDate": e.end})
        for e in p.education
    ]
    skills = []
    for line in skill_lines(source, v.skills, lang):
        familiarity = line.label == FAMILIARITY[lang]
        skills.append(_clean({"name": line.label, "level": line.label if familiarity else None,
                              "keywords": line.skills}))
    languages = []
    for part in _split(loc(p.languages, "languages") or ""):
        m = LANGUAGE.match(part)
        languages.append(_clean(m.groupdict()) if m else {"language": part})
    return _clean({
        "$schema": SCHEMA,
        "basics": basics,
        "work": work,
        "education": education,
        "certificates": [{"name": loc(x, "certifications")} for x in p.certifications],
        "publications": [
            _clean({"name": x.title, "publisher": x.venue, "releaseDate": x.year, "url": x.url})
            for x in source.publications(v)
        ],
        "skills": skills,
        "languages": languages,
        "meta": {"version": "v1.0.0", "generator": f"honest-cv {__version__}", "variant": v.id, "lang": lang},
    })


def export(source: Source, variant_id: str, lang: Lang, out_dir: Path) -> Path:
    data = json_resume(source, variant_id, lang)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{file_stem(source.profile.contact.name, variant_id, lang)}.resume.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
