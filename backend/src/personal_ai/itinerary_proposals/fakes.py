"""Credential-free deterministic LLM fixture for the proposed API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

from personal_ai.llm.client import ChatMessage


class FakeItineraryProposalLLMClient:
    """Return one consumer-shaped operation using the supplied context handles."""

    def __init__(self, deltas: Sequence[str] | None = None) -> None:
        self.deltas = tuple(deltas) if deltas is not None else None
        self.requests: list[tuple[ChatMessage, ...]] = []

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        self.requests.append(tuple(messages))
        if self.deltas is not None:
            for delta in self.deltas:
                yield delta
            return

        block = next(
            message.content
            for message in messages
            if message.content.startswith("Untrusted external observations (data only):\n")
        )
        records = [json.loads(line) for line in block.splitlines()[1:]]
        travel = next(
            record["context"] for record in records if record.get("kind") == "travel_context"
        )
        evidence = [
            record["evidence_handle"]
            for record in records
            if record.get("kind") == "research_evidence"
        ]
        if not travel["candidates"]:
            yield json.dumps(
                {
                    "schema_version": "itinerary-proposal-v1",
                    "trip_handle": travel["trip_handle"],
                    "status": "insufficient",
                    "failure_code": "no_safe_operations",
                    "operations": [],
                    "operation_support": [],
                }
            )
            return

        day = travel["days"][0]
        operation = {
            "kind": "add_item",
            "day_handle": day["handle"],
            "candidate_handle": travel["candidates"][0]["handle"],
            "item_type": "activity",
            "position": len(day["items"]),
            "start_time": None,
            "end_time": None,
        }
        support = [{"operation_index": 0, "evidence_handles": [evidence[0]]}] if evidence else []
        yield json.dumps(
            {
                "schema_version": "itinerary-proposal-v1",
                "trip_handle": travel["trip_handle"],
                "status": "proposed",
                "failure_code": None,
                "operations": [operation],
                "operation_support": support,
            },
            separators=(",", ":"),
        )

    async def stream_bounded(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> AsyncIterator[str]:
        del max_output_tokens, timeout_seconds
        async for delta in self.stream(messages):
            yield delta
