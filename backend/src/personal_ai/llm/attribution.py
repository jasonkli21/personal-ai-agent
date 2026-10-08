"""Safe per-invocation attribution logging for non-chat generation paths."""

from __future__ import annotations


def log_generation_attribution(logger, operation: str, metadata, *, fallback_identity=None) -> None:
    identity = getattr(metadata, "identity", None) or fallback_identity
    usage = getattr(metadata, "usage", None)
    logger.info(
        "Generation invocation operation=%s provider=%s model=%s status=%s "
        "input_tokens=%s output_tokens=%s total_tokens=%s usage_source=%s "
        "usage_confidence=%s error_code=%s",
        operation,
        getattr(identity, "provider_id", "unavailable"),
        getattr(identity, "model_id", "unavailable"),
        getattr(metadata, "status", "unavailable"),
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(usage, "total_tokens", None),
        getattr(usage, "source", "unavailable"),
        getattr(usage, "confidence", "unavailable"),
        getattr(metadata, "error_code", "unavailable"),
    )
