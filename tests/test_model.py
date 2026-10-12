import pytest
from pydantic import ValidationError

from honest_cv import document
from honest_cv.model import MissingTranslation, ProfileError, explain, load


def test_loads_example(ada):
    assert ada.profile.contact.name == "Ada Example"
    assert set(ada.variants) == {"backend", "platform", "leadership"}


def test_extends_overrides_and_merges_roles(ada):
    base, child = ada.resolve("backend"), ada.resolve("leadership")
    assert child.title != base.title and child.summary != base.summary
    assert child.skills == base.skills  # not set in the child: inherited
    assert child.roles["fintech"][0] == "ft_mentor"  # set in the child: replaced
    assert child.roles["bank"] == base.roles["bank"]  # other roles: merged from the parent


def test_extends_cycle(make_source):
    def mutate(raw):
        raw["variants"]["variants"]["backend"]["extends"] = "platform"

    with pytest.raises(ValidationError, match="variant cycle"):
        make_source(mutate)


def test_unknown_bullet(make_source):
    def mutate(raw):
        raw["variants"]["variants"]["backend"]["impact"] = ["nope"]

    with pytest.raises(ValidationError, match="unknown bullet 'nope'"):
        make_source(mutate)


def test_bullet_must_belong_to_role(make_source):
    def mutate(raw):
        raw["variants"]["variants"]["backend"]["roles"]["bank"] = ["ft_kafka"]

    with pytest.raises(ValidationError, match="does not belong to role 'bank'"):
        make_source(mutate)


def test_variant_skill_must_exist_in_inventory(make_source):
    def mutate(raw):
        raw["variants"]["variants"]["backend"]["skills"][0]["skills"].append("COBOL")

    with pytest.raises(ValidationError, match="'COBOL' is not in the inventory"):
        make_source(mutate)


def test_duplicate_bullet_id(make_source):
    def mutate(raw):
        raw["bullets"]["bullets"].append(dict(raw["bullets"]["bullets"][0]))

    with pytest.raises(ValidationError, match="duplicate bullet id"):
        make_source(mutate)


def test_unknown_field_rejected(make_source):
    def mutate(raw):
        raw["skills"]["skills"][0]["levle"] = "P"

    with pytest.raises(ValidationError, match="levle"):
        make_source(mutate)


def test_missing_translation(make_source):
    def mutate(raw):
        del raw["bullets"]["bullets"][0]["text"]["es"]

    source = make_source(mutate)
    document.build(source, "backend", "en")
    with pytest.raises(MissingTranslation, match="bullet imp_k8s: no 'es' text"):
        document.build(source, "backend", "es")


def test_missing_profile(tmp_path):
    with pytest.raises(ProfileError, match="missing profile.yaml"):
        load(tmp_path)


def test_comma_in_flow_mapping_gets_a_hint(tmp_path):
    (tmp_path / "profile.yaml").write_text("contact: {name: A, email: a@example.com}\n", encoding="utf-8")
    (tmp_path / "skills.yaml").write_text("skills:\n  - {name: AWS, level: P, evidence: EKS, RDS and MSK}\n", encoding="utf-8")
    with pytest.raises(ValidationError) as e:
        load(tmp_path)
    assert "Put text with commas in quotes" in explain(e.value)
