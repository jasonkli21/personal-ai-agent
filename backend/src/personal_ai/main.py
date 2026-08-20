"""FastAPI application entry point and Cloud Run health endpoints."""

from fastapi import FastAPI, Request

app = FastAPI(title="Personal AI System", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Minimal readiness endpoint used by Cloud Run and deployment checks."""
    return {"status": "ok", "service": "api"}


@app.post("/tasks/research")
async def receive_research_task(request: Request) -> dict[str, str]:
    """Acknowledge Pub/Sub push delivery; task processing is added in later phases."""
    await request.body()
    return {"status": "accepted", "service": "research-worker"}
