"""Owner-scoped account export and deletion-request controls."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from personal_ai.api.dependencies import get_current_owner_id, require_recent_auth
from personal_ai.auth.account_data import (
    AccountDataUnavailable,
    AccountRequestConflict,
    AccountRequestNotFound,
    ExportTooLarge,
    FirestoreAccountDataRepository,
)
from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/account", tags=["account"])


class _IdempotentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


def account_repository(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[FirestoreAccountDataRepository]:
    enabled = (
        settings.export_enabled
        if request.url.path == "/v1/account/export"
        else settings.deletion_enabled
    )
    # Dependency resolution precedes the handler's gate. Avoid credential or
    # datastore discovery for disabled account operations.
    if not enabled:
        raise ResourceNotFoundError("account action not found")
    try:
        repository = FirestoreAccountDataRepository(
            project_id=settings.firestore_project_id,
            emulator_host=settings.firestore_emulator_host,
        )
    except Exception as error:
        raise AccountDataUnavailable from error
    try:
        yield repository
    finally:
        repository.close()


@router.post("/export")
def export_account(
    payload: _IdempotentRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_recent_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[FirestoreAccountDataRepository, Depends(account_repository)],
):
    if not settings.export_enabled:
        raise ResourceNotFoundError("account export not found")
    try:
        exported = repository.export_owner(
            principal.owner_id,
            max_records=settings.export_max_records,
            max_bytes=settings.export_max_bytes,
        )
        repository.record_export(
            owner_id=principal.owner_id,
            idempotency_key=payload.idempotency_key,
            correlation_id=request.state.correlation_id,
        )
    except ExportTooLarge as error:
        raise HTTPException(status_code=413, detail="export_limit_exceeded") from error
    filename_date = datetime.now(UTC).date().isoformat()
    return JSONResponse(
        content=exported,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="personal-ai-export-{filename_date}.json"',
        },
    )


@router.post("/deletion")
def create_deletion_request(
    payload: _IdempotentRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_recent_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[FirestoreAccountDataRepository, Depends(account_repository)],
):
    if not settings.deletion_enabled:
        raise ResourceNotFoundError("account deletion not found")
    try:
        result = repository.create_deletion(
            owner_id=principal.owner_id,
            idempotency_key=payload.idempotency_key,
            correlation_id=request.state.correlation_id,
        )
    except AccountRequestConflict as error:
        raise HTTPException(status_code=409, detail="lifecycle_request_conflict") from error
    return result


@router.get("/deletion/{request_id}")
def get_deletion_request(
    request_id: UUID,
    owner_id: Annotated[str, Depends(get_current_owner_id)],
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[FirestoreAccountDataRepository, Depends(account_repository)],
):
    if not settings.deletion_enabled:
        raise ResourceNotFoundError("account deletion not found")
    try:
        return repository.get_deletion(owner_id=owner_id, request_id=request_id)
    except AccountRequestNotFound as error:
        raise ResourceNotFoundError("account deletion not found") from error


@router.post("/deletion/{request_id}/{action}")
def update_deletion_request(
    request_id: UUID,
    action: Literal["confirm", "cancel"],
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_recent_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[FirestoreAccountDataRepository, Depends(account_repository)],
):
    if not settings.deletion_enabled:
        raise ResourceNotFoundError("account deletion not found")
    try:
        return repository.transition_deletion(
            owner_id=principal.owner_id,
            request_id=request_id,
            action=action,
            correlation_id=request.state.correlation_id,
        )
    except AccountRequestNotFound as error:
        raise ResourceNotFoundError("account deletion not found") from error
    except AccountRequestConflict as error:
        raise HTTPException(status_code=409, detail="lifecycle_request_conflict") from error
