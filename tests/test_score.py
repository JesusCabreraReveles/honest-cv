import pytest

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
        v["skills"] = [g for g in v["skills"] if g["label"]["en"] != "Platforms"]

    source = make_source(mutate)
    r = by_keyword(score_variant(source, "backend", "en", [Keyword("SpringBoot")]))["SpringBoot"]
    assert r.status is Status.MISSING
    assert r.gap is Gap.IN_INVENTORY_NOT_IN_CV and r.level == "P"
    assert r.unused_bullets == ["bk_api"]


def test_required_and_overall_coverage(ada):
    kws = [Keyword("Java"), Keyword("Scala"), Keyword("Kafka", required=False), Keyword("Terraform", required=False)]
    s = score_variant(ada, "backend", "en", kws)
    assert s.required_coverage == 0.5 and s.coverage == 0.5


def test_score_job_ranks_variants(make_source):
    def mutate(raw):
        raw["variants"]["variants"]["platform"]["skills"] = [{"label": "Languages", "skills": ["Java"]}]

    source = make_source(mutate)
    scores = score_job(source, [Keyword("PostgreSQL"), Keyword("Java")])
    assert [s.variant for s in scores] == ["backend", "platform"]
    assert scores[0].coverage > scores[1].coverage


def test_gap_report_groups(ada):
    groups = gap_report(ada, "backend", "es", [Keyword("Java"), Keyword("Rust"), Keyword("Scala")])
    assert [r.keyword for r in groups["familiarity_only"]] == ["Rust"]
    assert [r.keyword for r in groups["not_in_inventory"]] == ["Scala"]
    assert groups["in_inventory_not_in_cv"] == []
