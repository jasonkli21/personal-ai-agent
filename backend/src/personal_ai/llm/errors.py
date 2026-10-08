"""Stable application errors exposed by language-model adapters."""


class LLMError(Exception):
    """Base error with a safe code suitable for application handling."""

    code = "llm_unavailable"


class LLMUnavailableError(LLMError):
    """The configured provider cannot currently serve the request."""

    code = "llm_unavailable"


class LLMTimeoutError(LLMError):
    """The provider did not complete within the configured timeout."""

    code = "llm_timeout"


class LLMInvalidConfigurationError(LLMError):
    """Local provider setup is absent or invalid."""

    code = "llm_invalid_configuration"


class LLMInvalidRequestError(LLMError):
    """The provider rejected the requested chat completion."""

    code = "llm_invalid_request"


class LLMInvalidResponseError(LLMError):
    """The provider returned output that violates application safety limits."""

    code = "llm_invalid_response"


class LLMIncompleteGenerationError(LLMError):
    """The provider ended a generation without a usable terminal success."""

    code = "llm_incomplete"


class LLMRejectedError(LLMError):
    """The provider explicitly rejected or blocked a generation request."""

    code = "llm_rejected"


class LLMUnsupportedCapabilityError(LLMError):
    """The selected provider runtime does not declare the requested operation."""

    code = "llm_unsupported_capability"
