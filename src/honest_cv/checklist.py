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

A line `evidence: ...` right under a heading applies to every line in that
section that has no evidence of its own.

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
                item.evidence = item.evidence or section_evidence
            out.items += items
        except ValueError as e:
            out.problems.append(f"line {n}: {e}")
    return out


def _items(body: str, mark: str, line: int, section: str) -> list[Item]:
    name, rest = DASH.split(body, maxsplit=1) if DASH.search(body) else (body, "")
    notes = PARENS.findall(name) + PARENS.findall(rest)
    name, rest = PARENS.sub("", name).strip(), PARENS.sub("", rest).strip()
    fields: dict = {}
    evidence: list[str] = []
    for segment in re.split(r"\s+·\s+|\s*;\s+", rest):
        segment = segment.strip().rstrip(".")
        if not segment or BLANK.search(segment) and not KEY.match(segment):
            continue
        if _is_question(segment):
            notes.append(segment)
            continue
        if k := KEY.match(segment):
            key, value = KEYS[k["key"].casefold()], k["value"].strip()
            if BLANK.fullmatch(value) or not value:
                continue
            if key == "years":
                number = NUMBER.search(value)
                if number is None:
                    raise ValueError(f"years should be a number, not '{value}'")
                fields["years"] = float(number.group().replace(",", "."))
            elif key == "last_used_year":
                year = YEAR.search(value)
                if year is None:
                    raise ValueError(f"last year used should be a year like 2026, not '{value}'")
                fields["last_used_year"] = int(year.group())
                extra = YEAR.sub("", value, count=1).strip(" .,")
                if extra:
                    notes.append(extra)
            elif _is_question(value):
                notes.append(value)
            else:
                evidence.append(value)
        else:
            evidence.append(segment)
    notes = [x.strip() for x in notes if x.strip() and not BLANK.search(x)]
    names = [x.strip() for x in re.split(r"\s+/\s+", name) if x.strip()]
    if any(len(x.split()) > MAX_SPLIT_WORDS for x in names):
        names = [" / ".join(names)]
    if not names:
        raise ValueError("no skill name")
    return [
        Item(
            name=x, mark=mark, line=line, section=section,
            evidence="; ".join(evidence) or None, notes="; ".join(notes) or None, **fields,
        )
        for x in names
    ]


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
        skill = find_skill(item.name, source)
        key = (skill.name if skill else item.name).casefold()
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
            out.updates.append((change, old))
        elif change.evidence and change.evidence.strip():
            out.upgrades.append((change, old))
        else:
            out.missing_evidence.append(change)
    return out


def describe(upgrades: list[tuple[SkillChange, Level]]) -> str:
    """The confirmation text: every upgrade with its evidence, for the person to read."""
    lines = [f"Confirm {len(upgrades)} skill upgrade(s):"]
    lines += [f"- {c.name}: {old.value} -> {c.level.value}. Evidence: {c.evidence}" for c, old in upgrades]
    lines.append("Accept only if every line is true and you can defend it in an interview.")
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
