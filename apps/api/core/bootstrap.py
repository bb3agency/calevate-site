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
from typing import Any, Final

from fastapi import FastAPI, Request
from starlette.types import ASGIApp, Receive, Scope, Send

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.health import HealthDetailGate, build_health_router
from apps.api.core.logging import configure_logging, get_logger
from apps.api.core.middleware import install_middleware
from apps.api.core.observability import (
    TracingMiddleware,
    init_observability,
    shutdown_tracing,
    tracing_enabled,
)
from apps.api.core.queue import close_queue
from apps.api.core.redis import close_redis
from apps.api.core.settings import get_settings, settings_scope, validate_bootstrap_env

log = get_logger(__name__)

#: What `signal.signal`/`signal.getsignal` deal in: a callable, `SIG_DFL`/`SIG_IGN`,
#: or `None` when the handler was not installed from Python.
_Handler = Callable[[int, FrameType | None], Any] | int | signal.Handlers | None

# Every origin this product's own pages are served from. A wildcard is never acceptable
# here because sessions are cookie-backed (`install_middleware` refuses one outright).
#
# THIS LIST IS READ TWICE, and the second reader is why an omission here is not merely a
# CORS inconvenience: `authn/cookies.enforce_same_origin` uses the SAME list as its CSRF
# `Origin` allowlist, deliberately, so that there is not a second list to keep in step. A
# missing origin therefore fails a request twice over — the browser refuses the response
# for want of `Access-Control-Allow-Origin`, and the API would refuse the request as
# cross-site even if the browser did not.
#
# THE APEX WAS MISSING, AND IT BROKE SIGN-IN, PASSWORD RESET AND THE MARKETING HEADER.
# Reported from the live site as "we could not reach Calevate" on correct credentials —
# which is exactly what a CORS-blocked `fetch` looks like from `lib/authn/transport.ts`:
# the request never completes, so the browser reports a network failure and the console
# renders `authn_unreachable`. The console was right that it could not reach us.
#
# `https://calevate.tech` is not an optional extra. The marketing page mounts
# `MarketingAccountNav`, which asks `GET /v1/auth/client/session` on every load because
# the session cookie is `HttpOnly` and "are you already signed in" cannot be answered any
# other way; and `/auth/sign-in`, `/auth/forgot-password` and `/auth/reset-password` are
# served on that hostname too, since only `/admin` and `/c/` are refused there.
#
# `https://www.calevate.tech` is deliberately NOT here. The `www` vhost is a server-scope
# `return 301` to the apex, so the browser follows the redirect before any of our script
# runs and `www` never becomes a document origin. Adding an origin that cannot occur
# widens the CSRF allowlist for nothing.
DEFAULT_CORS_ORIGINS = [
    "https://calevate.tech",
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


#: How many health-detail authorisations may run at once before the rest are denied the
#: detail. Two, because the number only has to cover the humans who ask during one
#: incident — a third simultaneous operator retries and gets it — while being small
#: enough that this route cannot spend the shared thread pool `auth._signing_key_for`
#: runs on. See `_ops_detail_gate` for why an unmetered route needs a number here at all.
_DETAIL_GATE_CONCURRENCY: Final = 2


def _ops_detail_gate() -> HealthDetailGate:
    """Answers "may this caller be told why we are unhealthy?" via the ONE ladder.

    `core.health` publishes a status word to everybody and its detail — which dependency
    is down, how far behind the queue is, WHICH configuration keys are not installed —
    to `ops:manage` only. `ops:manage` and not `platform:config` because this is the
    INCIDENT surface, which is the distinction `rbac.Permission` already draws in
    writing: its holders are whoever is on call, and "why is readiness red" is the first
    question they ask.

    IMPORTED INSIDE THE FUNCTION, which is the one thing here that is not stylistic.
    `core.auth` pulls the whole authentication and audit graph in behind it, and
    `core.health` sits on voice-runtime's pinned import surface
    (`tests/voice_runtime_import_surface_test.py`, which lists `httpx` as forbidden).
    Building the gate only for the non-minimal app therefore keeps that surface
    byte-for-byte what it was — and the existing test is what proves it, rather than
    this comment.

    A refusal is an ANSWER here, not an error: a probe must never 500 because the auth
    machinery it consults is unavailable. So the two failure classes are separated
    rather than swallowed together — "you did not present an `ops:manage` credential"
    is the ordinary case and is silent, "the check itself could not run" is not
    ordinary and gets a line an operator can act on.

    ═══ AND IT IS BOUNDED, BECAUSE OF WHERE IT IS MOUNTED ═══

    This gate put an AUTHENTICATION ATTEMPT on `/healthz` and `/healthz/ready`, which are
    the two routes in the process with `ratelimit.PROFILES["exempt"]` — no per-client
    limit at all, deliberately, because a probe must answer during an incident. What sits
    behind an authentication attempt is `auth._signing_key_for`, whose own docstring says
    it plainly: `PyJWKClient.get_signing_key` refetches the whole key set whenever the
    `kid` is unknown and never memoises the failure, so ANY caller can force one fetch per
    request by varying one field of an unsigned JWT, "and on `/healthz*` there is not even
    a rate-limit profile in front of it". That fix moved the fetch off the event loop and
    on to `asyncio.to_thread`; the thread pool it moved onto is `min(32, cpu+4)` threads
    wide and is shared with every other blocking call in the process, so an unmetered
    route feeding it is still an amplifier — a smaller one, aimed at a scarcer resource.
    The half that was left open is the mounting, and that is this function's, not
    `core.auth`'s.

    Two bounds, in the order that makes the common case free:

    1. **No credential, no check.** An uptime monitor and a load balancer send no
       `Authorization` header, so the overwhelming majority of traffic here costs a header
       read. This is not the security control — `requires` would refuse them anyway — it
       is what keeps the control below from ever being reached by honest traffic.
    2. **At most `_DETAIL_GATE_CONCURRENCY` authorisations in flight.** Past that the
       detail is DENIED rather than queued, which is the right failure for this surface
       and costs nothing an operator needs: everything withheld from the wire is written
       to `health_not_ready` regardless (`core.health`), so the log line is intact, and a
       single human with `curl` is never the request that loses the race.

    A plain integer rather than an `asyncio.Semaphore`: the app is built once at import
    and the test suite runs it under many event loops, and a semaphore binds itself to the
    first loop that touches it (`asyncio.mixins._LoopBoundMixin`). Counting is correct
    without one — an event loop is single-threaded, and the only `await` between the read
    and the increment is none.
    """
    from apps.api.core.auth import requires
    from apps.api.core.context import bearer_token

    guard = requires("ops:manage", realm="admin")
    in_flight = 0

    async def _gate(request: Request) -> bool:
        nonlocal in_flight
        # The same reading `core.auth` and the limiter both use — D-135 made it one
        # function so three layers cannot disagree about what a credential is.
        if bearer_token(request.headers.get("authorization")) is None:
            return False
        if in_flight >= _DETAIL_GATE_CONCURRENCY:
            # Not an error and not silent: it is the shape of an attempt to use this
            # route as an amplifier, and it is the only place that shape is visible.
            log.warning("health_detail_gate_saturated", extra={"in_flight": in_flight})
            return False
        in_flight += 1
        try:
            await guard(request)
        except ProblemError:
            return False
        except Exception:
            log.warning("health_detail_gate_unavailable", exc_info=True)
            return False
        finally:
            in_flight -= 1
        return True

    return _gate


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
            # EVERY connection this process opened, not just the one. `close_redis` was
            # the whole teardown, so the ARQ enqueue pool (`core/queue._pool`, built on
            # the first `enqueue` a request makes) and the alert-admission client
            # (`core/alert_admission._client`, built on the first alert) survived the
            # drain and were left to the OS at exit — while `close_admission`'s own
            # docstring said it was "called from the same shutdown path as `close_redis`",
            # which nothing had ever made true. Under `--reload` and in tests each
            # restart leaked another pool against the same Redis.
            #
            # Independently, in this order, and none may stop the next: a drain that
            # abandoned the tracing flush because a socket was already gone would lose
            # exactly the spans somebody is shutting the service down to read. `suppress`
            # rather than a log line for the same reason `close_admission` uses one —
            # a closed socket is the commonest way any of these is reached.
            with suppress(Exception):
                await close_redis()
            with suppress(Exception):
                await close_queue()
            with suppress(Exception):
                # IMPORTED HERE, not at module scope, and that is the one thing in this
                # block that is not stylistic. `core.bootstrap` is on voice-runtime's
                # PINNED import surface (hard rule 3,
                # `tests/voice_runtime_import_surface_test.py`), and a module-level import
                # grew it by `apps.api.core.alert_admission` — a module whose next change
                # would then be able to break a live-call service at boot. `core.alerting`
                # reaches this same module the same way and for the same reason.
                from apps.api.core.alert_admission import close_admission

                close_admission()
            # Flush before the process goes: an un-exported span is a span that never
            # happened, and a drain is exactly when the interesting ones are in flight.
            shutdown_tracing()

    # ═══ THE API DOCUMENTATION IS NOT A PRODUCTION SURFACE. ═══
    #
    # `/docs`, `/redoc` and `/openapi.json` were served unauthenticated in EVERY
    # environment. That is the whole path list, every request and response schema, and
    # the `x-calevate-permission` extension — i.e. a map of which permission guards
    # which route, published to anyone who asks, on the same host as the routes.
    #
    # The repo already half-knew: `integrations/routes.py` moved a handler docstring
    # into an explicit `description` "because `/docs` is in PUBLIC_PREFIXES", which is a
    # one-route mitigation of a whole-surface exposure.
    #
    # NOTHING LOSES A CAPABILITY, and that is checked rather than assumed
    # (`tests/health_disclosure_test.py`): the TypeScript client is generated by
    # `pnpm -C apps/web gen:api` from the COMMITTED `apps/web/src/lib/api/openapi.json`,
    # never from a running server, and `scripts/check_openapi_fresh` calls `app.openapi()`
    # — the method, which `openapi_url=None` does not remove. Only the HTTP routes go.
    # Staging keeps them, because staging is where the schema is read by a human.
    docs_served = settings.app_env != "prod"
    app = FastAPI(
        title=title,
        version=version,
        lifespan=lifespan,
        docs_url="/docs" if docs_served else None,
        redoc_url="/redoc" if docs_served else None,
        openapi_url="/openapi.json" if docs_served else None,
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

    # The status word and the status code are public — a probe reads them and carries no
    # credential. The DETAIL is disclosed only to `ops:manage`, and `minimal` is the
    # right predicate for "can this app ask that question at all": it is already what
    # this function means by "the latency path does not pay for it", and voice-runtime
    # authenticates no human being. Its readiness detail therefore goes to the log line
    # in `core.health` and nowhere else.
    app.include_router(
        build_health_router(service, detail_gate=None if minimal else _ops_detail_gate())
    )
    return app


__all__ = ["DEFAULT_CORS_ORIGINS", "SettingsScopeMiddleware", "create_app"]
