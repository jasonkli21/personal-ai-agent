"""Verification for Google-signed service identity tokens used by private workers."""

from __future__ import annotations

from google.auth.exceptions import TransportError
from google.oauth2 import id_token

from personal_ai.auth.google_transport import signing_key_request


class InvalidServiceToken(ValueError):
    """The caller is not the configured service identity."""


class ServiceTokenVerificationUnavailable(RuntimeError):
    """Google signing certificates could not be checked."""


def verify_google_service_token(token: str, *, audience: str, service_account: str) -> None:
    if not token or len(token) > 8192 or any(char.isspace() for char in token):
        raise InvalidServiceToken
    try:
        with signing_key_request() as request:
            claims = id_token.verify_oauth2_token(token, request, audience=audience)
    except TransportError as error:
        raise ServiceTokenVerificationUnavailable from error
    except Exception as error:
        raise InvalidServiceToken from error
    if (
        not isinstance(claims, dict)
        or claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
        or claims.get("email") != service_account
        or claims.get("email_verified") is not True
    ):
        raise InvalidServiceToken
