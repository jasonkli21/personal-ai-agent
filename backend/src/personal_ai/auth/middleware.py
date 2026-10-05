"""Application-wide authentication and safe request telemetry middleware."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from functools import partial
from uuid import uuid4

import anyio
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import MutableHeaders
from starlette.routing import Match

from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.auth.directory import (
    FirestorePrincipalDirectory,
    IdentityDirectoryUnavailable,
    IdentityMappingConflict,
    InMemoryPrincipalDirectory,
    PrincipalDirectory,
)
from personal_ai.auth.safeguards import (
    FirestoreSafeguardStore,
    InMemorySafeguardStore,
    SafeguardDenied,
    SafeguardStore,
    SafeguardUnavailable,
)
from personal_ai.auth.verification import (
    IdentityProviderUnavailable,
    InvalidIdentityToken,
    principal_from_google_token,
)
from personal_ai.settings import ContextBudgetInvalidError, Settings, get_settings

logger = logging.getLogger(__name__)
PUBLIC_PATHS = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
_store_initialization_lock = threading.Lock()
MAX_ITINERARY_PROPOSAL_REQUEST_BYTES = 262_144
MAX_BOOKING_EXTRACTION_REQUEST_BYTES = 1_300_000


def _settings_for_request(request: Request) -> Settings:
    """Honor FastAPI's settings override in tests without weakening production config."""
    override = request.app.dependency_overrides.get(get_settings)
    return override() if override is not None else get_settings()


def _identity_token(request: Request) -> str | None:
    forwarded = request.headers.get("x-user-id-token")
    authorization = request.headers.get("authorization", "")
    if forwarded:
        return forwarded.removeprefix("Bearer ").strip()
    if authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return None


def _has_matching_route(request: Request) -> bool:
    """Let the router return a safe 404/405 without requiring app config."""
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match in {Match.FULL, Match.PARTIAL}:
            return True
    return False


def _directory(request: Request, settings: Settings) -> PrincipalDirectory:
    configured = getattr(request.app.state, "principal_directory", None)
    if configured is not None:
        return configured
    with _store_initialization_lock:
        configured = getattr(request.app.state, "principal_directory", None)
        if configured is None:
            if settings.app_environment in {"local", "test"}:
                configured = InMemoryPrincipalDirectory()
            else:
                try:
                    configured = FirestorePrincipalDirectory(
                        project_id=settings.firestore_project_id,
                        emulator_host=settings.firestore_emulator_host,
                    )
                except Exception as error:
                    raise IdentityDirectoryUnavailable from error
            request.app.state.principal_directory = configured
        return configured


def _safeguards(request: Request, settings: Settings) -> SafeguardStore:
    configured = getattr(request.app.state, "safeguard_store", None)
    if configured is not None:
        return configured
    with _store_initialization_lock:
        configured = getattr(request.app.state, "safeguard_store", None)
        if configured is None:
            if settings.app_environment in {"local", "test"}:
                configured = InMemorySafeguardStore()
            else:
                try:
                    configured = FirestoreSafeguardStore(
                        project_id=settings.firestore_project_id,
                        emulator_host=settings.firestore_emulator_host,
                    )
                except Exception as error:
                    raise SafeguardUnavailable from error
            request.app.state.safeguard_store = configured
        return configured


def _ensure_active_principal(request, settings, principal, correlation_id) -> None:
    # Client construction may discover credentials, so it belongs in the same
    # worker thread as the first Firestore call.
    _directory(request, settings).ensure_active(principal, correlation_id=correlation_id)


def _enforce_safeguards(request, settings, principal) -> None:
    store = _safeguards(request, settings)
    store.consume_request(principal.owner_id, settings.api_rate_limit_per_minute)
    calls, tokens = _provider_reservation(request, settings)
    if calls or tokens:
        store.reserve_daily(
            principal.owner_id,
            calls,
            tokens,
            settings.provider_calls_per_day_limit,
            settings.input_tokens_per_day_limit,
        )


def _provider_reservation(request: Request, settings: Settings) -> tuple[int, int]:
    """Estimate request usage; this is not accounting for every provider RPC.

    Token counting, summary refresh, embeddings and worker activity can make
    additional calls. See the operational review before treating these counters
    as a provider-spend ceiling.
    """
    if request.method != "POST":
        return (0, 0)
    path = request.url.path
    uses_external = False
    if path.startswith("/v1/conversations/") and path.endswith(
        ("/messages", "/regenerate", "/edit-and-retry")
    ):
        calls = 2 + int(settings.memory_enabled) + int(settings.memory_extraction_enabled)
        uses_external = settings.ai_provider != "fake"
        tokens = settings.max_context_tokens
    elif path.startswith("/v1/research/") and path.endswith("/run"):
        calls = settings.research_max_queries * settings.research_attempt_limit + 2
        tokens = settings.research_max_evidence_context_tokens
        uses_external = settings.research_search_adapter != "fake" or settings.ai_provider != "fake"
    elif path == "/v1/research/iterative" or (
        path.endswith("/resume") and path.startswith("/v1/research/iterative/runs/")
    ):
        calls = settings.iterative_max_queries * settings.iterative_max_iterations + 2
        tokens = settings.iterative_max_tokens
        uses_external = settings.research_search_adapter != "fake" or settings.ai_provider != "fake"
    elif path.startswith("/v1/domains/") and path.endswith("/lookup"):
        calls, tokens = 1, 0
        uses_external = (
            path.startswith("/v1/domains/travel/") and settings.travel_places_adapter != "fake"
        ) or (
            path.startswith("/v1/domains/shopping/")
            and settings.shopping_products_adapter != "fake"
        )
    elif path == "/v1/travel/itinerary-proposals":
        calls = 1
        tokens = settings.itinerary_proposal_max_input_tokens
        uses_external = settings.itinerary_proposal_generator == "gemini"
    elif path == "/v1/travel/booking-extractions":
        calls = 1
        tokens = settings.booking_extraction_max_input_tokens
        uses_external = settings.booking_extraction_generator == "gemini"
    else:
        return (0, 0)
    return (calls, tokens) if uses_external else (0, 0)


def _provider_switch_is_on(request: Request, settings: Settings) -> bool:
    path = request.url.path
    method = request.method
    if (
        settings.chat_kill_switch_enabled
        and path.startswith("/v1/conversations/")
        and method in {"POST", "PUT", "PATCH", "DELETE"}
    ):
        return True
    if (
        settings.research_kill_switch_enabled
        and path.startswith(("/v1/research", "/v1/iterative-research"))
        and method in {"POST", "PUT", "PATCH"}
    ):
        return True
    return settings.external_providers_kill_switch_enabled and _provider_reservation(
        request, settings
    ) != (0, 0)


def _safeguard_error(
    request: Request,
    correlation_id: str,
    status_code: int,
    code: str,
    message: str,
    *,
    retry_after: int | None = None,
) -> JSONResponse:
    response_headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return _error(
        status_code,
        code,
        message,
        request=request,
        correlation_id=correlation_id,
        headers=response_headers,
    )


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    challenge: bool = False,
    request: Request | None = None,
    correlation_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    if challenge:
        response_headers["WWW-Authenticate"] = "Bearer"
    if headers:
        response_headers.update(headers)
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=response_headers,
    )
    return (
        _harden_response(response, request, correlation_id)
        if request and correlation_id
        else response
    )


async def authenticate_request(request: Request) -> Response | None:
    """Validate a request before dispatch; ``None`` lets the ASGI app handle it."""
    correlation_id = request.headers.get("x-request-id", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", correlation_id):
        correlation_id = str(uuid4())
    request.state.correlation_id = correlation_id
    if request.url.path in PUBLIC_PATHS and not request.headers.get("origin"):
        return None

    if request.method != "OPTIONS" and not _has_matching_route(request):
        return None

    try:
        settings = _settings_for_request(request)
    except ContextBudgetInvalidError:
        logger.error("request_rejected reason=context_budget_invalid")
        return _error(
            503,
            "context_budget_invalid",
            "The context budget is invalid.",
            request=request,
            correlation_id=correlation_id,
        )
    except Exception as error:  # noqa: BLE001 - configuration errors fail closed
        logger.error(
            "request_rejected reason=configuration_unavailable error_class=%s", type(error).__name__
        )
        return _error(
            503,
            "service_configuration_unavailable",
            "The service is temporarily unavailable.",
            request=request,
            correlation_id=correlation_id,
        )

    origin = request.headers.get("origin")
    if origin:
        allowed_origins = settings.allowed_web_origins
        if origin not in allowed_origins:
            logger.info("request_rejected reason=origin_denied")
            return _error(
                403,
                "origin_denied",
                "This request origin is not allowed.",
                request=request,
                correlation_id=correlation_id,
            )
        if request.method == "OPTIONS":
            allowed_methods = {"GET", "POST", "OPTIONS"}
            requested_method = request.headers.get("access-control-request-method", "").upper()
            allowed_headers = {"authorization", "content-type", "last-event-id", "x-request-id"}
            requested_headers = {
                header.strip().lower()
                for header in request.headers.get("access-control-request-headers", "").split(",")
                if header.strip()
            }
            if (
                requested_method and requested_method not in allowed_methods
            ) or not requested_headers.issubset(allowed_headers):
                logger.info("request_rejected reason=preflight_denied")
                return _error(
                    403,
                    "origin_denied",
                    "This request origin is not allowed.",
                    request=request,
                    correlation_id=correlation_id,
                )
            response = Response(status_code=204)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = ", ".join(sorted(allowed_methods))
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, Last-Event-ID, X-Request-ID"
            )
            response.headers["Access-Control-Max-Age"] = "600"
            response.headers["Vary"] = "Origin"
            return _harden_response(response, request, correlation_id)
        request.state.allowed_origin = origin

    if request.url.path not in PUBLIC_PATHS:
        if settings.auth_mode == "development" and settings.app_environment in {"local", "test"}:
            request.state.principal = AuthenticatedPrincipal.development()
        else:
            token = _identity_token(request)
            if token is None:
                logger.info("request_rejected reason=missing_identity")
                return _error(
                    401,
                    "authentication_required",
                    "Sign in to continue.",
                    challenge=True,
                    request=request,
                    correlation_id=correlation_id,
                )
            try:
                principal = await anyio.to_thread.run_sync(
                    principal_from_google_token, token, settings
                )
            except InvalidIdentityToken:
                logger.info("request_rejected reason=invalid_identity")
                return _error(
                    401,
                    "invalid_identity",
                    "Sign in again to continue.",
                    challenge=True,
                    request=request,
                    correlation_id=correlation_id,
                )
            except IdentityProviderUnavailable as error:
                logger.info(
                    "request_rejected reason=identity_provider_unavailable error_class=%s",
                    type(error).__name__,
                )
                return _error(
                    503,
                    "authentication_unavailable",
                    "Authentication is temporarily unavailable.",
                    request=request,
                    correlation_id=correlation_id,
                )

            try:
                await anyio.to_thread.run_sync(
                    partial(
                        _ensure_active_principal,
                        request,
                        settings,
                        principal,
                        correlation_id,
                    )
                )
            except IdentityMappingConflict:
                logger.info("request_rejected reason=inactive_principal")
                return _error(
                    403,
                    "access_denied",
                    "This account is not enabled for this application.",
                    request=request,
                    correlation_id=correlation_id,
                )
            except IdentityDirectoryUnavailable as error:
                logger.error(
                    "request_rejected reason=identity_directory_unavailable error_class=%s",
                    type(error).__name__,
                )
                return _error(
                    503,
                    "authentication_unavailable",
                    "Authentication is temporarily unavailable.",
                    request=request,
                    correlation_id=correlation_id,
                )
            request.state.principal = principal

    if request.url.path not in PUBLIC_PATHS:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return _error(
                401,
                "authentication_required",
                "Sign in to continue.",
                challenge=True,
                request=request,
                correlation_id=correlation_id,
            )
        if _provider_switch_is_on(request, settings):
            return _safeguard_error(
                request,
                correlation_id,
                503,
                "provider_disabled",
                "This capability is temporarily disabled.",
            )
        # Local and test defaults stay friction-free; focused tests can inject an
        # explicit store to exercise enforcement. Staging and production always
        # use durable counters and fail closed if Firestore is unavailable.
        enforce_safeguards = (
            settings.app_environment not in {"local", "test"}
            or getattr(request.app.state, "safeguard_store", None) is not None
        )
        if not enforce_safeguards:
            return None
        try:
            await anyio.to_thread.run_sync(
                partial(_enforce_safeguards, request, settings, principal)
            )
        except SafeguardDenied as error:
            logger.info("request_rejected reason=%s", error.code)
            return _safeguard_error(
                request,
                correlation_id,
                429,
                error.code,
                "A request limit has been reached. Please retry later.",
                retry_after=error.retry_after,
            )
        except SafeguardUnavailable as error:
            logger.error(
                "request_rejected reason=safeguard_unavailable error_class=%s", type(error).__name__
            )
            return _safeguard_error(
                request,
                correlation_id,
                503,
                "safety_limits_unavailable",
                "The service is temporarily unavailable.",
            )

    return None


class AuthenticationMiddleware:
    """Pure ASGI middleware that preserves cancellation for streamed responses."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        started = time.monotonic()
        response = await authenticate_request(request)
        correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
        status_code = 500
        app_receive = receive

        if (
            response is None
            and scope.get("method") == "POST"
            and scope.get("path")
            in {
                "/v1/travel/itinerary-proposals",
                "/v1/travel/booking-extractions",
            }
        ):
            is_extraction_request = scope.get("path") == "/v1/travel/booking-extractions"
            settings = _settings_for_request(request)
            body_limit = (
                MAX_BOOKING_EXTRACTION_REQUEST_BYTES
                if scope.get("path") == "/v1/travel/booking-extractions"
                else MAX_ITINERARY_PROPOSAL_REQUEST_BYTES
            )
            content_length = request.headers.get("content-length")
            too_large = False
            if content_length is not None:
                try:
                    too_large = int(content_length) > body_limit
                except ValueError:
                    too_large = True
            chunks: list[bytes] = []
            received = 0
            disconnected = False
            body_timed_out = False
            operation_timeout = (
                settings.booking_extraction_timeout_seconds
                if is_extraction_request
                else settings.itinerary_proposal_timeout_seconds
            )
            deadline = time.monotonic() + operation_timeout
            if is_extraction_request:
                request.state.booking_extraction_deadline = deadline
            while not too_large:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    body_timed_out = True
                    break
                try:
                    message = await asyncio.wait_for(receive(), timeout=remaining)
                except TimeoutError:
                    body_timed_out = True
                    break
                if message["type"] == "http.disconnect":
                    disconnected = True
                    break
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > body_limit:
                    too_large = True
                    break
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            if too_large:
                code, message = (
                    ("proposal_request_too_large", "The proposal request exceeds its size limit.")
                    if scope.get("path") == "/v1/travel/itinerary-proposals"
                    else ("request_body_too_large", "The request exceeds its size limit.")
                )
                response = _error(
                    413,
                    code,
                    message,
                    request=request,
                    correlation_id=correlation_id,
                )
            elif body_timed_out:
                response = _error(
                    408,
                    "booking_extraction_deadline_exceeded",
                    "The extraction request exceeded its total time limit.",
                    request=request,
                    correlation_id=correlation_id,
                )
            else:
                payload = b"".join(chunks)
                first = True

                async def replay_limited_body():
                    nonlocal first
                    if first:
                        first = False
                        return {"type": "http.request", "body": payload, "more_body": False}
                    if disconnected:
                        return {"type": "http.disconnect"}
                    return await receive()

                app_receive = replay_limited_body

        async def harden_send(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Request-ID", correlation_id)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Cache-Control", "no-store")
                allowed_origin = getattr(request.state, "allowed_origin", None)
                if allowed_origin:
                    headers.setdefault("Access-Control-Allow-Origin", allowed_origin)
                    headers.setdefault("Vary", "Origin")
                if scope.get("scheme") == "https":
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        try:
            if response is None:
                await self.app(scope, app_receive, harden_send)
            else:
                await response(scope, receive, harden_send)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "protected")
            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            logger.info(
                "api_request method=%s route=%s status=%d duration_ms=%d request_id=%s",
                scope.get("method", "GET"),
                route_template,
                status_code,
                elapsed_ms,
                correlation_id,
            )


def _harden_response(response: Response, request: Request, correlation_id: str) -> Response:
    response.headers.setdefault("X-Request-ID", correlation_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    allowed_origin = getattr(request.state, "allowed_origin", None)
    if allowed_origin:
        response.headers.setdefault("Access-Control-Allow-Origin", allowed_origin)
        response.headers.setdefault("Vary", "Origin")
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response
