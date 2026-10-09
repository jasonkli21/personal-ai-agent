"""One authorized local execution, with no cloud orchestration or fallback."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import anyio
from pydantic import BaseModel, ConfigDict, Field

from personal_ai.auth.dispatch_grants import DispatchGrantVerifier, SignedDispatchGrant
from personal_ai.llm.chatgpt.responses import (
    PROVIDER,
    SERIALIZER,
    BridgeProviderFailure,
    ChatGPTResponses,
)
from personal_ai.llm.client import (
    ExecutionProvenance,
    GenerationEvent,
    GenerationMetadata,
    ProviderIdentity,
)
from personal_ai.llm.external import PreparedExecution
from personal_ai.local_bridge.disclosure import CredentialEcho, LocalOutputGuard
from personal_ai.local_bridge.lifecycle import CredentialLifecycle
from personal_ai.local_bridge.store import LocalStoreError
from personal_ai.routing.contracts import DataUsePolicy


class BridgeDenied(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CompatibilityGate(BaseModel):
    """Local preflight evidence, not browser declarations or inferred eligibility."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    connection_id: UUID
    client_id: str = Field(min_length=1, max_length=200, repr=False)
    distribution: Literal["local_personal", "hosted_web_installed_bridge"]
    distribution_approval: str | None = Field(default=None, min_length=1, max_length=500)
    compatibility_reference: str = Field(min_length=1, max_length=500)
    plan_only_reference: str = Field(min_length=1, max_length=500)
    plan_only_verified: bool = False
    valid_until: int = Field(ge=0, strict=True)
    verified_at: int = Field(ge=0, strict=True)
    model_slugs: tuple[str, ...] = Field(min_length=1, max_length=256)
    data_use: DataUsePolicy

    def require_package(self, package, *, now):
        if (
            not self.plan_only_verified
            or self.connection_id != package.connection_id
            or not self.verified_at <= now < self.valid_until
            or self.valid_until - self.verified_at > 7 * 86400
            or package.model_id not in self.model_slugs
            or (
                self.distribution == "hosted_web_installed_bridge"
                and not self.distribution_approval
            )
            or self.data_use.status != "approved"
        ):
            raise BridgeDenied("bridge_compatibility_unverified")
        rank = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
        if rank[package.effective_sensitivity] > rank[self.data_use.max_sensitivity]:
            raise BridgeDenied("bridge_disclosure_denied")

    def require(self, package, snapshot, *, now):
        self.require_package(package, now=now)
        if self.client_id != snapshot.client_id:
            raise BridgeDenied("bridge_compatibility_unverified")


@dataclass(frozen=True, slots=True, repr=False)
class CallerSession:
    caller_id: UUID
    origin: str
    connection_id: UUID
    connection_revision: int
    authorization: str
    expires_at: int


class ChatGPTPlanBridge(Protocol):
    """Consume a prepared signed package, return only Phase 16 normalized events."""

    def execute(
        self,
        package: PreparedExecution,
        proof: SignedDispatchGrant,
        *,
        origin: str,
        authorization: str,
    ): ...


def exact_origin(origin: str):
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (parsed.scheme == "http" and parsed.hostname != "127.0.0.1")
        or origin != f"{parsed.scheme}://{parsed.netloc}"
    ):
        raise BridgeDenied("bridge_origin_invalid")
    return origin


class LocalChatGPTBridge:
    def __init__(
        self,
        lifecycle: CredentialLifecycle,
        provider: ChatGPTResponses,
        verifier: DispatchGrantVerifier,
        *,
        origins: tuple[str, ...],
        gates: tuple[CompatibilityGate, ...] = (),
        clock=time.time,
    ):
        self.lifecycle, self.provider, self.verifier = lifecycle, provider, verifier
        self.origins = frozenset(exact_origin(origin) for origin in origins)
        self.gates = {str(gate.connection_id): gate for gate in gates}
        if len(self.gates) != len(gates):
            raise BridgeDenied("bridge_gate_ambiguous")
        self.clock = clock
        self._sessions = {}
        self._session_lock = threading.Lock()

    def approve_pairing(self, origin: str, connection_id: str) -> CallerSession:
        """Local operator call only. HTTP has no unapproved pairing endpoint."""
        if origin not in self.origins:
            raise BridgeDenied("bridge_origin_denied")
        connection = next(
            (c for c in self.lifecycle.connections() if c.connection_id == connection_id), None
        )
        if connection is None or connection.state != "connected" or not connection.plan_permission:
            raise BridgeDenied("bridge_auth_required")
        session = CallerSession(
            uuid4(),
            origin,
            UUID(connection_id),
            connection.revision,
            secrets.token_urlsafe(32),
            int(self.clock()) + 300,
        )
        with self._session_lock:
            self._sessions = {
                k: s for k, s in self._sessions.items() if s.expires_at > self.clock()
            }
            if len(self._sessions) >= 32:
                raise BridgeDenied("bridge_pairing_capacity")
            self._sessions[hashlib.sha256(session.authorization.encode()).hexdigest()] = session
        return session

    def authorize(self, origin, authorization) -> CallerSession:
        if origin not in self.origins or not isinstance(authorization, str):
            raise BridgeDenied("bridge_caller_denied")
        if not 32 <= len(authorization) <= 128:
            raise BridgeDenied("bridge_caller_denied")
        with self._session_lock:
            session = self._sessions.get(hashlib.sha256(authorization.encode()).hexdigest())
        if session is None or session.origin != origin or self.clock() >= session.expires_at:
            raise BridgeDenied("bridge_caller_denied")
        return session

    async def connection(self, *, origin, authorization):
        session = self.authorize(origin, authorization)
        connections = await anyio.to_thread.run_sync(self.lifecycle.connections)
        return next(c for c in connections if c.connection_id == str(session.connection_id))

    async def models(self, *, origin, authorization):
        session = self.authorize(origin, authorization)
        snapshot = await anyio.to_thread.run_sync(
            self.lifecycle.snapshot, str(session.connection_id)
        )
        if snapshot.revision != session.connection_revision:
            raise BridgeDenied("bridge_connection_changed")
        models = await self.provider.discover(snapshot.access_token)
        guard = LocalOutputGuard(snapshot.protected_values)
        for model in models:
            guard.check(model.slug)
            guard.check(model.display_name)
        if not await anyio.to_thread.run_sync(
            self.lifecycle.current, snapshot.connection_id, snapshot.revision
        ):
            raise BridgeDenied("bridge_connection_changed")
        return models

    async def execute(self, package, proof, *, origin, authorization):
        session = self.authorize(origin, authorization)
        if (
            package.provider_id != PROVIDER
            or package.connection_id != session.connection_id
            or package.connection_revision != session.connection_revision
        ):
            raise BridgeDenied("bridge_selection_mismatch")
        self.verifier.verify(proof, package, caller_id=session.caller_id, now=int(self.clock()))
        gate = self.gates.get(str(package.connection_id))
        if gate is None:
            raise BridgeDenied("bridge_compatibility_unverified")
        # Local policy denial must precede even a rotating credential refresh.
        gate.require_package(package, now=int(self.clock()))
        # Validate the narrow serializer before touching credentials or recording a send.
        from personal_ai.llm.chatgpt.responses import serialize

        serialize(package.chat_messages(), package.model_id)
        try:
            duration = min(
                package.timeout_seconds,
                proof.claims.expires_at - self.clock(),
                session.expires_at - self.clock(),
            )
            async with asyncio.timeout(duration):
                snapshot = await anyio.to_thread.run_sync(
                    self.lifecycle.snapshot,
                    str(package.connection_id),
                    package.timeout_seconds + 30,
                )
                gate.require(package, snapshot, now=int(self.clock()))
                if snapshot.revision != package.connection_revision:
                    raise BridgeDenied("bridge_connection_changed")
                models = await self.provider.discover(snapshot.access_token)
                guard = LocalOutputGuard(snapshot.protected_values)
                for model in models:
                    guard.check(model.slug)
                    guard.check(model.display_name)
                if package.model_id not in {m.slug for m in models}:
                    raise BridgeDenied("bridge_model_unavailable")
                # Expiry and caller authority are rechecked after refresh/discovery.
                self.authorize(origin, authorization)
                self.verifier.verify(
                    proof, package, caller_id=session.caller_id, now=int(self.clock())
                )
                gate.require(package, snapshot, now=int(self.clock()))
                await anyio.to_thread.run_sync(
                    self.lifecycle.store.claim,
                    package.dispatch_identity,
                    package.fingerprint,
                    snapshot.connection_id,
                    snapshot.revision,
                )
                # Lock wait and wall-clock changes must not extend dispatch authority.
                self.authorize(origin, authorization)
                self.verifier.verify(
                    proof, package, caller_id=session.caller_id, now=int(self.clock())
                )
                gate.require(package, snapshot, now=int(self.clock()))
                if not await anyio.to_thread.run_sync(
                    self.lifecycle.current, snapshot.connection_id, snapshot.revision
                ):
                    raise BridgeDenied("bridge_connection_changed")
                stream = self.provider.stream(
                    package.chat_messages(),
                    model=package.model_id,
                    access_token=snapshot.access_token,
                    connection_id=snapshot.connection_id,
                    invocation_id=str(package.reservation_id),
                    max_output_bytes=package.max_output_bytes,
                    timeout_seconds=package.timeout_seconds,
                )
                try:
                    async for event in stream:
                        if not await anyio.to_thread.run_sync(
                            self.lifecycle.current, snapshot.connection_id, snapshot.revision
                        ):
                            raise BridgeDenied("bridge_connection_changed")
                        if self.clock() >= min(proof.claims.expires_at, session.expires_at):
                            raise BridgeDenied("bridge_authorization_expired")
                        if event.kind == "delta":
                            safe_delta = guard.feed(event.delta)
                            if safe_delta:
                                yield GenerationEvent.text_delta(safe_delta)
                            continue
                        if event.kind == "terminal":
                            safe_tail = guard.finish()
                            if safe_tail:
                                yield GenerationEvent.text_delta(safe_tail)
                            metadata = event.metadata
                            if metadata.error_code not in {
                                "bridge_timeout_unknown",
                                "bridge_transport_unknown",
                                "bridge_terminal_missing",
                                "bridge_protocol_invalid",
                                "bridge_output_bound",
                            }:
                                await anyio.to_thread.run_sync(
                                    self.lifecycle.store.settle,
                                    package.dispatch_identity,
                                    metadata.status,
                                )
                        yield event
                finally:
                    await stream.aclose()
        except CredentialEcho:
            raise BridgeDenied("bridge_credential_echo") from None
        except (TimeoutError, BridgeDenied, LocalStoreError, BridgeProviderFailure):
            # Caller handles safe denial; an already claimed receipt remains fenced.
            raise


class FakeChatGPTPlanBridge:
    """Independent neutral-contract fake, with no credentials or cloud services."""

    def __init__(self, *, text="synthetic response", status="success"):
        self.text, self.status = text, status
        self._seen = set()

    async def execute(self, package, proof=None, *, origin="", authorization=""):
        if package.dispatch_identity in self._seen:
            raise BridgeDenied("dispatch_already_claimed")
        self._seen.add(package.dispatch_identity)
        provenance = ExecutionProvenance(
            "connected_provider",
            "bridge_observed",
            PROVIDER,
            package.model_id,
            str(package.connection_id),
        )
        if len(self.text.encode()) > package.max_output_bytes:
            yield GenerationEvent.terminal(
                GenerationMetadata(
                    "incomplete",
                    ProviderIdentity(PROVIDER, package.model_id, SERIALIZER),
                    error_code="bridge_output_bound",
                    provenance=provenance,
                )
            )
            return
        yield GenerationEvent.text_delta(self.text)
        yield GenerationEvent.terminal(
            GenerationMetadata(
                self.status,
                ProviderIdentity(PROVIDER, package.model_id, SERIALIZER),
                invocation_id=str(package.reservation_id),
                provenance=provenance,
            )
        )
