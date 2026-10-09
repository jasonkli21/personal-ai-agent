"""CLI output stays portable; opt-in safe observation batches use the shared tier."""

import json
import logging

logger = logging.getLogger(__name__)


def emit(report, *, default=None, ensure_ascii=True):
    serialized = json.dumps(
        report, default=default, ensure_ascii=ensure_ascii, allow_nan=False
    )
    normalized = json.loads(serialized)
    print(json.dumps(normalized, indent=2, ensure_ascii=ensure_ascii))
    try:
        from personal_ai.artifacts.consumers import retain_evaluation
        from personal_ai.auth.scope import ApplicationScope
        from personal_ai.persistence.factory import persistence_factory
        from personal_ai.settings import get_settings

        settings = get_settings()
        if not settings.artifacts_enabled:
            return
        factory = persistence_factory(settings)
        # Retention requires a canonical owner; never silently attribute live output to local.
        owners = factory.principal_directory().active_owner_ids(limit=2)
        if len(owners) != 1:
            return
        rows = normalized if isinstance(normalized, list) else [normalized]
        retain_evaluation(
            factory.artifact_service(settings), rows, owner_id=owners[0], scope=ApplicationScope()
        )
    except Exception as error:  # noqa: BLE001 - optional retention must remain advisory
        logger.info("Optional evaluation artifact failed error_class=%s", type(error).__name__)
