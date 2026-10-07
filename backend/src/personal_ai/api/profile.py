"""Owner-authenticated management for sparse AI-owned profile defaults."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from personal_ai.api.dependencies import (
    get_application_registry,
    get_current_owner_id,
    get_global_profile_repository,
    get_request_scope,
)
from personal_ai.applications.registry import ApplicationRegistry
from personal_ai.auth.scope import STANDALONE_APPLICATION_ID, RequestScope
from personal_ai.context.profile import (
    GlobalProfile,
    GlobalProfileRepository,
    GlobalProfileUpdate,
)

router = APIRouter(prefix="/v1/profile", tags=["profile"])


def _require_profile_owner_scope(scope: RequestScope) -> None:
    if scope.application_id != STANDALONE_APPLICATION_ID or scope.workspace_id is not None:
        raise HTTPException(status_code=404, detail="not_found")


@router.get("", response_model=GlobalProfile)
def read_profile(
    owner_id: Annotated[str, Depends(get_current_owner_id)],
    scope: Annotated[RequestScope, Depends(get_request_scope)],
    repository: Annotated[GlobalProfileRepository, Depends(get_global_profile_repository)],
) -> GlobalProfile:
    _require_profile_owner_scope(scope)
    return repository.get(owner_id)


@router.put("", response_model=GlobalProfile)
def update_profile(
    update: GlobalProfileUpdate,
    owner_id: Annotated[str, Depends(get_current_owner_id)],
    scope: Annotated[RequestScope, Depends(get_request_scope)],
    registry: Annotated[ApplicationRegistry, Depends(get_application_registry)],
    repository: Annotated[GlobalProfileRepository, Depends(get_global_profile_repository)],
) -> GlobalProfile:
    _require_profile_owner_scope(scope)
    if any(
        application_id not in registry.application_ids
        for entry in update.fields
        for application_id in entry.shared_with_applications
    ):
        raise HTTPException(status_code=422, detail="profile_sharing_application_not_registered")
    return repository.update(owner_id, update)
