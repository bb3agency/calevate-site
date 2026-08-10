"""Calevate API — FastAPI modular monolith.

Run: uv run uvicorn apps.api.main:app --reload --port 8000

Module boundaries (TRD §1): tenancy, agents, engine, campaigns, ingest, postcall,
crm, analytics, billing, kb, integrations, compliance, audit. Each module owns its
tables; no cross-module SQL; they talk through service interfaces.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Calevate API",
    version="0.1.0",
    # Errors are RFC-9457 problem+json with user-safe messages (no internals).
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "api"}
