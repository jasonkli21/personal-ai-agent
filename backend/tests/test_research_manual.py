"""Explicit synthetic external smoke checks; skipped in offline CI."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_ai.agents.research.contracts import ResearchRequest, ResearchSession, evolve
from personal_ai.agents.research.repositories import FirestoreResearchRepository
from personal_ai.search.policy import canonical_url
from personal_ai.search.providers.brave import BraveSearchAdapter
from personal_ai.settings import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.skipif(os.getenv("RUN_RESEARCH_EMULATOR_TEST") != "1", reason="opt-in emulator check")
def test_research_emulator_atomic_replay_and_persistence():
    project, host = (
        os.environ.get("FIRESTORE_PROJECT_ID"),
        os.environ.get("FIRESTORE_EMULATOR_HOST"),
    )
    if not project or not host:
        pytest.fail("Explicit synthetic project and emulator host are required")
    repo = FirestoreResearchRepository(project_id=project, emulator_host=host)
    owner, now = "synthetic-research-" + str(uuid4()), datetime.now(UTC)
    request = ResearchRequest(question="Synthetic verification request", idempotency_key=uuid4())
    value = ResearchSession(
        id=uuid4(),
        owner_id=owner,
        request=request,
        request_fingerprint=request.fingerprint(),
        state="pending",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repo.create(value)
    assert repo.create(evolve(value, id=uuid4())).id == value.id
    claimed = repo.claim(owner, value.id, uuid4(), now, now + timedelta(seconds=30))
    repo.save(
        evolve(
            claimed,
            state="failed",
            failure_code="synthetic_verification",
            revision=claimed.revision + 1,
        )
    )
    reopened = FirestoreResearchRepository(project_id=project, emulator_host=host)
    assert reopened.get(owner, value.id).state == "failed"


@pytest.mark.anyio
@pytest.mark.skipif(
    os.getenv("RUN_RESEARCH_BRAVE_TEST") != "1", reason="opt-in licensed provider check"
)
async def test_brave_synthetic_public_query():
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        research_enabled=True,
        research_search_adapter="brave",
    )
    # Settings require explicit storage-rights acknowledgement and a supplied key.
    results = await BraveSearchAdapter(settings).search(
        "synthetic research verification Python documentation", 2
    )
    assert results
    assert all(canonical_url(r.url).startswith(("https://", "http://")) for r in results)
    assert any(r.text for r in results)
