import pytest
import yaml
from pydantic import ValidationError

from honest_cv import store
from honest_cv.model import Bullet, Level, SkillUpgradeError, load


@pytest.fixture
def profile(tmp_path, ada_raw):
    for name, data in ada_raw.items():
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return tmp_path


def test_init_profile_creates_loadable_templates(tmp_path):
    created = store.init_profile(tmp_path / "me")
    assert [p.name for p in created] == ["profile.yaml", "bullets.yaml", "skills.yaml", "variants.yaml"]
    assert load(tmp_path / "me").profile.contact.name == "Your Name"


def test_init_profile_never_overwrites(profile):
    before = (profile / "skills.yaml").read_text(encoding="utf-8")
    with pytest.raises(store.StoreError, match="not overwriting"):
        store.init_profile(profile)
    assert (profile / "skills.yaml").read_text(encoding="utf-8") == before


def test_new_skill_counts_as_upgrade_from_x(profile):
    with pytest.raises(SkillUpgradeError, match="requires evidence"):
        store.upsert_skill(profile, "Terraform", Level.LAB)
    with pytest.raises(SkillUpgradeError, match="requires human confirmation"):
        store.upsert_skill(profile, "Terraform", Level.LAB, evidence="Home lab")
    assert load(profile).inventory.get("Terraform") is None


def test_new_x_skill_needs_nothing(profile):
    store.upsert_skill(profile, "Haskell", Level.NONE)
    assert load(profile).inventory.get("Haskell").level is Level.NONE


def test_confirmed_upgrade_is_saved_and_keeps_fields(profile):
    store.upsert_skill(profile, "rust", Level.LAB, evidence="CLI tool", confirmed=True, years=1)
    rust = load(profile).inventory.get("Rust")
    assert (rust.level, rust.evidence, rust.years, rust.notes) == (Level.LAB, "CLI tool", 1, "Read the book, small exercises")


def test_downgrade_is_free(profile):
    store.upsert_skill(profile, "Java", Level.FAMILIARITY)
    assert load(profile).inventory.get("Java").level is Level.FAMILIARITY


def test_add_bullet(profile):
    store.add_bullet(profile, Bullet(id="ft_new", role="fintech", text={"en": "Did a thing."}))
    assert load(profile).bullet("ft_new").role == "fintech"


def test_invalid_write_leaves_files_untouched(profile):
    before = (profile / "bullets.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError, match="unknown role"):
        store.add_bullet(profile, Bullet(id="x", role="nope", text="Text"))
    with pytest.raises(ValidationError, match="duplicate bullet id"):
        store.add_bullet(profile, Bullet(id="ft_kafka", role="fintech", text="Text"))
    assert (profile / "bullets.yaml").read_text(encoding="utf-8") == before
    assert not list(profile.glob(".*.tmp"))


def test_last_used_year_must_be_a_year(profile):
    # Seen in manual testing: "last_used: 1" was saved. A year is what is meant.
    with pytest.raises(ValidationError, match="must be a calendar year"):
        store.upsert_skill(profile, "Java", Level.PRODUCTION, last_used_year=1)
    store.upsert_skill(profile, "Java", Level.PRODUCTION, last_used_year=2024)
    assert load(profile).inventory.get("Java").last_used_year == 2024


def test_text_is_saved_without_stray_whitespace(profile):
    store.upsert_skill(profile, "Rust", Level.LAB, evidence=" CLI tool on GitHub. ", confirmed=True)
    assert load(profile).inventory.get("Rust").evidence == "CLI tool on GitHub."


def test_set_contact_changes_only_given_fields(profile):
    store.set_contact(profile, email="ada@new.example", phone=store.CLEAR)
    contact = load(profile).profile.contact
    assert (contact.name, contact.email, contact.phone) == ("Ada Example", "ada@new.example", None)


def test_upsert_role_places_new_roles_by_date_and_edits_in_place(profile):
    store.upsert_role(profile, "agency", title="Contractor", company="Some Agency", start="2018", end="2019")
    store.upsert_role(profile, "fintech", end="2026")
    roles = load(profile).profile.roles
    assert [r.id for r in roles] == ["fintech", "agency", "bank", "startup"]
    assert roles[0].end == "2026" and roles[0].company == "Fictional Fintech"
    store.upsert_role(profile, "fintech", end=store.CLEAR)
    assert load(profile).profile.roles[0].end is None


def test_new_role_needs_its_required_fields(profile):
    before = (profile / "profile.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError, match="company"):
        store.upsert_role(profile, "half", title="Engineer", start="2024")
    assert (profile / "profile.yaml").read_text(encoding="utf-8") == before


def test_upsert_education(profile):
    store.upsert_education(profile, "universidad ficticia", end="2012")
    store.upsert_education(profile, "Online School", degree="Data Engineering bootcamp", end="2021")
    education = load(profile).profile.education
    assert [e.institution for e in education] == ["Universidad Ficticia", "Online School"]
    assert education[0].end == "2012"


def test_profile_details(profile):
    store.set_profile_details(profile, certifications=["CKA"], languages={"en": "English (C1)", "es": "Inglés (C1)"})
    p = load(profile).profile
    assert p.certifications == ["CKA"] and p.languages == {"en": "English (C1)", "es": "Inglés (C1)"}
    store.set_profile_details(profile, courses=[{"en": "Leadership course, 2021", "es": "Curso de liderazgo, 2021"}])
    p = load(profile).profile
    assert p.certifications == ["CKA"] and p.courses == [{"en": "Leadership course, 2021", "es": "Curso de liderazgo, 2021"}]


def test_save_variant_checks_references_and_children(profile):
    from honest_cv.model import Variant

    store.save_variant(profile, "sre", Variant(extends="platform", title="Site Reliability Engineer"))
    assert load(profile).resolve("sre").title == "Site Reliability Engineer"
    with pytest.raises(ValidationError, match="unknown bullet"):
        store.save_variant(profile, "bad", Variant(title="T", summary="S", impact=["nope"]))
    # Replacing a parent must not break the variants that extend it.
    with pytest.raises(ValidationError, match="missing 'summary'"):
        store.save_variant(profile, "backend", Variant(title="Backend only"))
    assert load(profile).resolve("platform").summary


# --- removal -------------------------------------------------------------------


def test_remove_bullet_leaves_no_reference(profile):
    out = store.remove_bullet(profile, "ft_k8s")
    source = load(profile)
    assert "ft_k8s" not in {b.id for b in source.bullets}
    assert set(out["variants_updated"]) == {"backend", "platform", "leadership"}
    assert all("ft_k8s" not in source.resolve(v).impact for v in source.variants)


def test_remove_skill_also_leaves_skill_groups_and_competencies(profile):
    out = store.remove_skill(profile, "kafka")
    source = load(profile)
    assert out["removed"] == "Kafka" and source.inventory.get("Kafka") is None
    for v in source.variants:
        resolved = source.resolve(v)
        assert "Kafka" not in resolved.competencies
        assert all("Kafka" not in g.skills for g in resolved.skills)


def test_remove_role_refuses_while_it_has_bullets(profile):
    before = {f: (profile / f).read_text(encoding="utf-8") for f in ("profile.yaml", "bullets.yaml")}
    with pytest.raises(ValueError, match="has 4 bullet"):
        store.remove_role(profile, "bank")
    assert before == {f: (profile / f).read_text(encoding="utf-8") for f in before}
    out = store.remove_role(profile, "bank", with_bullets=True)
    source = load(profile)
    assert "bank" not in {r.id for r in source.profile.roles} and len(out["bullets_removed"]) == 4
    assert all("bank" not in source.resolve(v).roles for v in source.variants)


def test_remove_unknown_is_an_error(profile):
    for fn, arg in ((store.remove_bullet, "nope"), (store.remove_skill, "COBOL"), (store.remove_role, "nope")):
        with pytest.raises(ValueError, match="unknown"):
            fn(profile, arg)
