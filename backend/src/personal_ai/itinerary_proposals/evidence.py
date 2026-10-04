"""Verified adapters from existing research records to proposal evidence handles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from personal_ai.evidence.contracts import Evidence, SourceObservation
from personal_ai.itinerary_proposals.contracts import EvidenceHandle, ProposalCitation


@dataclass(frozen=True, slots=True)
class ProposalEvidenceBlock:
    handle: str
    passage: str
    citation: ProposalCitation

    @classmethod
    def from_records(
        cls,
        evidence: Evidence,
        source: SourceObservation,
        token: str,
        *,
        expires_at: datetime | None = None,
    ) -> ProposalEvidenceBlock:
        handle = f"e_{token}"
        EvidenceHandle(handle)
        citation = ProposalCitation(
            evidence_handle=handle,
            url=source.canonical_url,
            title=source.title,
            observed_at=evidence.observed_at,
            expires_at=expires_at or evidence.expires_at,
        )
        return cls(handle=handle, passage=evidence.passage, citation=citation)

    def context_json(self) -> str:
        """Keep source UUIDs and URLs out of model context; expose one opaque handle."""
        return json.dumps(
            {
                "kind": "research_evidence",
                "evidence_handle": self.handle,
                "observed_at": self.citation.observed_at.isoformat(),
                "expires_at": self.citation.expires_at.isoformat(),
                "passage": self.passage,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
