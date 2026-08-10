"""Calevate voice-runtime — engine webhooks + in-call tool endpoints.

Run: uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime

LATENCY-CRITICAL (root CLAUDE.md hard rule 3). Handlers must:
  - verify HMAC before anything else,
  - ack in under 500ms,
  - defer all real work to ARQ,
  - do no heavy imports, no synchronous LLM calls, and no DB writes beyond the
    minimal event row.
This service is never redeployed casually — a dashboard deploy must not touch
live calls, so its deploy is never coupled to `api`.
"""

from fastapi import FastAPI

app = FastAPI(title="Calevate voice-runtime", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "voice-runtime"}
