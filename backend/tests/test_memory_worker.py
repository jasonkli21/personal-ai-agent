"""Private Pub/Sub worker transport; all worker dependencies are local fakes."""

import base64
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from personal_ai.entities import Message
from personal_ai.main import app as public_app
from personal_ai.memory.lifecycle import MemoryJob
from personal_ai.memory.lifecycle_jobs import (
    MemoryJobNotification,
    MemoryLifecycleCoordinator,
    MemoryLifecycleWorker,
)
from personal_ai.memory.lifecycle_repositories import (
    InMemoryMemoryLifecycleRepository,
    job_idempotency_id,
)
from personal_ai.settings import Settings
from personal_ai.worker import app as worker_app


def settings(**overrides):
    values = {"ai_provider": "gemini", "ai_model": "synthetic"}
    values.update(overrides)
    return Settings(**values)


def push_body(job_id=None):
    payload = MemoryJobNotification(job_id=job_id or uuid4()).model_dump_json().encode()
    return {"message": {"data": base64.b64encode(payload).decode(), "messageId": "synthetic"}}


def test_lifecycle_push_route_is_absent_from_public_api():
    with TestClient(public_app) as client:
        assert client.post("/tasks/research", json={}).status_code == 404
        assert client.post("/tasks/memory", json={}).status_code == 404


def test_disabled_private_worker_acknowledges_without_decoding_or_constructing_clients(
    monkeypatch,
):
    monkeypatch.setattr("personal_ai.worker.get_settings", lambda: settings())
    monkeypatch.setattr(
        "personal_ai.worker._components",
        lambda _: (_ for _ in ()).throw(AssertionError("disabled worker constructed clients")),
    )
    with TestClient(worker_app) as client:
        response = client.post("/tasks/memory", json={"not": "a Pub/Sub envelope"})
    assert response.status_code == 204


def test_authenticated_push_payload_dispatches_only_durable_job_id(monkeypatch):
    job_id = uuid4()
    settings_value = settings(memory_enabled=True, memory_lifecycle_worker_enabled=True)
    calls = []

    class Republisher:
        def republish_pending(self, *, limit):
            calls.append(("republish", limit))
            return 0

    class Worker:
        def process(self, value):
            calls.append(("process", value))
            return "completed"

    monkeypatch.setattr("personal_ai.worker.get_settings", lambda: settings_value)
    monkeypatch.setattr("personal_ai.worker._components", lambda _: (Worker(), Republisher()))
    with TestClient(worker_app) as client:
        response = client.post("/tasks/memory", json=push_body(job_id))
    assert response.status_code == 204
    assert calls == [("republish", 20), ("process", job_id)]


def test_retryable_worker_result_returns_retry_status_and_invalid_payload_is_acked(monkeypatch):
    settings_value = settings(memory_enabled=True, memory_lifecycle_worker_enabled=True)

    class Republisher:
        def republish_pending(self, *, limit):
            return 0

    class Worker:
        def process(self, _):
            return "retry"

    monkeypatch.setattr("personal_ai.worker.get_settings", lambda: settings_value)
    monkeypatch.setattr("personal_ai.worker._components", lambda _: (Worker(), Republisher()))
    with TestClient(worker_app) as client:
        retry = client.post("/tasks/memory", json=push_body())
        invalid = client.post(
            "/tasks/memory",
            json={"message": {"data": base64.b64encode(b'{"unexpected": true}').decode()}},
        )
    assert retry.status_code == 503
    assert invalid.status_code == 204


def test_job_is_durable_before_publish_and_pending_jobs_can_be_republished():
    now = datetime.now(UTC)
    owner_id, assistant_id, memory_id = "local", uuid4(), uuid4()
    completed = Message(
        id=assistant_id,
        owner_id=owner_id,
        conversation_id=uuid4(),
        role="assistant",
        content="synthetic completed turn",
        status="completed",
        created_at=now,
    )
    settings_value = settings(memory_enabled=True, memory_lifecycle_worker_enabled=True)
    lifecycle = InMemoryMemoryLifecycleRepository(None, None)

    class Publisher:
        fail = True
        calls = 0

        def publish(self, job, *, timeout):
            self.calls += 1
            stored = lifecycle.get_job(owner_id=owner_id, job_id=job.id)
            assert stored.publish_pending is True
            if self.fail:
                raise TimeoutError("synthetic_publish_loss")

    publisher = Publisher()
    coordinator = MemoryLifecycleCoordinator(
        settings_value, lifecycle, None, publisher=publisher
    )
    coordinator._enqueue(completed, "maintenance", (memory_id,))
    pending = lifecycle.pending_for_publish(now=now, limit=10)
    assert len(pending) == 1 and pending[0].candidate_memory_ids == (memory_id,)
    publisher.fail = False
    assert coordinator.republish_pending(limit=10) == 1
    assert publisher.calls == 2
    assert lifecycle.get_job(owner_id=owner_id, job_id=pending[0].id).publish_pending is False


def test_worker_completes_noop_jobs_and_acknowledges_duplicates():
    now = datetime.now(UTC)
    settings_value = settings(memory_enabled=True, memory_lifecycle_worker_enabled=True)
    lifecycle = InMemoryMemoryLifecycleRepository(None, None)
    key = "synthetic-noop-job"
    job = MemoryJob(
        id=job_idempotency_id(key),
        owner_id="local",
        job_type="maintenance",
        candidate_memory_ids=(),
        policy_version="score-v1",
        policy_snapshot={},
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    lifecycle.create_job(job)
    worker = MemoryLifecycleWorker(
        settings_value, lifecycle, None, None, None, clock=lambda: now
    )
    assert worker.process(job.id) == "completed"
    assert lifecycle.get_job(owner_id="local", job_id=job.id).status == "completed"
    assert worker.process(job.id) == "completed"
