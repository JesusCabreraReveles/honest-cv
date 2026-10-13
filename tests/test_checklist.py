"""Skill checklists: parsing a marked Markdown list and planning what to save."""

import pytest
import yaml

from honest_cv import checklist, cli, store
from honest_cv.model import Level, load

SAMPLE = """\
# My checklist

Mark P, L, F or X. This line and the legend below are ignored.
- **P** = production

## ★ Main skills — years and last year used
- [P] Java — Payments API at Example Bank · years: 10 · last year: 2026
- [p] Golang — FX service · años: 2 · último uso: 2025 (internal tool)
- [L] Rust — years: __ · last year: ____

## Messaging
evidence: Fictional Fintech, 2020–2026
- [P] Kafka / RabbitMQ
- [F] NATS (read the docs; which version?)
- [P] Pulsar — ¿qué clusters?
- [ ] ZeroMQ
- [?] MQTT
- [x] Scala
- [Q] Bad mark
"""


@pytest.fixture
def profile(tmp_path, ada_raw):
    for name, data in ada_raw.items():
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return tmp_path


def by_name(parsed):
    return {i.name: i for i in parsed.items}


def test_parse_fields_and_marks():
    items = by_name(checklist.parse(SAMPLE))
    java = items["Java"]
    assert (java.mark, java.evidence, java.years, java.last_used_year, java.section) == (
        "P", "Payments API at Example Bank", 10, 2026, "★ Main skills — years and last year used"
    )
    golang = items["Golang"]
    assert (golang.mark, golang.years, golang.last_used_year, golang.notes) == ("P", 2, 2025, "internal tool")
    assert (items["Rust"].years, items["Rust"].evidence) == (None, None)  # blanks are ignored
    assert items["ZeroMQ"].mark == "" and items["MQTT"].mark == "?" and items["Scala"].mark == "X"


def test_section_evidence_and_slash():
    items = by_name(checklist.parse(SAMPLE))
    assert items["Kafka"].evidence == items["RabbitMQ"].evidence == "Fictional Fintech, 2020–2026"
    # A question is never evidence, so the section line applies.
    assert items["Pulsar"].evidence == "Fictional Fintech, 2020–2026"
    assert "¿qué clusters?" in items["Pulsar"].notes
    long = checklist.parse("- [L] LLMs / agents other people used in production")
    assert [i.name for i in long.items] == ["LLMs / agents other people used in production"]


def test_unknown_mark_is_a_problem_not_a_guess():
    assert checklist.parse(SAMPLE).problems == ["line 19: unknown mark [Q]; use P, L, F or X"]


def test_plan_sorts_upgrades_updates_and_pending(profile):
    plan = checklist.plan(load(profile), checklist.parse(SAMPLE))
    upgrades = {c.name: (old, c.level) for c, old in plan.upgrades}
    updates = {c.name: (old, c.level) for c, old in plan.updates}
    # "Golang" is Ada's "Go" through the alias, so it updates that skill.
    assert upgrades == {"Go": (Level.LAB, Level.PRODUCTION), "RabbitMQ": (Level.NONE, Level.PRODUCTION),
                        "NATS": (Level.NONE, Level.FAMILIARITY), "Pulsar": (Level.NONE, Level.PRODUCTION)}
    assert updates == {"Java": (Level.PRODUCTION, Level.PRODUCTION), "Kafka": (Level.PRODUCTION, Level.PRODUCTION),
                       "Scala": (Level.NONE, Level.NONE)}
    # Rust (F -> L) has no evidence, not even from its section: pending, never saved.
    assert [i.name for i in plan.pending] == ["Rust"]
    assert plan.unmarked == 1 and plan.unsure == ["MQTT"]


def test_duplicate_lines_keep_the_lower_level(profile):
    text = "- [P] Kafka — a\n- [F] kafka — b\n"
    plan = checklist.plan(load(profile), checklist.parse(text))
    assert [(c.name, c.level) for c in plan.changes] == [("Kafka", Level.FAMILIARITY)]
    assert "using the lower" in plan.problems[0]


def test_describe_lists_every_upgrade(profile):
    plan = checklist.plan(load(profile), checklist.parse(SAMPLE))
    text = checklist.describe(plan.upgrades)
    assert "Go: L -> P. Evidence: FX service" in text and "RabbitMQ: X -> P" in text


def test_line_round_trips(profile):
    change = store.SkillChange("Kafka", Level.PRODUCTION, "Ledger", years=7, last_used_year=2026, notes="v3")
    item = checklist.parse(checklist.line(change)).items[0]
    assert (item.name, item.mark, item.evidence, item.years, item.last_used_year, item.notes) == (
        "Kafka", "P", "Ledger", 7, 2026, "v3"
    )


def test_cli_apply_saves_after_one_confirmation(profile, tmp_path, monkeypatch, capsys):
    path = tmp_path / "checklist.md"
    path.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(["checklist", "apply", str(profile), str(path)]) == 0
    inv = load(profile).inventory
    assert inv.get("Go").level is Level.PRODUCTION and inv.get("Go").years == 2
    assert inv.get("RabbitMQ").evidence == "Fictional Fintech, 2020–2026"
    assert inv.get("Rust").level is Level.FAMILIARITY
    out = capsys.readouterr().out
    assert "1 marked line(s) need evidence" in out and "Confirm 4 skill upgrade(s)" in out


def test_cli_apply_saves_nothing_when_declined(profile, tmp_path, monkeypatch):
    path = tmp_path / "checklist.md"
    path.write_text(SAMPLE, encoding="utf-8")
    before = (profile / "skills.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["checklist", "apply", str(profile), str(path)]) == 1
    assert (profile / "skills.yaml").read_text(encoding="utf-8") == before
