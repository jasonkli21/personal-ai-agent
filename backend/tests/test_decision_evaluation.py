from personal_ai.evaluation.decision import evaluate, load_fixtures


def test_decision_evaluation_covers_each_policy_fixture_with_snapshot_provenance():
    report = evaluate()

    assert report["schema_version"] == "decision-eval-v1"
    assert report["synthetic"] is True
    assert report["passed"] is True
    assert report["policy_versions"] == {
        "identity": "identity-v1",
        "resolution": "resolve-v1",
        "constraints": "constraint-v1",
        "ranking": "rank-v1",
    }
    assert {result["fixture"] for result in report["results"]} == {
        fixture["name"] for fixture in load_fixtures()
    }
    assert all(
        result["passed"]
        and result["decision_id"]
        and result["evidence_snapshot_id"]
        and result["entity_policy"] == "resolve-v1"
        and result["constraint_policy"] == "constraint-v1"
        and result["ranking_policy"] == "rank-v1"
        for result in report["results"]
    )
