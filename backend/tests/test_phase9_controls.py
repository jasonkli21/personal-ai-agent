"""Synthetic Phase 9 privacy, budget, account, and worker controls."""

from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from personal_ai.api.account import account_repository
from personal_ai.api.dependencies import (
    get_conversation_repository,
    get_message_repository,
    get_settings,
)
from personal_ai.auth.account_data import _portable
from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.auth.directory import InMemoryPrincipalDirectory
from personal_ai.auth.middleware import _provider_reservation, _provider_switch_is_on
from personal_ai.auth.safeguards import InMemorySafeguardStore, SafeguardDenied
from personal_ai.main import app
from personal_ai.settings import Settings
from personal_ai.storage.fake import InMemoryConversationRepository, InMemoryMessageRepository
from personal_ai.worker import app as worker_app


def settings(**updates) -> Settings:
    values = {
        "ai_provider": "fake",
        "ai_model": "synthetic",
        "app_environment": "test",
    }
    values.update(updates)
    return Settings(**values)


def owner_principal(issued_at: int | None = None) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        issuer="https://accounts.google.com",
        subject="synthetic-subject",
        owner_id="usr_0123456789abcdef0123456789abcdef",
        email="owner@gmail.com",
        issued_at=issued_at or int(time.time()),
        authenticated=True,
    )


@pytest.fixture
def authenticated_account_client(
    monkeypatch,
) -> Iterator[tuple[TestClient, AuthenticatedPrincipal]]:
    principal = owner_principal()
    configured = settings(
        auth_mode="google_oidc",
        auth_required=True,
        auth_audience="synthetic-client",
        auth_allowed_emails=("owner@gmail.com",),
        export_enabled=True,
        deletion_enabled=True,
    )
    app.dependency_overrides[get_settings] = lambda: configured
    app.state.principal_directory = InMemoryPrincipalDirectory()
    monkeypatch.setattr(
        "personal_ai.auth.middleware.principal_from_google_token",
        lambda token, _: principal if token == "synthetic-id-token" else None,
    )
    try:
        with TestClient(app) as client:
            yield client, principal
    finally:
        app.dependency_overrides.clear()
        app.state.principal_directory = None
        app.state.safeguard_store = None


def test_daily_budget_and_request_limits_fail_closed() -> None:
    store = InMemorySafeguardStore()
    store.consume_request("usr_test", 1)
    with pytest.raises(SafeguardDenied, match="rate_limit_exceeded"):
        store.consume_request("usr_test", 1)

    store.reserve_daily("usr_budget", 1, 12, 1, 12)
    with pytest.raises(SafeguardDenied, match="daily_budget_exceeded"):
        store.reserve_daily("usr_budget", 1, 0, 1, 12)
    with pytest.raises(SafeguardDenied, match="daily_budget_exceeded"):
        store.reserve_daily("usr_budget", 0, 1, 1, 12)


def test_export_encodes_non_finite_numbers_as_portable_values() -> None:
    assert _portable(float("inf")) == {"$type": "float", "value": "inf"}


def test_account_export_and_migration_collections_include_owner_audit_events() -> None:
    from personal_ai.auth.account_data import EXPORT_COLLECTIONS
    from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS

    assert "audit_events" in EXPORT_COLLECTIONS
    assert "audit_events" in OWNER_DATA_COLLECTIONS


def test_iterative_research_uses_the_provider_budget_and_emergency_switch() -> None:
    configured = settings(
        ai_provider="gemini",
        external_providers_kill_switch_enabled=True,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/research/iterative/runs/run-1/resume",
            "raw_path": b"/v1/research/iterative/runs/run-1/resume",
            "query_string": b"",
            "headers": [],
            "server": ("example.test", 443),
            "client": ("test", 1),
            "root_path": "",
        }
    )

    calls, tokens = _provider_reservation(request, configured)

    assert calls > 0 and tokens == configured.iterative_max_tokens
    assert _provider_switch_is_on(request, configured)


def test_middleware_enforces_injected_request_limit_and_keeps_request_id() -> None:
    configured = settings(api_rate_limit_per_minute=1)
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_conversation_repository] = lambda: InMemoryConversationRepository()
    app.dependency_overrides[get_message_repository] = lambda: InMemoryMessageRepository()
    app.state.safeguard_store = InMemorySafeguardStore()
    try:
        with TestClient(app) as client:
            first = client.post("/v1/conversations", json={})
            second = client.post(
                "/v1/conversations",
                json={},
                headers={"X-Request-ID": "synthetic-request"},
            )
    finally:
        app.dependency_overrides.clear()
        app.state.safeguard_store = None

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
    assert second.headers["x-request-id"] == "synthetic-request"


def test_recent_auth_export_is_owner_scoped_and_no_store(
    authenticated_account_client, monkeypatch
) -> None:
    client, principal = authenticated_account_client

    class Repository:
        def export_owner(self, owner_id, *, max_records, max_bytes):
            assert owner_id == principal.owner_id
            assert max_records == 5000 and max_bytes == 8_388_608
            return {
                "schema_version": "personal-ai-export-v1",
                "generated_at": "2026-10-03T00:00:00+00:00",
                "owner_id": owner_id,
                "collections": {"conversations": []},
            }

        def record_export(self, *, owner_id, idempotency_key, correlation_id):
            assert owner_id == principal.owner_id
            assert idempotency_key == key
            assert correlation_id

    key = uuid4()
    app.dependency_overrides[account_repository] = lambda: Repository()
    try:
        response = client.post(
            "/v1/account/export",
            headers={"Authorization": "Bearer synthetic-id-token"},
            json={"idempotency_key": str(key)},
        )
    finally:
        app.dependency_overrides.pop(account_repository, None)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('.json"')
    assert response.json()["owner_id"] == principal.owner_id


def test_account_export_requires_recent_auth(authenticated_account_client, monkeypatch) -> None:
    client, _ = authenticated_account_client
    monkeypatch.setattr(
        "personal_ai.auth.middleware.principal_from_google_token",
        lambda _token, _: owner_principal(int(time.time()) - 3600),
    )

    response = client.post(
        "/v1/account/export",
        headers={"Authorization": "Bearer synthetic-id-token"},
        json={"idempotency_key": str(uuid4())},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "reauthentication_required"


def test_deletion_confirmation_and_cancellation_are_audited_and_idempotent(
    authenticated_account_client,
) -> None:
    client, principal = authenticated_account_client

    class Repository:
        state = None

        def create_deletion(self, *, owner_id, idempotency_key, correlation_id):
            assert owner_id == principal.owner_id and correlation_id
            self.state = {
                "id": str(uuid4()),
                "owner_id": owner_id,
                "request_type": "deletion",
                "state": "pending_confirmation",
                "idempotency_key": str(idempotency_key),
                "confirmed_at": None,
                "irreversible_at": None,
                "completed_at": None,
                "audit_event_ids": ["request-audit"],
            }
            return self.state

        def transition_deletion(self, *, owner_id, request_id, action, correlation_id):
            assert owner_id == principal.owner_id and correlation_id
            if action == "confirm":
                self.state["state"] = "confirmed_pending_operator"
                self.state["confirmed_at"] = "synthetic-time"
            else:
                self.state["state"] = "cancelled"
            return self.state

        def get_deletion(self, *, owner_id, request_id):
            assert owner_id == principal.owner_id
            return self.state

    repository = Repository()
    app.dependency_overrides[account_repository] = lambda: repository
    try:
        headers = {"Authorization": "Bearer synthetic-id-token"}
        created = client.post(
            "/v1/account/deletion", headers=headers, json={"idempotency_key": str(uuid4())}
        )
        request_id = created.json()["id"]
        confirmed = client.post(f"/v1/account/deletion/{request_id}/confirm", headers=headers)
        cancelled = client.post(f"/v1/account/deletion/{request_id}/cancel", headers=headers)
        status = client.get(f"/v1/account/deletion/{request_id}", headers=headers)
    finally:
        app.dependency_overrides.pop(account_repository, None)

    assert created.status_code == 200
    assert confirmed.json()["state"] == "confirmed_pending_operator"
    assert cancelled.json()["state"] == status.json()["state"] == "cancelled"


@pytest.mark.parametrize("route", ["/tasks/memory", "/tasks/maintenance"])
def test_worker_rejects_forged_service_identity(route, monkeypatch) -> None:
    monkeypatch.setattr(
        "personal_ai.worker.get_settings",
        lambda: settings(
            worker_push_auth_required=True,
            worker_push_audience="https://worker.example",
            worker_push_service_account="pubsub@example.iam.gserviceaccount.com",
            worker_maintenance_auth_required=True,
            worker_maintenance_audience="https://worker.example",
            worker_maintenance_service_account="scheduler@example.iam.gserviceaccount.com",
            memory_enabled=True,
            memory_lifecycle_worker_enabled=True,
            maintenance_enabled=True,
        ),
    )
    monkeypatch.setattr(
        "personal_ai.worker.verify_google_service_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            __import__(
                "personal_ai.auth.service_tokens", fromlist=["InvalidServiceToken"]
            ).InvalidServiceToken()
        ),
    )

    with TestClient(worker_app) as client:
        response = client.post(route, headers={"Authorization": "Bearer forged"}, json={})

    assert response.status_code == 401


def test_worker_checks_expected_service_identity_before_its_feature_gate(monkeypatch) -> None:
    configured = settings(
        worker_push_auth_required=True,
        worker_push_audience="https://worker.example",
        worker_push_service_account="pubsub@example.iam.gserviceaccount.com",
    )
    calls = []
    monkeypatch.setattr("personal_ai.worker.get_settings", lambda: configured)
    monkeypatch.setattr(
        "personal_ai.worker.verify_google_service_token",
        lambda token, *, audience, service_account: calls.append(
            (token, audience, service_account)
        ),
    )

    with TestClient(worker_app) as client:
        response = client.post(
            "/tasks/memory",
            headers={"Authorization": "Bearer valid-synthetic-token"},
            json={},
        )

    assert response.status_code == 204
    assert calls == [
        (
            "valid-synthetic-token",
            "https://worker.example",
            "pubsub@example.iam.gserviceaccount.com",
        )
    ]
