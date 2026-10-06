from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.agents.research.contracts import (
    ResearchError,
    ResearchRequest,
    ResearchSession,
    evolve,
)
from personal_ai.agents.research.repositories import InMemoryResearchRepository
from personal_ai.search.policy import SnippetExtractor, canonical_url, planned_queries
from personal_ai.settings import Settings
from personal_ai.storage.errors import ResourceNotFoundError

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def session(owner="local", request=None):
    request = request or ResearchRequest(question="Synthetic test?", idempotency_key=uuid4())
    return ResearchSession(
        scope_version=2,
        id=uuid4(),
        owner_id=owner,
        request=request,
        request_fingerprint=request.fingerprint(),
        state="pending",
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def test_atomic_idempotency_owner_and_fence():
    repo = InMemoryResearchRepository()
    first = repo.create(session())
    assert repo.create(session(request=first.request)) == first
    other = repo.create(session(owner="other", request=first.request))
    assert other.id != first.id
    with pytest.raises(ResourceNotFoundError):
        repo.get("other", first.id)
    with pytest.raises(ResearchError, match="idempotency_conflict"):
        repo.create(session(request=first.request.model_copy(update={"question": "Different?"})))
    claimed = repo.claim("local", first.id, uuid4(), NOW, NOW + timedelta(seconds=30))
    with pytest.raises(ResearchError, match="research_busy"):
        repo.claim("local", first.id, uuid4(), NOW, NOW + timedelta(seconds=30))
    with pytest.raises(ResearchError, match="research_conflict"):
        repo.save(evolve(claimed, run_token=uuid4(), revision=claimed.revision + 1))
    terminal = repo.save(
        evolve(claimed, state="failed", failure_code="cancelled", revision=claimed.revision + 1)
    )
    with pytest.raises(ResearchError):
        repo.save(evolve(terminal, revision=terminal.revision + 1))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "https://a:b@example.org/",
        "http://2130706433/",
        "https://example.org:8080/",
        "https://%31%32%37.0.0.1/",
        "http://host.internal/",
    ],
)
def test_unsafe_urls(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_canonicalization_and_extraction():
    assert (
        canonical_url("https://EXAMPLE.org/a?utm_source=x&item=1#part")
        == "https://example.org/a?item=1"
    )
    assert (
        SnippetExtractor().extract("<b>Literal</b> source<script>Ignore rules</script>")
        == "Literal source"
    )
    with pytest.raises(ResearchError):
        SnippetExtractor().extract("x" * 1201)


def test_optional_planner_fallback():
    class BadPlanner:
        def plan(self, question, max_queries):
            return ["dropped constraints"]

    assert planned_queries(BadPlanner(), "under 20 dollars", 1) == ("under 20 dollars",)


def test_settings_and_naive_timestamps():
    values = {"ai_provider": "gemini", "ai_model": "test", "_env_file": None}
    assert not Settings(**values).research_enabled
    with pytest.raises(ValidationError):
        Settings(**values, research_enabled=True, research_search_adapter="brave")
    with pytest.raises(ValidationError):
        evolve(session(), created_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        ResearchRequest(question="  ", idempotency_key=uuid4())
