"""Restricted provider transport and paired loopback execution contracts."""

import asyncio
import json
import time
from dataclasses import asdict
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from personal_ai.auth.dispatch_grants import DispatchGrantVerifier, InvalidDispatchGrant
from personal_ai.llm.chatgpt.responses import (
    ChatGPTResponses,
    serialize,
)
from personal_ai.llm.client import ChatMessage, ExternalCompletion
from personal_ai.local_bridge.disclosure import CredentialEcho, LocalOutputGuard
from personal_ai.local_bridge.http import create_loopback_app
from personal_ai.local_bridge.runtime import (
    BridgeDenied,
    CompatibilityGate,
    FakeChatGPTPlanBridge,
    LocalChatGPTBridge,
)
from personal_ai.local_bridge.store import LocalStoreError
from tests.test_chatgpt_local_lifecycle import connected_lifecycle
from tests.test_external_execution_contracts import execution_package, signed_grant


def created():
    return {"type": "response.created", "response": {"id": "synthetic-response"}}


def delta(text="A streamed answer"):
    return {"type": "response.output_text.delta", "delta": text}


def completed(**overrides):
    response = {
        "id": "synthetic-response",
        "model": "account-visible-model",
        "status": "completed",
        "usage": {"input_tokens": 5, "output_tokens": 4, "total_tokens": 9},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "A streamed answer"},
                ],
            }
        ],
    }
    response.update(overrides)
    return {"type": "response.completed", "response": response}


def sse(events):
    return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)


class ProviderFixture:
    def __init__(self):
        self.requests = []
        self.events = [created(), delta(), completed()]
        self.raw = None
        self.catalog = [
            {
                "slug": "account-visible-model",
                "display_name": "Account visible",
                "visibility": "list",
            }
        ]
        self.status = 200
        self.error = {}
        self.stream = None
        self.provider = ChatGPTResponses(transport=httpx.MockTransport(self.handle))

    def handle(self, request):
        self.requests.append(request)
        assert request.url.host == "api.openai.com"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"models": self.catalog})
        assert request.url.path == "/v1/responses"
        if self.status != 200:
            return httpx.Response(self.status, json=self.error)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            **(
                {"stream": self.stream}
                if self.stream
                else {
                    "content": self.raw if self.raw is not None else sse(self.events),
                }
            ),
        )

    def sends(self):
        return [r for r in self.requests if r.url.path == "/v1/responses"]


async def collect(iterator):
    return [event async for event in iterator]


def transport_events(fixture, **kwargs):
    values = {
        "model": "account-visible-model",
        "access_token": "synthetic-access",
        "connection_id": "11111111-1111-4111-8111-111111111111",
        "invocation_id": "22222222-2222-4222-8222-222222222222",
        "max_output_bytes": 1024,
        "timeout_seconds": 2,
    }
    values.update(kwargs)
    return asyncio.run(collect(fixture.provider.stream([ChatMessage("user", "Hello")], **values)))


def bridge_fixture(tmp_path, *, gated=True):
    lifecycle, _oauth, connection = connected_lifecycle(tmp_path)
    provider = ProviderFixture()
    private = Ed25519PrivateKey.generate()
    with lifecycle.store.transaction() as tx:
        audience = UUID(tx.state.runtime_id)
    verifier = DispatchGrantVerifier(
        issuer="synthetic-authorized-issuer",
        keys={"key-v1": private.public_key()},
        audience=audience,
    )
    now = int(time.time())
    gate = CompatibilityGate(
        connection_id=UUID(connection.connection_id),
        client_id="oaiapp_synthetic",
        distribution="local_personal",
        compatibility_reference="synthetic-offline-compatibility",
        plan_only_reference="synthetic-offline-plan-only",
        plan_only_verified=True,
        verified_at=now,
        valid_until=now + 3600,
        model_slugs=("account-visible-model",),
        data_use={
            "status": "approved",
            "max_sensitivity": "sensitive",
            "policy_reference": "synthetic-privacy-policy",
        },
    )
    bridge = LocalChatGPTBridge(
        lifecycle,
        provider.provider,
        verifier,
        origins=("https://approved.example",),
        gates=(gate,) if gated else (),
    )
    session = bridge.approve_pairing("https://approved.example", connection.connection_id)
    package = execution_package(
        connection_id=session.connection_id, connection_revision=session.connection_revision
    )
    proof = signed_grant(package, private, caller_id=session.caller_id, audience=audience, now=now)
    return bridge, provider, session, package, proof, private


def run_bridge(bridge, session, package, proof):
    return asyncio.run(
        collect(
            bridge.execute(
                package, proof, origin=session.origin, authorization=session.authorization
            )
        )
    )


def test_restricted_serializer_maps_system_to_developer_without_unsupported_fields():
    body = json.loads(
        serialize(
            [ChatMessage("system", "instruction"), ChatMessage("user", "prompt")],
            "discovered-model",
        )
    )
    assert body == {
        "model": "discovered-model",
        "input": [
            {"role": "developer", "content": "instruction"},
            {"role": "user", "content": "prompt"},
        ],
        "store": False,
        "stream": True,
    }
    assert "max_output_tokens" not in body and "previous_response_id" not in body


def test_account_catalog_preserves_display_order_and_omits_hidden_models():
    fixture = ProviderFixture()
    fixture.catalog = [
        {"slug": "new-model", "display_name": "New model", "visibility": "list"},
        {"slug": "hidden-model", "display_name": "Hidden", "visibility": "hidden"},
        {"slug": "old-model", "display_name": "Old model", "visibility": "list"},
    ]
    models = asyncio.run(fixture.provider.discover("synthetic-access"))
    assert [model.slug for model in models] == ["new-model", "old-model"]
    assert fixture.requests[0].headers["authorization"] == "Bearer synthetic-access"
    assert all("synthetic-access" not in str(request.url) for request in fixture.requests)


def test_stream_reports_explicit_completion_usage_and_observed_provenance():
    fixture = ProviderFixture()
    events = transport_events(fixture)
    assert events[0].delta == "A streamed answer"
    metadata = events[-1].metadata
    assert metadata.status == "success" and metadata.usage.total_tokens == 9
    assert metadata.provenance.fact_source == "bridge_observed"
    assert len(fixture.sends()) == 1
    assert ExternalCompletion(events[0].delta, metadata.provenance, metadata).generation == metadata


@pytest.mark.parametrize(
    "events,code",
    [
        ([created(), delta()], "bridge_terminal_missing"),
        ([created(), delta(), completed(model="other-model")], "bridge_protocol_invalid"),
        ([created(), completed()], "bridge_protocol_invalid"),
        ([created(), delta(), completed(), delta("extra")], "bridge_protocol_invalid"),
        ([delta(), completed()], "bridge_protocol_invalid"),
        ([created(), delta(), completed(id="foreign-response")], "bridge_protocol_invalid"),
        (
            [
                created(),
                delta(),
                {
                    "type": "response.incomplete",
                    "response": {
                        "id": "synthetic-response",
                        "model": "account-visible-model",
                        "status": "incomplete",
                    },
                },
            ],
            "bridge_incomplete",
        ),
    ],
)
def test_terminal_loss_model_drift_and_protocol_failures_do_not_succeed(events, code):
    fixture = ProviderFixture()
    fixture.events = events
    result = transport_events(fixture)
    assert result[-1].metadata.status == "incomplete" and result[-1].metadata.error_code == code
    assert len(fixture.sends()) == 1


@pytest.mark.parametrize(
    "status,error,code",
    [
        (401, {"detail": "private-admission-details"}, "bridge_auth_required"),
        (403, {"detail": "private-admission-details"}, "bridge_admission_denied"),
        (503, {"detail": "private-admission-details"}, "bridge_transport_unknown"),
        (403, {"error": {"code": "subscription_sharing_user_not_eligible"}}, "bridge_ineligible"),
        (
            429,
            {"error": {"code": "subscription_sharing_usage_limit_exceeded"}},
            "bridge_usage_limit",
        ),
        (
            503,
            {"error": {"code": "subscription_sharing_usage_unavailable"}},
            "bridge_usage_unavailable",
        ),
        (
            400,
            {"error": {"code": "subscription_sharing_unsupported_capability"}},
            "bridge_unsupported_request",
        ),
    ],
)
def test_admission_and_usage_errors_are_normalized_without_body_or_billing_fallback(
    status, error, code
):
    fixture = ProviderFixture()
    fixture.status, fixture.error = status, error
    result = transport_events(fixture)
    assert result[-1].metadata.error_code == code
    assert "private-admission-details" not in str(asdict(result[-1]))
    assert len(fixture.sends()) == 1


def test_usage_failure_after_deltas_is_not_completion_or_reset_timestamp():
    fixture = ProviderFixture()
    fixture.events = [
        created(),
        delta(),
        {
            "type": "response.failed",
            "response": {
                "id": "synthetic-response",
                "model": "account-visible-model",
                "status": "failed",
                "error": {
                    "code": "subscription_sharing_usage_limit_exceeded",
                    "message": "private",
                },
            },
        },
    ]
    result = transport_events(fixture)
    assert result[-1].metadata.status == "failure"
    assert result[-1].metadata.error_code == "bridge_usage_limit"
    assert result[-1].metadata.rate_limits is None


@pytest.mark.parametrize(
    "raw",
    [
        b"data: " + b"x" * 131073,
        b"data: {bad-json}\n\n",
        b"data: {}\n",
        b"data: []\n\n",
    ],
)
def test_event_bounds_malformed_json_and_truncation_are_explicit(raw):
    fixture = ProviderFixture()
    fixture.raw = raw
    assert transport_events(fixture)[-1].metadata.error_code == "bridge_protocol_invalid"


class SlowStream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield sse([created(), delta()])
        await asyncio.sleep(1)
        yield sse([completed()])

    async def aclose(self):
        self.closed = True


def test_total_deadline_closes_stream_without_retry():
    fixture = ProviderFixture()
    fixture.stream = SlowStream()
    result = transport_events(fixture, timeout_seconds=0.01)
    assert result[-1].metadata.error_code == "bridge_timeout_unknown"
    assert fixture.stream.closed and len(fixture.sends()) == 1


def test_consumer_cancellation_closes_provider_and_retains_unknown_send_fence(tmp_path):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    provider.stream = SlowStream()

    async def stop():
        stream = bridge.execute(
            package, proof, origin=session.origin, authorization=session.authorization
        )
        event = await anext(stream)
        assert event.kind == "delta"
        await stream.aclose()

    asyncio.run(stop())
    assert provider.stream.closed and len(provider.sends()) == 1
    with bridge.lifecycle.store.transaction() as tx:
        assert tx.state.receipts[package.dispatch_identity]["status"] == "unknown"


def test_cancellation_of_running_consumer_closes_provider(tmp_path):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    provider.stream = SlowStream()

    async def stop():
        task = asyncio.create_task(
            collect(
                bridge.execute(
                    package, proof, origin=session.origin, authorization=session.authorization
                )
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(stop())
    assert provider.stream.closed
    with bridge.lifecycle.store.transaction() as tx:
        assert tx.state.receipts[package.dispatch_identity]["status"] == "unknown"


def test_local_output_bound_is_not_provider_token_bound():
    fixture = ProviderFixture()
    result = transport_events(fixture, max_output_bytes=1)
    assert result[-1].metadata.error_code == "bridge_output_bound"
    assert result[-1].metadata.status == "incomplete"
    assert all(event.kind != "delta" for event in result)
    assert "max_output_tokens" not in json.loads(fixture.sends()[0].content)


@pytest.mark.parametrize(
    "change",
    [
        {"output": [{"type": "function_call", "arguments": "{}"}]},
        {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "a different answer"},
                    ],
                }
            ]
        },
        {"status": "incomplete"},
        {"usage": {"input_tokens": True}},
    ],
)
def test_terminal_payload_cannot_hide_tools_text_drift_or_fabricated_usage(change):
    fixture = ProviderFixture()
    fixture.events = [created(), delta(), completed(**change)]
    assert transport_events(fixture)[-1].metadata.error_code == "bridge_protocol_invalid"


def test_unknown_events_and_duplicate_wire_keys_are_not_silently_accepted():
    fixture = ProviderFixture()
    fixture.raw = b'data: {"type":"response.created","type":"response.completed"}\n\n'
    assert transport_events(fixture)[-1].metadata.error_code == "bridge_protocol_invalid"
    fixture.raw = None
    fixture.events = [created(), delta(), {"type": "response.unverified_new_feature"}, completed()]
    assert transport_events(fixture)[-1].metadata.error_code == "bridge_protocol_invalid"


def test_compressed_provider_stream_is_rejected_before_decompression():
    fixture = ProviderFixture()
    original = fixture.handle

    def compressed(request):
        result = original(request)
        if request.url.path == "/v1/responses":
            result.headers["content-encoding"] = "gzip"
        return result

    fixture.provider = ChatGPTResponses(transport=httpx.MockTransport(compressed))
    assert transport_events(fixture)[-1].metadata.error_code == "bridge_protocol_invalid"
    assert fixture.requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "change",
    [
        {"plan_only_verified": False},
        {"valid_until": 1},
        {"client_id": "oaiapp_other"},
        {"model_slugs": ("other-model",)},
        {"distribution": "hosted_web_installed_bridge", "distribution_approval": None},
        {"data_use": {"status": "unknown"}},
    ],
)
def test_local_compatibility_attestation_cannot_be_waived_by_signed_package(tmp_path, change):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    original = bridge.gates[str(package.connection_id)]
    bridge.gates[str(package.connection_id)] = CompatibilityGate.model_validate(
        {
            **original.model_dump(),
            **change,
        }
    )
    with pytest.raises(BridgeDenied):
        run_bridge(bridge, session, package, proof)
    assert not provider.sends()


@pytest.mark.parametrize("denial", ["compatibility", "privacy"])
def test_local_policy_denial_precedes_any_credential_refresh(tmp_path, denial):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    gate = bridge.gates[str(package.connection_id)].model_dump()
    if denial == "compatibility":
        gate["plan_only_verified"] = False
    else:
        gate["data_use"]["max_sensitivity"] = "public"
    bridge.gates[str(package.connection_id)] = CompatibilityGate.model_validate(gate)
    with bridge.lifecycle.store.transaction() as tx:
        tx.state.registrations[str(package.connection_id)].credentials.expires_at = 1
        tx.save()
    prior_calls = list(bridge.lifecycle.oauth.calls)
    with pytest.raises(BridgeDenied):
        run_bridge(bridge, session, package, proof)
    assert bridge.lifecycle.oauth.calls == prior_calls
    assert not provider.requests
    with bridge.lifecycle.store.transaction() as tx:
        assert not tx.state.receipts


def test_expiry_during_catalog_refresh_aborts_without_claim_or_send(tmp_path):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    current_time = [proof.claims.issued_at]
    bridge.clock = lambda: current_time[0]
    original = provider.provider.discover

    async def expires(token):
        result = await original(token)
        current_time[0] = proof.claims.expires_at
        return result

    provider.provider.discover = expires
    with pytest.raises(InvalidDispatchGrant):
        run_bridge(bridge, session, package, proof)
    with bridge.lifecycle.store.transaction() as tx:
        assert not tx.state.receipts
    assert not provider.sends()


def test_local_output_cutoff_is_not_a_known_provider_terminal(tmp_path):
    bridge, _, session, package, _, private = bridge_fixture(tmp_path)
    package = package.model_copy(update={"max_output_bytes": 1})
    proof = signed_grant(
        package,
        private,
        caller_id=session.caller_id,
        audience=bridge.verifier.audience,
        now=int(time.time()),
    )
    result = run_bridge(bridge, session, package, proof)
    assert result[-1].metadata.error_code == "bridge_output_bound"
    with bridge.lifecycle.store.transaction() as tx:
        assert tx.state.receipts[package.dispatch_identity]["status"] == "unknown"


@pytest.mark.parametrize("status", [500, 502, 503])
def test_generic_server_error_does_not_prove_rejection_before_work(tmp_path, status):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    provider.status = status
    provider.error = {"error": {"message": "private upstream diagnostics"}}
    result = run_bridge(bridge, session, package, proof)
    assert result[-1].metadata.status == "incomplete"
    assert result[-1].metadata.error_code == "bridge_transport_unknown"
    assert "private upstream diagnostics" not in str(asdict(result[-1]))
    with bridge.lifecycle.store.transaction() as tx:
        assert tx.state.receipts[package.dispatch_identity]["status"] == "unknown"
    with pytest.raises(LocalStoreError, match="dispatch_already_claimed"):
        run_bridge(bridge, session, package, proof)
    assert len(provider.sends()) == 1


def test_bridge_executes_once_and_completed_provenance_contains_no_credentials(tmp_path, caplog):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    events = run_bridge(bridge, session, package, proof)
    assert events[-1].metadata.status == "success"
    safe_output = json.dumps([asdict(e) for e in events]) + caplog.text
    for private in (
        "synthetic-access",
        "synthetic-refresh",
        "synthetic-id-token",
        "synthetic-subject",
        "oaiapp_synthetic",
        "synthetic-code",
        session.authorization,
    ):
        assert private not in safe_output
    with pytest.raises(LocalStoreError, match="dispatch_already_claimed"):
        run_bridge(bridge, session, package, proof)
    assert len(provider.sends()) == 1


@pytest.mark.parametrize("mutation", ["gate", "model", "proof", "account", "origin", "caller"])
def test_unverified_stale_or_foreign_execution_stops_before_physical_send(tmp_path, mutation):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    if mutation == "gate":
        bridge.gates = {}
    elif mutation == "model":
        provider.catalog = []
    elif mutation == "proof":
        package = package.model_copy(update={"messages": tuple(reversed(package.messages))})
    elif mutation == "account":
        bridge.lifecycle.disconnect(str(package.connection_id))
    elif mutation == "origin":
        session = type(session)(
            session.caller_id,
            "https://foreign.example",
            session.connection_id,
            session.connection_revision,
            session.authorization,
            session.expires_at,
        )
    elif mutation == "caller":
        session = type(session)(
            session.caller_id,
            session.origin,
            session.connection_id,
            session.connection_revision,
            "not-a-local-caller",
            session.expires_at,
        )
    with pytest.raises((BridgeDenied, InvalidDispatchGrant, RuntimeError)):
        run_bridge(bridge, session, package, proof)
    assert not provider.sends()
    with bridge.lifecycle.store.transaction() as tx:
        assert not tx.state.receipts


def test_unknown_send_outcome_remains_fenced_across_runtime_restart_and_resigned_proof(tmp_path):
    bridge, provider, session, package, proof, private = bridge_fixture(tmp_path)
    provider.events = [created(), delta("partial")]
    events = run_bridge(bridge, session, package, proof)
    assert events[-1].metadata.error_code == "bridge_terminal_missing"
    with bridge.lifecycle.store.transaction() as tx:
        assert tx.state.receipts[package.dispatch_identity]["status"] == "unknown"
    second_proof = signed_grant(
        package,
        private,
        caller_id=session.caller_id,
        audience=bridge.verifier.audience,
        now=int(time.time()),
    )
    with pytest.raises(LocalStoreError):
        run_bridge(bridge, session, package, second_proof)
    assert len(provider.sends()) == 1


def test_simultaneous_dispatch_has_one_provider_effect(tmp_path):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)

    async def race():
        async def send():
            try:
                return await collect(
                    bridge.execute(
                        package, proof, origin=session.origin, authorization=session.authorization
                    )
                )
            except LocalStoreError as error:
                return error.code

        return await asyncio.gather(send(), send())

    results = asyncio.run(race())
    assert len(provider.sends()) == 1
    assert len([r for r in results if r == "dispatch_already_claimed"]) == 1


def test_credential_echo_across_delta_boundaries_cannot_escape_local_guard(tmp_path):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    provider.events = [created(), delta("safe synthetic-"), delta("access"), completed()]
    output = []

    async def send():
        async for event in bridge.execute(
            package, proof, origin=session.origin, authorization=session.authorization
        ):
            output.append(event)

    with pytest.raises(BridgeDenied, match="bridge_credential_echo"):
        asyncio.run(send())
    assert "synthetic-access" not in "".join(event.delta for event in output)
    with bridge.lifecycle.store.transaction() as tx:
        assert tx.state.receipts[package.dispatch_identity]["status"] == "unknown"


def test_catalog_cannot_echo_credentials_through_display_names(tmp_path):
    bridge, provider, session, _, _, _ = bridge_fixture(tmp_path)
    provider.catalog[0]["display_name"] = "synthetic-refresh"
    with pytest.raises(CredentialEcho):
        asyncio.run(bridge.models(origin=session.origin, authorization=session.authorization))


def test_guard_does_not_damage_benign_partial_prefixes():
    guard = LocalOutputGuard(("secret-value",))
    output = guard.feed("nice s") + guard.feed("ample") + guard.finish()
    assert output == "nice sample"
    assert guard.feed("secret-") == ""
    with pytest.raises(CredentialEcho):
        guard.feed("value")


def test_independent_fake_uses_same_neutral_events_and_single_send_identity():
    package = execution_package()
    fake = FakeChatGPTPlanBridge()
    result = asyncio.run(collect(fake.execute(package)))
    assert result[-1].metadata.provenance.mode == "connected_provider"
    assert result[-1].metadata.status == "success"
    with pytest.raises(BridgeDenied):
        asyncio.run(collect(fake.execute(package)))


def test_loopback_host_origin_peer_content_and_authorization_are_all_required(tmp_path):
    bridge, provider, session, package, proof, _ = bridge_fixture(tmp_path)
    app = create_loopback_app(bridge, port=8765)
    headers = {"Origin": session.origin, "X-Bridge-Authorization": session.authorization}
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1234)) as client:
        assert client.get("/connection", headers=headers).status_code == 200
        for changed in (
            {"Host": "localhost:8765"},
            {"Host": "rebind.example:8765"},
            {"Origin": "https://approved.example.evil"},
            {"Origin": "null"},
            {"X-Bridge-Authorization": "bad"},
            {"Authorization": "Bearer google-identity"},
            {"X-Forwarded-Host": "127.0.0.1:8765"},
        ):
            assert client.get("/connection", headers={**headers, **changed}).status_code == 403
        assert client.get("/connection", headers={}).status_code == 403
        duplicate_headers = client.get(
            "/connection",
            headers=[
                ("Origin", session.origin),
                ("Origin", session.origin),
                ("X-Bridge-Authorization", session.authorization),
            ],
        )
        assert duplicate_headers.status_code == 403
        assert client.get("/connection?token=bad", headers=headers).status_code == 403
        assert client.post("/execute", headers=headers, content="{}").status_code == 415
        invalid = client.post(
            "/execute",
            headers={**headers, "Content-Type": "application/json"},
            content='{"access_token":"never-echo-input"}',
        )
        assert invalid.status_code == 400 and "never-echo-input" not in invalid.text
        duplicate = client.post(
            "/execute",
            headers={**headers, "Content-Type": "application/json"},
            content='{"package":{},"package":{}}',
        )
        assert duplicate.status_code == 400
        result = client.post(
            "/execute",
            headers=headers,
            json={
                "package": package.model_dump(mode="json"),
                "proof": proof.model_dump(mode="json"),
            },
        )
        assert result.status_code == 200 and '"status":"success"' in result.text
        assert "synthetic-access" not in result.text and "oaiapp_synthetic" not in result.text
        assert result.headers["Access-Control-Allow-Origin"] == session.origin
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("192.0.2.1", 1234)) as client:
        assert client.get("/connection", headers=headers).status_code == 403
    assert len(provider.sends()) == 1


def test_private_network_preflight_is_a_separate_unverified_gate(tmp_path):
    bridge, _, session, _, _, _ = bridge_fixture(tmp_path)
    app = create_loopback_app(bridge, port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1234)) as client:
        headers = {
            "Origin": session.origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-bridge-authorization",
        }
        assert client.options("/execute", headers=headers).status_code == 200
        assert (
            client.options(
                "/execute",
                headers={
                    **headers,
                    "Access-Control-Request-Private-Network": "true",
                },
            ).status_code
            == 403
        )


def test_bridge_never_joins_managed_composition_or_automatic_provider_factory():
    from personal_ai.llm.errors import LLMInvalidConfigurationError
    from personal_ai.llm.providers import build_generation_adapter
    from personal_ai.settings import Settings

    with pytest.raises(LLMInvalidConfigurationError):
        build_generation_adapter(
            Settings(ai_provider="gemini", ai_model="synthetic-model"),
            provider="openai_chatgpt_plan",
        )
