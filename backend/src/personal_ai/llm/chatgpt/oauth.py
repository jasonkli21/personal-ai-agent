"""Documented public-client OAuth/OIDC transport. No API key or billing fallback."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import jwt

from personal_ai.llm.chatgpt.wire import decode_json

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = frozenset(
    {
        "openid",
        "profile",
        "email",
        "offline_access",
        "resource.invoke",
        "chatgpt.tokens.use.direct",
    }
)
REQUIRED_USAGE_SCOPES = frozenset({"resource.invoke", "chatgpt.tokens.use.direct"})
TERMINAL_REFRESH_ERRORS = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)


class OAuthFailure(RuntimeError):
    def __init__(self, code: str, *, uncertain=False):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedTokens:
    issuer: str
    subject: str
    access_token: str
    refresh_token: str | None
    id_token: str
    scopes: tuple[str, ...]
    expires_at: int
    earliest_refresh_at: int


class OpenAIOAuth:
    """Fixed HTTPS authority with bounded bodies and maintained JWT validation."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def _json(self, method, url, *, form=None, authorization=None, rotating=False):
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=5,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept-Encoding": "identity"},
            ) as client:
                headers = {"Authorization": f"Bearer {authorization}"} if authorization else {}
                with client.stream(method, url, data=form, headers=headers) as response:
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise OAuthFailure("oauth_response_invalid", uncertain=rotating)
                    body = bytearray()
                    deadline = time.monotonic() + 5
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline:
                            raise OAuthFailure("oauth_unavailable", uncertain=rotating)
                        body.extend(chunk)
                        if len(body) > 262144:
                            raise OAuthFailure("oauth_response_invalid", uncertain=rotating)
                    if not 200 <= response.status_code < 300:
                        try:
                            data = decode_json(body)
                        except (ValueError, RecursionError, UnicodeError):
                            data = {}
                        error = data.get("error") if isinstance(data, dict) else None
                        if isinstance(error, dict):
                            error = error.get("code")
                        safe = (
                            error
                            if isinstance(error, str)
                            and error
                            in TERMINAL_REFRESH_ERRORS
                            | {
                                "invalid_client",
                                "temporarily_unavailable",
                                "slow_down",
                            }
                            else "oauth_unavailable"
                        )
                        raise OAuthFailure(safe, uncertain=rotating and response.status_code >= 500)
                    try:
                        data = decode_json(body)
                    except (ValueError, RecursionError, UnicodeError):
                        raise OAuthFailure("oauth_response_invalid", uncertain=rotating) from None
                    if not isinstance(data, dict):
                        raise OAuthFailure("oauth_response_invalid", uncertain=rotating)
                    return data
        except httpx.HTTPError:
            raise OAuthFailure("oauth_unavailable", uncertain=rotating) from None

    def discovery(self):
        data = self._json("GET", ISSUER + "/.well-known/openid-configuration")
        expected = {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "/api/accounts/authorize",
            "token_endpoint": ISSUER + "/api/accounts/oauth/token",
            "jwks_uri": ISSUER + "/.well-known/jwks.json",
        }
        if any(data.get(key) != value for key, value in expected.items()):
            raise OAuthFailure("oauth_discovery_invalid")
        for field, required in (
            ("response_types_supported", "code"),
            ("code_challenge_methods_supported", "S256"),
            ("token_endpoint_auth_methods_supported", "none"),
            ("id_token_signing_alg_values_supported", "RS256"),
        ):
            if not isinstance(data.get(field), list) or required not in data[field]:
                raise OAuthFailure("oauth_discovery_invalid")
        revocation = data.get("revocation_endpoint")
        if not isinstance(revocation, str):
            raise OAuthFailure("oauth_discovery_invalid")
        parsed = urlsplit(revocation)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "auth.openai.com"
            or not parsed.path.startswith("/")
            or parsed.query
            or parsed.fragment
        ):
            raise OAuthFailure("oauth_discovery_invalid")
        return data

    def exchange(self, *, client_id, code, verifier, redirect_uri, nonce):
        data = self._json(
            "POST",
            ISSUER + "/api/accounts/oauth/token",
            form={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "resource": RESOURCE,
            },
        )
        return self._validate(data, client_id=client_id, nonce=nonce)

    def refresh(self, *, client_id, refresh_token, previous_id_token, subject, scopes):
        data = self._json(
            "POST",
            ISSUER + "/api/accounts/oauth/token",
            form={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "resource": RESOURCE,
            },
            rotating=True,
        )
        # Refresh may omit an unchanged ID token and granted scope set.
        if "scope" not in data:
            data["scope"] = " ".join(scopes)
        has_new_identity = "id_token" in data
        if not has_new_identity:
            data["id_token"] = previous_id_token
        try:
            return self._validate(
                data,
                client_id=client_id,
                subject=subject,
                retain_expired_id=not has_new_identity,
            )
        except OAuthFailure:
            # Rotation succeeded but validation/persistence cannot safely reuse the old token.
            raise OAuthFailure("oauth_identity_invalid", uncertain=True) from None

    def revoke(self, *, client_id, refresh_token) -> bool:
        endpoint = self.discovery()["revocation_endpoint"]
        try:
            with (
                httpx.Client(
                    transport=self.transport,
                    timeout=5,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    data={
                        "client_id": client_id,
                        "token": refresh_token,
                        "token_type_hint": "refresh_token",
                    },
                ) as response,
            ):
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _claims(self, token, *, audience, keys, require_nonce=False, expired=False):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 32768:
                raise ValueError()
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError()
            matches = [key for key in keys if key.get("kid") == header["kid"]]
            if (
                len(matches) != 1
                or matches[0].get("kty") != "RSA"
                or matches[0].get("use", "sig") != "sig"
                or matches[0].get("alg", "RS256") != "RS256"
            ):
                raise ValueError()
            key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=audience,
                issuer=ISSUER,
                options={
                    "require": ["exp", "iat", "sub", "aud", "iss"]
                    + (["nonce"] if require_nonce else []),
                    "verify_exp": not expired,
                },
            )
            if (
                claims["aud"] != audience
                or any(type(claims[field]) is not int for field in ("iat", "exp"))
                or claims.get("azp", audience) != audience
            ):
                raise ValueError()
            if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 200:
                raise ValueError()
            return claims
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            raise OAuthFailure("oauth_identity_invalid") from None

    def _validate(self, data, *, client_id, nonce=None, subject=None, retain_expired_id=False):
        try:
            self.discovery()
            keys = self._json("GET", ISSUER + "/.well-known/jwks.json")["keys"]
            if not isinstance(keys, list) or len(keys) > 32:
                raise ValueError()
            identity = self._claims(
                data["id_token"],
                audience=client_id,
                keys=keys,
                require_nonce=nonce is not None,
                expired=retain_expired_id,
            )
            if nonce is not None and (
                not isinstance(identity["nonce"], str)
                or not secrets.compare_digest(identity["nonce"], nonce)
            ):
                raise ValueError()
            if subject is not None and identity["sub"] != subject:
                raise ValueError()
            access = self._claims(data["access_token"], audience=RESOURCE, keys=keys)
            if access.get("client_id") != client_id or access["sub"] != identity["sub"]:
                raise ValueError()
            scopes = data["scope"].split()
            if (
                len(scopes) > 32
                or len(set(scopes)) != len(scopes)
                or any(len(scope) > 200 for scope in scopes)
            ):
                raise ValueError()
            if not set(scopes).issubset(set(access.get("scope", "").split())):
                raise ValueError()
            expiry, earliest = data["expires_in"], data.get("earliest_refresh_at", 0)
            if (
                data["token_type"].lower() != "bearer"
                or type(expiry) is not int
                or not 1 <= expiry <= 3600
                or type(earliest) is not int
                or earliest < 0
                or "openid" not in scopes
            ):
                raise ValueError()
            refresh = data.get("refresh_token")
            if "offline_access" in scopes and (
                not isinstance(refresh, str) or not 1 <= len(refresh) <= 32768
            ):
                raise ValueError()
            return VerifiedTokens(
                ISSUER,
                identity["sub"],
                data["access_token"],
                refresh,
                data["id_token"],
                tuple(scopes),
                min(int(time.time()) + expiry, access["exp"]),
                earliest,
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            raise OAuthFailure("oauth_identity_invalid") from None
