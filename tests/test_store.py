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
