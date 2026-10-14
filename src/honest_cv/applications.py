"""Track job applications: which CV and letter went to which post, and what happened.

They live in <profile>/applications.yaml, next to the profile they were built from.
Logging the same company and role again updates that application; each status
change is kept in its history with its date.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import Field

from honest_cv.model import Lang, Strict, load
from honest_cv.store import _write

FILE = "applications.yaml"


class Status(StrEnum):
    DRAFT = "draft"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Change(Strict):
    status: Status
    date: date


class Application(Strict):
    id: str
    company: str
    role: str
    url: str | None = None
    variant: str | None = None
    lang: Lang | None = None
    files: list[str] = []
    status: Status = Status.DRAFT
    history: list[Change] = []
    notes: str | None = None

    @property
    def updated(self) -> date | None:
        return self.history[-1].date if self.history else None


class Applications(Strict):
    applications: list[Application] = Field(default_factory=list)


def app_id(company: str, role: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{company} {role}".casefold()).strip("_") or "application"


def read(folder: str | Path) -> Applications:
    path = Path(folder) / FILE
    if not path.exists():
        return Applications()
    return Applications.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def log(
    folder: str | Path, company: str, role: str, *, status: Status | str | None = None,
    when: date | None = None, url: str | None = None, variant: str | None = None,
    lang: Lang | None = None, files: list[str] | None = None, notes: str | None = None,
) -> Application:
    """Add an application, or update the one for the same company and role. Fields left
    as None keep their value; files add to the list; a new status goes to the history."""
    folder = Path(folder)
    source = load(folder)
    if variant is not None and variant not in source.variants:
        raise ValueError(f"unknown variant '{variant}'; known: {', '.join(source.variants)}")
    data = read(folder)
    key = app_id(company, role)
    app = next((a for a in data.applications if a.id == key), None)
    if app is None:
        app = Application(id=key, company=company.strip(), role=role.strip())
        data.applications.append(app)
    for name, value in (("url", url), ("variant", variant), ("lang", lang), ("notes", notes)):
        if value is not None:
            setattr(app, name, value)
    app.files += [f for f in files or [] if f not in app.files]
    new = Status(status) if status is not None else None
    if new is not None and (new != app.status or not app.history):
        app.status = new
        app.history.append(Change(status=new, date=when or date.today()))
    elif not app.history:
        app.history.append(Change(status=app.status, date=when or date.today()))
    Applications.model_validate(data.model_dump())  # validate before writing
    _write(folder, FILE, data.model_dump(mode="json", exclude_defaults=True))
    return app


def listing(folder: str | Path, status: list[str] | None = None, today: date | None = None) -> dict:
    """Applications, most recently updated first, with days since their last change, and
    a count per status. `waiting` are the open ones (applied or interview) quiet for 14+ days."""
    today = today or date.today()
    apps = read(folder).applications
    wanted = {Status(s) for s in status or []}
    shown = sorted((a for a in apps if not wanted or a.status in wanted),
                   key=lambda a: a.updated or date.min, reverse=True)

    def row(a: Application) -> dict:
        return {**a.model_dump(mode="json", exclude_defaults=True, exclude={"history"}),
                "status": a.status.value, "updated": a.updated.isoformat() if a.updated else None,
                "days_since_update": (today - a.updated).days if a.updated else None}

    counts = {s.value: n for s in Status if (n := sum(a.status is s for a in apps))}
    waiting = [a.id for a in apps if a.status in (Status.APPLIED, Status.INTERVIEW)
               and a.updated and (today - a.updated).days >= 14]
    return {"applications": [row(a) for a in shown], "counts": counts, "waiting": waiting}
