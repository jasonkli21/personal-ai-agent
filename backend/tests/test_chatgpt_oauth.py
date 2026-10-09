"""Synthetic signed OAuth fixtures; no committed tokens, keys, or network calls."""

import json
import time
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from personal_ai.llm.chatgpt.oauth import (
    ISSUER,
    RESOURCE,
    SCOPES,
    OAuthFailure,
    OpenAIOAuth,
)


class OAuthFixture:
    def __init__(self):
        self.private = generate_private_key(public_exponent=65537, key_size=2048)
        self.client_id = "oaiapp_synthetic"
        self.nonce = "synthetic-one-time-nonce"
        self.subject = "synthetic-subject"
        self.requests = []
        self.id_overrides = {}
        self.access_overrides = {}
        self.token_overrides = {}
        self.status = 200
        self.error_body = {}
        self.jwks = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key()))
        self.jwks.update({"kid": "synthetic-key", "alg": "RS256", "use": "sig"})
        self.oauth = OpenAIOAuth(transport=httpx.MockTransport(self.handle))

    def sign(self, values):
        return jwt.encode(values, self.private, algorithm="RS256", headers={"kid": "synthetic-key"})

    def tokens(self):
        now = int(time.time())
        identity = {
            "iss": ISSUER,
            "aud": self.client_id,
            "sub": self.subject,
            "iat": now,
            "exp": now + 3600,
            "nonce": self.nonce,
        }
        identity.update(self.id_overrides)
        access = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": self.subject,
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
            "client_id": self.client_id,
            "scope": " ".join(sorted(SCOPES)),
        }
        access.update(self.access_overrides)
        result = {
            "access_token": self.sign(access),
            "id_token": self.sign(identity),
            "refresh_token": "synthetic-rotating-refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            "earliest_refresh_at": now,
            "scope": " ".join(sorted(SCOPES)),
        }
        result.update(self.token_overrides)
        return result

    def handle(self, request):
        self.requests.append(request)
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/api/accounts/authorize",
                    "token_endpoint": ISSUER + "/api/accounts/oauth/token",
                    "jwks_uri": ISSUER + "/.well-known/jwks.json",
                    "revocation_endpoint": ISSUER + "/api/accounts/oauth/revoke",
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [self.jwks]})
        if request.url.path == "/api/accounts/oauth/token":
            return httpx.Response(
                self.status, json=self.tokens() if self.status == 200 else self.error_body
            )
        if request.url.path == "/api/accounts/oauth/revoke":
            return httpx.Response(self.status)
        raise AssertionError("unexpected provider route")

    def exchange(self):
        return self.oauth.exchange(
            client_id=self.client_id,
            code="synthetic-code",
            verifier="v" * 64,
            redirect_uri="http://127.0.0.1:54321/auth/callback",
            nonce=self.nonce,
        )


def test_signed_identity_and_granted_scope_validation_and_exact_public_client_form():
    fixture = OAuthFixture()
    tokens = fixture.exchange()
    assert tokens.issuer == ISSUER and tokens.subject == fixture.subject
    assert set(tokens.scopes) == SCOPES
    request = next(r for r in fixture.requests if r.method == "POST")
    values = parse_qs(request.content.decode())
    assert values == {
        "grant_type": ["authorization_code"],
        "client_id": [fixture.client_id],
        "code": ["synthetic-code"],
        "code_verifier": ["v" * 64],
        "redirect_uri": ["http://127.0.0.1:54321/auth/callback"],
        "resource": [RESOURCE],
    }
    assert "synthetic-code" not in str(request.url)
    assert "synthetic-rotating-refresh" not in repr(tokens)


@pytest.mark.parametrize(
    "field,value",
    [
        ("nonce", "foreign"),
        ("iss", "https://foreign.example"),
        ("aud", "other-client"),
        ("exp", 1),
        ("iat", int(time.time()) + 86400),
        ("sub", ""),
    ],
)
def test_id_token_mismatch_rejected_without_disclosing_token(field, value):
    fixture = OAuthFixture()
    fixture.id_overrides[field] = value
    with pytest.raises(OAuthFailure, match="oauth_identity_invalid") as captured:
        fixture.exchange()
    assert captured.value.__suppress_context__


@pytest.mark.parametrize(
    "field,value",
    [
        ("client_id", "other-client"),
        ("aud", "foreign-resource"),
        ("sub", "other-account"),
        ("scope", "openid"),
        ("iss", "https://foreign.example"),
        ("exp", 1),
    ],
)
def test_access_token_identity_resource_client_scope_are_not_unverified_claims(field, value):
    fixture = OAuthFixture()
    fixture.access_overrides[field] = value
    with pytest.raises(OAuthFailure):
        fixture.exchange()


def test_invalid_signature_or_unknown_signing_key_is_not_accepted():
    fixture = OAuthFixture()
    attacker = generate_private_key(public_exponent=65537, key_size=2048)
    fixture.token_overrides["id_token"] = jwt.encode(
        {"iss": ISSUER},
        attacker,
        algorithm="RS256",
        headers={"kid": "synthetic-key"},
    )
    with pytest.raises(OAuthFailure):
        fixture.exchange()
    fixture.token_overrides["id_token"] = jwt.encode(
        {"iss": ISSUER},
        fixture.private,
        algorithm="RS256",
        headers={"kid": "unknown"},
    )
    with pytest.raises(OAuthFailure):
        fixture.exchange()


def test_identity_permission_does_not_invent_plan_scope():
    fixture = OAuthFixture()
    fixture.token_overrides["scope"] = "openid profile email"
    fixture.access_overrides["scope"] = "openid profile email"
    tokens = fixture.exchange()
    assert "chatgpt.tokens.use.direct" not in tokens.scopes


def test_refresh_omits_scope_and_uses_registration_and_replaces_rotating_token():
    fixture = OAuthFixture()
    previous = fixture.exchange()
    fixture.token_overrides["refresh_token"] = "synthetic-replacement"
    refreshed = fixture.oauth.refresh(
        client_id=fixture.client_id,
        refresh_token=previous.refresh_token,
        previous_id_token=previous.id_token,
        subject=previous.subject,
        scopes=previous.scopes,
    )
    assert refreshed.refresh_token == "synthetic-replacement"
    values = parse_qs([r for r in fixture.requests if r.method == "POST"][-1].content.decode())
    assert set(values) == {"grant_type", "client_id", "refresh_token", "resource"}
    assert values["grant_type"] == ["refresh_token"]
    assert fixture.oauth.revoke(client_id=fixture.client_id, refresh_token=refreshed.refresh_token)


@pytest.mark.parametrize(
    "error,uncertain",
    [
        ("invalid_grant", False),
        ("invalid_refresh_token", False),
        ("refresh_token_reused", False),
        ("invalid_client", False),
        ("unexpected-private-data", False),
    ],
)
def test_refresh_error_codes_are_bounded_and_safe(error, uncertain):
    fixture = OAuthFixture()
    previous = fixture.exchange()
    fixture.status, fixture.error_body = 400, {"error": error, "detail": "sensitive-response-text"}
    with pytest.raises(OAuthFailure) as captured:
        fixture.oauth.refresh(
            client_id=fixture.client_id,
            refresh_token=previous.refresh_token,
            previous_id_token=previous.id_token,
            subject=previous.subject,
            scopes=previous.scopes,
        )
    assert captured.value.uncertain is uncertain
    assert "sensitive-response-text" not in str(captured.value)
    assert "unexpected-private-data" not in str(captured.value)


def test_discovery_cannot_redirect_credentials_to_different_authority():
    fixture = OAuthFixture()
    original = fixture.handle

    def malicious(request):
        result = original(request)
        if request.url.path == "/.well-known/openid-configuration":
            data = result.json()
            data["revocation_endpoint"] = "https://foreign.example/revoke"
            return httpx.Response(200, json=data)
        return result

    fixture.oauth = OpenAIOAuth(transport=httpx.MockTransport(malicious))
    with pytest.raises(OAuthFailure, match="oauth_discovery_invalid"):
        fixture.exchange()


@pytest.mark.parametrize(
    "field",
    [
        "response_types_supported",
        "code_challenge_methods_supported",
        "token_endpoint_auth_methods_supported",
        "id_token_signing_alg_values_supported",
    ],
)
def test_public_client_pkce_and_signing_capabilities_must_be_declared(field):
    fixture = OAuthFixture()
    original = fixture.handle

    def changed(request):
        result = original(request)
        if request.url.path == "/.well-known/openid-configuration":
            data = result.json()
            data[field] = []
            return httpx.Response(200, json=data)
        return result

    fixture.oauth = OpenAIOAuth(transport=httpx.MockTransport(changed))
    with pytest.raises(OAuthFailure, match="oauth_discovery_invalid"):
        fixture.exchange()
