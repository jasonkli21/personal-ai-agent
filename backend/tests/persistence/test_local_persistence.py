"""Real local-engine contract coverage for P10.2 and P10.3."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import sqrt
from threading import Barrier, Event, Thread
from time import monotonic
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from personal_ai.auth.safeguards import SafeguardDenied
from personal_ai.auth.scope import ApplicationScope, application_scope_context
from personal_ai.context.contracts import ConversationSummary, fingerprint
from personal_ai.context.profile import (
    GlobalProfileFieldUpdate,
    GlobalProfileUpdate,
    InMemoryGlobalProfileRepository,
)
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.memory.contracts import (
    DerivedMemory,
    DerivedMemorySource,
    Memory,
    MemoryCandidate,
    identity,
    normalize,
)
from personal_ai.memory.lifecycle import MemoryJob, MemoryLifecycleEvent
from personal_ai.memory.lifecycle_repositories import event_idempotency_id, job_idempotency_id
from personal_ai.persistence.controls import (
    DynamoDBSafeguardStore,
    PostgresDailyBudgetRepository,
    PostgresDomainProviderRateLimiter,
)
from personal_ai.persistence.dynamodb import (
    DynamoDBConversationRepository,
    DynamoDBMemoryEffectGuard,
    DynamoDBMemoryJobRepository,
    DynamoDBMessageRepository,
    DynamoDBRuntimeTable,
    DynamoDBSummaryRepository,
)
from personal_ai.persistence.effect_receipts import PostgresEffectReceiptRepository
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.persistence.postgres_capabilities import (
    PostgresBookingExtractionRepository,
    PostgresItineraryProposalRepository,
)
from personal_ai.persistence.postgres_context import PostgresGlobalProfileRepository
from personal_ai.persistence.postgres_decisions import PostgresDecisionRepository
from personal_ai.persistence.postgres_domains import PostgresDomainRepository
from personal_ai.persistence.postgres_lifecycle import PostgresMemoryLifecycleRepository
from personal_ai.persistence.postgres_memory import (
    EffectGuardToken,
    PostgresMemoryRepository,
)
from personal_ai.persistence.postgres_research import PostgresResearchRepository
from personal_ai.storage.errors import ConversationConflictError

pytestmark = pytest.mark.persistence_integration
_DEFAULT_SOURCE_CONVERSATION_ID = UUID(int=10)
_DEFAULT_SOURCE_TURN_ID = UUID(int=12)
_DEFAULT_SOURCE_MESSAGE_ID = UUID(int=11)


@pytest.fixture
def postgres_database():
    dsn = os.environ.get("PERSISTENCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set PERSISTENCE_TEST_POSTGRES_DSN to an isolated local pgvector database")
    database = PostgresDatabase(dsn, environment="test", min_size=1, max_size=2)
    try:
        database.migrate()
        yield database
    finally:
        database.close()


@pytest.fixture
def dynamodb_table():
    endpoint = os.environ.get("PERSISTENCE_TEST_DYNAMODB_ENDPOINT")
    if not endpoint:
        pytest.skip("set PERSISTENCE_TEST_DYNAMODB_ENDPOINT to DynamoDB Local")
    from botocore.exceptions import ClientError

    table = DynamoDBRuntimeTable(endpoint, table_name=f"persistence-{uuid4().hex[:20]}")
    table.bootstrap()
    try:
        yield table
    finally:
        try:
            table.client.delete_table(TableName=table.table_name)
        except ClientError:
            pass


class _SourceGuard:
    def __init__(self, owner_id: str):
        self.token = EffectGuardToken(
            owner_id=owner_id,
            operation_id="integration-operation",
            attempt_id="integration-attempt",
            fingerprint="b" * 64,
            execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
            scope=ApplicationScope(application_id="personal_ai", workspace_id=None),
            coordination_conversation_id=UUID(int=999),
        )
        self.acknowledgements = []

    def acquire(self, record, *, timeout):
        return EffectGuardToken(
            owner_id=self.token.owner_id,
            operation_id=str(record.id),
            attempt_id="integration-attempt",
            fingerprint=sha256(record.model_dump_json(exclude_none=False).encode()).hexdigest(),
            execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
            scope=ApplicationScope(
                application_id=record.application_id, workspace_id=record.workspace_id
            ),
            coordination_conversation_id=self.token.coordination_conversation_id,
        )

    def acknowledge(self, token, *, outcome, result_refs):
        self.acknowledgements.append((outcome, result_refs))


def _memory(
    values: tuple[float, ...], owner_id: str, content: str = "Likes a quiet workspace",
    *, source_fingerprint: str = "a" * 64,
    source_conversation_id: UUID = _DEFAULT_SOURCE_CONVERSATION_ID,
    source_turn_id: UUID = _DEFAULT_SOURCE_TURN_ID,
    source_message_id: UUID = _DEFAULT_SOURCE_MESSAGE_ID,
) -> Memory:
    now = datetime.now(UTC)
    candidate = MemoryCandidate(
        memory_type="preference",
        content=content,
        confidence=0.9,
        source_message_ids=(source_message_id,),
        rationale_code="user_preference",
        effective_at=now,
    )
    return Memory(
        **candidate.model_dump(exclude={"effective_at"}),
        id=identity(owner_id, source_fingerprint, candidate),
        owner_id=owner_id,
        normalized_content=normalize(content),
        source_conversation_id=source_conversation_id,
        source_turn_id=source_turn_id,
        source_fingerprint=source_fingerprint,
        observed_at=now,
        effective_at=now,
        created_at=now,
        embedding=values,
        embedding_model="gemini-embedding-001",
        embedding_dimensions=len(values),
    )


def test_postgres_migration_and_lossless_2048_dimension_memory_roundtrip(postgres_database):
    owner_id = f"integration-{uuid4()}"
    guard = _SourceGuard(owner_id)
    repository = PostgresMemoryRepository(postgres_database, guard)
    vector = (1.0,) + (0.0,) * 2047
    memory = _memory(vector, owner_id)
    with application_scope_context(ApplicationScope(application_id="personal_ai", workspace_id=None)):
        saved, created = repository.create(memory)
        repeated, created_again = repository.create(memory)
        matches = repository.search(
            owner_id=memory.owner_id,
            embedding=vector,
            model=memory.embedding_model,
            dimensions=2048,
            limit=5,
        )
        incompatible = repository.search(
            owner_id=memory.owner_id, embedding=vector, model="incompatible-model",
            dimensions=2048, limit=5,
        )
    assert created is True
    assert created_again is False
    assert saved.embedding == vector == repeated.embedding
    assert len(matches) == 1 and matches[0].memory.id == memory.id
    assert matches[0].similarity == pytest.approx(1.0)
    assert incompatible == []
    assert len(guard.acknowledgements) == 2


def test_postgres_async_connection_boundary(postgres_database):
    async def read_one():
        await postgres_database.open_async()
        try:
            async with postgres_database.aconnection() as connection:
                row = await (await connection.execute("SELECT 1")).fetchone()
            return row[0]
        finally:
            await postgres_database.close_async()

    assert asyncio.run(read_one()) == 1


def test_postgres_provider_rate_limit_serializes_shared_slots(postgres_database):
    limiter = PostgresDomainProviderRateLimiter(postgres_database, "local-contract-provider")
    deadline = monotonic() + 2
    first = limiter._reserve(0.05, deadline)
    second = limiter._reserve(0.05, deadline)
    assert second >= first + 0.045


def test_pgvector_threshold_ties_and_local_storage_compute(postgres_database):
    owner_id = f"vector-boundary-{uuid4()}"
    repository = PostgresMemoryRepository(postgres_database, _SourceGuard(owner_id))
    vectors = {
        "tie-a": (0.8, 0.6, 0.0),
        "tie-b": (0.8, -0.6, 0.0),
        "below": (0.69999, sqrt(1 - 0.69999**2), 0.0),
        "above": (0.70001, sqrt(1 - 0.70001**2), 0.0),
    }
    records = [_memory(value, owner_id, label) for label, value in vectors.items()]
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    with application_scope_context(scope):
        for record in records:
            repository.create(record)
        matches = repository.search(
            owner_id=owner_id,
            embedding=(1.0, 0.0, 0.0),
            model="gemini-embedding-001",
            dimensions=3,
            limit=4,
        )
    expected = sorted(
        records,
        key=lambda record: (
            -sum(left * right for left, right in zip((1.0, 0.0, 0.0), record.embedding, strict=True)),
            str(record.id),
        ),
    )
    scores = {item.memory.content: item.similarity for item in matches}
    assert [item.memory.id for item in matches] == [record.id for record in expected]
    assert scores["above"] >= 0.7 > scores["below"]
    ties = [record for record in expected if record.content.startswith("tie-")]
    assert [item.memory.id for item in matches if item.memory.content.startswith("tie-")] == [
        item.id for item in ties
    ]

    scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
    with postgres_database.connection() as connection:
        table_bytes, total_bytes, toast_bytes = connection.execute(
            "SELECT pg_table_size('memories'),pg_total_relation_size('memories'),"
            "CASE WHEN reltoastrelid=0 THEN 0 ELSE pg_total_relation_size(reltoastrelid) END "
            "FROM pg_class WHERE oid='memories'::regclass"
        ).fetchone()
        explain = connection.execute(
            "EXPLAIN (ANALYZE,BUFFERS) SELECT record_id FROM memories "
            "WHERE scope_id=%s AND embedding_dimensions=3 "
            "ORDER BY embedding::vector <=> '[1,0,0]'::vector,record_id LIMIT 4",
            (scope_id,),
        ).fetchall()
    execution = next(line for (line,) in explain if line.startswith("Execution Time:"))
    assert table_bytes > 0 and total_bytes >= table_bytes and toast_bytes >= 0
    assert float(execution.split()[2]) >= 0
    print(
        f"local-vector-measurement bytes(table={table_bytes},total={total_bytes},"
        f"toast={toast_bytes}) {execution}"
    )


def test_postgres_scoped_replay_revision_and_ordered_event_contract(postgres_database):
    owner_id = f"postgres-replay-{uuid4()}"
    scope = ApplicationScope(application_id="research-app", workspace_id="workspace-a")
    repository = PostgresPayloadRepository(postgres_database, "research_request_keys")
    record_id = str(uuid4())
    payload = {"session_id": str(uuid4()), "request": {"query": "local contract"}}
    with application_scope_context(scope):
        created, was_created = repository.create_idempotent(
            owner_id=owner_id, scope=scope, record_id=record_id,
            idempotency_key="request-key", fingerprint="c" * 64, payload=payload,
        )
        replayed, was_created_again = repository.create_idempotent(
            owner_id=owner_id, scope=scope, record_id=str(uuid4()),
            idempotency_key="request-key", fingerprint="c" * 64,
            payload={"changed payload": "ignored on accepted replay"},
        )
        assert created == replayed == payload
        assert was_created and not was_created_again
        assert repository.get(owner_id=owner_id, scope=scope, record_id=record_id) == payload
        with pytest.raises(PersistenceConflict):
            repository.create_idempotent(
                owner_id=owner_id, scope=scope, record_id=str(uuid4()),
                idempotency_key="request-key", fingerprint="d" * 64, payload=payload,
            )
        assert repository.replace(
            owner_id=owner_id, scope=scope, record_id=record_id,
            expected_revision=1, payload={"revision": 2}, status="active",
        ) == 2
        with pytest.raises(PersistenceConflict):
            repository.replace(
                owner_id=owner_id, scope=scope, record_id=record_id,
                expected_revision=1, payload={"stale": True}, status="active",
            )

        events = PostgresPayloadRepository(postgres_database, "memory_lifecycle_events")
        aggregate_id = str(uuid4())
        first = events.append_event(
            owner_id=owner_id, scope=scope, aggregate_id=aggregate_id,
            record_id=str(uuid4()), payload={"event": "first"}, fingerprint="e" * 64,
            idempotency_key="event-1",
        )
        first_replay = events.append_event(
            owner_id=owner_id, scope=scope, aggregate_id=aggregate_id,
            record_id=str(uuid4()), payload={"event": "first"}, fingerprint="e" * 64,
            idempotency_key="event-1",
        )
        second = events.append_event(
            owner_id=owner_id, scope=scope, aggregate_id=aggregate_id,
            record_id=str(uuid4()), payload={"event": "second"}, fingerprint="f" * 64,
            idempotency_key="event-2",
        )
    assert first[1:] == (1, True)
    assert first_replay[1:] == (1, False)
    assert second[1:] == (2, True)


def test_postgres_research_replay_claim_and_revision_contract(postgres_database):
    from personal_ai.agents.research.contracts import (
        ResearchError,
        ResearchRequest,
        ResearchSession,
        evolve,
    )

    owner_id = f"research-{uuid4()}"
    now = datetime.now(UTC)
    request = ResearchRequest(
        question="How does the synthetic fixture work?", idempotency_key=uuid4()
    )
    original = ResearchSession(
        id=uuid4(), owner_id=owner_id, request=request,
        request_fingerprint=request.fingerprint(), state="pending",
        created_at=now, updated_at=now, expires_at=now + timedelta(days=1),
    )
    repository = PostgresResearchRepository(postgres_database)
    saved = repository.create(original)
    replay = repository.create(original.model_copy(update={"id": uuid4()}))
    assert replay.id == saved.id
    assert repository.get(owner_id, saved.id) == saved

    token = uuid4()
    claimed = repository.claim(
        owner_id, saved.id, token, now, now + timedelta(minutes=1)
    )
    assert claimed.state == "running" and claimed.run_token == token
    failed = evolve(
        claimed, state="failed", failure_code="synthetic_failure",
        updated_at=now + timedelta(seconds=1), revision=claimed.revision + 1,
    )
    assert repository.save(failed) == failed
    with pytest.raises(ResearchError, match="research_conflict"):
        repository.save(failed)


def test_postgres_research_scheduled_expiry_preserves_audit_and_scope(postgres_database):
    from personal_ai.agents.research.contracts import ResearchRequest, ResearchSession

    now = datetime.now(UTC)
    owner_id = f"expiry-owner-{uuid4()}"
    expired_request = ResearchRequest(question="Synthetic expiry?", idempotency_key=uuid4())
    expired = ResearchSession(
        id=uuid4(), owner_id=owner_id, request=expired_request,
        request_fingerprint=expired_request.fingerprint(), state="pending",
        created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=1),
    )
    future_request = ResearchRequest(question="Still available?", idempotency_key=uuid4())
    future = ResearchSession(
        id=uuid4(), owner_id=owner_id, request=future_request,
        request_fingerprint=future_request.fingerprint(), state="pending",
        created_at=now, updated_at=now, expires_at=now + timedelta(hours=1),
    )
    repository = PostgresResearchRepository(postgres_database)
    repository.create(expired)
    repository.create(future)
    assert repository.expire_due_for_owner(
        owner_id, now=now, correlation_id="maintenance-test", limit=10
    ) == 1
    saved = repository.get(owner_id, expired.id)
    assert saved.state == "expired" and saved.answer is None and saved.citations == ()
    assert saved.revision == expired.revision + 1
    assert repository.get(owner_id, future.id).state == "pending"
    with postgres_database.connection() as connection:
        audit = connection.execute(
            "SELECT payload FROM audit_events WHERE owner_id=%s "
            "AND payload->>'action'=%s",
            (owner_id, "research.evidence.expire"),
        ).fetchone()
    assert audit is not None and audit[0]["target_id"] == str(expired.id)


def test_postgres_decision_snapshot_and_evidence_lookup_contract(postgres_database):
    from personal_ai.decisions.service import DecisionService
    from personal_ai.evaluation.decision import NOW, _request, _widget
    from personal_ai.settings import Settings

    owner_id = "local"
    repository = PostgresDecisionRepository(postgres_database)
    key = f"postgres-{uuid4()}"
    source, candidate = _widget(key, "Local Synthetic Widget")
    request = _request(key, (candidate,), (source,))
    settings = Settings(
        _env_file=None, ai_provider="gemini", ai_model="synthetic",
        decision_enabled=True, decision_inspection_enabled=True,
    )
    result = DecisionService(
        settings, repository, owner_id=owner_id, clock=lambda: NOW
    ).create(request)

    loaded = repository.get(owner_id, result.decision.id)
    assert loaded == result
    listed_entities = repository.list_entities(owner_id, "object", 10)
    assert result.entities[0].id in {entity.id for entity in listed_entities}
    assert repository.list_claims(owner_id, (result.entities[0].id,), limit=20)
    for claim in result.claims:
        for evidence_id in claim.evidence_ids:
            matches = repository.find_claims_by_evidence(owner_id, evidence_id)
            assert claim.id in {item.id for item in matches}
    assert repository.create(result) == result


def test_postgres_proposal_replay_and_terminal_write_contract(postgres_database):
    import json
    from pathlib import Path

    from personal_ai.itinerary_proposals.contracts import ItineraryProposalResult, ProposalError
    from personal_ai.itinerary_proposals.repositories import proposal_id_for

    fixture_path = Path(__file__).parent.parent / "fixtures" / "itinerary-proposal-example.json"
    payload = json.loads(fixture_path.read_text())
    from personal_ai.itinerary_proposals.contracts import ItineraryProposalRequest

    request = ItineraryProposalRequest.model_validate(payload["request"])
    repo = PostgresItineraryProposalRepository(postgres_database)
    owner_id = f"proposal-owner-{uuid4()}"
    now = datetime.now(UTC)
    record, created = repo.begin(
        owner_id=owner_id, request=request,
        request_fingerprint=request.fingerprint(),
        now=now, execution_deadline=now + timedelta(seconds=30),
    )
    assert created and record.proposal_id == proposal_id_for(
        record.owner_id, request.idempotency_key
    )
    replay, created_again = repo.begin(
        owner_id=owner_id, request=request, request_fingerprint=request.fingerprint(),
        now=now + timedelta(seconds=1), execution_deadline=now + timedelta(seconds=31),
    )
    assert replay == record and not created_again
    with pytest.raises(ProposalError, match="idempotency_conflict"):
        repo.begin(
            owner_id=owner_id, request=request, request_fingerprint="0" * 64,
            now=now, execution_deadline=now + timedelta(seconds=30),
        )
    result = ItineraryProposalResult(
        proposal_id=record.proposal_id, state="insufficient", support_mode="context_only",
        trip_handle=request.context.trip_handle, operations=(), operation_support=(),
        citations=(), failure_code="no_safe_operations", created_at=record.created_at,
        expires_at=record.proposal_expires_at,
    )
    completed = repo.complete(record, result)
    assert completed.result == result and repo.get(owner_id, record.proposal_id) == completed


def test_postgres_extraction_replay_and_deletion_tombstone_contract(postgres_database):
    from personal_ai.booking_extractions.repositories import ExtractionError

    repository = PostgresBookingExtractionRepository(postgres_database)
    key = uuid4()
    digest = sha256(b"synthetic booking document").hexdigest()
    now = datetime.now(UTC)
    record, created = repository.begin(
        owner_id="local", key=key, fingerprint="1" * 64, source_sha256=digest,
        now=now, execution_deadline=now + timedelta(seconds=30),
    )
    assert created and record.state == "running"
    replay, created_again = repository.begin(
        owner_id="local", key=key, fingerprint="1" * 64, source_sha256=digest,
        now=now, execution_deadline=now + timedelta(seconds=30),
    )
    assert replay == record and not created_again
    deleted = repository.delete_by_key("local", key, digest, now)
    assert deleted.state == "deleted" and deleted.result is not None
    assert repository.get("local", record.extraction_id) == deleted
    with pytest.raises(ExtractionError, match="idempotency_conflict"):
        repository.delete_by_key("local", key, "2" * 64, now)


def test_postgres_extraction_concurrent_replay_checks_losing_fingerprint(
    postgres_database, monkeypatch,
):
    from threading import Barrier, Lock

    import personal_ai.persistence.postgres_capabilities as adapter
    from personal_ai.booking_extractions.repositories import ExtractionError

    repository = PostgresBookingExtractionRepository(postgres_database)
    key = uuid4()
    now = datetime.now(UTC)
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    with postgres_database.transaction() as connection:
        _ensure_namespace(connection, "race-owner", scope)
    initial_reads = Barrier(2)
    count_lock = Lock()
    initial_count = 0
    original_select = adapter._select

    def synchronized_select(connection, family, owner_id, app_scope, record_id, *, lock=False):
        nonlocal initial_count
        result = original_select(connection, family, owner_id, app_scope, record_id, lock=lock)
        should_wait = False
        if family == "booking_document_extractions":
            with count_lock:
                if initial_count < 2:
                    initial_count += 1
                    should_wait = True
        if should_wait:
            initial_reads.wait(timeout=5)
        return result

    monkeypatch.setattr(adapter, "_select", synchronized_select)
    results, errors = [], []

    def begin(fingerprint_value, source_hash):
        try:
            with application_scope_context(scope):
                results.append(repository.begin(
                    owner_id="race-owner", key=key, fingerprint=fingerprint_value,
                    source_sha256=source_hash, now=now,
                    execution_deadline=now + timedelta(seconds=30),
                ))
        except Exception as error:  # noqa: BLE001 - asserted after both writers finish
            errors.append(error)

    writers = (
        Thread(target=begin, args=("1" * 64, "a" * 64)),
        Thread(target=begin, args=("2" * 64, "b" * 64)),
    )
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=10)
    assert all(not writer.is_alive() for writer in writers)
    assert len(results) == 1, errors
    assert len(errors) == 1 and isinstance(errors[0], ExtractionError)
    assert errors[0].code == "idempotency_conflict"


def test_postgres_domain_snapshot_registration_and_lookup_fence_contract(postgres_database):
    from personal_ai.domains.contracts import DomainLookupReservation
    from personal_ai.domains.fixtures import FIXTURE_NOW, fixture_registry
    from personal_ai.domains.service import DomainService
    from personal_ai.settings import Settings

    settings = Settings(
        _env_file=None, ai_provider="gemini", ai_model="synthetic",
        decision_enabled=True, travel_enabled=True, shopping_enabled=True,
        domain_inspection_enabled=True,
    )
    repository = PostgresDomainRepository(postgres_database)
    decisions = PostgresDecisionRepository(postgres_database)
    fixture = next(item for item in fixture_registry() if item.fixture_id == "travel-research-needed")
    result = DomainService(
        settings, decisions, repository,
        owner_id="local", clock=lambda: FIXTURE_NOW,
    ).create(fixture.domain_id, fixture.request)
    assert repository.get("local", result.comparison.id) == result

    reservation = DomainLookupReservation(
        id=uuid4(), owner_id="local", domain_id="travel", idempotency_key=uuid4(),
        request_fingerprint="a" * 64, fence_token=uuid4(), created_at=FIXTURE_NOW,
        updated_at=FIXTURE_NOW,
    )
    reserved = repository.reserve_lookup(reservation)
    assert reserved.id == reservation.id and reserved.state == "reserved"
    other_domain = reservation.model_copy(update={"id": uuid4(), "domain_id": "shopping"})
    assert repository.reserve_lookup(other_domain).domain_id == "shopping"
    completed = repository.complete_lookup(reserved.id, reserved.fence_token, result)
    assert completed == result
    assert repository.get("local", result.comparison.id) == result


def test_postgres_dynamodb_portable_export_preserves_logical_records_and_coverage(
    postgres_database, dynamodb_table,
):
    from personal_ai.auth.account_data import ExportTooLarge
    from personal_ai.persistence.postgres_auth import PostgresAccountLifecycleRepository

    owner_id = f"portable-export-{uuid4()}"
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    now = datetime.now(UTC)
    conversations = DynamoDBConversationRepository(dynamodb_table)
    messages = DynamoDBMessageRepository(dynamodb_table, conversations)
    conversation = Conversation(
        id=uuid4(), owner_id=owner_id, application_id=scope.application_id,
        workspace_id=None, title="export conversation", created_at=now, updated_at=now,
    )
    user = Message(
        id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
        application_id=scope.application_id, role=MessageRole.USER,
        content="I like green tea", status=MessageStatus.COMPLETED,
        created_at=now + timedelta(seconds=1),
    )
    assistant = Message(
        id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
        application_id=scope.application_id, role=MessageRole.ASSISTANT,
        content="Noted", status=MessageStatus.COMPLETED,
        created_at=now + timedelta(seconds=2), parent_message_id=user.id,
    )
    summary = ConversationSummary(
        id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
        application_id=scope.application_id, content="The user prefers green tea.",
        source_message_ids=(user.id, assistant.id),
        source_fingerprint=fingerprint((user, assistant)),
        coverage_message_ids=(user.id, assistant.id),
        coverage_fingerprint=fingerprint((user, assistant), include_state=True),
        covers_through_message_id=assistant.id, source_token_count=12,
        summary_token_count=5, model="synthetic", created_at=now,
    )
    with application_scope_context(scope):
        conversations.create(conversation)
        messages.prepare_message_turn(
            owner_id=owner_id, conversation_id=conversation.id, expected_active_ids=[],
            supersede_from_message_id=None, messages=(user, assistant),
            updated_at=assistant.created_at,
        )
        DynamoDBSummaryRepository(dynamodb_table, conversations).create(summary)
        job_id = job_idempotency_id("portable-export-job", scope.application_id, scope.workspace_id)
        job = MemoryJob(
            id=job_id, owner_id=owner_id, application_id=scope.application_id,
            workspace_id=None, job_type="maintenance", candidate_memory_ids=(),
            policy_version="score-v1", policy_snapshot={},
            idempotency_key="portable-export-job", created_at=now, updated_at=now,
        )
        jobs = DynamoDBMemoryJobRepository(dynamodb_table)
        jobs.create_job(job)
        claimed_job = jobs.claim_job(
            owner_id=owner_id, job_id=job_id,
            now=now + timedelta(seconds=5), lease_seconds=30,
        )
        assert claimed_job is not None
        assert jobs.complete_job(
            claimed_job, token=claimed_job.lease_token, now=now + timedelta(seconds=6)
        )
        source_fp = fingerprint((user,))
        memory = _memory(
            (0.123456789012345, 0.987654321098765), owner_id, user.content,
            source_fingerprint=source_fp, source_conversation_id=conversation.id,
            source_turn_id=assistant.id, source_message_id=user.id,
        )
        memory, _ = PostgresMemoryRepository(
            postgres_database, _SourceGuard(owner_id)
        ).create(memory)
        PostgresGlobalProfileRepository(postgres_database).update(
            owner_id,
            GlobalProfileUpdate(
                fields=(
                    GlobalProfileFieldUpdate(
                        field="preferred_units",
                        value="metric",
                        shared_with_applications=("travel",),
                    ),
                )
            ),
        )
        PostgresDailyBudgetRepository(postgres_database).reserve_daily(
            owner_id, calls=2, tokens=321, call_limit=10, token_limit=1000
        )
        exported = PostgresAccountLifecycleRepository(
            postgres_database, dynamodb_table
        ).export_owner(owner_id, max_records=100, max_bytes=1_000_000)

    assert exported["schema_version"] == "personal-ai-export-v2"
    assert exported["snapshot_coverage"]["cross_store_snapshot"] is False
    assert exported["snapshot_coverage"]["postgres"]["isolation"] == "repeatable_read_read_only"
    assert exported["snapshot_coverage"]["dynamodb"]["consistency"] == "strong_bounded_key_reads"
    memory_data = exported["collections"]["memories"][0]["data"]
    assert memory_data["embedding"] == list(memory.embedding)
    assert exported["collections"]["conversations"][0]["document_id"] == str(conversation.id)
    assert {entry["document_id"] for entry in exported["collections"]["messages"]} == {
        str(user.id), str(assistant.id)
    }
    assert exported["collections"]["conversation_summaries"][0]["document_id"] == str(summary.id)
    assert exported["collections"]["memory_lifecycle_jobs"][0]["document_id"] == str(job.id)
    assert exported["collections"]["memory_lifecycle_jobs"][0]["data"]["status"] == "completed"
    profile_data = exported["collections"]["global_profiles"][0]["data"]
    assert profile_data["owner_id"] == owner_id
    assert profile_data["fields"][0]["set_by"] == "user"
    assert profile_data["fields"][0]["value"] == "metric"
    usage_data = exported["collections"]["usage_budgets"][0]["data"]
    assert usage_data["provider_calls"] == 2
    assert usage_data["input_tokens"] == 321
    assert usage_data["budget_day"] == datetime.now(UTC).date().isoformat()
    with application_scope_context(scope), pytest.raises(ExportTooLarge):
        PostgresAccountLifecycleRepository(
            postgres_database, dynamodb_table
        ).export_owner(owner_id, max_records=1, max_bytes=1_000_000)


def test_postgres_global_profile_repository_contract_and_concurrency(postgres_database):
    owner_id = f"profile-contract-{uuid4()}"
    repository = PostgresGlobalProfileRepository(postgres_database)
    memory_repository = InMemoryGlobalProfileRepository(clock=lambda: datetime.now(UTC))
    assert repository.get(owner_id).revision == 0
    assert repository.get(owner_id).fields == ()

    first_update = GlobalProfileUpdate(
        fields=(
            GlobalProfileFieldUpdate(
                field="preferred_units",
                value="metric",
                shared_with_applications=("travel",),
            ),
            GlobalProfileFieldUpdate(field="locale", value="en-GB"),
        )
    )
    with application_scope_context(
        ApplicationScope(application_id="travel", workspace_id="team-a")
    ):
        first = repository.update(owner_id, first_update)
    memory_repository.update(owner_id, first_update)
    assert first.revision == 1
    assert first.owner_id == owner_id

    # The repository is canonical owner-wide storage, independent of a
    # request's application and workspace namespace.
    with application_scope_context(
        ApplicationScope(application_id="shopping", workspace_id="team-b")
    ):
        assert repository.get(owner_id).revision == 1
        second = repository.update(
            owner_id,
            GlobalProfileUpdate(
                fields=(
                    GlobalProfileFieldUpdate(
                        field="response_style",
                        value="concise",
                        shared_with_applications=("travel", "shopping"),
                    ),
                )
            ),
        )
    memory_repository.update(
        owner_id,
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(
                    field="response_style",
                    value="concise",
                    shared_with_applications=("travel", "shopping"),
                ),
            )
        ),
    )
    assert second.revision == 2
    assert repository.get(f"other-{owner_id}").fields == ()
    pg_shared = repository.shared_fields(
        owner_id, "travel", ("preferred_units", "locale", "response_style")
    )
    memory_shared = memory_repository.shared_fields(
        owner_id, "travel", ("preferred_units", "locale", "response_style")
    )
    projection = lambda records: tuple(
        (item.field, item.value, item.shared_with_applications) for _, item in records
    )
    assert projection(pg_shared) == projection(memory_shared)
    assert [item.field for _, item in pg_shared] == ["preferred_units", "response_style"]
    assert repository.shared_fields(owner_id, "shopping", ("preferred_units",)) == ()

    revoked = repository.update(
        owner_id,
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(field="preferred_units", value="imperial"),
            )
        ),
    )
    assert revoked.revision == 3
    assert repository.shared_fields(owner_id, "travel", ("preferred_units",)) == ()
    assert repository.get(owner_id).fields[0].set_by == "user"
    removed = repository.update(
        owner_id, GlobalProfileUpdate(remove_fields=("locale",))
    )
    assert removed.revision == 4
    assert {item.field for item in removed.fields} == {"preferred_units", "response_style"}

    concurrent_owner = f"profile-concurrent-{uuid4()}"
    barrier = Barrier(3)
    results = []
    failures = []

    def concurrent_update(update):
        try:
            barrier.wait()
            results.append(repository.update(concurrent_owner, update))
        except Exception as error:  # noqa: BLE001 - surface failures in the asserting thread
            failures.append(error)

    initial_updates = (
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(
                    field="preferred_units",
                    value="metric",
                    shared_with_applications=("travel",),
                ),
            )
        ),
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(field="locale", value="en-GB"),
            )
        ),
    )
    threads = [Thread(target=concurrent_update, args=(update,)) for update in initial_updates]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(item.revision for item in results) == [1, 2]
    current = repository.get(concurrent_owner)
    assert current.revision == 2
    assert {item.field for item in current.fields} == {"preferred_units", "locale"}

    barrier = Barrier(3)
    results.clear()
    updates = (
        GlobalProfileUpdate(
            fields=(GlobalProfileFieldUpdate(field="response_style", value="detailed"),)
        ),
        GlobalProfileUpdate(
            fields=(GlobalProfileFieldUpdate(field="answer_length", value="expanded"),)
        ),
    )
    threads = [Thread(target=concurrent_update, args=(update,)) for update in updates]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(item.revision for item in results) == [3, 4]
    current = repository.get(concurrent_owner)
    assert current.revision == 4
    assert {item.field for item in current.fields} == {
        "preferred_units", "locale", "response_style", "answer_length"
    }

    with pytest.raises(TimeoutError, match="postgres operation deadline exceeded"):
        repository.shared_fields(
            owner_id, "travel", ("preferred_units",), deadline=monotonic() - 1
        )

def test_derived_memory_keeps_original_sources_and_excludes_inactive_dependencies(
    postgres_database,
):
    from hashlib import sha256

    from personal_ai.memory.lifecycle import MemoryLifecycleState

    owner_id = f"derived-memory-{uuid4()}"
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    records = (
        _memory(
            (1.0, 0.0, 0.0), owner_id, "I prefer green tea", source_fingerprint="1" * 64,
            source_conversation_id=UUID(int=310), source_turn_id=UUID(int=312),
            source_message_id=UUID(int=311),
        ),
        _memory(
            (1.0, 0.0, 0.0), owner_id, "I prefer green tea", source_fingerprint="2" * 64,
            source_conversation_id=UUID(int=320), source_turn_id=UUID(int=322),
            source_message_id=UUID(int=321),
        ),
    )
    ordered = tuple(sorted(records, key=lambda item: str(item.id)))
    sources = tuple(
        DerivedMemorySource(
            memory_id=record.id, source_fingerprint=record.source_fingerprint,
            source_conversation_id=record.source_conversation_id,
            source_turn_id=record.source_turn_id, source_message_ids=record.source_message_ids,
            excerpt=record.content,
        )
        for record in ordered
    )
    identity_payload = sha256("\0".join(
        [owner_id, "extractive-v1"]
        + [f"{source.memory_id}:{source.source_fingerprint}" for source in sources]
    ).encode()).hexdigest()
    derived_content = "Historical personal context from repeated user statements:\n" + "\n".join(
        source.excerpt for source in sources
    )
    derived = DerivedMemory(
        id=uuid5(NAMESPACE_URL, "personal-ai-derived-memory:" + identity_payload),
        owner_id=owner_id, application_id=scope.application_id, workspace_id=scope.workspace_id,
        memory_type="preference", content=derived_content,
        normalized_content=normalize(derived_content), confidence=0.9, importance=0.8,
        effective_at=max(record.effective_at for record in ordered),
        created_at=datetime.now(UTC), embedding=(0.5, 0.5, 0.5),
        embedding_model="gemini-embedding-001", embedding_dimensions=3,
        source_memory_ids=tuple(source.memory_id for source in sources), sources=sources,
        source_set_identity=identity_payload, derivation_policy_version="extractive-v1",
        rationale_code="repeated_explicit_preference",
    )
    repository = PostgresMemoryRepository(postgres_database, _SourceGuard(owner_id))
    with application_scope_context(scope):
        for record in records:
            repository.create(record)
        saved, created = repository.create_derived(derived)
        repeated, created_again = repository.create_derived(derived)
        found = repository.get_derived(owner_id=owner_id, memory_id=derived.id)
        ranked = repository.search_derived(
            owner_id=owner_id, embedding=(1.0, 0.0, 0.0),
            model=derived.embedding_model, dimensions=3, limit=5,
        )
        inactive = MemoryLifecycleState(
            memory_id=ordered[0].id, owner_id=owner_id, retrieval_status="superseded",
            state_version=1,
        )
        PostgresPayloadRepository(
            postgres_database, "memory_lifecycle_states"
        ).create(
            owner_id=owner_id, scope=scope, record_id=str(ordered[0].id),
            payload=inactive.model_dump(mode="json"), status="superseded",
        )
        ranked_after_inactivation = repository.search_derived(
            owner_id=owner_id, embedding=(1.0, 0.0, 0.0),
            model=derived.embedding_model, dimensions=3, limit=5,
        )
    assert created and not created_again
    assert saved == repeated == found == derived
    assert [item.memory.id for item in ranked] == [derived.id]
    assert ranked_after_inactivation == []


def test_postgres_memory_lifecycle_guard_replay_and_cross_conversation_accounting(
    postgres_database, dynamodb_table, monkeypatch,
):
    owner_id = f"lifecycle-owner-{uuid4()}"
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(), owner_id=owner_id, title="lifecycle source", created_at=now,
        updated_at=now,
    )
    consuming_conversation = Conversation(
        id=uuid4(), owner_id=owner_id, title="completed turn", created_at=now,
        updated_at=now,
    )
    conversations = DynamoDBConversationRepository(dynamodb_table)
    messages = DynamoDBMessageRepository(dynamodb_table, conversations)
    with application_scope_context(scope):
        conversations.create(conversation)
        conversations.create(consuming_conversation)
        user = Message(
            id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
            role=MessageRole.USER, content="I prefer green tea", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=1),
        )
        assistant = Message(
            id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
            role=MessageRole.ASSISTANT, content="Understood", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=2), parent_message_id=user.id,
        )
        messages.prepare_message_turn(
            owner_id=owner_id, conversation_id=conversation.id, expected_active_ids=[],
            supersede_from_message_id=None, messages=(user, assistant),
            updated_at=assistant.created_at,
        )
        consuming_user = Message(
            id=uuid4(), conversation_id=consuming_conversation.id, owner_id=owner_id,
            role=MessageRole.USER, content="Thanks", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=3),
        )
        consuming_assistant = Message(
            id=uuid4(), conversation_id=consuming_conversation.id, owner_id=owner_id,
            role=MessageRole.ASSISTANT, content="You're welcome", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=4), parent_message_id=consuming_user.id,
        )
        messages.prepare_message_turn(
            owner_id=owner_id, conversation_id=consuming_conversation.id,
            expected_active_ids=[], supersede_from_message_id=None,
            messages=(consuming_user, consuming_assistant), updated_at=consuming_assistant.created_at,
        )
        source_fingerprint = fingerprint((user,))
        candidate = MemoryCandidate(
            memory_type="preference", content=user.content, confidence=0.9,
            source_message_ids=(user.id,), rationale_code="user_preference",
            effective_at=user.created_at,
        )
        memory = Memory(
            **candidate.model_dump(exclude={"effective_at"}),
            id=identity(owner_id, source_fingerprint, candidate), owner_id=owner_id,
            normalized_content=normalize(candidate.content),
            source_conversation_id=conversation.id, source_turn_id=assistant.id,
            source_fingerprint=source_fingerprint, observed_at=user.created_at,
            effective_at=user.created_at, created_at=now, embedding=(1.0, 0.0),
            embedding_model="test-model", embedding_dimensions=2,
        )
        guard = DynamoDBMemoryEffectGuard(dynamodb_table, messages)
        memories = PostgresMemoryRepository(postgres_database, guard)
        memories.create(memory)
        lifecycle = PostgresMemoryLifecycleRepository(memories, messages, jobs=None)
        key = "lifecycle-retrieval-contract"
        event = MemoryLifecycleEvent(
            id=event_idempotency_id(key, scope.application_id, scope.workspace_id),
            owner_id=owner_id, application_id=scope.application_id,
            workspace_id=scope.workspace_id, scope_version=2, memory_id=memory.id,
            event_type="retrieved", reason_code="contract_test", policy_version="score-v1",
            actor="developer_test", occurred_at=now + timedelta(seconds=5),
            idempotency_key=key, expected_state_version=0,
        )
        entered_effect, release_effect = Event(), Event()
        original_apply = lifecycle._apply_event_tx

        def pause_before_effect(*args, **kwargs):
            entered_effect.set()
            if not release_effect.wait(timeout=5):
                raise TimeoutError("test effect interleave timed out")
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(lifecycle, "_apply_event_tx", pause_before_effect)
        applied_results, apply_errors = [], []

        def apply_retrieval_event():
            try:
                with application_scope_context(scope):
                    applied_results.append(lifecycle.apply_event(
                        event, completed_assistant_id=consuming_assistant.id,
                        completed_assistant_conversation_id=consuming_conversation.id,
                    ))
            except Exception as error:  # noqa: BLE001 - surfaced below
                apply_errors.append(error)

        old_worker = Thread(target=apply_retrieval_event)
        old_worker.start()
        assert entered_effect.wait(timeout=5)
        with pytest.raises(ConversationConflictError):
            messages.supersede_path(
                owner_id=owner_id, conversation_id=consuming_conversation.id,
                message_id=consuming_user.id,
                updated_at=consuming_assistant.created_at + timedelta(seconds=1),
            )
        release_effect.set()
        old_worker.join(timeout=5)
        assert not old_worker.is_alive()
        assert apply_errors == []
        monkeypatch.setattr(lifecycle, "_apply_event_tx", original_apply)
        applied = applied_results[0]
        replayed = lifecycle.apply_event(
            event, completed_assistant_id=consuming_assistant.id,
            completed_assistant_conversation_id=consuming_conversation.id,
        )
        rebuilt = lifecycle.rebuild_state(owner_id=owner_id, memory_id=memory.id)
        events = lifecycle.list_events(owner_id=owner_id, memory_id=memory.id)

    assert applied.status == "applied" and applied.event_id == event.id
    assert replayed.status == "replayed" and replayed.state.retrieval_count == 1
    assert rebuilt.retrieval_count == 1 and rebuilt.state_version == 1
    assert tuple(item.id for item in events) == (event.id,)


def test_dynamodb_job_publication_replay_and_generation_fencing(dynamodb_table):
    owner_id = f"dynamodb-job-{uuid4()}"
    scope = ApplicationScope(application_id="integration-app", workspace_id="workspace-a")
    now = datetime.now(UTC)
    job_id = job_idempotency_id("dynamodb-job-contract", scope.application_id, scope.workspace_id)
    job = MemoryJob(
        id=job_id, owner_id=owner_id, application_id=scope.application_id,
        workspace_id=scope.workspace_id, job_type="maintenance", candidate_memory_ids=(),
        policy_version="score-v1", policy_snapshot={"forgetting_policy_version": "forget-v1"},
        idempotency_key="dynamodb-job-contract", created_at=now, updated_at=now,
    )
    jobs = DynamoDBMemoryJobRepository(dynamodb_table)
    with application_scope_context(scope):
        saved, created = jobs.create_job(job)
        replay, replay_created = jobs.create_job(job)
        assert saved.id == replay.id == job.id
        assert created and not replay_created
        published = jobs.pending_for_publish(now=now + timedelta(seconds=5), limit=10)
        assert job.id in {item.id for item in published}
        claimed = jobs.claim_job(
            owner_id=owner_id, job_id=job.id, now=now + timedelta(seconds=5), lease_seconds=30
        )
        assert claimed is not None and claimed.lease_generation == 1
        assert jobs.claim_job(
            owner_id=owner_id, job_id=job.id, now=now + timedelta(seconds=6), lease_seconds=30
        ) is None
        assert jobs.fail_job(
            claimed, token=claimed.lease_token, now=now + timedelta(seconds=7),
            reason="transient", retryable=True,
        )
        retry = jobs.get_job(owner_id=owner_id, job_id=job.id)
        assert retry.status == "retry"
        reclaimed = jobs.claim_job(
            owner_id=owner_id, job_id=job.id,
            now=retry.next_attempt_at + timedelta(seconds=1), lease_seconds=30,
        )
        assert reclaimed is not None and reclaimed.lease_generation == 2
        assert jobs.complete_job(
            reclaimed, token=reclaimed.lease_token, now=reclaimed.updated_at + timedelta(seconds=1)
        )
        assert not jobs.complete_job(
            claimed, token=claimed.lease_token, now=reclaimed.updated_at + timedelta(seconds=2)
        )


def test_dynamodb_conversation_message_directory_and_branch_semantics(dynamodb_table):
    conversations = DynamoDBConversationRepository(dynamodb_table)
    messages = DynamoDBMessageRepository(dynamodb_table, conversations)
    scope = ApplicationScope(application_id="integration-app", workspace_id="workspace-a")
    now = datetime.now(UTC)
    conversation = Conversation(
        id=UUID(int=100),
        owner_id="integration-owner",
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        title="integration",
        created_at=now,
        updated_at=now,
    )
    with application_scope_context(scope):
        conversations.create(conversation)
        synthetic_active = tuple(
            Message(
                id=UUID(int=1000 + index), conversation_id=conversation.id,
                owner_id=conversation.owner_id, application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                role=MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
                content=f"covered message {index}", status=MessageStatus.COMPLETED,
                created_at=now + timedelta(seconds=index + 1),
                parent_message_id=(UUID(int=1000 + index - 1) if index % 2 else None),
            )
            for index in range(258)
        )
        summary = ConversationSummary(
            id=uuid4(), conversation_id=conversation.id, owner_id=conversation.owner_id,
            application_id=scope.application_id, workspace_id=scope.workspace_id,
            content="bounded summary coverage", source_message_ids=tuple(m.id for m in synthetic_active),
            source_fingerprint=fingerprint(synthetic_active),
            coverage_message_ids=tuple(m.id for m in synthetic_active),
            coverage_fingerprint=fingerprint(synthetic_active, include_state=True),
            covers_through_message_id=synthetic_active[-1].id,
            source_token_count=258, summary_token_count=8, counter_kind="estimated",
            model="test-model", created_at=now,
        )
        summaries = DynamoDBSummaryRepository(dynamodb_table, conversations)
        summaries.create(summary)
        compatible_summary = summaries.compatible(
            owner_id=conversation.owner_id, conversation_id=conversation.id, active=synthetic_active
        )
        user = Message(
            id=UUID(int=101), conversation_id=conversation.id, owner_id=conversation.owner_id,
            application_id=scope.application_id, workspace_id=scope.workspace_id,
            role=MessageRole.USER, content="first", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=1),
        )
        assistant = Message(
            id=UUID(int=102), conversation_id=conversation.id, owner_id=conversation.owner_id,
            application_id=scope.application_id, workspace_id=scope.workspace_id,
            role=MessageRole.ASSISTANT, content="answer", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=2), parent_message_id=user.id,
        )
        messages.prepare_message_turn(
            owner_id=conversation.owner_id,
            conversation_id=conversation.id,
            expected_active_ids=[],
            supersede_from_message_id=None,
            messages=(user, assistant),
            updated_at=assistant.created_at,
        )
        active = messages.list_active(owner_id=conversation.owner_id, conversation_id=conversation.id)
        listed = conversations.list(owner_id=conversation.owner_id)
        fetched = messages.get(
            owner_id=conversation.owner_id, conversation_id=conversation.id, message_id=assistant.id
        )
        replaced = messages.supersede_path(
            owner_id=conversation.owner_id, conversation_id=conversation.id,
            message_id=user.id, updated_at=assistant.created_at + timedelta(seconds=1),
        )
        active_after_cut = messages.list_active(
            owner_id=conversation.owner_id, conversation_id=conversation.id
        )
        assistant_after_cut = messages.get(
            owner_id=conversation.owner_id, conversation_id=conversation.id, message_id=assistant.id
        )
    assert [item.id for item in active] == [user.id, assistant.id]
    assert listed[0].id == conversation.id
    assert fetched.id == assistant.id
    assert fetched.status is MessageStatus.COMPLETED
    assert compatible_summary is not None and compatible_summary.id == summary.id
    assert [message.id for message in replaced] == [user.id, assistant.id]
    assert active_after_cut == []
    assert assistant_after_cut.status is MessageStatus.SUPERSEDED

    long_conversation = Conversation(
        id=UUID(int=103), owner_id=conversation.owner_id, application_id=scope.application_id,
        workspace_id=scope.workspace_id, title="long history", created_at=now, updated_at=now,
    )
    with application_scope_context(scope):
        conversations.create(long_conversation)
        parent_id = None
        last_id = None
        for index in range(70):
            message = Message(
                id=UUID(int=5000 + index), conversation_id=long_conversation.id,
                owner_id=conversation.owner_id, application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                role=MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
                content=f"long-history-{index}", status=MessageStatus.COMPLETED,
                created_at=now + timedelta(seconds=index + 1), parent_message_id=parent_id,
            )
            messages.create(message)
            parent_id = message.id
            last_id = message.id
        long_active = messages.list_active(
            owner_id=long_conversation.owner_id, conversation_id=long_conversation.id
        )
        long_last = messages.get(
            owner_id=long_conversation.owner_id, conversation_id=long_conversation.id,
            message_id=last_id,
        )
    assert len(long_active) == 70
    assert long_last.id == last_id and long_last.status is MessageStatus.COMPLETED


def test_dynamodb_conversation_update_and_touch_support_null_and_named_workspaces(dynamodb_table):
    repository = DynamoDBConversationRepository(dynamodb_table)
    now = datetime.now(UTC)
    cases = (
        ApplicationScope(application_id="personal_ai", workspace_id=None),
        ApplicationScope(application_id="travel", workspace_id="workspace-named"),
    )
    for index, scope in enumerate(cases):
        owner_id = f"conversation-update-{index}-{uuid4()}"
        conversation = Conversation(
            id=uuid4(), owner_id=owner_id, application_id=scope.application_id,
            workspace_id=scope.workspace_id, title="before", created_at=now,
            updated_at=now,
        )
        with application_scope_context(scope):
            saved = repository.create(conversation)
            updated = repository.update(saved.model_copy(update={
                "title": "after", "updated_at": now + timedelta(seconds=1),
            }))
            touched = repository.touch(
                owner_id=owner_id, conversation_id=conversation.id,
                updated_at=now + timedelta(seconds=2),
            )
            current = repository.get(owner_id=owner_id, conversation_id=conversation.id)
        assert updated.title == current.title == "after"
        assert touched.persistence_revision == current.persistence_revision == 3
        assert touched.updated_at == current.updated_at == now + timedelta(seconds=2)


def test_cross_store_apply_wins_abort_race_and_late_apply_is_fenced(
    postgres_database, dynamodb_table
):
    owner_id = f"effect-owner-{uuid4()}"
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(), owner_id=owner_id, title="effect source", created_at=now, updated_at=now
    )
    conversations = DynamoDBConversationRepository(dynamodb_table)
    messages = DynamoDBMessageRepository(dynamodb_table, conversations)
    with application_scope_context(scope):
        conversations.create(conversation)
        user = Message(
            id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
            role=MessageRole.USER, content="I prefer tea", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=1),
        )
        assistant = Message(
            id=uuid4(), conversation_id=conversation.id, owner_id=owner_id,
            role=MessageRole.ASSISTANT, content="Understood", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=2), parent_message_id=user.id,
        )
        messages.prepare_message_turn(
            owner_id=owner_id, conversation_id=conversation.id, expected_active_ids=[],
            supersede_from_message_id=None, messages=(user, assistant), updated_at=assistant.created_at,
        )

    source_fingerprint = fingerprint((user,))
    candidate = MemoryCandidate(
        memory_type="preference", content="I prefer tea", confidence=0.9,
        source_message_ids=(user.id,), rationale_code="user_preference", effective_at=user.created_at,
    )
    record = Memory(
        **candidate.model_dump(exclude={"effective_at"}),
        id=identity(owner_id, source_fingerprint, candidate), owner_id=owner_id,
        normalized_content=normalize(candidate.content), source_conversation_id=conversation.id,
        source_turn_id=assistant.id, source_fingerprint=source_fingerprint,
        observed_at=user.created_at, effective_at=user.created_at, created_at=now,
        embedding=(1.0, 0.0), embedding_model="test-model", embedding_dimensions=2,
    )
    guard = DynamoDBMemoryEffectGuard(dynamodb_table, messages)
    token = guard.acquire(record, timeout=5)
    with application_scope_context(scope), pytest.raises(ConversationConflictError):
        messages.supersede_path(
            owner_id=owner_id, conversation_id=conversation.id,
            message_id=user.id, updated_at=assistant.created_at + timedelta(seconds=1),
        )
    receipts = PostgresEffectReceiptRepository(postgres_database)
    apply_entered, release_apply = Event(), Event()
    recovery_looked_up, recovery_started_abort = Event(), Event()

    class _RacingReceipts:
        def apply(self, **kwargs):
            return receipts.apply(**kwargs)

        def get(self, **kwargs):
            result = receipts.get(**kwargs)
            recovery_looked_up.set()
            return result

        def abort_if_unresolved(self, **kwargs):
            recovery_started_abort.set()
            return receipts.abort_if_unresolved(**kwargs)

    racing_receipts = _RacingReceipts()
    memory_repository = PostgresMemoryRepository(
        postgres_database, guard, receipt_repository=racing_receipts
    )
    effect_count = []
    apply_result = []
    recovery_result = []
    errors = []

    def apply_effect(connection):
        apply_entered.set()
        if not release_apply.wait(timeout=5):
            raise TimeoutError("test interleave timed out")
        scope_id = _ensure_namespace(connection, owner_id, scope)
        event_id = f"effect:{token.operation_id}:{token.attempt_id}"
        connection.execute(
            "INSERT INTO memory_lifecycle_events(record_id,scope_id,owner_id,application_id,"
            "workspace_id,record_version,status,revision,event_sequence,created_at,payload) "
            "VALUES (%s,%s,%s,%s,NULL,1,'applied',1,1,%s,'{}'::jsonb)",
            (event_id, scope_id, owner_id, scope.application_id, now),
        )
        effect_count.append(event_id)
        return {"event_id": event_id}

    def apply_old_worker():
        try:
            apply_result.append(receipts.apply(
                owner_id=owner_id, scope=scope, operation_id=token.operation_id,
                attempt_id=token.attempt_id, fingerprint=token.fingerprint,
                execution_deadline=token.execution_deadline, effect=apply_effect,
            ))
        except Exception as error:  # noqa: BLE001 - surfaced in the parent thread below
            errors.append(error)

    def recover():
        try:
            recovery_result.append(memory_repository.recover_pending_operations(
                owner_id=owner_id, conversation_id=conversation.id, scope=scope
            ))
        except Exception as error:  # noqa: BLE001 - surfaced in the parent thread below
            errors.append(error)

    old_worker = Thread(target=apply_old_worker)
    old_worker.start()
    assert apply_entered.wait(timeout=5)
    recovery = Thread(target=recover)
    recovery.start()
    assert recovery_looked_up.wait(timeout=5)
    assert recovery_started_abort.wait(timeout=5)
    release_apply.set()
    old_worker.join(timeout=5)
    recovery.join(timeout=5)
    assert not old_worker.is_alive() and not recovery.is_alive()
    assert errors == [], [getattr(error, "response", str(error)) for error in errors]
    assert apply_result[0][0].outcome == "applied"
    assert recovery_result == [1]
    assert len(effect_count) == 1
    assert guard.pending_operations(
        owner_id=owner_id, conversation_id=conversation.id, scope=scope
    ) == ()

    # A second operation with no apply in flight is aborted during recovery.
    second_candidate = candidate.model_copy(update={"content": "I prefer coffee"})
    second_fingerprint = source_fingerprint
    second_record = record.model_copy(update={
        "id": identity(owner_id, second_fingerprint, second_candidate),
        "content": second_candidate.content,
        "normalized_content": normalize(second_candidate.content),
        "source_fingerprint": second_fingerprint,
    })
    second_token = guard.acquire(second_record, timeout=5)
    assert memory_repository.recover_pending_effects(owner_id=owner_id, limit=10) == 1
    late_effects = []
    with pytest.raises(PersistenceConflict):
        receipts.apply(
            owner_id=owner_id, scope=scope, operation_id=second_token.operation_id,
            attempt_id=second_token.attempt_id, fingerprint=second_token.fingerprint,
            execution_deadline=second_token.execution_deadline,
            effect=lambda connection: late_effects.append("committed") or {},
        )
    assert late_effects == []
    assert guard.pending_operations(
        owner_id=owner_id, conversation_id=conversation.id, scope=scope
    ) == ()
    with application_scope_context(scope):
        messages.supersede_path(
            owner_id=owner_id, conversation_id=conversation.id,
            message_id=user.id, updated_at=assistant.created_at + timedelta(seconds=2),
        )
    with application_scope_context(scope):
        assert messages.list_active(owner_id=owner_id, conversation_id=conversation.id) == []


def test_account_wide_safeguards_use_dynamodb_windows_and_postgres_daily_budgets(
    postgres_database, dynamodb_table
):
    owner_id = f"budget-owner-{uuid4()}"
    budgets = PostgresDailyBudgetRepository(postgres_database)
    safeguards = DynamoDBSafeguardStore(dynamodb_table, budgets)
    safeguards.consume_request(owner_id, limit=1)
    with pytest.raises(SafeguardDenied) as denied:
        safeguards.consume_request(owner_id, limit=1)
    assert denied.value.code == "rate_limit_exceeded"

    with application_scope_context(ApplicationScope(application_id="travel", workspace_id="workspace")):
        safeguards.reserve_daily(owner_id, 1, 10, call_limit=2, token_limit=20)
    with application_scope_context(ApplicationScope(application_id="personal_ai", workspace_id=None)):
        safeguards.reserve_daily(owner_id, 1, 10, call_limit=2, token_limit=20)
    with pytest.raises(SafeguardDenied) as denied_daily:
        safeguards.reserve_daily(owner_id, 1, 0, call_limit=2, token_limit=20)
    assert denied_daily.value.code == "daily_budget_exceeded"
    with postgres_database.connection() as connection:
        calls, tokens, expires_at = connection.execute(
            "SELECT provider_calls,input_tokens,expires_at FROM usage_budgets WHERE owner_id=%s",
            (owner_id,),
        ).fetchone()
    assert (calls, tokens) == (2, 20)
    assert expires_at > datetime.now(UTC) + timedelta(days=89)


def test_expired_daily_usage_budgets_are_purged_within_the_batch_limit(postgres_database):
    owner_id = f"expired-budget-{uuid4()}"
    budgets = PostgresDailyBudgetRepository(postgres_database)
    budgets.reserve_daily(owner_id, 1, 5, call_limit=2, token_limit=10)
    now = datetime.now(UTC)
    with postgres_database.transaction() as connection:
        connection.execute(
            "UPDATE usage_budgets SET expires_at=%s WHERE owner_id=%s",
            (now - timedelta(seconds=1), owner_id),
        )

    assert budgets.purge_expired(now, limit=1) == 1
    with postgres_database.connection() as connection:
        remaining = connection.execute(
            "SELECT count(*) FROM usage_budgets WHERE owner_id=%s", (owner_id,)
        ).fetchone()[0]
    assert remaining == 0


def test_job_effect_guard_pins_lease_and_source_until_receipt_recovery(
    postgres_database, dynamodb_table
):
    owner_id = f"job-effect-owner-{uuid4()}"
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    now = datetime.now(UTC)
    conversation = Conversation(
        id=UUID(int=200), owner_id=owner_id, title="job effect source",
        created_at=now, updated_at=now,
    )
    conversations = DynamoDBConversationRepository(dynamodb_table)
    messages = DynamoDBMessageRepository(dynamodb_table, conversations)
    with application_scope_context(scope):
        conversations.create(conversation)
        user = Message(
            id=UUID(int=201), conversation_id=conversation.id, owner_id=owner_id,
            role=MessageRole.USER, content="I prefer green tea", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=1),
        )
        assistant = Message(
            id=UUID(int=202), conversation_id=conversation.id, owner_id=owner_id,
            role=MessageRole.ASSISTANT, content="I will remember that", status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=2), parent_message_id=user.id,
        )
        messages.prepare_message_turn(
            owner_id=owner_id, conversation_id=conversation.id, expected_active_ids=[],
            supersede_from_message_id=None, messages=(user, assistant),
            updated_at=assistant.created_at,
        )
        source_fingerprint = fingerprint((user,))
        candidate = MemoryCandidate(
            memory_type="preference", content=user.content, confidence=0.9,
            source_message_ids=(user.id,), rationale_code="user_preference",
            effective_at=user.created_at,
        )
        memory = Memory(
            **candidate.model_dump(exclude={"effective_at"}),
            id=identity(owner_id, source_fingerprint, candidate), owner_id=owner_id,
            normalized_content=normalize(candidate.content),
            source_conversation_id=conversation.id, source_turn_id=assistant.id,
            source_fingerprint=source_fingerprint, observed_at=user.created_at,
            effective_at=user.created_at, created_at=now, embedding=(1.0, 0.0),
            embedding_model="test-model", embedding_dimensions=2,
        )
        job_id = job_idempotency_id("job-effect-test", scope.application_id, scope.workspace_id)
        pending = MemoryJob(
            id=job_id, owner_id=owner_id, application_id=scope.application_id,
            workspace_id=scope.workspace_id, job_type="maintenance",
            candidate_memory_ids=(memory.id,), policy_version="score-v1",
            policy_snapshot={"derivation_policy_version": "derive-v1"},
            idempotency_key="job-effect-test", created_at=now, updated_at=now,
        )
        jobs = DynamoDBMemoryJobRepository(dynamodb_table)
        jobs.create_job(pending)
        claimed = jobs.claim_job(
            owner_id=owner_id, job_id=job_id, now=now, lease_seconds=60
        )
        assert claimed is not None and claimed.lease_token is not None

    guard = DynamoDBMemoryEffectGuard(dynamodb_table, messages)
    receipts = PostgresEffectReceiptRepository(postgres_database)
    effect_entered, release_effect = Event(), Event()
    recovery_entered, release_recovery = Event(), Event()
    errors = []
    applied, recovered = [], []

    class _RacingReceipts:
        def apply(self, **kwargs):
            return receipts.apply(**kwargs)

        def get(self, **kwargs):
            receipt = receipts.get(**kwargs)
            recovery_entered.set()
            return receipt

        def abort_if_unresolved(self, **kwargs):
            release_recovery.set()
            return receipts.abort_if_unresolved(**kwargs)

    memory_repository = PostgresMemoryRepository(
        postgres_database, guard, receipt_repository=_RacingReceipts()
    )

    def effect(connection):
        effect_entered.set()
        if not release_effect.wait(timeout=5):
            raise TimeoutError("job effect interleave timed out")
        scope_id = _ensure_namespace(connection, owner_id, scope)
        connection.execute(
            "INSERT INTO memory_lifecycle_events(record_id,scope_id,owner_id,application_id,"
            "workspace_id,record_version,status,revision,event_sequence,aggregate_id,created_at,payload) "
            "VALUES (%s,%s,%s,%s,NULL,1,'applied',1,1,%s,%s,'{}'::jsonb)",
            (f"job-effect:{job_id}", scope_id, owner_id, scope.application_id,
             str(job_id), now),
        )
        return {"job_id": str(job_id)}

    def apply_effect():
        try:
            applied.append(memory_repository.apply_job_effect(
                job=claimed, lease_token=claimed.lease_token, record=memory,
                operation_id=f"{job_id}:maintenance", effect=effect,
            ))
        except Exception as error:  # noqa: BLE001 - surfaced in the parent thread below
            errors.append(error)

    def recover_effect():
        try:
            recovered.append(memory_repository.recover_pending_job_operation(
                owner_id=owner_id, job_id=job_id, scope=scope
            ))
        except Exception as error:  # noqa: BLE001 - surfaced in the parent thread below
            errors.append(error)

    worker = Thread(target=apply_effect)
    worker.start()
    entered = effect_entered.wait(timeout=5)
    if not entered:
        worker.join(timeout=5)
    assert entered, errors
    assert jobs.claim_job(
        owner_id=owner_id, job_id=job_id, now=claimed.lease_expires_at + timedelta(seconds=1),
        lease_seconds=60,
    ) is None
    recovery = Thread(target=recover_effect)
    recovery.start()
    assert recovery_entered.wait(timeout=5)
    assert release_recovery.wait(timeout=5)
    release_effect.set()
    worker.join(timeout=5)
    recovery.join(timeout=5)
    assert not worker.is_alive() and not recovery.is_alive()
    assert errors == [], [getattr(error, "response", str(error)) for error in errors]
    assert applied[0][0].outcome == "applied"
    assert recovered == [1]
    next_claim = jobs.claim_job(
        owner_id=owner_id, job_id=job_id,
        now=claimed.lease_expires_at + timedelta(seconds=1), lease_seconds=60,
    )
    assert next_claim.lease_generation == claimed.lease_generation + 1
    late_effects = []
    with pytest.raises(ConversationConflictError):
        memory_repository.apply_job_effect(
            job=claimed, lease_token=claimed.lease_token, record=memory,
            operation_id=f"{job_id}:late", effect=lambda connection: late_effects.append(True) or {},
        )
    assert late_effects == []

    aborted_operation = f"{job_id}:aborted-maintenance"
    guard.acquire_job(
        next_claim, next_claim.lease_token, memory,
        operation_id=aborted_operation, timeout=5,
    )
    assert memory_repository.recover_pending_job_operation(
        owner_id=owner_id, job_id=job_id, scope=scope
    ) == 1
    with pytest.raises(ConversationConflictError):
        memory_repository.apply_job_effect(
            job=next_claim, lease_token=next_claim.lease_token, record=memory,
            operation_id=aborted_operation,
            effect=lambda connection: late_effects.append(True) or {},
        )
    assert late_effects == []
