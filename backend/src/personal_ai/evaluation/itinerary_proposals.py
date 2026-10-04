"""Adversarial offline conformance checks for the proposed travel proposal API."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.itinerary_proposals.contracts import ItineraryProposalRequest
from personal_ai.itinerary_proposals.fakes import FakeItineraryProposalLLMClient
from personal_ai.itinerary_proposals.repositories import InMemoryItineraryProposalRepository
from personal_ai.itinerary_proposals.service import ItineraryProposalService
from personal_ai.settings import Settings

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/itinerary-proposal-example.json"
NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _cases(fixture: dict) -> list[dict]:
    valid = copy.deepcopy(fixture)

    cross_kind = copy.deepcopy(fixture)
    cross_kind["model_output"]["operations"][0]["candidate_handle"] = "h_item0001"

    protected = copy.deepcopy(fixture)
    protected["request"]["context"]["days"][0]["items"][0]["protected"] = True
    protected["model_output"]["operations"] = [
        {
            "kind": "move_item",
            "item_handle": "h_item0001",
            "day_handle": "h_day00001",
            "position": 0,
        }
    ]

    extra_model_field = copy.deepcopy(fixture)
    extra_model_field["model_output"]["provider_url"] = "https://untrusted.example/"

    unknown_evidence = copy.deepcopy(fixture)
    unknown_evidence["model_output"]["operation_support"] = [
        {"operation_index": 0, "evidence_handles": ["e_unknown0001"]}
    ]

    unknown_request_field = copy.deepcopy(fixture)
    unknown_request_field["request"]["context"]["owner_id"] = "private-owner"

    return [
        {"name": "consumer-shaped-candidate-add", "fixture": valid, "expected_state": "proposed"},
        {
            "name": "cross-kind-candidate-handle",
            "fixture": cross_kind,
            "expected_state": "failed",
            "expected_failure": "invalid_model_output",
        },
        {
            "name": "protected-item-move",
            "fixture": protected,
            "expected_state": "failed",
            "expected_failure": "invalid_model_output",
        },
        {
            "name": "unknown-model-field",
            "fixture": extra_model_field,
            "expected_state": "failed",
            "expected_failure": "invalid_model_output",
        },
        {
            "name": "unknown-evidence-handle",
            "fixture": unknown_evidence,
            "expected_state": "failed",
            "expected_failure": "invalid_model_output",
        },
        {
            "name": "private-request-field",
            "fixture": unknown_request_field,
            "expected_state": "rejected",
            "expected_failure": "invalid_request",
        },
    ]


async def evaluate() -> dict:
    settings = Settings(
        _env_file=None,
        app_environment="test",
        ai_provider="fake",
        ai_model="synthetic",
        itinerary_proposals_enabled=True,
        itinerary_proposal_storage="memory",
    )
    results = []
    for index, case in enumerate(_cases(load_fixture()), start=1):
        payload = copy.deepcopy(case["fixture"])
        payload["request"]["idempotency_key"] = f"00000000-0000-4000-8000-{index:012d}"
        try:
            request = ItineraryProposalRequest.model_validate(payload["request"])
        except ValidationError:
            state, failure_code = "rejected", "invalid_request"
        else:
            llm = FakeItineraryProposalLLMClient((json.dumps(payload["model_output"]),))
            service = ItineraryProposalService(
                settings,
                InMemoryItineraryProposalRepository(),
                ContextAssembler(settings, EstimatedTokenCounter()),
                llm,
                owner_id="local",
                clock=lambda: NOW,
            )
            result = await service.create(request)
            state, failure_code = result.state, result.failure_code
        expected_state = case["expected_state"]
        expected_failure = case.get("expected_failure")
        results.append(
            {
                "name": case["name"],
                "expected_state": expected_state,
                "state": state,
                "expected_failure": expected_failure,
                "failure_code": failure_code,
                "passed": state == expected_state and failure_code == expected_failure,
            }
        )
    return {
        "schema_version": "itinerary-proposal-eval-v1",
        "synthetic": True,
        "external_providers_called": False,
        "passed": all(item["passed"] for item in results),
        "results": results,
    }


if __name__ == "__main__":
    report = asyncio.run(evaluate())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
