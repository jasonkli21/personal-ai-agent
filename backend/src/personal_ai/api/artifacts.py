"""Private, scoped artifact retrieval through the existing verified request boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from personal_ai.api.dependencies import get_request_scope
from personal_ai.artifacts.contracts import ArtifactUnavailable
from personal_ai.auth.scope import ApplicationScope, RequestScope
from personal_ai.persistence.factory import persistence_factory
from personal_ai.settings import Settings, get_settings

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
def read_artifact(
    artifact_id: UUID,
    scope: Annotated[RequestScope, Depends(get_request_scope)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    if not settings.artifacts_enabled:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        service = persistence_factory(settings).artifact_service(settings)
        value = service.read(
            artifact_id,
            owner_id=scope.owner_id,
            scope=ApplicationScope(
                application_id=scope.application_id, workspace_id=scope.workspace_id
            ),
        )
    except ArtifactUnavailable as error:
        raise HTTPException(status_code=404, detail="artifact_unavailable") from error
    return JSONResponse(content=value, headers={"Cache-Control": "no-store"})
