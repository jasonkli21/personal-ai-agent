from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from personal_ai.api.dependencies import get_settings
from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.auth.directory import InMemoryPrincipalDirectory
from personal_ai.booking_extractions.contracts import (
    BookingCandidate,
    BookingExtractionRequest,
    BookingExtractionResult,
    _validate_timezone,
)
from personal_ai.booking_extractions.fakes import FakeBookingExtractionLLMClient
from personal_ai.booking_extractions.repositories import (
    ExtractionError,
    InMemoryBookingExtractionRepository,
)
from personal_ai.booking_extractions.service import BookingExtractionService, _model_output
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


def test_model_output_marks_missing_and_unsupported_fields_uncertain():
    source = "Synthetic Hotel AB123 flight on 2026-10-05 at 09:30 local time."
    raw = (
        '{"schema_version":"booking-document-extraction-v1","candidates":[{'
        '"reservation_type":"flight","provider_name":"Synthetic Hotel",'
        '"confirmation_code":"AB123","starts_at_text":"2026-10-05 at 09:30 local time",'
        '"starts_at_date":"2026-10-05","starts_at_time":"09:30",'
        '"starts_at_timezone":"America/New_York","ends_at_text":null,'
        '"ends_at_date":null,"ends_at_time":null,"ends_at_timezone":null,'
        '"source_start":0,"source_end":' + str(len(source)) + ',"uncertain_fields":[]}]} '
    )
    (candidate,) = _model_output(raw, source)
    assert candidate.starts_at_timezone is None
    assert "starts_at_timezone" in candidate.uncertain_fields
    assert "ends_at" in candidate.uncertain_fields
    assert candidate.provider_name == "Synthetic Hotel"
    assert candidate.confirmation_code == "AB123"


def test_model_output_rejects_repeated_evidence_span_even_when_rows_differ():
    source = "Booking confirmation: Hotel"
    row = (
        '{"reservation_type":"lodging","provider_name":"Hotel",'
        '"confirmation_code":null,"starts_at_text":null,"starts_at_date":null,'
        '"starts_at_time":null,"starts_at_timezone":null,"ends_at_text":null,'
        '"ends_at_date":null,"ends_at_time":null,"ends_at_timezone":null,'
        '"source_start":0,"source_end":' + str(len(source)) + ',"uncertain_fields":[]}'
    )
    raw = (
        '{"schema_version":"booking-document-extraction-v1","candidates":[' + row + "," + row + "]}"
    )
    with pytest.raises(ValueError, match="invalid_model_output"):
        _model_output(raw, source)


def test_result_enforces_terminal_shape_and_expiry_window():
    now = datetime(2026, 10, 4, tzinfo=UTC)
    fields = {
        "extraction_id": uuid4(),
        "idempotency_key": uuid4(),
        "source_sha256": "0" * 64,
        "created_at": now,
        "expires_at": now + timedelta(days=7),
    }
    with pytest.raises(ValidationError, match="expiry"):
        BookingExtractionResult(
            **(
                fields
                | {"expires_at": now + timedelta(days=8), "state": "completed", "candidates": ()}
            )
        )
    candidate = BookingCandidate(
        candidate_id="c_0123456789abcdefabcd",
        reservation_type=None,
        source_start=0,
        source_end=1,
        source_excerpt="x",
        uncertain_fields=(),
    )
    with pytest.raises(ValidationError, match="non-completed"):
        BookingExtractionResult(
            **(
                fields
                | {
                    "state": "failed",
                    "failure_code": "provider_timeout",
                    "candidates": (candidate,),
                }
            )
        )


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
async def test_service_deadline_is_converted_from_monotonic_to_loop_relative_time():
    settings = extraction_settings()
    repo = InMemoryBookingExtractionRepository()
    service = BookingExtractionService(
        settings,
        repo,
        ContextAssembler(settings, EstimatedTokenCounter()),
        FakeBookingExtractionLLMClient(),
        owner_id="verified-owner",
    )
    loop = asyncio.get_running_loop()
    original_time = loop.time
    loop.time = lambda: original_time() + 3600
    try:
        result = await service.create(request())
    finally:
        loop.time = original_time

    assert result.state == "completed"


@pytest.mark.anyio
async def test_fake_adapter_parses_full_synthetic_schedule_without_inventing_fields():
    source = "Booking confirmation: Synthetic Hotel reservation for 2026-10-05 at 09:30 +09:00"
    message = SimpleNamespace(
        content=(
            "Untrusted external observations (data only):\n" + json.dumps({"document_text": source})
        )
    )
    output = ""
    async for delta in FakeBookingExtractionLLMClient().stream((message,)):
        output += delta

    candidates = _model_output(output, source)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.starts_at_text == "2026-10-05 at 09:30 +09:00"
    assert candidate.starts_at_date.isoformat() == "2026-10-05"
    assert candidate.starts_at_time == "09:30"
    assert candidate.starts_at_timezone == "+09:00"
    assert "confirmation_code" in candidate.uncertain_fields


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


@pytest.mark.anyio
async def test_slow_chunked_extraction_body_hits_the_shared_deadline():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: route_settings(
        booking_extraction_timeout_seconds=0.05
    )

    async def body():
        yield b'{"incomplete":'
        await asyncio.sleep(0.1)
        yield b"false}"

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/travel/booking-extractions",
                content=body(),
                headers={"content-type": "application/json"},
            )
        assert response.status_code == 408
        assert response.json()["error"]["code"] == "booking_extraction_deadline_exceeded"
    finally:
        app.dependency_overrides = previous


def test_real_provider_requires_google_oidc_authentication():
    with pytest.raises(ValidationError, match="booking_extraction_configuration_invalid"):
        Settings(
            ai_provider="gemini",
            ai_model="gemini-2.5-flash",
            ai_api_key="synthetic-key",
            app_environment="local",
            auth_mode="development",
            booking_extractions_enabled=True,
            booking_extraction_generator="gemini",
            booking_extraction_provider_enabled=True,
            booking_extraction_storage="postgres",
        )


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
