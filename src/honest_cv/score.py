"""Keyword coverage of a CV variant against a job post, and gaps classified
against the person's own inventory.

The MCP client's LLM extracts the keywords from the job post; this module only
measures, deterministically.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from honest_cv import document
from honest_cv.document import FAMILIARITY, Document
from honest_cv.model import Lang, Level, Skill, Source

# Each group lists spellings of the same thing. The first one is the canonical name.
SYNONYMS: list[list[str]] = [
    ["Kubernetes", "k8s"],
    ["JavaScript", "JS", "ECMAScript"],
    ["TypeScript", "TS"],
    ["PostgreSQL", "Postgres", "psql"],
    ["Go", "Golang"],
    ["Node.js", "NodeJS", "Node"],
    ["React", "React.js", "ReactJS"],
    ["Vue", "Vue.js", "VueJS"],
    ["Next.js", "NextJS"],
    ["AWS", "Amazon Web Services"],
    ["GCP", "Google Cloud", "Google Cloud Platform"],
    ["Azure", "Microsoft Azure"],
    ["CI/CD", "CI", "CD", "continuous integration", "continuous delivery", "continuous deployment"],
    ["Spring Boot", "SpringBoot"],
    ["Machine Learning", "ML"],
    ["Artificial Intelligence", "AI"],
    ["Large Language Models", "LLM", "LLMs"],
    ["Natural Language Processing", "NLP"],
    ["C#", "CSharp", "C Sharp"],
    [".NET", "dotnet", ".NET Core"],
    ["C++", "CPP"],
    ["Terraform", "TF", "HCL"],
    ["Elasticsearch", "Elastic Search", "ELK"],
    ["RabbitMQ", "Rabbit MQ", "AMQP"],
    ["Kafka", "Apache Kafka"],
    ["Microservices", "microservice", "micro-services"],
    ["REST", "RESTful", "REST API", "REST APIs"],
    ["gRPC", "grpc"],
    ["MongoDB", "Mongo"],
    ["MySQL", "My SQL"],
    ["SQL Server", "MSSQL", "MS SQL"],
    ["Docker", "containers", "containerization"],
    ["GitHub Actions", "GHA"],
    ["Observability", "monitoring", "telemetry"],
    ["OpenTelemetry", "OTel"],
    ["Distributed Systems", "distributed system"],
    ["Event-Driven Architecture", "event-driven", "EDA"],
    ["Domain-Driven Design", "DDD"],
    ["Test-Driven Development", "TDD"],
    ["Site Reliability Engineering", "SRE"],
    ["Infrastructure as Code", "IaC"],
]

# Short tokens like "Go", "AI" or "CI" collide with ordinary words, so they only
# match with the exact casing given.
CASE_SENSITIVE_MAX_LEN = 3


class Status(StrEnum):
    FOUND = "found"
    FOUND_AS_FAMILIARITY = "found_as_familiarity"  # only on the Familiarity line
    MISSING = "missing"


class Gap(StrEnum):
    IN_INVENTORY_NOT_IN_CV = "in_inventory_not_in_cv"  # a P/L skill, or your bullet pool shows it
    FAMILIARITY_ONLY = "familiarity_only"  # you have it at F
    NOT_IN_INVENTORY = "not_in_inventory"  # X, or never recorded


@dataclass
class KeywordResult:
    keyword: str
    required: bool
    status: Status
    matched_as: str | None = None
    gap: Gap | None = None
    skill: str | None = None  # inventory skill the keyword maps to
    level: str | None = None
    unused_bullets: list[str] = field(default_factory=list)  # pool bullets that mention it


@dataclass
class Score:
    variant: str
    lang: Lang
    coverage: float  # all keywords, F-only matches count half
    required_coverage: float
    keywords: list[KeywordResult]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Keyword:
    term: str
    required: bool = True


def _pattern(term: str) -> re.Pattern:
    # (?<!\w) / (?!\w) instead of \b, so "C++", "C#" and ".NET" match too.
    flags = 0 if len(term) <= CASE_SENSITIVE_MAX_LEN else re.IGNORECASE
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags)


def spellings(term: str, source: Source | None = None) -> list[str]:
    """The term plus its synonyms and, if it maps to an inventory skill, its aliases."""
    found = [term]
    key = term.casefold()
    for group in SYNONYMS:
        if key in (g.casefold() for g in group):
            found += group
    if source is not None:
        skill = find_skill(term, source)
        if skill is not None:
            found += [skill.name, *skill.aliases]
            for group in SYNONYMS:
                if skill.name.casefold() in (g.casefold() for g in group):
                    found += group
    seen, out = set(), []
    for s in found:
        if s.casefold() not in seen:
            seen.add(s.casefold())
            out.append(s)
    return out


def find_skill(term: str, source: Source) -> Skill | None:
    names = {term.casefold()}
    for group in SYNONYMS:
        if term.casefold() in (g.casefold() for g in group):
            names |= {g.casefold() for g in group}
    for skill in source.inventory.skills:
        if {skill.name.casefold(), *(a.casefold() for a in skill.aliases)} & names:
            return skill
    return None


def _match(term_spellings: list[str], text: str) -> str | None:
    for s in term_spellings:
        m = _pattern(s).search(text)
        if m:
            return m.group(0)
    return None


def cv_text(doc: Document) -> tuple[str, str]:
    """(main text, Familiarity line). Kept apart so an F-only match is visible."""
    label = FAMILIARITY[doc.lang]
    parts = [doc.title, doc.summary, " · ".join(doc.competencies), *doc.impact]
    for r in doc.roles:
        parts += [r.heading, r.context or "", *r.bullets]
    familiar = ""
    for s in doc.skills:
        if s.label == label:
            familiar = ", ".join(s.skills)
        else:
            parts.append(f"{s.label}: {', '.join(s.skills)}")
    parts += [*doc.education, *doc.certifications]
    return "\n".join(parts), familiar


def score_variant(source: Source, variant: str, lang: Lang, keywords: list[Keyword]) -> Score:
    doc = document.build(source, variant, lang)
    main, familiar = cv_text(doc)
    used = set(source.resolve(variant).impact)
    for ids in source.resolve(variant).roles.values():
        used |= set(ids)

    results = []
    for kw in keywords:
        names = spellings(kw.term, source)
        skill = find_skill(kw.term, source)
        r = KeywordResult(kw.term, kw.required, Status.MISSING, skill=skill and skill.name,
                          level=skill and skill.level.value)
        if hit := _match(names, main):
            r.status, r.matched_as = Status.FOUND, hit
        elif hit := _match(names, familiar):
            r.status, r.matched_as = Status.FOUND_AS_FAMILIARITY, hit
            r.gap = Gap.FAMILIARITY_ONLY
        else:
            r.gap = _classify(skill)
            # Not a recorded skill, but the person's own bullets show it (e.g. "CI/CD").
            # An explicit X stays a gap: the person said they don't have it.
            if skill is None and any(_bullet_mentions(b, names, lang) for b in source.bullets):
                r.gap = Gap.IN_INVENTORY_NOT_IN_CV
        if r.status is Status.MISSING and r.gap is Gap.IN_INVENTORY_NOT_IN_CV:
            r.unused_bullets = [
                b.id
                for b in source.bullets
                if b.id not in used and _bullet_mentions(b, names, lang)
            ]
        results.append(r)

    return Score(variant, lang, _coverage(results), _coverage([r for r in results if r.required]), results)


def _classify(skill: Skill | None) -> Gap:
    if skill is None or skill.level is Level.NONE:
        return Gap.NOT_IN_INVENTORY
    if skill.level is Level.FAMILIARITY:
        return Gap.FAMILIARITY_ONLY
    return Gap.IN_INVENTORY_NOT_IN_CV


def _bullet_mentions(bullet, names: list[str], lang: Lang) -> bool:
    # Tags are labels, not prose: compare them whole and ignoring case.
    if {t.casefold() for t in bullet.tags} & {n.casefold() for n in names}:
        return True
    text = bullet.text if isinstance(bullet.text, str) else bullet.text.get(lang, "")
    return _match(names, text) is not None


def _coverage(results: list[KeywordResult]) -> float:
    if not results:
        return 1.0
    points = sum(1.0 if r.status is Status.FOUND else 0.5 if r.status is Status.FOUND_AS_FAMILIARITY else 0.0
                 for r in results)
    return round(points / len(results), 3)


def score_job(
    source: Source, keywords: list[Keyword], lang: Lang = "en", variants: list[str] | None = None
) -> list[Score]:
    """Coverage for each variant, best first."""
    scores = [score_variant(source, v, lang, keywords) for v in variants or list(source.variants)]
    return sorted(scores, key=lambda s: (s.required_coverage, s.coverage), reverse=True)


def gap_report(source: Source, variant: str, lang: Lang, keywords: list[Keyword]) -> dict[str, list[KeywordResult]]:
    """Missing keywords grouped by what can honestly be done about them."""
    score = score_variant(source, variant, lang, keywords)
    groups: dict[str, list[KeywordResult]] = {g.value: [] for g in Gap}
    for r in score.keywords:
        if r.gap is not None:
            groups[r.gap.value].append(r)
    return groups
