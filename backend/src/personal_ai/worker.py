"""Private Cloud Run entry point for bounded memory lifecycle push jobs."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError

from personal_ai.llm.memory import GeminiMemoryAdapter
from personal_ai.memory.lifecycle_jobs import (
    MemoryJobNotification,
    MemoryLifecycleCoordinator,
    MemoryLifecycleWorker,
    PubSubMemoryJobPublisher,
)
from personal_ai.memory.lifecycle_repositories import FirestoreMemoryLifecycleRepository
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.settings import Settings, get_settings
from personal_ai.storage import FirestoreMessageRepository
from personal_ai.storage.errors import ResourceNotFoundError, StorageError

logger = logging.getLogger(__name__)
app = FastAPI(title="Personal AI Memory Worker", version="0.1.0")


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
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )
    lifecycle = FirestoreMemoryLifecycleRepository(memories, messages)
    publisher = PubSubMemoryJobPublisher(settings)
    republisher = MemoryLifecycleCoordinator(
        settings, lifecycle, memories, publisher=publisher
    )
    worker = MemoryLifecycleWorker(
        settings,
        lifecycle,
        memories,
        messages,
        GeminiMemoryAdapter(settings),
    )
    return worker, republisher


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "memory-worker"}


@app.post("/tasks/memory", status_code=204)
async def receive_memory_task(request: Request) -> Response:
    """Accept authenticated Pub/Sub push envelopes containing opaque job IDs."""
    settings = get_settings()
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
        worker, _ = _components(settings)
        result = worker.process(notification.job_id)
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
