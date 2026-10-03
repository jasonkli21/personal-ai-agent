"""Google OIDC ID-token validation and stable owner mapping."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any

from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.settings import Settings

MAX_TOKEN_LENGTH = 8192
TOKEN_CACHE_SIZE = 256
TOKEN_CACHE_MARGIN_SECONDS = 60
_cache_lock = threading.Lock()
_verified_tokens: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()


class InvalidIdentityToken(ValueError):
    """The supplied token is not a valid, correctly scoped Google ID token."""


class IdentityProviderUnavailable(RuntimeError):
    """Google's verification keys could not be checked within the request bound."""


class _BoundedGoogleAuthRequest(GoogleAuthRequest):
    """Cap certificate fetches so an identity check cannot hang a request."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=3, **kwargs):
        return super().__call__(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=min(timeout or 3, 3),
            **kwargs,
        )


def _verified_claims(token: str, audience: str) -> dict[str, Any]:
    token_fingerprint = hashlib.sha256(f"{audience}\0{token}".encode()).hexdigest()
    now = int(time.time())
    with _cache_lock:
        cached = _verified_tokens.get(token_fingerprint)
        if cached and now < cached[0] - TOKEN_CACHE_MARGIN_SECONDS:
            _verified_tokens.move_to_end(token_fingerprint)
            return cached[1]
        _verified_tokens.pop(token_fingerprint, None)

    try:
        claims = id_token.verify_oauth2_token(
            token,
            _BoundedGoogleAuthRequest(),
            audience=audience,
        )
    except TransportError as error:
        raise IdentityProviderUnavailable from error
    except (ValueError, TypeError, KeyError) as error:
        raise InvalidIdentityToken from error
    except Exception as error:
        raise IdentityProviderUnavailable from error

    if not isinstance(claims, dict):
        raise InvalidIdentityToken
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)) or expiry <= now + TOKEN_CACHE_MARGIN_SECONDS:
        raise InvalidIdentityToken
    with _cache_lock:
        _verified_tokens[token_fingerprint] = (int(expiry), claims)
        _verified_tokens.move_to_end(token_fingerprint)
        while len(_verified_tokens) > TOKEN_CACHE_SIZE:
            _verified_tokens.popitem(last=False)
    return claims


def principal_from_google_token(token: str, settings: Settings) -> AuthenticatedPrincipal:
    """Validate a Google ID token and map its stable subject to an opaque owner."""
    if not token or len(token) > MAX_TOKEN_LENGTH or any(char.isspace() for char in token):
        raise InvalidIdentityToken
    if settings.auth_mode != "google_oidc" or not settings.auth_required:
        raise InvalidIdentityToken

    claims = _verified_claims(token, settings.auth_audience)
    issuer = claims.get("iss")
    canonical_issuer = "https://accounts.google.com"
    if issuer not in {"accounts.google.com", canonical_issuer}:
        raise InvalidIdentityToken
    if settings.auth_issuer == "accounts.google.com" and issuer != "accounts.google.com":
        raise InvalidIdentityToken
    if settings.auth_issuer == canonical_issuer and issuer != canonical_issuer:
        raise InvalidIdentityToken

    subject = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    issued_at = claims.get("iat")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or email.strip().lower() not in settings.auth_allowed_emails
        or email_verified is not True
        or not isinstance(issued_at, (int, float))
    ):
        raise InvalidIdentityToken
    email_domain = email.strip().lower().rsplit("@", 1)[-1]
    if email_domain != "gmail.com":
        if not settings.auth_hosted_domain or claims.get("hd") != settings.auth_hosted_domain:
            raise InvalidIdentityToken
        if email_domain != settings.auth_hosted_domain:
            raise InvalidIdentityToken
    if issued_at > now_with_skew():
        raise InvalidIdentityToken

    owner_digest = hashlib.sha256(f"{canonical_issuer}\0{subject}".encode()).hexdigest()
    return AuthenticatedPrincipal(
        issuer=canonical_issuer,
        subject=subject,
        owner_id=f"usr_{owner_digest[:32]}",
        email=email.strip().lower(),
        issued_at=int(issued_at),
        authenticated=True,
    )


def now_with_skew() -> int:
    """Allow a small clock skew while rejecting future-issued credentials."""
    return int(time.time()) + 60
