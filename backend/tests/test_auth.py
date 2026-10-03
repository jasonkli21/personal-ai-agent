"""Authentication, stable owner mapping, and safe failure behavior."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from personal_ai.api.dependencies import (
    get_conversation_repository,
    get_message_repository,
    get_settings,
)
from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.auth.directory import InMemoryPrincipalDirectory
from personal_ai.auth.verification import (
    IdentityProviderUnavailable,
    InvalidIdentityToken,
    principal_from_google_token,
)
from personal_ai.main import app
from personal_ai.settings import Settings
from personal_ai.storage.fake import InMemoryConversationRepository, InMemoryMessageRepository


def oidc_settings(**updates) -> Settings:
    return Settings(
        ai_provider="fake",
        ai_model="fake-model",
        app_environment="test",
        auth_mode="google_oidc",
        auth_required=True,
        auth_issuer="https://accounts.google.com",
        auth_audience="personal-ai-web-client",
        auth_allowed_emails=("owner@gmail.com",),
        research_enabled=False,
        **updates,
    )


@pytest.fixture
def oidc_client() -> Iterator[tuple[TestClient, InMemoryPrincipalDirectory]]:
    directory = InMemoryPrincipalDirectory()
    app.dependency_overrides[get_settings] = oidc_settings
    app.state.principal_directory = directory
    with TestClient(app) as client:
        yield client, directory
    app.dependency_overrides.clear()
    app.state.principal_directory = None


def test_google_token_uses_verified_subject_and_exact_audience(monkeypatch) -> None:
    calls: list[str] = []

    def verify(token, request, audience):
        del request
        calls.append(audience)
        assert token == "signed-id-token"
        return {
            "iss": "https://accounts.google.com",
            "sub": "stable-google-subject",
            "aud": audience,
            "email": "owner@gmail.com",
            "email_verified": True,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }

    monkeypatch.setattr("personal_ai.auth.verification.id_token.verify_oauth2_token", verify)
    settings = oidc_settings()

    first = principal_from_google_token("signed-id-token", settings)
    second = principal_from_google_token("signed-id-token", settings)

    assert first == second
    assert first.owner_id.startswith("usr_")
    assert first.owner_id != first.email
    assert first.subject == "stable-google-subject"
    assert calls == ["personal-ai-web-client"]


@pytest.mark.parametrize(
    "claim_update",
    [
        {"iss": "https://attacker.example"},
        {"sub": ""},
        {"email": "another@example.com"},
        {"email_verified": False},
        {"exp": 1791000000},
    ],
)
def test_google_token_rejects_invalid_or_unapproved_claims(monkeypatch, claim_update) -> None:
    claims = {
        "iss": "https://accounts.google.com",
        "sub": "stable-google-subject",
        "email": "owner@gmail.com",
        "email_verified": True,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    claims.update(claim_update)
    monkeypatch.setattr(
        "personal_ai.auth.verification.id_token.verify_oauth2_token",
        lambda token, request, audience: claims,
    )

    with pytest.raises(InvalidIdentityToken):
        token_name = "bad-token-" + "-".join(claim_update.keys())
        principal_from_google_token(token_name, oidc_settings())


def test_google_token_is_not_accepted_in_development_mode(monkeypatch) -> None:
    settings = Settings(ai_provider="fake", ai_model="fake-model")
    with pytest.raises(InvalidIdentityToken):
        principal_from_google_token("signed-id-token", settings)


def test_workspace_identity_requires_matching_verified_hosted_domain(monkeypatch) -> None:
    claims = {
        "iss": "https://accounts.google.com",
        "sub": "workspace-subject",
        "email": "owner@example.com",
        "email_verified": True,
        "hd": "example.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    monkeypatch.setattr(
        "personal_ai.auth.verification.id_token.verify_oauth2_token",
        lambda _token, _request, audience: {**claims, "aud": audience},
    )
    settings = Settings(
        ai_provider="fake",
        ai_model="test",
        app_environment="test",
        auth_mode="google_oidc",
        auth_required=True,
        auth_audience="personal-ai-web-client",
        auth_allowed_emails=("owner@example.com",),
        auth_hosted_domain="example.com",
    )

    assert principal_from_google_token("workspace-token", settings).email == "owner@example.com"
    claims["hd"] = "attacker.example"
    with pytest.raises(InvalidIdentityToken):
        principal_from_google_token("workspace-token-wrong-domain", settings)


def test_protected_routes_reject_missing_and_invalid_tokens(oidc_client, monkeypatch) -> None:
    client, _ = oidc_client
    path = "/v1/research/00000000-0000-4000-8000-000000000000"
    missing = client.get(path)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authentication_required"

    monkeypatch.setattr(
        "personal_ai.auth.middleware.principal_from_google_token",
        lambda token, settings: (_ for _ in ()).throw(InvalidIdentityToken()),
    )
    invalid = client.get(path, headers={"Authorization": "Bearer invalid"})
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_identity"


def test_protected_routes_fail_closed_when_identity_provider_is_unavailable(
    oidc_client, monkeypatch
) -> None:
    client, _ = oidc_client
    monkeypatch.setattr(
        "personal_ai.auth.middleware.principal_from_google_token",
        lambda token, settings: (_ for _ in ()).throw(IdentityProviderUnavailable()),
    )

    response = client.get(
        "/v1/research/00000000-0000-4000-8000-000000000000",
        headers={"Authorization": "Bearer signed"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


def test_identity_mapping_is_created_idempotently_and_can_be_revoked(
    oidc_client, monkeypatch
) -> None:
    client, directory = oidc_client
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository()
    app.dependency_overrides[get_conversation_repository] = lambda: conversations
    app.dependency_overrides[get_message_repository] = lambda: messages
    principal = AuthenticatedPrincipal(
        issuer="https://accounts.google.com",
        subject="subject-1",
        owner_id="usr_owner-one",
        email="owner@example.com",
        issued_at=int(time.time()),
        authenticated=True,
    )
    monkeypatch.setattr(
        "personal_ai.auth.middleware.principal_from_google_token",
        lambda token, settings: principal,
    )
    headers = {"Authorization": "Bearer signed"}

    first = client.post("/v1/conversations", headers=headers, json={})
    second = client.post("/v1/conversations", headers=headers, json={})

    assert first.status_code == second.status_code == 201
    assert first.json()["owner_id"] == second.json()["owner_id"] == principal.owner_id
    directory.deactivate(principal.owner_id)
    revoked = client.post("/v1/conversations", headers=headers, json={})
    assert revoked.status_code == 403
    assert revoked.json()["error"]["code"] == "access_denied"


def test_cors_uses_an_exact_origin_allowlist() -> None:
    settings = Settings(
        ai_provider="fake",
        ai_model="fake-model",
        allowed_origins=("https://personal.example",),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            allowed = client.options(
                "/v1/conversations",
                headers={
                    "Origin": "https://personal.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
            denied = client.options(
                "/v1/conversations",
                headers={
                    "Origin": "https://attacker.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert allowed.status_code == 204
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://personal.example"
    assert denied.status_code == 403
