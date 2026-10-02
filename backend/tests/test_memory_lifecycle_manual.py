"""Explicit synthetic emulator/private push checks; ordinary tests never contact services."""

import os
from datetime import UTC, datetime
from time import monotonic, sleep
from uuid import uuid4

import pytest

from personal_ai.evaluation.memory_lifecycle import build_fixture, load_fixtures
from personal_ai.memory.inspection import inspect_records
from personal_ai.memory.lifecycle_jobs import (
    MemoryLifecycleCoordinator,
    MemoryLifecycleWorker,
    PubSubMemoryJobPublisher,
)
from personal_ai.memory.lifecycle_repositories import FirestoreMemoryLifecycleRepository
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.settings import Settings
from personal_ai.storage import FirestoreConversationRepository, FirestoreMessageRepository


def persist_synthetic(name, *, emulator):
    assert os.environ.get("FIRESTORE_PROJECT_ID"), "Explicit synthetic project required"
    if emulator:
        assert os.environ.get("FIRESTORE_EMULATOR_HOST"), "Explicit emulator host required"
    else:
        assert not os.environ.get("FIRESTORE_EMULATOR_HOST"), "Cloud push must use cloud storage"
    fixture = next(item for item in load_fixtures() if item["name"] == name).copy()
    fixture["name"] += ":" + str(uuid4())
    env = build_fixture(fixture)
    settings = Settings(
        memory_enabled=True,
        memory_lifecycle_worker_enabled=True,
        memory_consolidation_enabled=True,
        memory_contradiction_automation_enabled=True,
        memory_forgetting_enabled=True,
        memory_lifecycle_inspection_enabled=True,
        memory_embedding_model="fake-v1",
        memory_embedding_dimensions=3,
    )
    conversations = FirestoreConversationRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    messages = FirestoreMessageRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    memories = FirestoreMemoryRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    for conversation in env["conversations"]._conversations.values():
        conversations.create(conversation)
    for message in env["messages"]._messages.values():
        messages.create(message)
    for memory in env["records"].values():
        memories.create(memory)
    lifecycle = FirestoreMemoryLifecycleRepository(memories, messages)
    coordinator = MemoryLifecycleCoordinator(settings, lifecycle, memories)
    ids = tuple(record.id for record in env["records"].values())
    job_type = "consolidation" if fixture.get("action") == "consolidate" else "maintenance"
    completed = env["completed"].model_copy(update={"created_at": datetime.now(UTC)})
    coordinator._enqueue(completed, job_type, ids)
    jobs = lifecycle.pending_for_publish(now=datetime.now(UTC), limit=100)
    job = next(job for job in jobs if set(job.candidate_memory_ids) == set(ids))
    return env, settings, messages, memories, lifecycle, job


@pytest.mark.skipif(
    os.environ.get("RUN_MEMORY_LIFECYCLE_EMULATOR_TEST") != "1",
    reason="Opt-in synthetic lifecycle emulator check",
)
@pytest.mark.parametrize(
    "name",
    [
        "repeated-explicit-preference",
        "clear-explicit-correction",
        "ambiguous-negation",
        "stale-low-value-memory",
    ],
)
def test_emulator_lifecycle_atomic_persistence_and_read_only_inspection(name):
    env, settings, messages, memories, lifecycle, job = persist_synthetic(name, emulator=True)
    worker = MemoryLifecycleWorker(settings, lifecycle, memories, messages, env["embedder"])
    assert worker.process(job.id) == "completed"
    assert worker.process(job.id) == "completed"
    for memory in env["records"].values():
        assert memories.get(owner_id="local", memory_id=memory.id) == memory
        state = lifecycle.get_state(owner_id="local", memory_id=memory.id)
        assert lifecycle.rebuild_state(owner_id="local", memory_id=memory.id) == state
    report = inspect_records(
        settings,
        memories,
        messages,
        "local",
        [memory.id for memory in env["records"].values()],
        lifecycle,
    )
    assert all(score.similarity is None for score in report.scores)
    settings.memory_lifecycle_worker_enabled = False
    assert worker.process(job.id) == "disabled"


@pytest.mark.skipif(
    os.environ.get("RUN_MEMORY_LIFECYCLE_PUBSUB_TEST") != "1",
    reason="Opt-in synthetic private Cloud Run/Pub/Sub check",
)
def test_cloud_authenticated_push_completes_synthetic_durable_job():
    env, settings, _, _, lifecycle, job = persist_synthetic(
        "clear-explicit-correction", emulator=False
    )
    PubSubMemoryJobPublisher(settings).publish(job, timeout=5)
    deadline = monotonic() + 55
    while monotonic() < deadline:
        current = lifecycle.get_job(owner_id="local", job_id=job.id)
        if current.status in ("completed", "terminal"):
            assert current.status == "completed"
            break
        sleep(1)
    else:
        pytest.fail("Synthetic Pub/Sub job did not complete within the check deadline")
    old = env["records"]["older"]
    assert lifecycle.get_state(owner_id="local", memory_id=old.id).retrieval_status == "superseded"
