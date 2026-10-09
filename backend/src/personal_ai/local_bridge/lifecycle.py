"""Local registration and renewable-session ownership. No browser/cloud secrets."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

from personal_ai.llm.chatgpt.oauth import (
    ISSUER,
    REQUIRED_USAGE_SCOPES,
    RESOURCE,
    SCOPES,
    TERMINAL_REFRESH_ERRORS,
    OAuthFailure,
    OpenAIOAuth,
)
from personal_ai.local_bridge.store import Credentials, ProtectedLocalStore, Registration


@dataclass(frozen=True, slots=True)
class SafeConnection:
    connection_id: str
    state: str
    plan_permission: bool
    revision: int
    remote_revocation: str = "unknown"


@dataclass(frozen=True, slots=True, repr=False)
class SignInAttempt:
    attempt_id: str
    state: str
    nonce: str
    verifier: str
    redirect_uri: str
    expires_at: int
    connection_id: str
    client_id: str | None
    revision: int


@dataclass(frozen=True, slots=True, repr=False)
class CredentialSnapshot:
    connection_id: str
    revision: int
    client_id: str
    subject: str
    access_token: str
    protected_values: tuple[str, ...]


class CredentialLifecycle:
    def __init__(self, store: ProtectedLocalStore, oauth: OpenAIOAuth, *, clock=time.time):
        self.store, self.oauth, self.clock = store, oauth, clock
        self._attempts = {}
        self._attempt_lock = threading.Lock()

    def connections(self) -> tuple[SafeConnection, ...]:
        with self.store.transaction() as tx:
            return tuple(self._safe(r) for r in tx.state.registrations.values())

    @staticmethod
    def _safe(registration):
        return SafeConnection(
            registration.connection_id,
            registration.state,
            registration.credentials is not None
            and REQUIRED_USAGE_SCOPES.issubset(registration.credentials.scopes),
            registration.revision,
            registration.remote_revocation,
        )

    def begin(self, redirect_uri: str, *, connection_id: str | None = None):
        """Local controller only; the authorization URL must never be an IPC response."""
        parsed = urlsplit(redirect_uri)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.path != "/auth/callback"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or not parsed.port
        ):
            raise OAuthFailure("oauth_callback_invalid")
        self.oauth.discovery()
        with self.store.transaction() as tx:
            selected = tx.state.registrations.get(connection_id) if connection_id else None
            if connection_id and selected is None:
                raise OAuthFailure("oauth_registration_missing")
            if selected is None and len(tx.state.registrations) >= 32:
                raise OAuthFailure("oauth_registration_capacity")
            connection_id = connection_id or str(uuid4())
            client_id = selected.client_id if selected else None
            attempt = SignInAttempt(
                str(uuid4()),
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(64),
                redirect_uri,
                int(self.clock()) + 180,
                connection_id,
                client_id,
                selected.revision if selected else 0,
            )
            query = {
                "client_id": client_id or "dynamic_agent_client",
                "ext_agent_host_id": tx.state.host_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": " ".join(sorted(SCOPES)),
                "resource": RESOURCE,
                "state": attempt.state,
                "nonce": attempt.nonce,
                "code_challenge_method": "S256",
                "code_challenge": base64.urlsafe_b64encode(
                    hashlib.sha256(attempt.verifier.encode()).digest()
                )
                .decode()
                .rstrip("="),
            }
            # ID-token hints are optional. Omit them to keep ID tokens out of
            # system-browser authorization URLs/history; validate the selected
            # account after the ordinary account selector instead.
            if not client_id:
                query["agent_name_hint"] = "Personal AI Local Bridge"
        with self._attempt_lock:
            self._attempts = {
                k: v for k, v in self._attempts.items() if v.expires_at > self.clock()
            }
            if len(self._attempts) >= 8 or any(
                value.connection_id == connection_id for value in self._attempts.values()
            ):
                raise OAuthFailure("oauth_attempt_busy")
            self._attempts[attempt.attempt_id] = attempt
        return attempt.attempt_id, ISSUER + "/api/accounts/authorize?" + urlencode(query)

    def cancel(self, attempt_id):
        with self._attempt_lock:
            self._attempts.pop(attempt_id, None)

    def complete(self, attempt_id: str, callback: dict[str, str]) -> SafeConnection:
        with self._attempt_lock:
            attempt = self._attempts.pop(attempt_id, None)
        if (
            attempt is None
            or self.clock() >= attempt.expires_at
            or not isinstance(callback.get("state"), str)
            or not secrets.compare_digest(callback["state"], attempt.state)
        ):
            raise OAuthFailure("oauth_state_invalid")
        if "error" in callback:
            raise OAuthFailure("oauth_consent_denied")
        client_id = callback.get("client_id", attempt.client_id)
        code = callback.get("code")
        if (
            not isinstance(client_id, str)
            or not client_id.startswith("oaiapp_")
            or not re.fullmatch(r"oaiapp_[A-Za-z0-9_-]{1,193}", client_id)
            or (attempt.client_id and client_id != attempt.client_id)
            or not isinstance(code, str)
            or not 1 <= len(code) <= 8192
        ):
            raise OAuthFailure("oauth_callback_invalid")
        with self.store.transaction() as tx:
            registration = tx.state.registrations.get(attempt.connection_id)
            if registration is None:
                # Retain issued client even when code exchange expires/fails.
                registration = Registration(
                    connection_id=attempt.connection_id, client_id=client_id
                )
                tx.state.registrations[attempt.connection_id] = registration
                tx.save()
            if registration.client_id != client_id:
                raise OAuthFailure("oauth_client_mismatch")
            if registration.revision != attempt.revision:
                raise OAuthFailure("oauth_connection_changed")
            tokens = self.oauth.exchange(
                client_id=client_id,
                code=code,
                verifier=attempt.verifier,
                redirect_uri=attempt.redirect_uri,
                nonce=attempt.nonce,
            )
            if registration.subject is not None and (
                tokens.subject != registration.subject or tokens.issuer != registration.issuer
            ):
                raise OAuthFailure("oauth_account_mismatch")
            if any(
                r.connection_id != registration.connection_id and r.client_id == client_id
                for r in tx.state.registrations.values()
            ):
                raise OAuthFailure("oauth_registration_duplicate")
            registration.issuer, registration.subject = tokens.issuer, tokens.subject
            self._replace(registration, tokens)
            tx.save()
            return self._safe(registration)

    @staticmethod
    def _replace(registration, tokens, *, new_session=True):
        registration.credentials = Credentials(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            id_token=tokens.id_token,
            scopes=tokens.scopes,
            expires_at=tokens.expires_at,
            earliest_refresh_at=tokens.earliest_refresh_at,
        )
        registration.refresh_pending = False
        if new_session:
            registration.revision += 1
        registration.remote_revocation = "unknown"
        registration.state = (
            "connected"
            if REQUIRED_USAGE_SCOPES.issubset(tokens.scopes)
            else ("permission_required")
        )

    def snapshot(
        self, connection_id: str, minimum_validity_seconds: int = 30
    ) -> CredentialSnapshot:
        if type(minimum_validity_seconds) is not int or not 1 <= minimum_validity_seconds <= 150:
            raise OAuthFailure("bridge_request_invalid")
        UUID(connection_id)
        with self.store.transaction() as tx:
            registration = tx.state.registrations.get(connection_id)
            if registration is None or registration.credentials is None:
                raise OAuthFailure("bridge_auth_required")
            if registration.state in {"disconnected", "reauth"}:
                raise OAuthFailure("bridge_auth_required")
            if registration.refresh_pending:
                # Crash/timeout after rotating-token send: do not replay under any identity.
                registration.state = "reauth"
                tx.save()
                raise OAuthFailure("bridge_refresh_uncertain")
            credentials = registration.credentials
            if not REQUIRED_USAGE_SCOPES.issubset(credentials.scopes):
                raise OAuthFailure("bridge_permission_required")
            if self.clock() >= credentials.expires_at - minimum_validity_seconds:
                if not credentials.refresh_token:
                    raise OAuthFailure("bridge_auth_required")
                if self.clock() < credentials.earliest_refresh_at:
                    raise OAuthFailure("bridge_refresh_not_available")
                registration.refresh_pending = True
                tx.save()
                try:
                    tokens = self.oauth.refresh(
                        client_id=registration.client_id,
                        refresh_token=credentials.refresh_token,
                        previous_id_token=credentials.id_token,
                        subject=registration.subject,
                        scopes=credentials.scopes,
                    )
                    if (
                        tokens.subject != registration.subject
                        or tokens.issuer != registration.issuer
                    ):
                        raise OAuthFailure("oauth_account_mismatch", uncertain=True)
                    self._replace(registration, tokens, new_session=False)
                except OAuthFailure as error:
                    if error.code in TERMINAL_REFRESH_ERRORS:
                        registration.credentials = None
                        registration.revision += 1
                        registration.state, registration.refresh_pending = "reauth", False
                    elif error.uncertain:
                        registration.state = "reauth"
                    else:
                        registration.state, registration.refresh_pending = "unavailable", False
                    tx.save()
                    raise
                tx.save()
                credentials = registration.credentials
            if registration.state in {"reauth", "permission_required"}:
                raise OAuthFailure("bridge_auth_required")
            if self.clock() >= credentials.expires_at - minimum_validity_seconds:
                raise OAuthFailure("bridge_auth_required")
            registration.state = "connected"
            tx.save()
            return CredentialSnapshot(
                connection_id,
                registration.revision,
                registration.client_id,
                registration.subject,
                credentials.access_token,
                tuple(
                    value
                    for value in (
                        credentials.access_token,
                        credentials.refresh_token,
                        credentials.id_token,
                        registration.subject,
                        registration.client_id,
                        tx.state.host_id,
                    )
                    if value
                ),
            )

    def current(self, connection_id: str, revision: int) -> bool:
        with self.store.transaction() as tx:
            r = tx.state.registrations.get(connection_id)
            return bool(
                r
                and r.revision == revision
                and r.state == "connected"
                and r.credentials
                and r.credentials.expires_at > self.clock()
                and not r.refresh_pending
            )

    def disconnect(self, connection_id: str) -> SafeConnection:
        with self._attempt_lock:
            self._attempts = {
                k: v for k, v in self._attempts.items() if v.connection_id != connection_id
            }
        with self.store.transaction() as tx:
            registration = tx.state.registrations.get(connection_id)
            if registration is None:
                raise OAuthFailure("oauth_registration_missing")
            registration.state = "disconnected"
            registration.revision += 1
            tx.save()  # Stop requests even if revoke hangs/crashes.
            confirmed = False
            try:
                if registration.credentials and registration.credentials.refresh_token:
                    confirmed = self.oauth.revoke(
                        client_id=registration.client_id,
                        refresh_token=registration.credentials.refresh_token,
                    )
            except OAuthFailure:
                pass
            finally:
                registration.credentials = None
                registration.refresh_pending = False
                registration.remote_revocation = "confirmed" if confirmed else "unconfirmed"
                tx.save()
            return self._safe(registration)
