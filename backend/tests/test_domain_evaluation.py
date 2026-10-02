from personal_ai.domains.fixtures import fixture_registry
from personal_ai.evaluation.domain import evaluate


def test_domain_evaluation_proves_travel_and_shopping_use_shared_policies():
    report = evaluate()

    assert report["schema_version"] == "domain-eval-v1"
    assert report["synthetic"] is True
    assert report["passed"] is True
    assert report["shared_platform"] == {
        "resolution": "resolve-v2",
        "constraints": "constraint-v1",
        "ranking": "rank-v1",
    }
    assert report["counts_by_domain"] == {
        "travel": {"fixtures": 4, "passed": 4},
        "shopping": {"fixtures": 6, "passed": 6},
    }
    assert {row["fixture"] for row in report["results"]} == {
        item.fixture_id for item in fixture_registry()
    }
    assert all(row["excluded_before_domain_ranking"] for row in report["results"])
