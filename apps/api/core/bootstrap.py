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
from types import FrameType
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

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
from apps.api.core.settings import get_settings, settings_scope, validate_bootstrap_env

log = get_logger(__name__)

#: What `signal.signal`/`signal.getsignal` deal in: a callable, `SIG_DFL`/`SIG_IGN`,
#: or `None` when the handler was not installed from Python.
_Handler = Callable[[int, FrameType | None], Any] | int | signal.Handlers | None

# Client realm, admin realm, and local dev. Prod origins come from the edge config;
# a wildcard is never acceptable here because sessions are cookie-backed.
DEFAULT_CORS_ORIGINS = [
    "https://app.calevate.tech",
    "https://admin.calevate.tech",
    "http://localhost:3000",
]


def _install_signal_handlers() -> None:
    """Add the restart ALERT to whatever the server already does about SIGTERM/SIGINT.

    ═══ THIS USED TO DESTROY THE DRAIN IT CLAIMED TO PROVIDE. ═══

    The docstring said "graceful drain … uvicorn already traps these; we add the alert",
    and the body then did `signal.signal(sig, _handler)` with a handler that RAISED
    `KeyboardInterrupt` — replacing uvicorn's handler rather than adding to it. The
    ordering makes that fatal: `Server.serve()` enters `capture_signals()` (which
    installs `handle_exit`) and only THEN runs `startup()`, which runs this lifespan. So
    this ran second and won.

    What was lost, measured rather than reasoned — a real `uvicorn.Server`, a request
    sleeping in a handler, `SIGTERM` delivered mid-flight: the `KeyboardInterrupt`
    escaped `asyncio.run` entirely. The in-flight request never completed, uvicorn's
    `shutdown()` — the code that closes the listening sockets and then WAITS for open
    connections under `timeout_graceful_shutdown` — never ran, and the lifespan's own
    `finally` (Redis close, span flush) never ran either. `stop_grace_period: 30s` in
    compose.prod.yml exists to give that drain room and had nothing to give it to.

    On `hooks.calevate.tech` that is the founder's exact fear made routine: voice-runtime
    is the only service with live calls on it, Bolna webhooks are at-most-once with no
    retry (D-31), and every deploy dropped whatever was in flight.

    THE FIX IS TO CHAIN, NOT TO REPLACE. The previous handler is captured and called, so
    uvicorn's `handle_exit` still sets `should_exit` and still drains. `KeyboardInterrupt`
    is kept for the case where nobody else installed anything (a bare `python -m`, a test
    harness) — there, raising it is the only way to stop, and there is no drain to lose.

    Idempotent against itself: a lifespan that runs twice must not capture its own
    handler as "the previous one" and recurse.
    """

    def _chain(previous: _Handler) -> _Handler:
        def _handler(signum: int, frame: FrameType | None) -> None:
            alert("PROCESS_RESTART", "signal_received", detail=signal.Signals(signum).name)
            if callable(previous):
                # Uvicorn's `handle_exit`: sets `should_exit`, and the main loop then
                # closes the sockets and waits for in-flight requests.
                previous(signum, frame)
                return
            # SIG_DFL/SIG_IGN — nothing is listening for this, so there is no drain to
            # preserve and stopping is on us.
            raise KeyboardInterrupt

        _handler.__calevate_chained__ = True  # type: ignore[attr-defined]
        return _handler

    for sig in (signal.SIGTERM, signal.SIGINT):
        # ValueError = not the main thread (tests, some ASGI servers): nothing to install.
        with suppress(ValueError):
            previous = signal.getsignal(sig)
            if getattr(previous, "__calevate_chained__", False):
                continue
            signal.signal(sig, _chain(previous))


class SettingsScopeMiddleware:
    """One request, one resolution of `Settings`. Raw ASGI, on purpose.

    NOT `BaseHTTPMiddleware`: that one runs the downstream app in a separate task with
    an anyio stream in between, which is real overhead on a 500ms ack budget and makes
    the lifetime of a ContextVar something you have to reason about rather than read.
    Three lines of ASGI have neither problem — the scope opens and closes around the
    same await, in the same task.

    Only `http`. A websocket has no bounded unit of work to pin to and lifespan runs
    before there is anything to pin, so both pass straight through and keep reading the
    process-wide answer.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with settings_scope():
            await self.app(scope, receive, send)


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

    # ADDED LAST, SO IT IS THE OUTERMOST, and that position is the whole point: the
    # configuration a request runs on has to be fixed before any other layer reads it,
    # including the error handler that renders a refusal and the middleware that decides
    # whether to shed. §2 step 5 locks the order of the middleware that TOUCHES a
    # request; this one touches nothing — it opens a scope and closes it — so it sits
    # outside that ladder rather than inside it.
    #
    # WHY IT EXISTS. Console config now reaches every process within ~5 seconds with no
    # restart, which means a refresh can land BETWEEN two `get_settings()` calls in one
    # request. Each call returns a coherent object; a request making two does not. Two
    # keys that must agree — a rate and the price it converts, a provider and its
    # credential — then produce a wrong answer rather than a stale one.
    #
    # Cost: one ContextVar set and one reset per request, on a scope that is not
    # entered for websockets or lifespan. Measured at ~1µs against a 500ms ack budget
    # (hard rule 3), and it removes a database-shaped hazard rather than adding one:
    # inside the scope `get_settings()` cannot even reach the `lru_cache`.
    app.add_middleware(SettingsScopeMiddleware)

    app.include_router(build_health_router(service))
    return app


__all__ = ["DEFAULT_CORS_ORIGINS", "SettingsScopeMiddleware", "create_app"]
