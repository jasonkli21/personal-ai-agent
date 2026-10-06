"""Application and workspace scope contracts across persisted identities."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from personal_ai.auth.scope import (
    ApplicationScope,
    application_scope_context,
    scope_matches,
    scoped_record,
)
from personal_ai.entities import Conversation
from personal_ai.memory.contracts import (
    DerivedMemory,
    DerivedMemorySource,
    MemoryCandidate,
    identity,
    normalize,
)
from personal_ai.memory.lifecycle_repositories import event_idempotency_id, job_idempotency_id
from personal_ai.storage import InMemoryConversationRepository, ResourceNotFoundError

OWNER = "same-owner"
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _conversation(identifier: int) -> Conversation:
    return Conversation(
        id=UUID(int=identifier),
        owner_id=OWNER,
        title=f"Conversation {identifier}",
        created_at=NOW,
        updated_at=NOW,
    )


def test_conversations_are_isolated_by_application_and_workspace_for_one_owner():
    repository = InMemoryConversationRepository()
    standalone = repository.create(_conversation(1))
    travel_scope = ApplicationScope(application_id="travel", workspace_id=None)
    with application_scope_context(travel_scope):
        travel = repository.create(_conversation(2))
        assert travel.application_id == "travel"
        assert travel.workspace_id is None
        assert travel.scope_version == 2
        assert repository.list(owner_id=OWNER) == [travel]
        with pytest.raises(ResourceNotFoundError):
            repository.get(owner_id=OWNER, conversation_id=standalone.id)

    workspace_scope = ApplicationScope(application_id="travel", workspace_id="team-a")
    with application_scope_context(workspace_scope):
        workspace = repository.create(_conversation(3))
        assert repository.list(owner_id=OWNER) == [workspace]
        with pytest.raises(ResourceNotFoundError):
            repository.get(owner_id=OWNER, conversation_id=travel.id)


def test_absent_scope_fields_decode_as_legacy_standalone_only():
    data = _conversation(4).model_dump(mode="python")
    data.pop("application_id")
    data.pop("workspace_id")
    data.pop("scope_version")
    legacy = Conversation.model_validate(data)

    assert legacy.application_id == "personal_ai"
    assert legacy.workspace_id is None
    assert legacy.scope_version == 1
    assert scope_matches(legacy, ApplicationScope())
    assert not scope_matches(legacy, ApplicationScope(application_id="shopping"))


def test_memory_v1_identity_is_preserved_and_new_scope_namespaces_are_distinct():
    candidate = MemoryCandidate(
        memory_type="preference",
        content="  I like tea  ",
        confidence=0.9,
        source_message_ids=(UUID(int=10),),
        rationale_code="user_preference",
    )
    fingerprint = "a" * 64
    old_key = sha256(
        (OWNER + "\0" + fingerprint + "\0preference\0" + normalize(candidate.content)).encode()
    ).hexdigest()
    legacy_id = uuid5(NAMESPACE_URL, "personal-ai-memory:" + old_key)

    assert identity(OWNER, fingerprint, candidate) == legacy_id
    with application_scope_context(ApplicationScope(application_id="shopping")):
        app_id = identity(OWNER, fingerprint, candidate)
        assert app_id != legacy_id
    with application_scope_context(
        ApplicationScope(application_id="shopping", workspace_id="team-a")
    ):
        workspace_id = identity(OWNER, fingerprint, candidate)
        assert workspace_id not in {legacy_id, app_id}


def _derived_memory(application_id="personal_ai", workspace_id=None):
    ids = (UUID(int=21), UUID(int=22))
    sources = tuple(
        DerivedMemorySource(
            memory_id=identifier,
            source_fingerprint=f"{index:x}" * 64,
            source_conversation_id=UUID(int=31 + index),
            source_turn_id=UUID(int=41 + index),
            source_message_ids=(UUID(int=51 + index),),
            excerpt="I like tea",
        )
        for index, identifier in enumerate(ids, start=1)
    )
    namespace = [] if application_id == "personal_ai" and workspace_id is None else [
        application_id,
        workspace_id or "",
    ]
    key = sha256(
        "\0".join(
            [OWNER, *namespace, "extractive-v1"]
            + [f"{item.memory_id}:{item.source_fingerprint}" for item in sources]
        ).encode()
    ).hexdigest()
    return DerivedMemory(
        id=uuid5(NAMESPACE_URL, "personal-ai-derived-memory:" + key),
        owner_id=OWNER,
        application_id=application_id,
        workspace_id=workspace_id,
        memory_type="preference",
        content="Historical personal context from repeated user statements:\nI like tea\nI like tea",
        normalized_content=normalize(
            "Historical personal context from repeated user statements:\nI like tea\nI like tea"
        ),
        confidence=0.8,
        importance=0.7,
        effective_at=NOW,
        created_at=NOW,
        embedding=(1.0, 0.0),
        embedding_model="test-embedding",
        embedding_dimensions=2,
        source_memory_ids=ids,
        sources=sources,
        source_set_identity=key,
        derivation_policy_version="extractive-v1",
        rationale_code="repeated_explicit_preference",
    )


def test_derived_memory_v2_identity_is_stable_per_scope():
    standalone = _derived_memory()
    assert scoped_record(standalone).id == standalone.id
    assert scoped_record(standalone).scope_version == 2
    travel = _derived_memory("travel")
    workspace = _derived_memory("travel", "team-a")
    assert len({standalone.id, travel.id, workspace.id}) == 3


def test_lifecycle_replay_ids_keep_standalone_v1_and_partition_new_scopes():
    key = "synthetic:replay"
    assert event_idempotency_id(key) == uuid5(
        NAMESPACE_URL, "personal-ai-memory-event:" + key
    )
    assert job_idempotency_id(key) == uuid5(NAMESPACE_URL, "personal-ai-memory-job:" + key)
    with application_scope_context(ApplicationScope(application_id="health")):
        app_event = event_idempotency_id(key)
        app_job = job_idempotency_id(key)
        assert app_event != event_idempotency_id(key, "personal_ai", None)
        assert app_job != job_idempotency_id(key, "personal_ai", None)
    with application_scope_context(
        ApplicationScope(application_id="health", workspace_id="team-a")
    ):
        assert event_idempotency_id(key) != app_event
        assert job_idempotency_id(key) != app_job
