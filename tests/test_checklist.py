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
    assert items["Scala"].evidence is None  # an X line claims nothing
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
    # Java gets new years. Kafka and Scala repeat the inventory, so they save nothing:
    # the section's evidence line never replaces the evidence Kafka already has.
    assert updates == {"Java": (Level.PRODUCTION, Level.PRODUCTION)}
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
    text = checklist.describe(plan.upgrades, load(profile))
    # RabbitMQ is not in the inventory: "new", never "X", which reads as "I don't have it".
    assert "Go: L -> P. Evidence: FX service" in text and "RabbitMQ: new -> P" in text


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


# --- built-in checklists -----------------------------------------------------

BUILTINS = sorted(checklist.BUILTIN.glob("*.md"))


@pytest.mark.parametrize("path", BUILTINS, ids=lambda p: p.stem)
def test_builtin_checklists_are_well_formed(path):
    # The contract for community checklists: title, description, a ★ section,
    # unmarked lines only, canonical names and no duplicates.
    from honest_cv.score import SYNONYMS

    text = path.read_text(encoding="utf-8")
    parsed = checklist.parse(text)
    assert parsed.problems == []
    assert text.startswith("# ") and checklist.available()
    assert any("★" in i.section for i in parsed.items), "needs a ★ section"
    assert {i.mark for i in parsed.items} == {""}, "built-in lines stay unmarked"
    canonical = {g.casefold(): group[0] for group in SYNONYMS for g in group}
    wrong = [i.name for i in parsed.items if canonical.get(i.name.casefold(), i.name) != i.name]
    assert wrong == [], f"use the canonical name from score.SYNONYMS: {wrong}"
    keys = [canonical.get(i.name.casefold(), i.name).casefold() for i in parsed.items]
    assert len(keys) == len(set(keys)), "a skill is listed twice"


def test_compose_merges_without_duplicates_and_prefills(ada):
    text = checklist.compose(["backend-jvm", "platform-sre"], ada)
    parsed = checklist.parse(text)
    names = [i.name.casefold() for i in parsed.items]
    assert len(names) == len(set(names))
    items = by_name(parsed)
    # Kubernetes is in both ★ sections: asked once, prefilled from Ada's inventory.
    assert items["Kubernetes"].mark == "P" and items["Kubernetes"].years == 5
    assert "★" in items["Terraform"].section and items["Terraform"].mark == ""
    # Skills in the inventory but in no list are not lost, except X ones: asking
    # again about what the person doesn't have only makes the file longer.
    assert items["Django"].section == "Also in your inventory"
    assert "Scala" not in checklist.compose(["platform-sre"], ada)


def test_compose_then_apply_changes_nothing(ada):
    every = [b.id for b in checklist.available()]
    plan = checklist.plan(ada, checklist.parse(checklist.compose(every, ada)))
    assert (plan.upgrades, plan.updates, plan.pending, plan.problems) == ([], [], [], [])


def test_parentheses_inside_evidence_are_kept():
    item = checklist.parse("- [P] Go — FX service (internal tool); CLIs · years: 2 (on and off)").items[0]
    assert (item.evidence, item.notes, item.years) == ("FX service (internal tool); CLIs", "on and off", 2)
    item = checklist.parse("- [P] Kafka — Ledger at Acme Co. (v3)").items[0]
    assert (item.evidence, item.notes) == ("Ledger at Acme Co.", "v3")


def test_unknown_builtin_is_an_error(ada):
    with pytest.raises(ValueError, match="unknown checklist"):
        checklist.compose(["cobol"], ada)


def test_cli_new_writes_and_never_overwrites(profile, capsys):
    assert cli.main(["checklist", "new", str(profile), "backend-go", "engineering-lead"]) == 0
    path = profile / "checklist.md"
    assert "## ★ Main skills" in path.read_text(encoding="utf-8")
    assert cli.main(["checklist", "new", str(profile), "frontend"]) == 1
    assert "Frontend" not in path.read_text(encoding="utf-8")


# Found applying a real, hand-written checklist.


def test_a_dash_inside_parentheses_is_not_the_evidence_separator():
    item = checklist.parse("- [X] Cloud certifications (none yet; next: AWS Solutions Architect – Associate)").items[0]
    assert (item.name, item.evidence) == ("Cloud certifications", None)
    assert item.notes == "none yet; next: AWS Solutions Architect – Associate"


def test_text_after_a_semicolon_in_the_name_is_a_note():
    item = checklist.parse("- [X] LLM response streaming (SSE); event streaming with Kafka, yes").items[0]
    assert item.name == "LLM response streaming"
    assert item.notes == "SSE; event streaming with Kafka, yes"


def test_a_comma_list_of_short_names_is_several_skills():
    parsed = checklist.parse("- [X] Diffusion models (tuning), FFmpeg, MLOps (retraining)")
    assert [i.name for i in parsed.items] == ["Diffusion models", "FFmpeg", "MLOps"]


def test_two_names_for_one_skill_merge_at_the_lower_level(ada):
    plan = checklist.plan(ada, checklist.parse("- [F] OpenID Connect\n- [P] OIDC — SSO for the portal\n"))
    assert [(c.name, c.level, c.evidence) for c, _ in plan.upgrades] == [
        ("OpenID Connect", Level.FAMILIARITY, "SSO for the portal")
    ]
    assert "using the lower" in plan.problems[0]


# --- the person's own templates ---------------------------------------------

ACCOUNTING = """\
# Accounting
Skills for an accountant. Any profession works: this is the same format.

## ★ Main skills — years and last year used
- [P] Month-end close — Example Corp
- [ ] IFRS

## Tools
- [ ] SAP FI
- [ ] Excel
"""


@pytest.fixture
def own(profile):
    (profile / checklist.OWN).mkdir()
    (profile / checklist.OWN / "accounting.md").write_text(ACCOUNTING, encoding="utf-8")
    return profile


def test_own_templates_are_listed_with_the_built_in_ones(own):
    found = {b.id: b for b in checklist.available(own)}
    assert found["accounting"].origin == "yours" and found["accounting"].skills == 4
    assert found["accounting"].description.startswith("Skills for an accountant")
    assert found["backend-go"].origin == "built-in"
    assert "accounting" not in {b.id for b in checklist.available()}


def test_compose_an_own_template_with_a_built_in_one(own):
    text = checklist.compose(["accounting", "engineering-lead"], load(own), folder=own)
    items = by_name(checklist.parse(text))
    assert text.startswith("# Skill checklist: Accounting, Engineering leadership\n")
    # The template's own marks are not answers: the inventory prefills the lines.
    assert items["Month-end close"].mark == "" and "★" in items["Month-end close"].section
    assert items["SAP FI"].section == "Tools"


def test_compose_takes_a_path(tmp_path, ada):
    path = tmp_path / "shared.md"
    path.write_text(ACCOUNTING, encoding="utf-8")
    assert "- [ ] IFRS" in checklist.compose([str(path)], ada)
    with pytest.raises(ValueError, match="or the path to a .md file"):
        checklist.compose([str(tmp_path / "missing.md")], ada)


def test_title_names_imported_skills_only_when_there_are_some(ada):
    # The inventory's leftover skills once made every title say "imported skills".
    assert checklist.compose(["platform-sre"], ada).splitlines()[0] == "# Skill checklist: Platform and SRE"


def test_skills_no_achievement_shows(ada):
    # Ada's bullets never mention Redis or AWS; Kafka has several. F and X never count.
    assert checklist.unbacked(ada, ["Kafka", "Redis", "AWS", "Rust", "Scala", "Elixir"]) == ["Redis", "AWS"]


def test_cli_lists_own_templates(own, capsys):
    assert cli.main(["checklist", "list", str(own)]) == 0
    assert "accounting" in capsys.readouterr().out


def test_cli_apply_names_unbacked_skills_even_with_nothing_to_save(profile, tmp_path, capsys):
    path = tmp_path / "checklist.md"
    path.write_text("- [P] Redis\n- [P] Kafka\n", encoding="utf-8")
    assert cli.main(["checklist", "apply", str(profile), str(path)]) == 0
    out = capsys.readouterr().out
    assert "Nothing to save." in out and "1 P/L skill(s) with no achievement that shows them: Redis." in out
