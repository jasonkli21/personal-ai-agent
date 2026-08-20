"""FastAPI application entry point and Cloud Run health endpoints."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from personal_ai.api.routes import router as conversations_router
from personal_ai.storage import ResourceNotFoundError, StorageError

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


@app.exception_handler(StorageError)
async def storage_error(_: Request, __: StorageError) -> JSONResponse:
    """Map storage failures without disclosing provider-specific details."""
    return _error_response(503, "storage_unavailable", "Storage is temporarily unavailable.")


@app.get("/health")
async def health() -> dict[str, str]:
    """Minimal readiness endpoint used by Cloud Run and deployment checks."""
    return {"status": "ok", "service": "api"}


@app.post("/tasks/research")
async def receive_research_task(request: Request) -> dict[str, str]:
    """Acknowledge Pub/Sub push delivery; task processing is added in later phases."""
    await request.body()
    return {"status": "accepted", "service": "research-worker"}
