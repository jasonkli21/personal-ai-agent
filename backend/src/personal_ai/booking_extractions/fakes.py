"""Synthetic LLM adapter for booking extraction tests and local development."""

from __future__ import annotations

import json
import re
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
        end = min(len(document), start + 240) if start >= 0 else 0
        schedule = (
            re.search(
                r"(?P<date>\d{4}-\d{2}-\d{2}) at (?P<time>(?:[01]\d|2[0-3]):[0-5]\d) (?P<zone>[+-](?:0\d|1[0-4]):[0-5]\d)",
                document[start:end],
            )
            if start >= 0
            else None
        )
        excerpt = document[start:end]
        has_lodging_evidence = bool(re.search(r"\b(hotel|lodging)\b", excerpt, re.IGNORECASE))
        uncertainty = []
        if not has_lodging_evidence:
            uncertainty.append("reservation_type")
        if "synthetic hotel" not in excerpt.casefold():
            uncertainty.append("provider_name")
        uncertainty.append("confirmation_code")
        if not schedule:
            uncertainty.extend(("starts_at", "starts_at_timezone"))
        uncertainty.extend(("ends_at", "ends_at_timezone"))
        result = {
            "schema_version": "booking-document-extraction-v1",
            "candidates": (
                [
                    {
                        "reservation_type": "lodging" if has_lodging_evidence else None,
                        "provider_name": "Synthetic Hotel",
                        "confirmation_code": None,
                        "starts_at_text": schedule.group(0) if schedule else None,
                        "starts_at_date": schedule.group("date") if schedule else None,
                        "starts_at_time": schedule.group("time") if schedule else None,
                        "starts_at_timezone": schedule.group("zone") if schedule else None,
                        "ends_at_text": None,
                        "ends_at_date": None,
                        "ends_at_time": None,
                        "ends_at_timezone": None,
                        "source_start": start,
                        "source_end": end,
                        "uncertain_fields": uncertainty,
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
