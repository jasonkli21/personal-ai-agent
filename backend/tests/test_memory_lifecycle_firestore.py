"""Installed Firestore SDK serialization/transaction boundaries without a network."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from google.cloud.firestore_v1.vector import Vector

from personal_ai.evaluation.memory_lifecycle import NOW, build_fixture, load_fixtures
from personal_ai.memory.lifecycle_policy import make_event
from personal_ai.memory.lifecycle_repositories import FirestoreMemoryLifecycleRepository
from personal_ai.memory.repositories import FirestoreMemoryRepository


def environment(name="repeated-explicit-preference"):
    fixture = next(item for item in load_fixtures() if item["name"] == name)
    env = build_fixture(fixture)
    records = {}
    for memory in env["records"].values():
        records[("memories", str(memory.id))] = memory.model_dump(mode="json")
    for conversation in env["conversations"]._conversations.values():
        records[("conversations", str(conversation.id))] = conversation.model_dump(mode="json")
    for message in env["messages"]._messages.values():
        records[("messages", str(message.id))] = message.model_dump(mode="json")
    client = MagicMock()
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    transaction = client.transaction.return_value
    transaction.id, transaction._write_pbs = b"offline", []
    references = {}

    def collection(name):
        result = MagicMock()

        def document(identifier):
            reference = references.setdefault((name, identifier), MagicMock())
            reference.path = name + "/" + identifier
            reference.get.side_effect = lambda **kw: SimpleNamespace(
                exists=records.get((name, identifier)) is not None,
                to_dict=lambda: records.get((name, identifier)),
            )
            return reference

        result.document.side_effect = document
        return result

    client.collection.side_effect = collection
    memories = FirestoreMemoryRepository(client)
    lifecycle = FirestoreMemoryLifecycleRepository(memories, env["messages"], clock=lambda: NOW)
    return env, lifecycle, records, references, client, transaction


def assert_rpc_bounds(client):
    for method in (client._firestore_api.begin_transaction, client._firestore_api.commit):
        assert method.call_args.kwargs["retry"] is None
        assert 0 < method.call_args.kwargs["timeout"] <= 5


def test_event_and_projection_commit_atomically_with_source_and_ancestor_reads():
    env, lifecycle, records, refs, client, transaction = environment()
    memory = env["records"]["a"]
    event = make_event(
        owner_id="local",
        memory_id=memory.id,
        event_type="retrieved",
        reason_code="injected",
        policy_version="score-v1",
        idempotency_key="mocked-event",
        expected_state_version=0,
        occurred_at=NOW,
    )
    outcome = lifecycle.apply_event(event, completed_assistant_id=env["completed"].id)
    assert outcome.status == "applied"
    assert transaction.create.call_count == transaction.set.call_count == 1
    assert_rpc_bounds(client)
    for reference in refs.values():
        for call in reference.get.call_args_list:
            assert call.kwargs["retry"] is None and 0 < call.kwargs["timeout"] <= 5
    assert (
        refs[("messages", str(memory.source_message_ids[0]))].get.call_args.kwargs["transaction"]
        is transaction
    )
    transaction.create.reset_mock()
    transaction.set.reset_mock()
    records[("conversations", str(memory.source_conversation_id))]["context_preparation_id"] = (
        "changing"
    )
    assert lifecycle.apply_event(event).reason == "source_inactive"
    transaction.create.assert_not_called()
    transaction.set.assert_not_called()


def test_consolidation_commits_all_sources_events_reverse_links_and_operation_together():
    env, lifecycle, records, _refs, client, transaction = environment()
    ids = tuple(record.id for record in env["records"].values())
    env["coordinator"]._enqueue(env["completed"], "consolidation", ids)
    job = next(iter(env["lifecycle"].jobs.values()))
    claimed = env["lifecycle"].claim_job(owner_id="local", job_id=job.id, now=NOW, lease_seconds=60)
    records[("memory_lifecycle_jobs", str(job.id))] = claimed.model_dump(mode="json")
    plan = env["worker"].consolidator.plan(
        owner_id="local",
        source_ids=job.candidate_memory_ids,
        job=claimed,
        settings=env["settings"],
        memories=env["memories"],
        messages=env["messages"],
        lifecycle=env["lifecycle"],
        embedder=env["embedder"],
        now=NOW,
        timeout=5,
    )
    assert plan.derived is not None
    assert (
        lifecycle.commit_consolidation(
            job=claimed, token=claimed.lease_token, derived=plan.derived, now=NOW
        )
        == "applied"
    )
    assert transaction.create.call_count == 6  # derived, two events, two links, operation
    assert transaction.set.call_count == 2
    derived_data = transaction.create.call_args_list[0].args[1]
    assert isinstance(derived_data["embedding"], Vector)
    assert derived_data["schema_version"] == 2
    assert_rpc_bounds(client)
    transaction.create.reset_mock()
    transaction.set.reset_mock()
    records[("messages", str(env["records"]["b"].source_message_ids[0]))]["status"] = "superseded"
    assert (
        lifecycle.commit_consolidation(
            job=claimed, token=claimed.lease_token, derived=plan.derived, now=NOW
        )
        == "source_inactive"
    )
    transaction.create.assert_not_called()
    transaction.set.assert_not_called()
