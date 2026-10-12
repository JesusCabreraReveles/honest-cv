"""Writes to a profile folder. Every write validates the whole profile first and
replaces the file atomically, so a bad edit never leaves a broken profile behind.

PyYAML does not keep comments: a file rewritten here loses them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import yaml

from honest_cv.model import FILES, Bullet, Level, Skill, Source, set_skill_level

TEMPLATES = Path(__file__).parent / "templates" / "profile"


class StoreError(ValueError):
    pass


def init_profile(folder: str | Path) -> list[Path]:
    folder = Path(folder).expanduser()
    existing = [f for f in FILES if (folder / f).exists()]
    if existing:
        raise StoreError(f"{folder}: already has {', '.join(existing)}; not overwriting")
    folder.mkdir(parents=True, exist_ok=True)
    created = []
    for name in FILES:
        shutil.copyfile(TEMPLATES / name, folder / name)
        created.append(folder / name)
    return created


def _read(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _raw(folder: Path) -> dict[str, dict]:
    return {name: _read(folder, name) for name in FILES}


def _validate(raw: dict[str, dict]) -> Source:
    return Source(
        profile=raw["profile.yaml"],
        bullets=raw["bullets.yaml"].get("bullets", []),
        inventory=raw["skills.yaml"],
        variants=raw["variants.yaml"].get("variants", {}),
    )


def _write(folder: Path, name: str, data: dict) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, folder / name)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _dump_model(model) -> dict:
    return model.model_dump(mode="json", exclude_defaults=True)


def upsert_skill(
    folder: str | Path,
    name: str,
    level: Level,
    *,
    evidence: str | None = None,
    confirmed: bool = False,
    **fields,
) -> Skill:
    """Add or change a skill. A new skill counts as moving up from `X`, so it
    needs evidence and confirmation unless it is recorded as `X`."""
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    skills = raw["skills.yaml"].setdefault("skills", [])
    index = next((i for i, s in enumerate(skills) if s["name"].casefold() == name.casefold()), None)
    current = Skill(**skills[index]) if index is not None else Skill(name=name, level=Level.NONE)
    updated = set_skill_level(current, level, evidence=evidence, confirmed=confirmed)
    changes = {k: v for k, v in fields.items() if v is not None}
    updated = Skill(**{**updated.model_dump(), **changes})
    if index is None:
        skills.append(_dump_model(updated))
    else:
        skills[index] = _dump_model(updated)
    _validate(raw)
    _write(folder, "skills.yaml", raw["skills.yaml"])
    return updated


def add_bullet(folder: str | Path, bullet: Bullet) -> Bullet:
    folder = Path(folder).expanduser()
    raw = _raw(folder)
    raw["bullets.yaml"].setdefault("bullets", []).append(_dump_model(bullet))
    _validate(raw)
    _write(folder, "bullets.yaml", raw["bullets.yaml"])
    return bullet
