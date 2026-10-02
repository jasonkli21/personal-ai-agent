"""FastAPI application entry point and Cloud Run health endpoints."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from personal_ai.api.routes import router as conversations_router
from personal_ai.context import ContextError
from personal_ai.llm.errors import LLMError
from personal_ai.services import InvalidRetryTargetError
from personal_ai.settings import ContextBudgetInvalidError
from personal_ai.storage import ConversationConflictError, ResourceNotFoundError, StorageError

app = FastAPI(title="Personal AI System", version="0.1.0")
app.include_router(conversations_router)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Return the common safe JSON error envelope."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
    """Avoid exposing framework validation internals to API clients."""
    return _error_response(422, "validation_error", "Request validation failed.")


@app.exception_handler(ResourceNotFoundError)
async def resource_not_found(_: Request, __: ResourceNotFoundError) -> JSONResponse:
    """Map missing or foreign owner-scoped records to a safe 404."""
    return _error_response(404, "not_found", "The requested resource was not found.")


@app.exception_handler(ConversationConflictError)
async def conversation_conflict(_: Request, __: ConversationConflictError) -> JSONResponse:
    """Report concurrent conversation mutations without exposing store details."""
    return _error_response(409, "conversation_busy", "A response is already in progress. Please retry.")


@app.exception_handler(StorageError)
async def storage_error(_: Request, __: StorageError) -> JSONResponse:
    """Map storage failures without disclosing provider-specific details."""
    return _error_response(503, "storage_unavailable", "Storage is temporarily unavailable.")



@app.exception_handler(InvalidRetryTargetError)
async def invalid_retry_target(_: Request, __: InvalidRetryTargetError) -> JSONResponse:
    return _error_response(422, "invalid_retry_target", "This message cannot be retried.")


@app.get("/health")
async def health() -> dict[str, str]:
    """Minimal readiness endpoint used by Cloud Run and deployment checks."""
    return {"status": "ok", "service": "api"}


@app.post("/tasks/research")
async def receive_research_task(request: Request) -> dict[str, str]:
    """Acknowledge Pub/Sub push delivery; task processing is added in later phases."""
    await request.body()
    return {"status": "accepted", "service": "research-worker"}


@app.exception_handler(ContextError)
async def context_error(_: Request, error: ContextError) -> JSONResponse:
    message = (
        "This message exceeds the context budget. Edit it to a shorter message and retry."
        if error.code == "context_message_too_large" else "The context budget is invalid."
    )
    return _error_response(422, error.code, message)


@app.exception_handler(LLMError)
async def preparation_provider_error(_: Request, error: LLMError) -> JSONResponse:
    return _error_response(503, error.code, "Context preparation is unavailable. Please retry.")


@app.exception_handler(ContextBudgetInvalidError)
async def context_configuration_error(_: Request, __: ContextBudgetInvalidError) -> JSONResponse:
    return _error_response(503, "context_budget_invalid", "The context budget is invalid.")
