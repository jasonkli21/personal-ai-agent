"""Offline cross-domain evaluation using fixed synthetic Phase 7 records."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.domains.fixtures import FIXTURE_NOW, fixture_registry
from personal_ai.domains.repositories import InMemoryDomainRepository
from personal_ai.domains.service import DomainService
from personal_ai.evaluation.output import emit
from personal_ai.settings import Settings


def evaluate() -> dict:
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        travel_enabled=True,
        shopping_enabled=True,
        domain_inspection_enabled=True,
    )
    results = []
    for fixture in fixture_registry():
        service = DomainService(
            settings,
            InMemoryDecisionRepository(),
            InMemoryDomainRepository(),
            owner_id="local",
            clock=lambda: FIXTURE_NOW,
        )
        result = service.create(fixture.domain_id, fixture.request)
        selected = next((row for row in result.comparison.rows if row.selected), None)
        actual_eligible = sum(row.eligible for row in result.comparison.rows)
        actual_cell = None
        if fixture.expected_cell:
            attribute, _ = fixture.expected_cell
            actual_cell = next(
                (cell for row in result.comparison.rows for cell in row.cells if cell.field == attribute),
                None,
            )
        state_ok = result.comparison.state == fixture.expected_state
        selected_ok = selected.name == fixture.expected_selected_name if selected else fixture.expected_selected_name is None
        eligible_ok = actual_eligible == fixture.expected_eligible_count if fixture.expected_eligible_count is not None else True
        cell_ok = (
            actual_cell is not None and actual_cell.status == fixture.expected_cell[1]
            if fixture.expected_cell else True
        )
        provenance_ok = all(
            source.evidence_id and source.source_observation_id and source.url
            for row in result.comparison.rows
            for cell in row.cells
            for source in cell.sources
        )
        filtered_before_ranking = all(
            row.eligible or row.rank is None and row.score is None and not row.features
            for row in result.comparison.rows
        )
        results.append({
            "fixture": fixture.fixture_id,
            "domain": fixture.domain_id,
            "decision_id": str(result.comparison.decision_id),
            "comparison_id": str(result.comparison.id),
            "state": result.comparison.state,
            "expected_state": fixture.expected_state,
            "selected": selected.name if selected else None,
            "expected_selected": fixture.expected_selected_name,
            "eligible_count": actual_eligible,
            "expected_eligible_count": fixture.expected_eligible_count,
            "expected_cell": {
                "field": fixture.expected_cell[0],
                "status": fixture.expected_cell[1],
                "actual_status": actual_cell.status if actual_cell else None,
            } if fixture.expected_cell else None,
            "domain_feature_policy": result.comparison.feature_policy_version,
            "shared_resolution_policy": result.comparison.decision_policy_versions.resolution,
            "shared_constraint_policy": result.comparison.decision_policy_versions.constraints,
            "shared_ranking_policy": result.comparison.decision_policy_versions.ranking,
            "source_links_attributed": provenance_ok,
            "excluded_before_domain_ranking": filtered_before_ranking,
            "passed": all((
                state_ok,
                selected_ok,
                eligible_ok,
                cell_ok,
                provenance_ok,
                filtered_before_ranking,
            )),
        })

    root = Path(__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip())
    return {
        "schema_version": "domain-eval-v1",
        "synthetic": True,
        "tested_at": datetime.now(UTC).isoformat(),
        "revision": f"{revision}-working-tree" if dirty else revision,
        "shared_platform": {
            "resolution": results[0]["shared_resolution_policy"],
            "constraints": results[0]["shared_constraint_policy"],
            "ranking": results[0]["shared_ranking_policy"],
        },
        "counts_by_domain": {
            domain_id: {
                "fixtures": sum(item["domain"] == domain_id for item in results),
                "passed": sum(item["domain"] == domain_id and item["passed"] for item in results),
            }
            for domain_id in ("travel", "shopping")
        },
        "passed": all(item["passed"] for item in results),
        "results": results,
    }


if __name__ == "__main__":
    report = evaluate()
    emit(report)
    raise SystemExit(0 if report["passed"] else 1)
