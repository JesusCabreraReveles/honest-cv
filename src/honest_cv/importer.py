"""Import a profile from JSON Resume or a LinkedIn data export (ZIP of CSVs).

Contact, roles, education, certifications, languages and each role's
achievements are mapped to the profile. Skills come without a level, because
neither format says whether a skill was used in production: they are written to
a checklist for the person to mark, never to the inventory.

Importing into an existing profile only adds what is missing. Nothing is
overwritten, and every write is validated like any other edit.

A LinkedIn profile PDF ("Save to PDF") changes layout without notice, so it is
not parsed here: the server returns its text and the MCP client organizes it
with the editing tools, with the person's approval.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from honest_cv import store
from honest_cv.model import FILES

MONTHS = {
    **{m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)},
    **{m: i for i, m in enumerate(["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"], 1)},
    "sept": 9, "set": 9,
}
BULLET_MARK = re.compile(r"^\s*(?:[-•*·▪●–]|\d+[.)])\s+")


@dataclass
class Imported:
    """A profile read from another format, before it is merged."""

    contact: dict = field(default_factory=dict)
    roles: list[dict] = field(default_factory=list)  # each with "highlights": list[str]
    education: list[dict] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    publications: list[dict] = field(default_factory=list)  # title, venue, year, url
    courses: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    title: str | None = None  # headline, e.g. "Backend Engineer"
    summary: str | None = None  # the person's own summary
    source: str = ""
    missing: list[str] = field(default_factory=list)  # files the export lacks


@dataclass
class Report:
    added: dict[str, list[str]] = field(default_factory=dict)
    skipped: dict[str, list[str]] = field(default_factory=dict)
    skills_checklist: str | None = None
    skills: int = 0
    skills_checklist_kept: bool = False  # it existed already and may hold the person's marks
    missing: list[str] = field(default_factory=list)
    note: str | None = None

    def add(self, what: str, name: str) -> None:
        self.added.setdefault(what, []).append(name)

    def skip(self, what: str, name: str) -> None:
        self.skipped.setdefault(what, []).append(name)


# --- dates --------------------------------------------------------------------


def norm_date(value: object) -> str | None:
    """'2016-03-01', 'Mar 2016', 'mar. 2016', '2016' -> '2016-03' or '2016'."""
    text = str(value or "").strip().lower().replace(".", "")
    if not text or text in {"present", "presente", "actualidad", "now"}:
        return None
    if m := re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-\d{1,2})?", text):
        return f"{m[1]}-{int(m[2]):02}" if m[2] else m[1]
    if m := re.fullmatch(r"([a-záé]+)\s+(?:de\s+)?(\d{4})", text):
        month = MONTHS.get(m[1][:4]) or MONTHS.get(m[1][:3])
        return f"{m[2]}-{month:02}" if month else m[2]
    if m := re.search(r"\b(19|20)\d{2}\b", text):
        return m.group()
    return None


def highlights(text: str | None) -> list[str]:
    """Split a role description into achievement lines: one per list item or paragraph."""
    if not text:
        return []
    lines = [x.strip() for x in str(text).splitlines()]
    items = [BULLET_MARK.sub("", x) for x in lines if BULLET_MARK.match(x)]
    if items:
        return [x for x in items if x]
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", str(text)) if p.strip()]


# --- JSON Resume --------------------------------------------------------------


def from_json_resume(data: dict) -> Imported:
    b = data.get("basics") or {}
    loc = b.get("location") or {}
    place = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("countryCode")) if x)
    links = [b["url"]] if b.get("url") else []
    links += [p["url"] for p in b.get("profiles") or [] if p.get("url")]
    out = Imported(source="JSON Resume", title=b.get("label") or None, summary=b.get("summary") or None)
    out.contact = {k: v for k, v in {"name": b.get("name"), "email": b.get("email"), "phone": b.get("phone"),
                                     "location": place or None, "links": links}.items() if v}
    for w in data.get("work") or []:
        out.roles.append({
            "title": w.get("position"), "company": w.get("name") or w.get("company"),
            "start": norm_date(w.get("startDate")), "end": norm_date(w.get("endDate")),
            "location": w.get("location"),
            "highlights": [h for h in w.get("highlights") or [] if h] or highlights(w.get("summary")),
        })
    for e in data.get("education") or []:
        degree = " ".join(x for x in (e.get("studyType"), e.get("area")) if x)
        out.education.append({"institution": e.get("institution"), "degree": degree or None,
                              "start": norm_date(e.get("startDate")), "end": norm_date(e.get("endDate"))})
    for c in data.get("certificates") or []:
        if c.get("name"):
            out.certifications.append(", ".join(x for x in (c["name"], c.get("issuer")) if x))
    for x in data.get("publications") or []:
        if x.get("name"):
            out.publications.append({"title": x["name"], "venue": x.get("publisher"),
                                     "year": x.get("releaseDate"), "url": x.get("url")})
    for lang in data.get("languages") or []:
        if lang.get("language"):
            out.languages.append(f"{lang['language']} ({lang['fluency']})" if lang.get("fluency") else lang["language"])
    for s in data.get("skills") or []:
        # With keywords, "name" is usually a category ("Backend"), not a skill.
        out.skills += [x for x in (s.get("keywords") or [s.get("name")]) if x]
    return out


# --- LinkedIn data export -----------------------------------------------------


# What a profile needs from the export. The basic export, the one LinkedIn offers when you
# pick files, has only Profile.csv; these come with the full archive.
EXPECTED = ("Positions.csv", "Education.csv", "Skills.csv")


def _zip_files(data: bytes) -> dict[str, bytes]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    return {n.rsplit("/", 1)[-1].lower(): zf.read(n) for n in zf.namelist() if n.lower().endswith(".csv")}


def _dir_files(folder: Path) -> dict[str, bytes]:
    # Safari unzips downloads by default, so the export often arrives as a folder.
    return {p.name.lower(): p.read_bytes() for p in folder.rglob("*.csv") if p.is_file()}


def _csv(files: dict[str, bytes], name: str, header_hint: str) -> list[dict]:
    """Rows of a CSV in the export. Some files start with notes before the header."""
    if name.lower() not in files:
        return []
    lines = files[name.lower()].decode("utf-8-sig").splitlines()
    start = next((i for i, x in enumerate(lines) if header_hint.lower() in x.lower()), None)
    if start is None:
        return []
    # Keep the newlines: a quoted field such as a role's description spans several lines.
    rows = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in rows]


def from_linkedin_zip(data: bytes) -> Imported:
    return from_linkedin(_zip_files(data))


def from_linkedin(zf: dict[str, bytes]) -> Imported:
    """A LinkedIn data export, as {file name: contents}."""
    profile = (_csv(zf, "Profile.csv", "First Name") or [{}])[0]
    out = Imported(source="LinkedIn data export", title=profile.get("Headline") or None,
                   summary=" ".join((profile.get("Summary") or "").split()) or None)
    name = " ".join(x for x in (profile.get("First Name"), profile.get("Last Name")) if x)
    emails = _csv(zf, "Email Addresses.csv", "Email Address")
    email = next((e["Email Address"] for e in emails if e.get("Primary", "").lower() == "yes"), None)
    email = email or next((e["Email Address"] for e in emails if e.get("Email Address")), None)
    phone = next((p.get("Number") for p in _csv(zf, "PhoneNumbers.csv", "Number") if p.get("Number")), None)
    links = [w for w in re.split(r"[,\s]+", profile.get("Websites", "")) if w.startswith("http")]
    out.contact = {k: v for k, v in {"name": name, "email": email, "phone": phone,
                                     "location": profile.get("Geo Location"), "links": links}.items() if v}
    for p in _csv(zf, "Positions.csv", "Company Name"):
        out.roles.append({
            "title": p.get("Title"), "company": p.get("Company Name"),
            "start": norm_date(p.get("Started On")), "end": norm_date(p.get("Finished On")),
            "location": p.get("Location") or None, "highlights": highlights(p.get("Description")),
        })
    for e in _csv(zf, "Education.csv", "School Name"):
        out.education.append({"institution": e.get("School Name"), "degree": e.get("Degree Name") or None,
                              "start": norm_date(e.get("Start Date")), "end": norm_date(e.get("End Date"))})
    for c in _csv(zf, "Certifications.csv", "Name"):
        if c.get("Name"):
            out.certifications.append(", ".join(x for x in (c["Name"], c.get("Authority")) if x))
    for x in _csv(zf, "Publications.csv", "Name"):
        if x.get("Name"):
            out.publications.append({"title": x["Name"], "venue": x.get("Publisher") or None,
                                     "year": norm_date(x.get("Published On")), "url": x.get("Url") or None})
    for x in _csv(zf, "Courses.csv", "Name"):
        if x.get("Name"):
            out.courses.append(x["Name"])
    for lang in _csv(zf, "Languages.csv", "Name"):
        if lang.get("Name"):
            out.languages.append(f"{lang['Name']} ({lang['Proficiency']})" if lang.get("Proficiency") else lang["Name"])
    out.skills = [s["Name"] for s in _csv(zf, "Skills.csv", "Name") if s.get("Name")]
    out.missing = [n for n in EXPECTED if n.lower() not in zf]
    return out


def read(path: str | Path) -> Imported:
    path = Path(path).expanduser()
    suffix = path.suffix.lower()
    if suffix == ".json":
        return from_json_resume(json.loads(path.read_text(encoding="utf-8")))
    if path.is_dir():
        files = _dir_files(path)
        if "profile.csv" not in files:
            raise ValueError(f"{path}: no Profile.csv here; is it the unzipped LinkedIn export?")
        return from_linkedin(files)
    if suffix == ".zip":
        return from_linkedin_zip(path.read_bytes())
    raise ValueError(
        f"{path.name}: import reads JSON Resume (.json) or a LinkedIn data export (.zip, or its folder). "
        "For a LinkedIn profile PDF, read its text and add the data with the editing tools."
    )


# --- merge into a profile -----------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_") or "role"


def _role_id(role: dict, taken: set[str]) -> str:
    base = _slug(role.get("company") or "role")
    candidates = [base, f"{base}_{(role.get('start') or '')[:4]}".rstrip("_")]
    for c in candidates:
        if c not in taken:
            return c
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def merge(folder: str | Path, data: Imported, *, dry_run: bool = False) -> Report:
    """Add what the profile lacks. An empty folder becomes a new profile."""
    folder = Path(folder).expanduser()
    report = Report(missing=list(data.missing))
    if data.missing:
        report.note = (f"This export has no {', '.join(data.missing)}: it is LinkedIn's basic export, which only "
                       "has the profile. Request the full archive (Settings → Data privacy → Download your "
                       "data, the larger one; it can take up to a day), or use the profile PDF.")
    new_profile = not (folder / "profile.yaml").exists()
    if new_profile and not dry_run:
        store.init_profile(folder)
    raw = store._raw(folder) if not new_profile or not dry_run else {f: {} for f in FILES}
    profile = raw["profile.yaml"]
    if new_profile:
        profile.clear()

    contact = profile.setdefault("contact", {})
    for key, value in data.contact.items():
        if key == "links":
            for link in value:
                if link not in contact.setdefault("links", []):
                    contact["links"].append(link)
                    report.add("links", link)
        elif not contact.get(key) or (new_profile and key in {"name", "email"}):
            contact[key] = value
            report.add("contact", key)
        elif contact.get(key) != value:
            report.skip("contact", f"{key} (kept yours)")

    roles = profile.setdefault("roles", [])
    bullets = raw["bullets.yaml"].setdefault("bullets", [])
    taken_roles = {r["id"] for r in roles}
    taken_bullets = {b["id"] for b in bullets}
    for role in sorted(data.roles, key=lambda r: r.get("start") or "", reverse=True):
        if not (role.get("title") and role.get("company") and role.get("start")):
            report.skip("roles", f"{role.get('title') or '?'} at {role.get('company') or '?'} (missing title, company or start)")
            continue
        same = next((r for r in roles if r.get("company", "").casefold() == role["company"].casefold()
                     and str(r.get("start")) == role["start"]), None)
        label = f"{role['title']} at {role['company']}"
        if same is not None:
            report.skip("roles", f"{label} (already there as '{same['id']}')")
            continue
        rid = _role_id(role, taken_roles)
        taken_roles.add(rid)
        roles.append({k: v for k, v in {"id": rid, "title": role["title"], "company": role["company"],
                                        "location": role.get("location"), "start": role["start"],
                                        "end": role.get("end")}.items() if v})
        report.add("roles", f"{label} ({rid})")
        for n, text in enumerate(role.get("highlights") or [], 1):
            bid = f"{rid}_imported_{n}"
            if bid in taken_bullets:
                continue
            taken_bullets.add(bid)
            bullets.append({"id": bid, "role": rid, "tags": ["imported"], "text": text})
            report.add("bullets", bid)
    roles.sort(key=lambda r: str(r.get("start") or ""), reverse=True)

    education = profile.setdefault("education", [])
    for e in data.education:
        if not e.get("institution") or not e.get("degree"):
            report.skip("education", f"{e.get('institution') or '?'} (missing institution or degree)")
            continue
        if any(x.get("institution", "").casefold() == e["institution"].casefold() for x in education):
            report.skip("education", f"{e['institution']} (already there)")
            continue
        education.append({k: v for k, v in e.items() if v})
        report.add("education", e["institution"])

    certifications = profile.setdefault("certifications", [])
    for c in data.certifications:
        if c not in certifications:
            certifications.append(c)
            report.add("certifications", c)
    courses = profile.setdefault("courses", [])
    for c in data.courses:
        if c not in courses:
            courses.append(c)
            report.add("courses", c)
    publications = profile.setdefault("publications", [])
    for x in data.publications:
        if any(p.get("title", "").casefold() == x["title"].casefold() for p in publications):
            report.skip("publications", f"{x['title']} (already there)")
            continue
        taken = {p.get("id") for p in publications}
        pid = base = _slug(x["title"])
        n = 2
        while pid in taken:
            pid, n = f"{base}_{n}", n + 1
        publications.append({"id": pid, **{k: v for k, v in x.items() if v}})
        report.add("publications", x["title"])
    if data.languages and not profile.get("languages"):
        profile["languages"] = ", ".join(data.languages)
        report.add("languages", profile["languages"])

    variants = raw["variants.yaml"].get("variants") or {}
    title = data.title or next((r["title"] for r in data.roles if r.get("title")), None)
    if not variants and title and data.summary:
        # A first variant from the person's own headline and summary, so a CV builds
        # right away. Their real variants come later, from the interview.
        variants["main"] = {
            "title": title, "summary": data.summary,
            "roles": {r["id"]: [b["id"] for b in bullets if b.get("role") == r["id"]] for r in roles},
            "max_pages": 2,
        }
        raw["variants.yaml"]["variants"] = variants
        report.add("variants", "main")
    store._validate(raw)
    if not contact.get("email"):
        report.note = " ".join(x for x in (report.note, "There is no email in it: add yours with set_contact "
                                                         "(or edit profile.yaml) before sending a CV.") if x)
    report.skills = len(data.skills)
    if data.skills:
        report.skills_checklist = str(folder / "imported-skills.md")
    if dry_run:
        return report
    store._write(folder, "profile.yaml", profile)
    store._write(folder, "bullets.yaml", raw["bullets.yaml"])
    if "variants" in report.added:
        store._write(folder, "variants.yaml", raw["variants.yaml"])
    if data.skills and Path(report.skills_checklist).exists():
        report.skills_checklist_kept = True
    elif data.skills:
        lines = [f"# Skills imported from {data.source}", "",
                 "Mark each line with P, L, F or X and write after ' — ' where you used it.",
                 "Then: honest-cv checklist apply <profile> <this file>", "", "## Imported"]
        seen = set()
        for s in data.skills:
            if s.casefold() not in seen:
                seen.add(s.casefold())
                lines.append(f"- [ ] {s}")
        Path(report.skills_checklist).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
