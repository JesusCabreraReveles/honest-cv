"""Skill checklists: a Markdown list a person marks with one letter per skill.

    ## Messaging and streaming
    - [P] Kafka — reconciliation flow at Acme
    - [F] RabbitMQ (read the docs)
    - [ ] NATS

The mark is P, L, F or X (any case). `[ ]` means not marked yet and `[?]` means
unsure; both are skipped. After the name:
- text after " — " is the evidence;
- text in parentheses is a note;
- `years: 8` and `last year: 2026` (also `años:` and `último uso:`) fill those fields;
- a question ("which services?") is kept as a note, never as evidence;
- blanks like `__` are ignored, so a template line can be left half filled.
"A / B" with short names records two skills with the same mark.

A line `evidence: ...` right under a heading applies to every P, L or F line in
that section that has no evidence of its own.

The honesty rule does not change: a skill that moves up a level (a new one
counts as moving up from X) needs evidence and the person's confirmation.
Marked lines without evidence are reported as pending, never saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from honest_cv.model import LEVEL_RANK, Level, Source
from honest_cv.score import find_skill
from honest_cv.store import SkillChange

ITEM = re.compile(r"^\s*[-*+]\s*\[(?P<mark>[^\]]?)\]\s*(?P<body>.+?)\s*$")
HEADING = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")
SECTION_EVIDENCE = re.compile(r"^\s*>?\s*(?:evidence|evidencia)\s*:\s*(?P<text>.+?)\s*$", re.I)
MAX_SPLIT_WORDS = 3  # "Kafka / Redpanda" is two skills; "LLMs / agents others used" is one
DASH = re.compile(r"\s+(?:—|–|--)\s+")
PARENS = re.compile(r"\(([^()]*)\)")
TRAILING_PARENS = re.compile(r"\s*\(([^()]*)\)\s*$")
SEPARATOR = re.compile(r"\s+·\s+|;\s+")
BLANK = re.compile(r"_{2,}")
YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
KEYS = {
    "years": "years",
    "año": "years",
    "años": "years",
    "anos": "years",
    "last year": "last_used_year",
    "last used": "last_used_year",
    "last use": "last_used_year",
    "last_used_year": "last_used_year",
    "último uso": "last_used_year",
    "ultimo uso": "last_used_year",
    "último año": "last_used_year",
    "evidence": "evidence",
    "evidencia": "evidence",
}
KEY = re.compile(r"^\s*(?P<key>" + "|".join(sorted(map(re.escape, KEYS), key=len, reverse=True)) + r")\s*:\s*(?P<value>.*)$", re.I)


@dataclass
class Item:
    name: str
    mark: str  # "P", "L", "F", "X", "" (not marked) or "?" (unsure)
    line: int
    section: str = ""
    evidence: str | None = None
    years: float | None = None
    last_used_year: int | None = None
    notes: str | None = None
    evidence_from_section: bool = False

    @property
    def level(self) -> Level | None:
        return Level(self.mark) if self.mark in {lvl.value for lvl in Level} else None


@dataclass
class Parsed:
    items: list[Item] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def parse(text: str) -> Parsed:
    out = Parsed()
    section, section_evidence = "", None
    for n, line in enumerate(text.splitlines(), start=1):
        if m := HEADING.match(line):
            section, section_evidence = m["title"], None
            continue
        if m := SECTION_EVIDENCE.match(line):
            if not BLANK.search(m["text"]):
                section_evidence = m["text"]
            continue
        m = ITEM.match(line)
        if not m:
            continue
        mark = m["mark"].strip().upper()
        if mark not in {"", "?", "P", "L", "F", "X"}:
            out.problems.append(f"line {n}: unknown mark [{m['mark']}]; use P, L, F or X")
            continue
        try:
            items = _items(m["body"], mark, n, section)
            for item in items:
                if item.mark in {"P", "L", "F"} and not item.evidence and section_evidence:
                    # An X line claims nothing, so it needs none.
                    item.evidence, item.evidence_from_section = section_evidence, True
            out.items += items
        except ValueError as e:
            out.problems.append(f"line {n}: {e}")
    return out


def _items(body: str, mark: str, line: int, section: str) -> list[Item]:
    dash = next((m for m in DASH.finditer(body) if _outside_parens(body, m.start())), None)
    name, rest = (body[: dash.start()], body[dash.end() :]) if dash else (body, "")
    notes = PARENS.findall(name)
    # After the name, "; more text" is a note: "LLM streaming (SSE); Kafka events, yes".
    name, *extra = _split_outside_parens(_tidy(PARENS.sub("", name)))
    notes += extra
    fields: dict = {}
    evidence: list[str] = []
    segments = _split_outside_parens(rest)
    for n, segment in enumerate(segments):
        segment = segment.strip()
        if not segment or BLANK.search(segment) and not KEY.match(segment):
            continue
        if _is_question(segment):
            notes.append(segment)
            continue
        k = KEY.match(segment)
        if k and KEYS[k["key"].casefold()] != "evidence":
            key, value = KEYS[k["key"].casefold()], k["value"]
            notes += PARENS.findall(value)
            value = PARENS.sub("", value).strip()
            if BLANK.fullmatch(value) or not value:
                continue
            if key == "years":
                number = NUMBER.search(value)
                if number is None:
                    raise ValueError(f"years should be a number, not '{value}'")
                fields["years"] = float(number.group().replace(",", "."))
            else:
                year = YEAR.search(value)
                if year is None:
                    raise ValueError(f"last year used should be a year like 2026, not '{value}'")
                fields["last_used_year"] = int(year.group())
                extra = YEAR.sub("", value, count=1).strip(" .,")
                if extra:
                    notes.append(extra)
            continue
        value = k["value"].strip() if k else segment
        # A parenthesis that ends the line is a note: "Kafka — Ledger (v3)". Inside the
        # evidence, or after "evidence:", it is kept: "FX service (internal tool); CLIs".
        if not k and n == len(segments) - 1 and (m := TRAILING_PARENS.search(value)):
            notes.append(m.group(1))
            value = value[: m.start()].strip()
        if _is_question(value):
            notes.append(value)
        elif value and not BLANK.search(value):
            evidence.append(value)
    notes = [x.strip() for x in notes if x.strip() and not BLANK.search(x)]
    name = name.strip()
    names = [x.strip() for x in re.split(r"\s+/\s+|,\s+", name) if x.strip()]
    if any(len(x.split()) > MAX_SPLIT_WORDS for x in names):
        names = [name]
    if not names:
        raise ValueError("no skill name")
    return [
        Item(
            name=x, mark=mark, line=line, section=section,
            evidence="; ".join(evidence) or None, notes="; ".join(notes) or None, **fields,
        )
        for x in names
    ]


def _outside_parens(text: str, at: int) -> bool:
    return text[:at].count("(") == text[:at].count(")")


def _tidy(text: str) -> str:
    """Spacing left behind by a removed "(...)": "diffusion models , FFmpeg" -> "..., FFmpeg"."""
    return re.sub(r"\s+([,;.])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()


def _split_outside_parens(text: str) -> list[str]:
    """Split on " · " and "; ", but not inside parentheses, which hold free notes."""
    parts, start = [], 0
    for m in SEPARATOR.finditer(text):
        if _outside_parens(text, m.start()):
            parts.append(text[start : m.start()])
            start = m.end()
    parts.append(text[start:])
    return parts


def _is_question(text: str) -> bool:
    text = text.strip()
    return text.startswith("¿") or text.endswith("?")


@dataclass
class Plan:
    """What applying a checklist would do. Nothing is saved until `changes` is."""

    upgrades: list[tuple[SkillChange, Level]] = field(default_factory=list)  # need confirmation
    updates: list[tuple[SkillChange, Level]] = field(default_factory=list)  # same level or lower
    pending: list[Item] = field(default_factory=list)  # checklist lines: upgrade without evidence
    missing_evidence: list[SkillChange] = field(default_factory=list)
    unmarked: int = 0
    unsure: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def changes(self) -> list[SkillChange]:
        return [c for c, _ in self.updates + self.upgrades]

    def summary(self) -> dict:
        def row(c: SkillChange, old: Level) -> dict:
            return {"name": c.name, "from": old.value, "to": c.level.value, "evidence": c.evidence}

        return {
            "upgrades": [row(c, old) for c, old in self.upgrades],
            "updates": [row(c, old) for c, old in self.updates],
            "pending_evidence": [
                {"name": i.name, "level": i.mark, "line": i.line, "notes": i.notes} for i in self.pending
            ],
            "unmarked": self.unmarked,
            "unsure": self.unsure,
            "problems": self.problems,
        }


def plan(source: Source, parsed: Parsed) -> Plan:
    out = Plan(problems=list(parsed.problems))
    merged: dict[str, Item] = {}
    for item in parsed.items:
        if item.mark == "":
            out.unmarked += 1
            continue
        if item.mark == "?":
            out.unsure.append(item.name)
            continue
        key = _key(item.name, source)
        if key in merged:
            merged[key] = _merge(merged[key], item, out.problems)
        else:
            merged[key] = item
    pairs = [
        (
            i,
            SkillChange(
                name=i.name, level=i.level, evidence=i.evidence,
                years=i.years, last_used_year=i.last_used_year, notes=i.notes,
            ),
        )
        for i in merged.values()
    ]
    for item, change in pairs:
        skill = find_skill(item.name, source)
        if item.evidence_from_section and skill is not None and LEVEL_RANK[item.level] <= LEVEL_RANK[skill.level]:
            # The section line backs an upgrade; it never replaces what a skill already says.
            change.evidence = None
    classify(source, [c for _, c in pairs], out)
    missing = {id(c) for c in out.missing_evidence}
    out.pending = [i for i, c in pairs if id(c) in missing]
    return out


def classify(source: Source, changes: list[SkillChange], out: Plan | None = None) -> Plan:
    """Sort changes into upgrades (need confirmation), updates (same level or lower)
    and upgrades without evidence. Names that match an inventory skill, its aliases
    or a synonym are renamed to it, so "Golang" updates "Go"."""
    out = out or Plan()
    for change in changes:
        skill = find_skill(change.name, source)
        old = skill.level if skill else Level.NONE
        if skill is not None:
            change.name = skill.name
        if LEVEL_RANK[change.level] <= LEVEL_RANK[old]:
            if skill is None or _changes_something(change, skill):
                out.updates.append((change, old))
        elif change.evidence and change.evidence.strip():
            out.upgrades.append((change, old))
        else:
            out.missing_evidence.append(change)
    return out


def _changes_something(change: SkillChange, skill) -> bool:
    """A line that repeats what the inventory already says saves nothing."""
    if change.level != skill.level:
        return True
    fields = ("evidence", "years", "last_used_year", "aliases", "notes")
    return any(getattr(change, f) is not None and getattr(change, f) != getattr(skill, f) for f in fields)


def new_skills(upgrades: list[tuple[SkillChange, Level]], source: Source) -> frozenset[str]:
    """Upgrades of skills not in the inventory yet. They are shown as "new", never as
    "X", which would read as if the person had said they don't have them."""
    return frozenset(c.name for c, _ in upgrades if source.inventory.get(c.name) is None)


def describe(upgrades: list[tuple[SkillChange, Level]], source: Source) -> str:
    """The confirmation text: every upgrade with its evidence, for the person to read."""
    new = new_skills(upgrades, source)
    lines = [f"Confirm {len(upgrades)} skill upgrade(s):"]
    lines += [f"- {c.name}: {'new' if c.name in new else old.value} -> {c.level.value}. Evidence: {c.evidence}"
              for c, old in upgrades]
    lines.append('Type "yes" or "sí" and accept only if every line is true and you can defend it in an interview.')
    return "\n".join(lines)


def _merge(a: Item, b: Item, problems: list[str]) -> Item:
    """The same skill listed twice: keep the lower level, and fill blanks from either."""
    if a.mark != b.mark:
        problems.append(f"{a.name}: marked {a.mark} on line {a.line} and {b.mark} on line {b.line}; using the lower")
    low = a if LEVEL_RANK[a.level] <= LEVEL_RANK[b.level] else b
    other = b if low is a else a
    merged = Item(**low.__dict__)
    for f in ("evidence", "years", "last_used_year", "notes"):
        if getattr(merged, f) is None:
            setattr(merged, f, getattr(other, f))
    return merged


def read(path: str | Path) -> Parsed:
    return parse(Path(path).expanduser().read_text(encoding="utf-8"))


def line(change: SkillChange) -> str:
    """One checklist line for a change, the inverse of `parse` for a single item."""
    parts = [change.evidence] if change.evidence else []
    if change.years is not None:
        parts.append(f"years: {change.years:g}")
    if change.last_used_year is not None:
        parts.append(f"last year: {change.last_used_year}")
    if change.evidence and change.evidence.rstrip().endswith(")") and len(parts) == 1:
        parts = [f"evidence: {change.evidence}"]  # so its parentheses are not read as a note
    text = f"- [{change.level.value}] {change.name}"
    if parts:
        text += " — " + " · ".join(parts)
    if change.notes:
        text += f" ({change.notes})"
    return text


def write_pending(folder: str | Path, changes: list[SkillChange]) -> Path:
    """Save upgrades a client could not confirm as a checklist, for the CLI to apply."""
    path = Path(folder).expanduser() / "pending-upgrades.md"
    body = ["# Skill upgrades waiting for your confirmation", ""]
    body += [line(c) for c in changes]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


# --- built-in checklists ------------------------------------------------------

BUILTIN = Path(__file__).parent / "checklists"
STAR = "★ Main skills — years and last year used"
LEGEND = """\
<!-- Mark each line between the brackets:
  P = used in production at a job      L = your own project or lab
  F = familiarity (you tried or read about it)      X = you don't have it
  [ ] = not marked yet (skipped)       [?] = unsure (skipped)
After " — " write where and how you used it: that is the evidence an upgrade needs.
A line "evidence: ..." under a heading applies to every line in that section without its own.
Text in (parentheses) is a private note. Years and last year are asked only in the ★ section.
Then run: honest-cv checklist apply <profile> <this file> -->
"""


OWN = "checklists"  # the person's own templates: <profile>/checklists/*.md


@dataclass
class Builtin:
    """A checklist template: built in, or the person's own."""

    id: str
    title: str
    description: str
    skills: int
    origin: str = "built-in"
    path: str = ""


def _template(path: Path, origin: str) -> Builtin:
    text = path.read_text(encoding="utf-8")
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    title = next((x.lstrip("# ") for x in lines if x.startswith("# ")), path.stem)
    description = next((x for x in lines if not x.startswith(("#", "-", "<!--", "evidence:"))), "")
    return Builtin(path.stem, title, description, len(parse(text).items), origin, str(path))


def available(folder: Path | None = None) -> list[Builtin]:
    """The built-in templates, plus the person's own in <folder>/checklists/. An own
    template with a built-in's id replaces it: the person's file is the one they mean."""
    out = {path.stem: _template(path, "built-in") for path in sorted(BUILTIN.glob("*.md"))}
    if folder is not None:
        out |= {path.stem: _template(path, "yours") for path in sorted((Path(folder) / OWN).glob("*.md"))}
    return list(out.values())


def _resolve(ids: list[str], folder: Path | None) -> list[Builtin]:
    """Template ids from `available`, or paths to any Markdown file in the checklist format."""
    known = {b.id: b for b in available(folder)}
    out, unknown = [], []
    for i in ids:
        if i in known:
            out.append(known[i])
        elif i.endswith(".md") and (path := Path(i).expanduser()).is_file():
            out.append(_template(path, "file"))
        else:
            unknown.append(i)
    if unknown:
        raise ValueError(f"unknown checklist(s): {', '.join(unknown)}; available: {', '.join(sorted(known))}, "
                         "or the path to a .md file")
    return out


def unbacked(source: Source, names: list[str]) -> list[str]:
    """P and L skills among `names` that no achievement mentions: each one needs a real
    example from the person, or the CV claims it with nothing behind it."""
    from honest_cv.score import _match, spellings

    pool = "\n".join(
        t for b in source.bullets for t in ([b.text] if isinstance(b.text, str) else list(b.text.values())) + b.tags
    )
    out = []
    for name in names:
        skill = find_skill(name, source)
        if skill and skill.level in (Level.PRODUCTION, Level.LAB) and skill.name not in out:
            if _match(spellings(skill.name, source), pool) is None:
                out.append(skill.name)
    return out


def _canonical(name: str) -> str:
    from honest_cv.score import SYNONYMS

    key = name.casefold()
    return next((g[0] for g in SYNONYMS if key in (x.casefold() for x in g)), name)


def compose(ids: list[str], source: Source | None = None, extra: list[str] | None = None,
            folder: Path | None = None) -> str:
    """Merge checklist templates into one, without duplicates, prefilled from the inventory.

    `ids` are built-in or own templates (see `available`), or paths to .md files. Sections
    with the same heading merge. A skill keeps its first place, and the ★ sections come
    first, so a key skill is asked once with its years. Marks in a template are ignored:
    the inventory prefills the lines. `extra` names skills found elsewhere, e.g. in an
    imported LinkedIn profile."""
    if not ids and not extra:
        raise ValueError("name at least one checklist, or extra skills")
    templates = _resolve(ids, folder)
    parsed = [parse(Path(t.path).read_text(encoding="utf-8")) for t in templates]
    sections: dict[str, list[str]] = {STAR: []}
    seen: set[str] = set()
    for p in parsed:
        for item in p.items:
            if "★" in item.section:
                _add(sections, STAR, item.name, seen)
    for p in parsed:
        for item in p.items:
            if "★" not in item.section:
                _add(sections, item.section, item.name, seen)
    for name in extra or []:
        _add(sections, "Found in your imported profile", name, seen, source)
    if source is not None:
        # X skills in no list stay out: asking again about what they don't have is noise.
        rest = [
            s.name for s in source.inventory.skills
            if _key(s.name, source) not in seen and s.level is not Level.NONE
        ]
        for name in rest:
            _add(sections, "Also in your inventory", name, seen, source)

    titles = [t.title for t in templates] + (["imported skills"] if extra else [])
    out = [f"# Skill checklist: {', '.join(titles)}", "", LEGEND]
    for heading, names in sections.items():
        if not names:
            continue
        out += [f"## {heading}"]
        out += [_render(name, heading == STAR, source) for name in names]
        out.append("")
    return "\n".join(out)


def _key(name: str, source: Source | None) -> str:
    skill = find_skill(name, source) if source is not None else None
    return (skill.name if skill else _canonical(name)).casefold()


def _add(sections: dict[str, list[str]], heading: str, name: str, seen: set[str], source: Source | None = None) -> None:
    key = _key(name, source)
    if key in seen:
        return
    seen.add(key)
    sections.setdefault(heading, []).append(name)


def _render(name: str, star: bool, source: Source | None) -> str:
    skill = find_skill(name, source) if source is not None else None
    if skill is None:
        return f"- [ ] {name}" + (" — years: __ · last year: ____" if star else "")
    change = SkillChange(
        name=skill.name, level=skill.level, evidence=skill.evidence,
        years=skill.years, last_used_year=skill.last_used_year, notes=skill.notes,
    )
    text = line(change)
    if star and skill.years is None:
        text += (" · " if " — " in text else " — ") + "years: __"
    if star and skill.last_used_year is None:
        text += (" · " if " — " in text else " — ") + "last year: ____"
    return text
