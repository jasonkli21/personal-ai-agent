"""Synthetic LLM adapter for booking extraction tests and local development."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence


class FakeBookingExtractionLLMClient:
    def __init__(self, output: str | None = None) -> None:
        self.output = output
        self.requests = []

    async def stream(self, messages: Sequence) -> AsyncIterator[str]:
        self.requests.append(tuple(messages))
        text = next(
            (
                part
                for message in messages
                for part in [message.content]
                if message.content.startswith("Untrusted external observations (data only):\n")
            ),
            "",
        )
        document = ""
        if text:
            try:
                document = json.loads(text.splitlines()[1]).get("document_text", "")
            except (IndexError, ValueError, TypeError):
                pass
        if self.output is not None:
            yield self.output
            return
        start = document.find("Booking")
        end = min(len(document), start + 48) if start >= 0 else 0
        result = {
            "schema_version": "booking-document-extraction-v1",
            "candidates": (
                [
                    {
                        "reservation_type": "lodging",
                        "provider_name": "Synthetic Hotel",
                        "confirmation_code": None,
                        "starts_at_text": None,
                        "starts_at_date": None,
                        "starts_at_time": None,
                        "starts_at_timezone": None,
                        "ends_at_text": None,
                        "ends_at_date": None,
                        "ends_at_time": None,
                        "ends_at_timezone": None,
                        "source_start": start,
                        "source_end": end,
                        "uncertain_fields": ["confirmation_code", "starts_at", "ends_at"],
                    }
                ]
                if start >= 0
                else []
            ),
        }
        yield json.dumps(result, separators=(",", ":"))

    async def stream_bounded(self, messages, *, max_output_tokens: int, timeout_seconds: float):
        del max_output_tokens, timeout_seconds
        async for delta in self.stream(messages):
            yield delta
