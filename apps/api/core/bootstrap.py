"""The locked bootstrap order (BACKEND-PATTERNS §2). Deviations need a decision entry.

1. Bootstrap-env validation (DATABASE_URL/REDIS_URL class only — fail fast)
2. Tenant-safe config load (Pydantic Settings)
3. Tracing init (OTel) before the app exists
4. App build: body limit, log redaction path list, trust-proxy as a CIDR predicate
5. Middleware in FIXED order: security headers → CORS → auth → rate limit →
   error handler → observability (correlation id) → routes
6. Raw-body preservation for webhook routes (voice-runtime)
7. Signal handlers: graceful drain; unhandled-exception handlers that alert THEN exit

`create_app()` is shared by `api` and `voice-runtime` so neither can drift from the
order; voice-runtime passes `minimal=True` to skip everything it does not pay for on
the latency path (hard rule 3).
"""

from __future__ import annotations

import signal
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from apps.api.core.alerting import alert
from apps.api.core.health import build_health_router
from apps.api.core.logging import configure_logging, get_logger
from apps.api.core.middleware import install_middleware
from apps.api.core.observability import (
    TracingMiddleware,
    init_observability,
    shutdown_tracing,
    tracing_enabled,
)
from apps.api.core.redis import close_redis
from apps.api.core.settings import get_settings, validate_bootstrap_env

log = get_logger(__name__)

# Client realm, admin realm, and local dev. Prod origins come from the edge config;
# a wildcard is never acceptable here because sessions are cookie-backed.
DEFAULT_CORS_ORIGINS = [
    "https://app.calevate.tech",
    "https://admin.calevate.tech",
    "http://localhost:3000",
]


def _install_signal_handlers() -> None:
    """Graceful drain on SIGTERM/SIGINT. Uvicorn already traps these; we add the
    alert so a restart loop is visible in the alert stream, not just in logs (§8)."""

    def _handler(signum: int, _frame: object) -> None:
        alert("PROCESS_RESTART", "signal_received", detail=signal.Signals(signum).name)
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGINT):
        # ValueError = not the main thread (tests, some ASGI servers): nothing to install.
        with suppress(ValueError):
            signal.signal(sig, _handler)


def create_app(
    *,
    service: str,
    title: str,
    version: str = "0.1.0",
    minimal: bool = False,
    cors_origins: list[str] | None = None,
    on_startup: Callable[[], AsyncIterator[None]] | None = None,
) -> FastAPI:
    # 1. Bootstrap-env validation — fail fast with an operator-actionable message.
    validate_bootstrap_env()
    # 2. Tenant-safe config load.
    settings = get_settings()
    # 4. Log redaction path list is installed with the formatter.
    configure_logging("INFO" if settings.app_env != "local" else "DEBUG")
    # 3. Tracing/error reporting, BEFORE the app exists so a failure during app build
    # is still captured. Config-gated and scrubbed (hard rule 6).
    observability = init_observability(service)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _install_signal_handlers()
        log.info(
            "service_start",
            extra={
                "service": service,
                "env": settings.app_env,
                # An operator should see at a glance whether errors go anywhere.
                "observability": observability,
                "release": settings.release_version,
            },
        )
        if on_startup is not None:
            async for _ in on_startup():
                break
        try:
            yield
        finally:
            log.info("service_stop", extra={"service": service})
            await close_redis()
            # Flush before the process goes: an un-exported span is a span that never
            # happened, and a drain is exactly when the interesting ones are in flight.
            shutdown_tracing()

    app = FastAPI(
        title=title,
        version=version,
        lifespan=lifespan,
        # Errors are RFC-9457 problem+json with user-safe messages (hard rule).
        responses={
            "default": {
                "description": "RFC-9457 problem+json",
                "content": {"application/problem+json": {}},
            }
        },
    )

    # 5. Middleware, outermost last. Error handlers are registered by the caller for
    # `api`; voice-runtime installs them too but adds no CORS (no browser calls it).
    #
    # The tracing middleware is added FIRST, which Starlette makes it the INNERMOST —
    # it runs just inside CorrelationIdMiddleware, so the server span can carry the
    # correlation id that every log line and audit row already carries (§2 step 5 puts
    # observability last before routes for the same reason).
    #
    # It is added only when tracing actually came up, which is what makes it acceptable
    # on the latency-critical service (hard rule 3). MEASURED on the receiver's ASGI
    # chain: 0.5µs with tracing off — this middleware is not in the chain at all, so a
    # deploy without a collector is byte-for-byte today's service; 44µs when tracing is
    # on and the trace is not sampled (the 90% case at the default ratio); 84µs when it
    # is sampled and exported. Against a 500ms ack budget that is 0.017% at worst, and
    # the SDK import (~79ms, ~220ms with the exporter, vs fastapi's own ~456ms) is paid
    # once at boot. Export is batched on a background thread and drops rather than
    # blocks, so a sick collector cannot reach the ack path.
    if tracing_enabled():
        app.add_middleware(TracingMiddleware, trust_incoming_traceparent=not minimal)
    if not minimal:
        install_middleware(app, cors_origins=cors_origins or DEFAULT_CORS_ORIGINS)

    app.include_router(build_health_router(service))
    return app


__all__ = ["DEFAULT_CORS_ORIGINS", "create_app"]
