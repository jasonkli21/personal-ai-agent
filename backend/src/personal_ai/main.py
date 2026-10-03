"""FastAPI application entry point and Cloud Run health endpoints."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from personal_ai.agents.research.contracts import ResearchError
from personal_ai.api.account import router as account_router
from personal_ai.api.decisions import router as decisions_router
from personal_ai.api.domains import router as domains_router
from personal_ai.api.iterative_research import router as iterative_research_router
from personal_ai.api.research import router as research_router
from personal_ai.api.routes import router as conversations_router
from personal_ai.auth.account_data import AccountDataUnavailable
from personal_ai.auth.middleware import AuthenticationMiddleware
from personal_ai.context import ContextError
from personal_ai.decisions.repositories import DecisionError
from personal_ai.domains.contracts import DomainContractError
from personal_ai.domains.providers import DomainProviderError
from personal_ai.llm.errors import LLMError
from personal_ai.services import InvalidRetryTargetError
from personal_ai.settings import ContextBudgetInvalidError, validate_startup_configuration
from personal_ai.storage import ConversationConflictError, ResourceNotFoundError, StorageError


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_startup_configuration()
    yield


app = FastAPI(title="Personal AI System", version="0.1.0", lifespan=lifespan)
app.add_middleware(AuthenticationMiddleware)
app.include_router(conversations_router)
app.include_router(research_router)
app.include_router(iterative_research_router)
app.include_router(decisions_router)
app.include_router(domains_router)
app.include_router(account_router)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Return the common safe JSON error envelope."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
    """Avoid exposing framework validation internals to API clients."""
    return _error_response(422, "validation_error", "Request validation failed.")


@app.exception_handler(HTTPException)
async def http_exception(_: Request, error: HTTPException) -> JSONResponse:
    code = error.detail if isinstance(error.detail, str) else "request_rejected"
    message = {
        "authentication_required": "Sign in to continue.",
        "reauthentication_required": "Sign in again before this account action.",
        "feature_disabled": "This account action is not available.",
    }.get(code, "The request could not be completed.")
    headers = error.headers or {}
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


@app.exception_handler(ResourceNotFoundError)
async def resource_not_found(_: Request, __: ResourceNotFoundError) -> JSONResponse:
    """Map missing or foreign owner-scoped records to a safe 404."""
    return _error_response(404, "not_found", "The requested resource was not found.")


@app.exception_handler(ConversationConflictError)
async def conversation_conflict(_: Request, __: ConversationConflictError) -> JSONResponse:
    """Report concurrent conversation mutations without exposing store details."""
    return _error_response(
        409, "conversation_busy", "A response is already in progress. Please retry."
    )


@app.exception_handler(StorageError)
async def storage_error(_: Request, __: StorageError) -> JSONResponse:
    """Map storage failures without disclosing provider-specific details."""
    return _error_response(503, "storage_unavailable", "Storage is temporarily unavailable.")


@app.exception_handler(AccountDataUnavailable)
async def account_data_unavailable(_: Request, __: AccountDataUnavailable) -> JSONResponse:
    return _error_response(
        503, "account_data_unavailable", "Account data is temporarily unavailable."
    )


@app.exception_handler(InvalidRetryTargetError)
async def invalid_retry_target(_: Request, __: InvalidRetryTargetError) -> JSONResponse:
    return _error_response(422, "invalid_retry_target", "This message cannot be retried.")


@app.get("/health")
async def health() -> dict[str, str]:
    """Minimal readiness endpoint used by Cloud Run and deployment checks."""
    return {"status": "ok", "service": "api"}


@app.exception_handler(ContextError)
async def context_error(_: Request, error: ContextError) -> JSONResponse:
    message = (
        "This message exceeds the context budget. Edit it to a shorter message and retry."
        if error.code == "context_message_too_large"
        else "The context budget is invalid."
    )
    return _error_response(422, error.code, message)


@app.exception_handler(LLMError)
async def preparation_provider_error(_: Request, error: LLMError) -> JSONResponse:
    return _error_response(503, error.code, "Context preparation is unavailable. Please retry.")


@app.exception_handler(ContextBudgetInvalidError)
async def context_configuration_error(_: Request, __: ContextBudgetInvalidError) -> JSONResponse:
    return _error_response(503, "context_budget_invalid", "The context budget is invalid.")


@app.exception_handler(ResearchError)
async def research_error(_: Request, error: ResearchError) -> JSONResponse:
    return _error_response(
        error.status,
        error.code,
        "Research could not proceed. Check the session or start a new request.",
    )


@app.exception_handler(DecisionError)
async def decision_error(_: Request, error: DecisionError) -> JSONResponse:
    return _error_response(
        error.status,
        error.code,
        "The decision could not be completed. Check its evidence and constraints.",
    )


@app.exception_handler(DomainContractError)
async def domain_contract_error(_: Request, error: DomainContractError) -> JSONResponse:
    return _error_response(
        error.status,
        error.code,
        "The domain comparison could not be completed. Check its constraints and source evidence.",
    )


@app.exception_handler(DomainProviderError)
async def domain_provider_error(_: Request, error: DomainProviderError) -> JSONResponse:
    return _error_response(
        error.status, error.code, "The configured source is unavailable or declined the request."
    )
