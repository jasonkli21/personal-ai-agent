"""Phase 20 deterministic lifecycle, disclosure, budget and export regressions."""

import gzip
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from personal_ai.artifacts.consumers import (
    retain_debug_replay,
    retain_evaluation,
    retain_routing_trace,
)
from personal_ai.artifacts.contracts import (
    MAX_RAW_BYTES,
    ArtifactBudgetExceeded,
    ArtifactConflict,
    ArtifactRef,
    ArtifactUnavailable,
)
from personal_ai.artifacts.gcs import PrivateGCSArtifactStore
from personal_ai.artifacts.local import InMemoryArtifactMetadataRepository, InMemoryArtifactStore
from personal_ai.artifacts.service import ArtifactService, decode, encode
from personal_ai.auth.scope import ApplicationScope
from personal_ai.settings import Settings

SCOPE = ApplicationScope()
NOW = datetime(2026, 10, 8, tzinfo=UTC)


@pytest.fixture
def tier():
    clock = [NOW]
    repo = InMemoryArtifactMetadataRepository(clock=lambda: clock[0])
    store = InMemoryArtifactStore()
    service = ArtifactService(repo, store, clock=lambda: clock[0])
    return service, repo, store, clock


def write(service, value=None, **kwargs):
    options = {
        "owner_id": "owner",
        "scope": SCOPE,
        "kind": "evaluation",
        "identity": "run-1",
        "schema_version": "test-v1",
        "required": True,
    }
    options.update(kwargs)
    return service.write(value or {"score": 1}, **options)


def test_roundtrip_scope_generation_hash_and_jsonl(tier):
    service, repo, store, _ = tier
    rows = [{"case_id": "a", "score": 1}, {"case_id": "b", "score": 0}]
    ref = write(service, rows, jsonl=True)
    assert ref.status == "ready" and ref.generation == "1"
    assert service.read(ref.artifact_id, owner_id="owner", scope=SCOPE) == rows
    assert gzip.decompress(store.objects[ref.key][1]).count(b"\n") == 2
    assert len(ref.model_dump_json().encode()) < 8192
    assert "case_id" not in ref.model_dump_json()
    for owner, scope in (
        ("other", SCOPE),
        ("owner", ApplicationScope(application_id="travel")),
        ("owner", ApplicationScope(workspace_id="x")),
    ):
        with pytest.raises(ArtifactUnavailable):
            service.read(ref.artifact_id, owner_id=owner, scope=scope)
    assert repo.observations()["dynamodb"]["artifact_body_bytes"] == 0


def test_scope_key_and_ready_reference_are_validated(tier):
    ref = write(tier[0])
    for changes in (
        {"owner_id": "other"},
        {"key": "arbitrary"},
        {"generation": None},
        {"expires_at": NOW + timedelta(days=91)},
        {"created_at": NOW.replace(tzinfo=None)},
    ):
        with pytest.raises(ValueError):
            ArtifactRef.model_validate({**ref.model_dump(), **changes})


def test_idempotency_does_not_extend_expiry_or_overwrite_body(tier):
    service, repo, store, clock = tier
    ref = write(service)
    clock[0] += timedelta(hours=1)
    assert write(service) == ref
    assert len(store.objects) == 1
    with pytest.raises(ArtifactUnavailable):
        write(service, {"score": 2})
    assert repo.records[ref.artifact_id] == ref


def test_atomic_budget_across_threads_and_day_reset(tier):
    _, repo, _, clock = tier
    repo.max_operations = 4

    def reserve(_):
        try:
            repo.reserve(operations=1, byte_count=2)
            return True
        except ArtifactBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(reserve, range(20))) == 4
    assert repo.operations == 4 and repo.bytes_reserved == 8
    clock[0] += timedelta(days=1)
    repo.reserve(operations=1, byte_count=2)
    assert repo.operations == 1


def test_byte_and_object_stock_guards_before_upload(tier):
    service, repo, store, _ = tier
    repo.max_live_bytes = 1
    assert write(service, required=False) is None
    assert not store.objects and not repo.records
    repo.max_live_bytes = 1024
    repo.max_objects = 1
    write(service)
    assert write(service, identity="run-2", required=False) is None
    assert len(store.objects) == 1


def test_optional_failure_is_advisory_required_failure_explicit(tier, monkeypatch):
    service, repo, store, _ = tier

    def unavailable(*args, **kwargs):
        raise OSError("transient")

    monkeypatch.setattr(store, "put", unavailable)
    assert write(service, required=False) is None
    with pytest.raises(ArtifactUnavailable, match="required_artifact_not_ready"):
        write(service)
    assert next(iter(repo.records.values())).status == "pending"


def test_upload_before_metadata_crash_reconciles_same_generation(tier, monkeypatch):
    service, repo, store, _ = tier
    real_update = repo.update
    monkeypatch.setattr(repo, "update", lambda *a, **k: (_ for _ in ()).throw(OSError("crash")))
    assert write(service, required=False) is None
    assert len(store.objects) == 1
    monkeypatch.setattr(repo, "update", real_update)
    assert service.reconcile()["ready"] == 1
    assert write(service).generation == "1"


def test_crash_before_upload_marks_missing_then_expires(tier, monkeypatch):
    service, repo, store, clock = tier
    monkeypatch.setattr(store, "put", lambda *a: (_ for _ in ()).throw(OSError("crash")))
    write(service, required=False)
    assert service.reconcile()["missing"] == 0
    clock[0] += timedelta(minutes=11)
    assert service.reconcile()["missing"] == 1
    clock[0] += timedelta(days=8)
    assert service.reconcile()["deleted"] == 1
    assert next(iter(repo.records.values())).status == "deleted"


def test_missing_and_corrupt_body_never_return_success(tier):
    service, repo, store, _ = tier
    ref = write(service)
    store.objects[ref.key] = (ref.generation, b"corrupt")
    with pytest.raises(ArtifactUnavailable):
        service.read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    assert repo.records[ref.artifact_id].status == "missing"
    assert service.reconcile()["deleted"] == 1
    assert not store.objects


def test_generation_precondition_prevents_deleting_replacement(tier):
    service, repo, store, _ = tier
    ref = write(service)
    store.objects[ref.key] = ("99", b"replacement")
    with pytest.raises(ArtifactConflict):
        service.delete(ref)
    assert store.objects[ref.key][0] == "99"
    assert repo.records[ref.artifact_id].status == "deleting"


def test_delete_crash_after_body_removal_is_idempotently_recovered(tier, monkeypatch):
    service, repo, store, _ = tier
    ref = write(service)
    update = repo.update

    def fail_deleted(ref, **kwargs):
        if ref.status == "deleted":
            raise OSError("crash")
        return update(ref, **kwargs)

    monkeypatch.setattr(repo, "update", fail_deleted)
    with pytest.raises(OSError):
        service.delete(ref)
    assert not store.objects and repo.records[ref.artifact_id].status == "deleting"
    monkeypatch.setattr(repo, "update", update)
    assert service.reconcile()["deleted"] == 1
    assert service.delete(ref).status == "deleted"


def test_expiry_denies_before_delayed_physical_cleanup(tier):
    service, _, store, clock = tier
    ref = write(service, retention_days=1)
    clock[0] += timedelta(days=1)
    with pytest.raises(ArtifactUnavailable):
        service.read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    assert store.objects
    assert service.reconcile()["deleted"] == 1
    assert not store.objects


def test_owner_fence_denies_reads_writes_and_cleans_all_scopes(tier):
    service, repo, store, _ = tier
    ref = write(service)
    write(service, scope=ApplicationScope(application_id="travel"), identity="run-2")
    repo.fence("owner")
    with pytest.raises(ArtifactUnavailable):
        service.read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    assert write(service, identity="run-3", required=False) is None
    assert service.reconcile(owner_id="owner")["deleted"] == 2
    assert not store.objects


def test_revocation_during_upload_denies_ready_publication(tier, monkeypatch):
    service, repo, store, _ = tier
    put = store.put

    def fenced(key, body):
        generation = put(key, body)
        repo.fence("owner")
        return generation

    monkeypatch.setattr(store, "put", fenced)
    assert write(service, required=False) is None
    assert next(iter(repo.records.values())).status == "pending"
    service.reconcile()
    assert not store.objects


def test_grant_dependencies_fail_closed_and_recheck(tier):
    service, _, store, _ = tier
    assert write(service, grant_dependencies=("grant-v1",), required=False) is None
    allowed = [True]
    service.authorize = lambda ref: allowed[0]
    ref = write(service, grant_dependencies=("grant-v1",))
    allowed[0] = False
    with pytest.raises(ArtifactUnavailable):
        service.read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    service.reconcile()
    assert not store.objects


@pytest.mark.parametrize(
    "scope,sensitivity",
    [
        (SCOPE, "sensitive"),
        (SCOPE, "restricted"),
        (ApplicationScope(application_id="health"), "public"),
        (ApplicationScope(application_id="finance"), "public"),
    ],
)
def test_sensitive_verbose_retention_disabled(tier, scope, sensitivity):
    assert write(tier[0], scope=scope, sensitivity=sensitivity, required=False) is None
    assert not tier[2].objects


def test_observations_reject_raw_prompts_embeddings_and_routing_overflow(tier):
    service = tier[0]
    for value in (
        {"prompt": "secret"},
        {"nested": [{"embeddings": [1, 2]}]},
        {"candidates": [{}] * 33},
    ):
        assert (
            retain_routing_trace(
                service, value, owner_id="owner", scope=SCOPE, routing_decision_id=uuid4()
            )
            is None
        )
    assert not tier[2].objects


def test_source_rights_gate_and_expiry(tier):
    service, _, store, clock = tier
    expiry = NOW + timedelta(hours=1)
    assert (
        retain_debug_replay(
            service,
            [{"score": 1}],
            owner_id="owner",
            scope=SCOPE,
            run_id=uuid4(),
            source_rights_until=expiry,
        )
        is None
    )
    ref = retain_debug_replay(
        service,
        [{"score": 1}],
        owner_id="owner",
        scope=SCOPE,
        run_id=uuid4(),
        source_rights_until=expiry,
        source_rights_verified=True,
    )
    assert ref.expires_at == expiry
    clock[0] = expiry
    service.reconcile()
    assert not store.objects


def test_shared_consumers_correlate_and_batch_events(tier):
    service, _, store, _ = tier
    run = uuid4()
    evaluation = retain_evaluation(
        service, [{"score": 1}] * 100, owner_id="owner", scope=SCOPE, evaluation_run_id=run
    )
    assert evaluation.evaluation_run_id == run
    decision = uuid4()
    trace = retain_routing_trace(
        service,
        {"candidates": [{"endpoint_id": "x"}]},
        owner_id="owner",
        scope=SCOPE,
        routing_decision_id=decision,
    )
    assert trace.routing_decision_id == decision and len(store.objects) == 2
    assert evaluation.uncompressed_bytes > evaluation.compressed_bytes


def test_export_freezes_exact_generations_and_fails_missing(tier):
    service, _, store, _ = tier
    source = write(service)
    snapshot = {
        "collections": {
            "artifact_metadata": [
                {"document_id": str(source.artifact_id), "data": source.model_dump(mode="json")}
            ]
        },
        "snapshot_coverage": {"consistency": "declared"},
    }
    ref = service.freeze_export(
        snapshot,
        owner_id="owner",
        scope=SCOPE,
        identity="export-1",
        max_records=10,
        max_bytes=100000,
    )
    body = service.read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    assert body["artifact_manifest"][0]["generation"] == source.generation
    assert body["artifact_bodies"][0]["body"] == {"score": 1}
    del store.objects[source.key]
    with pytest.raises(ArtifactUnavailable):
        service.freeze_export(
            snapshot,
            owner_id="owner",
            scope=SCOPE,
            identity="export-2",
            max_records=10,
            max_bytes=100000,
        )


def test_export_oversize_is_explicit_not_partial(tier):
    with pytest.raises(ArtifactUnavailable):
        tier[0].freeze_export(
            {"collections": {}},
            owner_id="owner",
            scope=SCOPE,
            identity="export",
            max_records=10,
            max_bytes=1,
        )
    assert not tier[2].objects


def test_compression_ceilings_and_hash_validation(tier):
    with pytest.raises(ArtifactUnavailable):
        encode({"value": "x" * (MAX_RAW_BYTES + 1)})
    ref = write(tier[0])
    raw, body = encode({"score": 2})
    with pytest.raises(ArtifactUnavailable):
        decode(ref, body)
    assert raw


def test_cas_and_immutable_metadata(tier):
    service, repo, _, _ = tier
    ref = write(service)
    with pytest.raises(ArtifactConflict):
        repo.update(ref.model_copy(update={"status": "missing"}), expected_revision=1)
    with pytest.raises(ArtifactConflict):
        repo.update(
            ref.model_copy(update={"sha256": "0" * 64, "status": "missing"}),
            expected_revision=ref.revision,
        )


def test_gcs_requires_private_preflight_and_generation_requests(tier):
    ref = write(tier[0])
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/b/test-artifacts"):
            return httpx.Response(
                200,
                json={
                    "location": "US-CENTRAL1",
                    "storageClass": "STANDARD",
                    "softDeletePolicy": {"retentionDurationSeconds": "0"},
                    "iamConfiguration": {
                        "publicAccessPrevention": "enforced",
                        "uniformBucketLevelAccess": {"enabled": True},
                    },
                },
            )
        if request.method == "POST":
            assert request.url.params["ifGenerationMatch"] == "0"
            return httpx.Response(200, json={"generation": "42"})
        if request.method == "DELETE":
            assert request.url.params["generation"] == "42"
            assert request.url.params["ifGenerationMatch"] == "42"
            return httpx.Response(204)
        assert request.url.params["generation"] == "42"
        return httpx.Response(200, content=b"body")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ArtifactUnavailable):
        PrivateGCSArtifactStore("test-artifacts", region="us-central1")
    store = PrivateGCSArtifactStore(
        "test-artifacts",
        region="us-central1",
        preflight_verified=True,
        client=client,
        token=lambda: "test-token",
    )
    with pytest.raises(ArtifactUnavailable):
        store.put(ref.key, b"body")
    store.verify_private_bucket()
    assert store.put(ref.key, b"body") == "42"
    assert store.read(ref.key, "42", max_bytes=4) == b"body"
    store.delete(ref.key, "42")
    assert all("predefinedAcl" not in r.url.params for r in requests)
    assert all(r.url.host == "storage.googleapis.com" for r in requests)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"versioning": {"enabled": True}},
        {"softDeletePolicy": {"retentionDurationSeconds": "604800"}},
        {"location": "EU"},
        {"storageClass": "NEARLINE"},
        {"retentionPolicy": {"retentionPeriod": "1"}},
        {"iamConfiguration": {"publicAccessPrevention": "inherited"}},
    ],
)
def test_gcs_denies_unsafe_bucket_policies(unsafe):
    facts = {
        "location": "US-CENTRAL1",
        "storageClass": "STANDARD",
        "softDeletePolicy": {"retentionDurationSeconds": "0"},
        "iamConfiguration": {
            "publicAccessPrevention": "enforced",
            "uniformBucketLevelAccess": {"enabled": True},
        },
    }
    facts.update(unsafe)
    store = PrivateGCSArtifactStore(
        "test-artifacts",
        region="us-central1",
        preflight_verified=True,
        token=lambda: "token",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=facts))
        ),
    )
    with pytest.raises(ArtifactUnavailable):
        store.verify_private_bucket()


def test_gcs_duplicate_upload_validates_existing_generation(tier):
    ref = write(tier[0])

    def handler(req):
        if req.method == "POST":
            return httpx.Response(412)
        if req.url.params.get("alt") == "media":
            return httpx.Response(200, content=b"body")
        return httpx.Response(200, json={"generation": "7"})

    store = PrivateGCSArtifactStore(
        "test-artifacts",
        region="us-central1",
        preflight_verified=True,
        token=lambda: "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store.verified = True
    assert store.put(ref.key, b"body") == "7"
    with pytest.raises(ArtifactConflict):
        store.put(ref.key, b"xxxx")


def test_settings_keep_cloud_disabled_and_require_attestation():
    base = {"_env_file": None, "ai_provider": "fake", "ai_model": "fake"}
    assert not Settings(**base).artifacts_enabled
    with pytest.raises(ValueError):
        Settings(**base, artifacts_enabled=True, artifact_store="gcs")
    with pytest.raises(ValueError):
        Settings(**base, artifact_max_operations_per_day=1001)


def test_monthly_operation_and_body_transfer_guards(tier):
    _, repo, _, clock = tier
    for _ in range(4):
        repo.reserve(operations=1000, byte_count=0)
        clock[0] += timedelta(days=1)
    with pytest.raises(ArtifactBudgetExceeded, match="monthly"):
        repo.reserve(operations=1, byte_count=0)
    clock[0] = datetime(2026, 11, 1, tzinfo=UTC)
    for _ in range(4):
        repo.reserve(operations=1, byte_count=0, read_bytes=16777216)
        clock[0] += timedelta(days=1)
    with pytest.raises(ArtifactBudgetExceeded, match="monthly"):
        repo.reserve(operations=1, byte_count=0, read_bytes=1)


def test_reconciliation_rotates_batches_without_starvation(tier):
    service, _, store, clock = tier
    first = write(service)
    second = write(service, identity="run-2", retention_days=1)
    assert service.reconcile(limit=1)["checked"] == 1
    clock[0] += timedelta(days=1)
    service.reconcile(limit=1)
    assert second.key not in store.objects
    assert first.key in store.objects


def test_export_retry_returns_same_frozen_snapshot(tier):
    service = tier[0]
    old = {"collections": {}, "snapshot_coverage": {"snapshot_id": "old"}}
    ref = service.freeze_export(
        old, owner_id="owner", scope=SCOPE, identity="export-1", max_records=10, max_bytes=10000
    )
    newer = {"collections": {}, "snapshot_coverage": {"snapshot_id": "new"}}
    retry = service.freeze_export(
        newer, owner_id="owner", scope=SCOPE, identity="export-1", max_records=10, max_bytes=10000
    )
    assert retry == ref
    assert service.read(ref.artifact_id, owner_id="owner", scope=SCOPE)["snapshot"] == old


def test_export_propagates_dependency_and_expiry(tier):
    service, _, _, clock = tier
    allowed = [True]
    service.authorize = lambda ref: allowed[0]
    source = write(
        service,
        grant_dependencies=("grant-v1",),
        source_rights_until=NOW + timedelta(hours=1),
        source_rights_verified=True,
    )
    snapshot = {
        "collections": {
            "artifact_metadata": [
                {"document_id": str(source.artifact_id), "data": source.model_dump(mode="json")}
            ]
        }
    }
    export = service.freeze_export(
        snapshot, owner_id="owner", scope=SCOPE, identity="export", max_records=10, max_bytes=100000
    )
    assert export.grant_dependencies == source.grant_dependencies
    assert export.expires_at == source.expires_at
    allowed[0] = False
    with pytest.raises(ArtifactUnavailable):
        service.read(export.artifact_id, owner_id="owner", scope=SCOPE)
    clock[0] += timedelta(hours=1)
    assert service.reconcile()["deleted"] == 2


def test_actual_trace_retention_uses_captured_manifest_and_failure_is_optional(tier):
    from personal_ai.artifacts.consumers import ArtifactContextTraceRepository
    from personal_ai.context.builder import ContextBuildManifest
    from personal_ai.context.traces import ContextTraceManifest, InMemoryContextTraceRepository

    manifest = ContextBuildManifest(
        counter_kind="estimated",
        counter_version="fake-v1",
        global_input_tokens=400,
        actual_input_tokens=17,
        effective_sensitivity="personal",
    )
    trace = ContextTraceManifest.from_build(
        manifest,
        request_id="actual-request",
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        scope=SCOPE,
        recorded_at=NOW,
    )
    compact = InMemoryContextTraceRepository()
    wrapper = ArtifactContextTraceRepository(compact, lambda: tier[0])
    wrapper._retain("owner", trace)
    ref = next(iter(tier[1].records.values()))
    body = tier[0].read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    assert body["actual_build"] is True and body["actual_input_tokens"] == 17
    bad = ArtifactContextTraceRepository(compact, lambda: (_ for _ in ()).throw(OSError("failure")))
    bad._retain("owner", trace)  # no inference failure


def test_artifact_api_is_scoped_private_and_default_off(tier, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from personal_ai.api.dependencies import get_request_scope
    from personal_ai.auth.scope import RequestScope
    from personal_ai.main import app
    from personal_ai.settings import get_settings

    ref = write(tier[0])
    scope = [RequestScope(owner_id="owner", request_id="request")]
    enabled = [False]
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.update(
        {
            get_settings: lambda: Settings(
                ai_provider="fake", ai_model="fake", artifacts_enabled=enabled[0]
            ),
            get_request_scope: lambda: scope[0],
        }
    )
    monkeypatch.setattr(
        "personal_ai.api.artifacts.persistence_factory",
        lambda settings: SimpleNamespace(artifact_service=lambda settings: tier[0]),
    )
    try:
        client = TestClient(app)
        assert client.get(f"/v1/artifacts/{ref.artifact_id}").status_code == 404
        enabled[0] = True
        response = client.get(f"/v1/artifacts/{ref.artifact_id}")
        assert response.status_code == 200 and response.json() == {"score": 1}
        assert response.headers["cache-control"] == "no-store"
        scope[0] = RequestScope(owner_id="other", request_id="request")
        assert client.get(f"/v1/artifacts/{ref.artifact_id}").status_code == 404
    finally:
        app.dependency_overrides = previous


def test_racing_upload_after_delete_is_reclaimed_from_tombstone(tier, monkeypatch):
    service, repo, store, _ = tier
    original_put, original_delete = store.put, store.delete

    def race(key, body):
        pending = next(iter(repo.records.values()))
        service.delete(pending)  # object not yet visible; reference becomes a tombstone
        generation = original_put(key, body)
        monkeypatch.setattr(store, "delete", lambda *a: (_ for _ in ()).throw(OSError("offline")))
        return generation

    monkeypatch.setattr(store, "put", race)
    assert write(service, required=False) is None
    assert next(iter(repo.records.values())).status == "deleted"
    assert store.objects
    monkeypatch.setattr(store, "delete", original_delete)
    assert service.reconcile()["failed"] == 0
    assert not store.objects


def test_provider_fence_denies_before_profile_reservation_or_send():
    from contextlib import contextmanager
    from types import SimpleNamespace

    from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
    from personal_ai.usage.contracts import UsageAdmissionDenied

    calls = []

    class Connection:
        def execute(self, query, params=None):
            calls.append(query)
            return SimpleNamespace(
                fetchone=lambda: (1,) if "artifact_owner_fences" in query else None
            )

    class Database:
        @contextmanager
        def transaction(self):
            yield Connection()

    invocation = SimpleNamespace(owner_id="owner", endpoint=SimpleNamespace())
    attempt = SimpleNamespace(started_at=NOW)
    with pytest.raises(UsageAdmissionDenied, match="provider_owner_deletion_fenced"):
        PostgresProviderUsageAccounting(Database()).reserve_attempt(
            invocation, attempt, max_attempts=1
        )
    assert len(calls) == 2
    assert all("provider_attempts" not in query for query in calls)


def test_fenced_memory_job_never_claims_or_dispatches():
    from types import SimpleNamespace

    from personal_ai.memory.lifecycle_jobs import MemoryLifecycleWorker

    settings = Settings(
        ai_provider="fake",
        ai_model="fake",
        memory_enabled=True,
        memory_lifecycle_worker_enabled=True,
    )
    lifecycle = SimpleNamespace(
        get_job_by_id=lambda **k: SimpleNamespace(owner_id="owner"),
        claim_job=lambda **k: (_ for _ in ()).throw(AssertionError("fenced job claimed")),
    )
    worker = MemoryLifecycleWorker(
        settings, lifecycle, None, None, None, owner_active=lambda _: False
    )
    assert worker.process(uuid4()) == "disabled"


def test_required_export_storage_failure_does_not_record_success(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from personal_ai.api.account import export_account

    configured = Settings(
        ai_provider="fake", ai_model="fake", export_enabled=True, artifacts_enabled=True
    )
    repository = SimpleNamespace(
        export_owner=lambda *a, **k: {"collections": {}},
        record_export=lambda **k: (_ for _ in ()).throw(AssertionError("failed export recorded")),
    )
    monkeypatch.setattr(
        "personal_ai.api.account.persistence_factory",
        lambda settings: SimpleNamespace(
            artifact_service=lambda settings: (_ for _ in ()).throw(OSError("offline"))
        ),
    )
    with pytest.raises(HTTPException) as caught:
        export_account(
            SimpleNamespace(idempotency_key=uuid4()),
            SimpleNamespace(state=SimpleNamespace(correlation_id="request")),
            SimpleNamespace(owner_id="owner"),
            configured,
            repository,
        )
    assert caught.value.status_code == 503
    assert caught.value.detail == "export_artifact_unavailable"


def test_account_export_returns_ready_frozen_envelope(tier, monkeypatch):
    import json
    from types import SimpleNamespace

    from personal_ai.api.account import export_account

    configured = Settings(
        ai_provider="fake", ai_model="fake", export_enabled=True, artifacts_enabled=True
    )
    snapshots = ["original", "newer"]
    records = []
    repository = SimpleNamespace(
        export_owner=lambda *a, **k: {
            "collections": {},
            "snapshot_coverage": {"id": snapshots.pop(0)},
        },
        record_export=lambda **k: records.append(k),
    )
    monkeypatch.setattr(
        "personal_ai.api.account.persistence_factory",
        lambda settings: SimpleNamespace(artifact_service=lambda settings: tier[0]),
    )
    payload = SimpleNamespace(idempotency_key=uuid4())
    request = SimpleNamespace(state=SimpleNamespace(correlation_id="request"))
    principal = SimpleNamespace(owner_id="owner")
    first = export_account(payload, request, principal, configured, repository)
    second = export_account(payload, request, principal, configured, repository)
    assert json.loads(first.body) == json.loads(second.body)
    assert json.loads(first.body)["snapshot"]["snapshot_coverage"]["id"] == "original"
    assert json.loads(first.body)["schema_version"] == "account-artifact-export-v1"
    assert len(records) == 2


def test_store_change_cannot_read_delete_or_forget_old_body(tier):
    service, repo, store, _ = tier
    ref = write(service)
    different = InMemoryArtifactStore()
    different.store_id = "gcs:other-artifacts"
    alternate = ArtifactService(repo, different, clock=lambda: NOW)
    with pytest.raises(ArtifactUnavailable, match="store_identity_mismatch"):
        alternate.read(ref.artifact_id, owner_id="owner", scope=SCOPE)
    with pytest.raises(ArtifactUnavailable, match="store_identity_mismatch"):
        alternate.delete(ref)
    assert alternate.reconcile()["failed"] == 1
    assert repo.records[ref.artifact_id].status == "ready"
    assert ref.key in store.objects
