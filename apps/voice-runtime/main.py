"""Calevate voice-runtime — engine webhooks + in-call tool endpoints.

Run: uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime
(the directory is hyphenated by decision D-18, so it is not importable as a module
path — `--app-dir` is how it gets on sys.path.)

LATENCY-CRITICAL (root CLAUDE.md hard rule 3). Handlers must:
  - verify authenticity per engine before anything else,
  - ack in under 500ms,
  - defer all real work to ARQ,
  - do no heavy imports, no synchronous LLM calls, and no DB writes beyond the
    minimal event row.

This service is never redeployed casually — a dashboard deploy must not touch live
calls, so its deploy is never coupled to `api`. It DOES reuse `apps/api/core` as a
library (bootstrap order, problem+json, logging, queue): shared library code is not
deploy coupling, and re-implementing the error shape here would guarantee drift. The
import surface is asserted by `import_surface_test.py`, which is what actually keeps
the latency promise honest.
"""

from apps.api.core.bootstrap import create_app
from apps.api.core.errors import install_error_handlers
from fastapi import FastAPI
from webhook_routes import router as webhook_router

app: FastAPI = create_app(
    service="voice-runtime",
    title="Calevate voice-runtime",
    version="0.1.0",
    # No CORS, no rate limiter, no load-shed middleware: no browser calls this service,
    # and an engine callback must ALWAYS land (BACKEND-PATTERNS §6 lists engine
    # webhooks among the never-shed prefixes).
    minimal=True,
)
install_error_handlers(app)
app.include_router(webhook_router)
