"""Private Cloud Run entry point for bounded memory lifecycle push jobs."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID, uuid4

import anyio
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError

from personal_ai.agents.research.repositories import FirestoreResearchRepository
from personal_ai.auth.directory import FirestorePrincipalDirectory
from personal_ai.auth.service_tokens import (
    InvalidServiceToken,
    ServiceTokenVerificationUnavailable,
    verify_google_service_token,
)
from personal_ai.llm.memory import GeminiMemoryAdapter
from personal_ai.memory.lifecycle_jobs import (
    MemoryJobNotification,
    MemoryLifecycleCoordinator,
    MemoryLifecycleWorker,
    PubSubMemoryJobPublisher,
)
from personal_ai.memory.lifecycle_repositories import FirestoreMemoryLifecycleRepository
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.settings import Settings, get_settings, validate_startup_configuration
from personal_ai.storage import FirestoreMessageRepository
from personal_ai.storage.async_io import io_call
from personal_ai.storage.errors import ResourceNotFoundError, StorageError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_startup_configuration()
    yield


app = FastAPI(title="Personal AI Memory Worker", version="0.1.0", lifespan=lifespan)


class _PubSubMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: str


class _PubSubEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _PubSubMessage


def _components(settings: Settings):
    memories = FirestoreMemoryRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )
    messages = FirestoreMessageRepository(
        client=memories.client,
    )
    lifecycle = FirestoreMemoryLifecycleRepository(memories, messages)
    publisher = PubSubMemoryJobPublisher(settings)
    republisher = MemoryLifecycleCoordinator(settings, lifecycle, memories, publisher=publisher)
    worker = MemoryLifecycleWorker(
        settings,
        lifecycle,
        memories,
        messages,
        GeminiMemoryAdapter(settings),
    )
    return worker, republisher


def _process_memory_job(
    settings: Settings,
    job_id: UUID,
    application_id: str,
    workspace_id: str | None,
) -> str:
    worker, _ = _components(settings)
    return worker.process(job_id, application_id=application_id, workspace_id=workspace_id)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "memory-worker"}


@app.post("/tasks/memory", status_code=204)
async def receive_memory_task(request: Request) -> Response:
    """Accept authenticated Pub/Sub push envelopes containing opaque job IDs."""
    settings = get_settings()
    if settings.worker_push_auth_required:
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        try:
            await io_call(
                verify_google_service_token,
                token,
                audience=settings.worker_push_audience,
                service_account=settings.worker_push_service_account,
            )
        except InvalidServiceToken:
            logger.info("Memory job push rejected reason=invalid_service_identity")
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        except ServiceTokenVerificationUnavailable as error:
            logger.info("Memory job push unavailable error_class=%s", type(error).__name__)
            return Response(status_code=503)
    if settings.worker_kill_switch_enabled:
        return Response(status_code=204)
    if not settings.memory_enabled or not settings.memory_lifecycle_worker_enabled:
        return Response(status_code=204)

    try:
        if int(request.headers.get("content-length", "0")) > 4096:
            return Response(status_code=204)
        body = await request.body()
        if len(body) > 4096:
            return Response(status_code=204)
        envelope_data: Any = json.loads(body)
        envelope = _PubSubEnvelope.model_validate(envelope_data)
        payload = base64.b64decode(envelope.message.data, validate=True)
        notification = MemoryJobNotification.model_validate_json(payload)
    except (ValueError, TypeError, ValidationError, binascii.Error, json.JSONDecodeError):
        # Malformed push data is permanent. Acknowledge without logging the payload.
        logger.info("Memory job push acknowledged reason=invalid_envelope")
        return Response(status_code=204)

    try:
        # Firestore, embeddings and service-token verification are synchronous;
        # keep them off the request loop so one slow job cannot stall health/push.
        result = await io_call(
            _process_memory_job,
            settings,
            notification.job_id,
            notification.application_id,
            notification.workspace_id,
        )
    except ResourceNotFoundError:
        return Response(status_code=204)
    except StorageError as error:
        logger.info("Memory worker unavailable error_class=%s", type(error).__name__)
        return Response(status_code=503)
    except Exception as error:  # noqa: BLE001 - transient infrastructure errors retry via Pub/Sub
        logger.info("Memory worker failed error_class=%s", type(error).__name__)
        return Response(status_code=503)

    if result in ("completed", "disabled"):
        return Response(status_code=204)
    return Response(status_code=503)


@app.post("/tasks/maintenance")
async def run_scheduled_maintenance(request: Request) -> Response:
    """Run bounded, authenticated maintenance without physically deleting records."""
    settings = get_settings()
    if settings.worker_maintenance_auth_required:
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        try:
            await io_call(
                verify_google_service_token,
                token,
                audience=settings.worker_maintenance_audience,
                service_account=settings.worker_maintenance_service_account,
            )
        except InvalidServiceToken:
            logger.info("Scheduled maintenance rejected reason=invalid_service_identity")
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        except ServiceTokenVerificationUnavailable as error:
            logger.info("Scheduled maintenance unavailable error_class=%s", type(error).__name__)
            return Response(status_code=503)
    if settings.worker_kill_switch_enabled or not settings.maintenance_enabled:
        return Response(status_code=204)

    try:
        directory = FirestorePrincipalDirectory(
            project_id=settings.firestore_project_id,
            emulator_host=settings.firestore_emulator_host,
        )
        owner_ids = await anyio.to_thread.run_sync(partial(directory.active_owner_ids, limit=2))
        if not owner_ids:
            logger.info("Scheduled maintenance completed reason=no_active_owner")
            return Response(status_code=204)
        if len(owner_ids) != 1:
            logger.error("Scheduled maintenance rejected reason=multiple_active_owners")
            return Response(status_code=503)
        _, republisher = await anyio.to_thread.run_sync(_components, settings)
        published = await anyio.to_thread.run_sync(
            partial(republisher.republish_pending, limit=settings.memory_job_candidate_limit)
        )
        research = FirestoreResearchRepository(
            project_id=settings.firestore_project_id,
            emulator_host=settings.firestore_emulator_host,
        )
        expired = await anyio.to_thread.run_sync(
            partial(
                research.expire_due_for_owner,
                owner_ids[0],
                now=datetime.now(UTC),
                correlation_id=str(uuid4()),
                limit=settings.maintenance_batch_size,
            )
        )
    except Exception as error:  # noqa: BLE001 - scheduler retries transient operational failures
        logger.info("Scheduled maintenance failed error_class=%s", type(error).__name__)
        return Response(status_code=503)
    logger.info(
        "Scheduled maintenance completed republished=%d expired_sessions=%d", published, expired
    )
    return Response(
        content=json.dumps({"republished_jobs": published, "expired_sessions": expired}),
        media_type="application/json",
    )
