"""Default-off owner-scoped provider usage inspection."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from personal_ai.api.dependencies import get_request_scope
from personal_ai.auth.scope import RequestScope
from personal_ai.persistence.factory import persistence_factory
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/developer", tags=["developer"])


@router.get("/provider-usage")
def provider_usage_summary(
    settings: Annotated[Settings, Depends(get_settings)],
    scope: Annotated[RequestScope, Depends(get_request_scope)],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict:
    if not settings.provider_usage_inspection_enabled:
        raise ResourceNotFoundError("provider usage inspection not found")
    accounting = persistence_factory(settings).provider_usage_accounting(settings)
    return accounting.summary(
        owner_id=scope.owner_id,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        days=days,
    )
