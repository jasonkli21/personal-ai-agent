"""Standalone loopback IPC prototype. Never mount this on the managed API."""

from __future__ import annotations

import json
from dataclasses import asdict

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from personal_ai.auth.dispatch_grants import InvalidDispatchGrant, SignedDispatchGrant
from personal_ai.llm.chatgpt.oauth import OAuthFailure
from personal_ai.llm.chatgpt.responses import BridgeProviderFailure
from personal_ai.llm.errors import LLMError
from personal_ai.llm.external import PreparedExecution
from personal_ai.local_bridge.disclosure import CredentialEcho
from personal_ai.local_bridge.runtime import BridgeDenied, LocalChatGPTBridge
from personal_ai.local_bridge.store import LocalStoreError


class DispatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    package: PreparedExecution
    proof: SignedDispatchGrant


def strict_json(body):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("invalid_json_constant")

    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid_constant)


def create_loopback_app(
    bridge: LocalChatGPTBridge,
    *,
    port: int,
    private_network_verified=False,
) -> FastAPI:
    if not 1024 <= port <= 65535:
        raise ValueError("bridge_port_invalid")
    host = f"127.0.0.1:{port}"
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Do not trust Forwarded/X-Forwarded-* or DNS aliases. Duplicate credentials
        # and Host/Origin are ambiguous even if a framework picks a first value.
        for name in ("host", "origin", "x-bridge-authorization", "content-type"):
            if len(request.headers.getlist(name)) > 1:
                return JSONResponse({"error": "bridge_request_denied"}, status_code=403)
        if (
            request.client is None
            or request.client.host != "127.0.0.1"
            or request.headers.get("host") != host
            or request.headers.get("origin") not in bridge.origins
            or request.headers.get("authorization")
            or request.url.query
            or any(key.startswith(("forwarded", "x-forwarded")) for key in request.headers)
        ):
            return JSONResponse({"error": "bridge_request_denied"}, status_code=403)
        origin = request.headers["origin"]
        cors = {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }
        if request.method == "OPTIONS":
            method = request.headers.get("access-control-request-method")
            headers = {
                h.strip().lower()
                for h in request.headers.get("access-control-request-headers", "").split(",")
                if h.strip()
            }
            if method not in {"GET", "POST"} or not headers.issubset(
                {
                    "content-type",
                    "x-bridge-authorization",
                }
            ):
                return JSONResponse({"error": "bridge_request_denied"}, status_code=403)
            if request.headers.get("access-control-request-private-network") == "true":
                if not private_network_verified:
                    return JSONResponse({"error": "bridge_transport_unverified"}, status_code=403)
                cors["Access-Control-Allow-Private-Network"] = "true"
            cors.update(
                {
                    "Access-Control-Allow-Methods": "GET, POST",
                    "Access-Control-Allow-Headers": "Content-Type, X-Bridge-Authorization",
                }
            )
            return JSONResponse({}, headers=cors)
        try:
            await anyio.to_thread.run_sync(
                bridge.authorize, origin, request.headers.get("x-bridge-authorization")
            )
        except BridgeDenied as error:
            return JSONResponse({"error": error.code}, status_code=403, headers=cors)
        response = await call_next(request)
        response.headers.update(cors)
        return response

    def caller(request):
        return {
            "origin": request.headers["origin"],
            "authorization": request.headers["x-bridge-authorization"],
        }

    @app.get("/connection")
    async def connection(request: Request):
        try:
            result = await bridge.connection(**caller(request))
            return asdict(result)
        except (BridgeDenied, OAuthFailure, LocalStoreError):
            return JSONResponse({"error": "bridge_unavailable"}, status_code=409)

    @app.get("/models")
    async def models(request: Request):
        try:
            return {"models": [asdict(model) for model in await bridge.models(**caller(request))]}
        except (BridgeDenied, OAuthFailure, LocalStoreError, BridgeProviderFailure, CredentialEcho):
            return JSONResponse({"error": "bridge_models_unavailable"}, status_code=409)

    @app.post("/execute")
    async def execute(request: Request):
        if request.headers.get("content-type") != "application/json":
            return JSONResponse({"error": "bridge_request_invalid"}, status_code=415)
        try:
            body = bytearray()
            with anyio.fail_after(5):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 300000:
                        return JSONResponse({"error": "bridge_request_too_large"}, status_code=413)
            submitted = DispatchInput.model_validate(strict_json(body))
        except (ValueError, RecursionError, TimeoutError, UnicodeError):
            # Never return framework validation detail containing submitted secrets/content.
            return JSONResponse({"error": "bridge_request_invalid"}, status_code=400)
        stream = bridge.execute(submitted.package, submitted.proof, **caller(request))

        async def events():
            try:
                async for event in stream:
                    yield (
                        b"data: "
                        + json.dumps(asdict(event), separators=(",", ":")).encode()
                        + b"\n\n"
                    )
            except (
                BridgeDenied,
                InvalidDispatchGrant,
                OAuthFailure,
                LocalStoreError,
                BridgeProviderFailure,
                LLMError,
                TimeoutError,
            ) as error:
                # Protocol interruption has no terminal success and partial output is transient.
                code = getattr(error, "code", "bridge_execution_interrupted")
                yield (
                    b"data: "
                    + json.dumps({"kind": "interrupted", "error": code}).encode()
                    + b"\n\n"
                )
            finally:
                await stream.aclose()

        return StreamingResponse(events(), media_type="text/event-stream")

    return app
