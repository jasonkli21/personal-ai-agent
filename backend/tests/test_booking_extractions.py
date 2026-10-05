from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from personal_ai.api.dependencies import get_settings
from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.auth.directory import InMemoryPrincipalDirectory
from personal_ai.booking_extractions.contracts import (
    BookingExtractionRequest,
    BookingExtractionResult,
    _validate_timezone,
)
from personal_ai.booking_extractions.fakes import FakeBookingExtractionLLMClient
from personal_ai.booking_extractions.repositories import (
    ExtractionError,
    FirestoreBookingExtractionRepository,
    InMemoryBookingExtractionRepository,
)
from personal_ai.booking_extractions.service import BookingExtractionService
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.main import app
from personal_ai.settings import Settings
from personal_ai.storage.errors import ResourceNotFoundError


def request(
    text: str = "Booking confirmation: synthetic hotel reservation",
) -> BookingExtractionRequest:
    return BookingExtractionRequest(
        idempotency_key=uuid4(),
        source_sha256=sha256(text.encode()).hexdigest(),
        media_type="text/plain",
        consent="submit_for_booking_extraction",
        synthetic_fixture=True,
        document_text=text,
    )


def extraction_settings() -> Settings:
    return Settings(
        ai_provider="fake",
        ai_model="fake",
        booking_extractions_enabled=True,
        booking_extraction_storage="memory",
    )


def route_settings(**updates) -> Settings:
    values = {
        "_env_file": None,
        "ai_provider": "fake",
        "ai_model": "synthetic",
        "app_environment": "test",
        "booking_extractions_enabled": True,
        "booking_extraction_storage": "memory",
        "booking_extraction_generator": "fake",
    }
    values.update(updates)
    return Settings(**values)


def test_request_is_hash_bound_strict_and_bounded():
    text = "synthetic booking"
    with pytest.raises(ValidationError):
        BookingExtractionRequest(
            idempotency_key=uuid4(),
            source_sha256="0" * 64,
            media_type="text/plain",
            consent="submit_for_booking_extraction",
            document_text=text,
        )
    with pytest.raises(ValidationError):
        BookingExtractionRequest(
            idempotency_key=uuid4(),
            source_sha256=sha256(text.encode()).hexdigest(),
            media_type="text/plain",
            consent="submit_for_booking_extraction",
            document_text=text,
            owner_id="browser-controlled",
        )


def test_timezone_offset_is_a_real_iana_offset():
    _validate_timezone("+14:00")
    _validate_timezone("-09:30")
    with pytest.raises(ValueError, match="unknown timezone"):
        _validate_timezone("+14:01")


@pytest.mark.anyio
async def test_service_replays_validated_candidate_and_delete_tombstone():
    settings = extraction_settings()
    repo = InMemoryBookingExtractionRepository()
    llm = FakeBookingExtractionLLMClient()
    service = BookingExtractionService(
        settings,
        repo,
        ContextAssembler(settings, EstimatedTokenCounter()),
        llm,
        owner_id="verified-owner",
    )
    submitted = request()
    result = await service.create(submitted)
    assert result.state == "completed"
    assert len(result.candidates) == 1
    assert result.candidates[0].source_excerpt.startswith("Booking")
    assert "synthetic hotel" in result.candidates[0].source_excerpt
    replay = await service.create(submitted)
    assert replay == result
    assert len(llm.requests) == 1

    deleted = service.delete(result.extraction_id)
    assert deleted.state == "deleted"
    assert service.detail_by_key(submitted.idempotency_key).state == "deleted"
    changed_text = "other source"
    changed = submitted.model_copy(
        update={
            "document_text": changed_text,
            "source_sha256": sha256(changed_text.encode()).hexdigest(),
        }
    )
    with pytest.raises(ExtractionError, match="idempotency_conflict"):
        await service.create(changed)


@pytest.mark.anyio
async def test_service_rejects_bad_spans_without_exposing_model_output():
    text = "Booking confirmation: synthetic hotel reservation"
    malformed = (
        '{"schema_version":"booking-document-extraction-v1","candidates":['
        '{"reservation_type":"lodging","provider_name":"Synthetic Hotel",'
        '"confirmation_code":null,"starts_at_text":null,"starts_at_timezone":null,'
        '"starts_at_date":null,"starts_at_time":null,"ends_at_text":null,'
        '"ends_at_date":null,"ends_at_time":null,"ends_at_timezone":null,'
        '"source_start":0,"source_end":999,'
        '"uncertain_fields":[]}]} '
    )
    settings = extraction_settings()
    service = BookingExtractionService(
        settings,
        InMemoryBookingExtractionRepository(),
        ContextAssembler(settings, EstimatedTokenCounter()),
        FakeBookingExtractionLLMClient(malformed),
        owner_id="verified-owner",
    )
    result = await service.create(request(text))
    assert result.state == "failed"
    assert result.failure_code == "invalid_model_output"
    assert result.candidates == ()


@pytest.mark.anyio
async def test_expiry_cleanup_removes_candidates_and_keeps_idempotency_tombstone():
    settings = extraction_settings()
    repo = InMemoryBookingExtractionRepository()
    now = datetime(2026, 10, 4, tzinfo=UTC)
    service = BookingExtractionService(
        settings,
        repo,
        ContextAssembler(settings, EstimatedTokenCounter()),
        FakeBookingExtractionLLMClient(),
        owner_id="verified-owner",
        clock=lambda: now,
    )
    submitted = request()
    result = await service.create(submitted)
    cleaned = repo.purge_expired(now + timedelta(days=8), limit=10)
    assert cleaned == 1
    record = repo.get_by_key("verified-owner", submitted.idempotency_key)
    assert record.result is not None
    assert record.result.state == "expired"
    assert record.result.candidates == ()
    assert record.request_fingerprint == submitted.fingerprint()
    assert result.state == "completed"


def test_repository_fences_concurrent_duplicate_and_owner_scopes_detail():
    repo = InMemoryBookingExtractionRepository()
    submitted = request()
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 10, 4, tzinfo=UTC)
    first, created = repo.begin(
        owner_id="owner-a",
        key=submitted.idempotency_key,
        fingerprint=submitted.fingerprint(),
        source_sha256=submitted.source_sha256,
        now=start,
        execution_deadline=start + timedelta(seconds=30),
    )
    replay, replay_created = repo.begin(
        owner_id="owner-a",
        key=submitted.idempotency_key,
        fingerprint=submitted.fingerprint(),
        source_sha256=submitted.source_sha256,
        now=start,
        execution_deadline=start + timedelta(seconds=30),
    )
    assert created and not replay_created and first.extraction_id == replay.extraction_id
    deleted = repo.delete("owner-a", first.extraction_id)
    assert deleted.state == "deleted" and deleted.result is not None
    blocked, was_created = repo.begin(
        owner_id="owner-a",
        key=submitted.idempotency_key,
        fingerprint=submitted.fingerprint(),
        source_sha256=submitted.source_sha256,
        now=start,
        execution_deadline=start + timedelta(seconds=30),
    )
    assert not was_created and blocked.state == "deleted"
    with pytest.raises(ResourceNotFoundError):
        repo.get("owner-b", first.extraction_id)


def test_delete_by_key_before_post_creates_owner_scoped_fencing_tombstone():
    repo = InMemoryBookingExtractionRepository()
    submitted = request()
    now = datetime(2026, 10, 4, tzinfo=UTC)
    deleted = repo.delete_by_key("owner-a", submitted.idempotency_key, submitted.source_sha256, now)
    assert deleted.state == "deleted"
    result, created = repo.begin(
        owner_id="owner-a",
        key=submitted.idempotency_key,
        fingerprint=submitted.fingerprint(),
        source_sha256=submitted.source_sha256,
        now=now,
        execution_deadline=now + timedelta(seconds=30),
    )
    assert not created and result.state == "deleted"
    with pytest.raises(ExtractionError, match="idempotency_conflict"):
        repo.delete_by_key("owner-a", submitted.idempotency_key, "0" * 64, now)
    with pytest.raises(ResourceNotFoundError):
        repo.get("owner-b", deleted.extraction_id)


def test_firestore_retention_uses_native_timestamps_and_preserves_tombstone():
    records = {}
    refs = {}
    collections = {}
    client = MagicMock()
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    transaction = client.transaction.return_value
    transaction.id, transaction._write_pbs = b"offline", []

    def collection(name):
        result = collections.setdefault(name, MagicMock())

        def document(identifier):
            key = (name, identifier)
            ref = refs.setdefault(key, MagicMock())
            ref.get.side_effect = lambda **kwargs: SimpleNamespace(
                exists=key in records,
                to_dict=lambda: records[key],
            )
            return ref

        result.document.side_effect = document
        return result

    def write(ref, value):
        key = next(key for key, candidate in refs.items() if candidate is ref)
        records[key] = value

    transaction.set.side_effect = write
    client.collection.side_effect = collection
    repo = FirestoreBookingExtractionRepository(client)
    submitted = request()
    now = datetime(2026, 10, 4, tzinfo=UTC)
    record, created = repo.begin(
        owner_id="verified-owner",
        key=submitted.idempotency_key,
        fingerprint=submitted.fingerprint(),
        source_sha256=submitted.source_sha256,
        now=now,
        execution_deadline=now + timedelta(seconds=30),
    )
    assert created
    stored = records[("booking_document_extractions", str(record.extraction_id))]
    assert isinstance(stored["created_at"], datetime)
    assert isinstance(stored["execution_deadline"], datetime)
    assert isinstance(stored["expires_at"], datetime)

    terminal = BookingExtractionResult(
        extraction_id=record.extraction_id,
        idempotency_key=record.idempotency_key,
        source_sha256=record.source_sha256,
        state="completed",
        candidates=(),
        created_at=record.created_at,
        expires_at=record.expires_at,
    )
    repo.complete(record, terminal)
    snapshot = SimpleNamespace(
        id=str(record.extraction_id),
        to_dict=lambda: records[("booking_document_extractions", str(record.extraction_id))],
    )
    query = collections["booking_document_extractions"].where.return_value
    query.where.return_value.limit.return_value.stream.return_value = [snapshot]
    expired_at = now + timedelta(days=8)
    assert repo.purge_expired(expired_at, limit=10) == 1
    expired = repo.get("verified-owner", record.extraction_id)
    assert expired.state == "expired"
    assert expired.result is not None and expired.result.candidates == ()
    assert expired.request_fingerprint == submitted.fingerprint()
    assert query.where.call_args.args == ("expires_at", "<=", expired_at)


def test_fake_http_route_reopens_same_owner_result_and_delete_tombstone():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: route_settings()
    submitted = request()
    payload = submitted.model_dump(mode="json")
    try:
        with TestClient(app) as client:
            response = client.post("/v1/travel/booking-extractions", json=payload)
            result = response.json()
            detail = client.get(f"/v1/travel/booking-extractions/{result['extraction_id']}")
            by_key = client.get(
                "/v1/travel/booking-extractions/by-key/" + str(submitted.idempotency_key)
            )
            deleted = client.delete(f"/v1/travel/booking-extractions/{result['extraction_id']}")
            deleted_replay = client.get(
                "/v1/travel/booking-extractions/by-key/" + str(submitted.idempotency_key)
            )
        assert response.status_code == 201
        assert detail.json() == result == by_key.json()
        assert deleted.json()["state"] == "deleted"
        assert deleted_replay.json()["state"] == "deleted"
        assert deleted_replay.json()["candidates"] == []
    finally:
        app.dependency_overrides = previous


def test_fake_http_delete_by_key_fences_a_late_post():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: route_settings()
    submitted = request()
    try:
        with TestClient(app) as client:
            deleted = client.request(
                "DELETE",
                "/v1/travel/booking-extractions/by-key/" + str(submitted.idempotency_key),
                json={"source_sha256": submitted.source_sha256},
            )
            late_post = client.post(
                "/v1/travel/booking-extractions", json=submitted.model_dump(mode="json")
            )
        assert deleted.status_code == 200
        assert late_post.status_code == 201
        assert deleted.json()["state"] == late_post.json()["state"] == "deleted"
        assert late_post.json()["candidates"] == []
    finally:
        app.dependency_overrides = previous


def test_booking_extraction_http_requires_verified_owner(monkeypatch):
    previous = app.dependency_overrides.copy()
    principal = AuthenticatedPrincipal(
        issuer="https://accounts.google.com",
        subject="synthetic-subject",
        owner_id="usr_synthetic-owner",
        email="owner@gmail.com",
        issued_at=int(time()),
        authenticated=True,
    )
    configured = route_settings(
        auth_mode="google_oidc",
        auth_required=True,
        auth_audience="synthetic-client",
        auth_allowed_emails=("owner@gmail.com",),
    )
    app.dependency_overrides[get_settings] = lambda: configured
    app.state.principal_directory = InMemoryPrincipalDirectory()
    monkeypatch.setattr(
        "personal_ai.auth.middleware.principal_from_google_token",
        lambda token, settings: principal,
    )
    submitted = request()
    try:
        with TestClient(app) as client:
            anonymous = client.post(
                "/v1/travel/booking-extractions", json=submitted.model_dump(mode="json")
            )
            authenticated = client.post(
                "/v1/travel/booking-extractions",
                headers={"Authorization": "Bearer synthetic-token"},
                json=submitted.model_dump(mode="json"),
            )
        assert anonymous.status_code == 401
        assert authenticated.status_code == 201
    finally:
        app.dependency_overrides = previous
        app.state.principal_directory = None


def test_disabled_route_and_fake_private_input_fail_closed():
    previous = app.dependency_overrides.copy()
    submitted = request()
    payload = submitted.model_dump(mode="json")
    try:
        app.dependency_overrides[get_settings] = lambda: route_settings(
            booking_extractions_enabled=False
        )
        with TestClient(app) as client:
            disabled = client.post("/v1/travel/booking-extractions", json=payload)
        assert disabled.status_code == 404

        app.dependency_overrides[get_settings] = lambda: route_settings()
        payload["synthetic_fixture"] = False
        with TestClient(app) as client:
            private = client.post("/v1/travel/booking-extractions", json=payload)
        assert private.status_code == 404
    finally:
        app.dependency_overrides = previous


def test_booking_extraction_http_rejects_body_over_limit_before_parsing():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: route_settings()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/travel/booking-extractions",
                content=b" " * 1_300_001,
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_body_too_large"
    finally:
        app.dependency_overrides = previous
