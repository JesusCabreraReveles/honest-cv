import pytest
import yaml

from tests.conftest import ADA
from honest_cv.score import Gap, Keyword, Status, _pattern, gap_report, score_job, score_variant, spellings


def by_keyword(score):
    return {r.keyword: r for r in score.keywords}


def test_synonyms_match_both_ways(ada):
    s = by_keyword(score_variant(ada, "backend", "en", [Keyword("k8s"), Keyword("Golang"), Keyword("postgres")]))
    assert s["k8s"].status is Status.FOUND and s["k8s"].matched_as == "Kubernetes"
    assert s["Golang"].matched_as == "Go"
    assert s["postgres"].matched_as == "PostgreSQL"


def test_inventory_aliases_count_as_spellings(ada):
    assert "k8s" in spellings("Kubernetes", ada)


@pytest.mark.parametrize("term,text,hit", [
    ("Go", "Built tools in Go and Rust", True),
    ("Go", "ready to go live", False),          # short terms are case-sensitive
    ("Java", "JavaScript frontend", False),     # word boundaries
    ("C++", "Wrote C++ services", True),        # symbols at the edge
    ("C#", "C# and .NET", True),
    (".NET", "C# and .NET.", True),
    ("Kafka", "apache kafka streams", True),    # long terms ignore case
])
def test_word_boundaries(term, text, hit):
    assert bool(_pattern(term).search(text)) is hit


def test_familiarity_only_match(ada):
    r = by_keyword(score_variant(ada, "backend", "en", [Keyword("Rust")]))["Rust"]
    assert r.status is Status.FOUND_AS_FAMILIARITY and r.gap is Gap.FAMILIARITY_ONLY
    assert score_variant(ada, "backend", "en", [Keyword("Rust")]).coverage == 0.5


def test_x_skill_is_a_gap_you_do_not_have(ada):
    r = by_keyword(score_variant(ada, "backend", "en", [Keyword("Scala")]))["Scala"]
    assert r.status is Status.MISSING and r.gap is Gap.NOT_IN_INVENTORY and r.level == "X"


def test_unknown_keyword_is_not_in_inventory(ada):
    r = by_keyword(score_variant(ada, "backend", "en", [Keyword("Terraform")]))["Terraform"]
    assert r.gap is Gap.NOT_IN_INVENTORY and r.skill is None


def test_in_inventory_not_in_cv_points_to_unused_bullets(make_source):
    def mutate(raw):
        v = raw["variants"]["variants"]["backend"]
        v["roles"]["bank"] = ["bk_obs"]
        v["skills"] = [g for g in v["skills"] if g["label"]["en"] != "Frameworks"]

    source = make_source(mutate)
    r = by_keyword(score_variant(source, "backend", "en", [Keyword("SpringBoot")]))["SpringBoot"]
    assert r.status is Status.MISSING
    assert r.gap is Gap.IN_INVENTORY_NOT_IN_CV and r.level == "P"
    assert r.unused_bullets == ["bk_api"]


def test_required_and_overall_coverage(ada):
    kws = [Keyword("Java"), Keyword("Scala"), Keyword("Kafka", required=False), Keyword("Terraform", required=False)]
    s = score_variant(ada, "backend", "en", kws)
    assert s.required_coverage == 0.5 and s.coverage == 0.5


def job_keywords():
    data = yaml.safe_load((ADA / "job-keywords.yaml").read_text(encoding="utf-8"))
    return [Keyword(k) for k in data["required"]] + [Keyword(k, required=False) for k in data["preferred"]]


def test_sample_job_ranks_platform_first(ada):
    scores = score_job(ada, job_keywords())
    assert scores[0].variant == "platform"
    assert scores[0].required_coverage > scores[-1].required_coverage


def test_sample_job_shows_every_kind_of_gap(ada):
    groups = gap_report(ada, "backend", "en", job_keywords())
    assert {r.keyword for r in groups["in_inventory_not_in_cv"]} == {"CI/CD", "gRPC", "SRE"}
    assert {r.keyword for r in groups["familiarity_only"]} == {"Rust"}
    assert {r.keyword for r in groups["not_in_inventory"]} == {"Terraform", "Prometheus", "Scala"}


def test_bullet_pool_counts_as_evidence(ada):
    r = by_keyword(score_variant(ada, "backend", "en", [Keyword("CI/CD")]))["CI/CD"]
    assert r.gap is Gap.IN_INVENTORY_NOT_IN_CV and r.skill is None and r.unused_bullets == ["ft_ci"]


def test_tags_match_ignoring_case(ada):
    # "SRE" is short, so prose matching is case-sensitive, but the tag "sre" still counts.
    r = by_keyword(score_variant(ada, "backend", "en", [Keyword("SRE")]))["SRE"]
    assert r.gap is Gap.IN_INVENTORY_NOT_IN_CV


def test_x_skill_stays_a_gap_even_if_a_bullet_mentions_it(make_source):
    def mutate(raw):
        raw["bullets"]["bullets"].append({"id": "x_scala", "role": "fintech", "tags": ["scala"], "text": "Read Scala code."})

    r = by_keyword(score_variant(make_source(mutate), "backend", "en", [Keyword("Scala")]))["Scala"]
    assert r.gap is Gap.NOT_IN_INVENTORY


def test_gap_report_groups(ada):
    groups = gap_report(ada, "backend", "es", [Keyword("Java"), Keyword("Rust"), Keyword("Scala")])
    assert [r.keyword for r in groups["familiarity_only"]] == ["Rust"]
    assert [r.keyword for r in groups["not_in_inventory"]] == ["Scala"]
    assert groups["in_inventory_not_in_cv"] == []


def test_spanish_spellings_match():
    # Found scoring a Spanish CV: "observabilidad" did not count as Observability.
    from honest_cv.score import _match, spellings

    text = "Introduje la observabilidad; infraestructura como código con Terraform; integración continua."
    for term in ("Observability", "Infrastructure as Code", "CI/CD"):
        assert _match(spellings(term), text), term

