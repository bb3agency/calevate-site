"""Middleware, installed in the FIXED order of BACKEND-PATTERNS §2 step 5:

    security headers → CORS → auth → rate limit → error handler → observability → routes

Starlette makes the LAST-added middleware outermost, so `install_middleware` adds them
in reverse of that list. Auth is the one deliberate placement change: it is a per-route
`Depends` rather than a middleware, so that OpenAPI carries the security requirement
into the generated TypeScript client (no ad-hoc fetch — CLAUDE.md conventions). It
still executes after everything above it, which is what the ordering is about.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from calevate_shared.client_address import client_ip
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.api.core.alerting import alert
from apps.api.core.context import (
    IMPERSONATE_HEADER,
    IMPERSONATION_GRANT_HEADER,
    ORG_HEADER,
    bearer_token,
    correlation_id_var,
    principal_var,
)
from apps.api.core.errors import PROBLEM_CONTENT_TYPE, ProblemError
from apps.api.core.loadshed import get_platform_status, is_shed
from apps.api.core.logging import get_logger
from apps.api.core.ratelimit import (
    bucket_subject,
    consume,
    fingerprint,
    profile_for,
    too_many_requests,
)
from apps.api.core.settings import get_settings

log = get_logger(__name__)

CORRELATION_HEADER = "X-Correlation-Id"
MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB; CSV import gets its own streaming route

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # HSTS is also set at the edge (DEPLOYMENT §5); duplicated so a direct-to-origin
    # request is never weaker than a proxied one.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}

Handler = Callable[[Request], Awaitable[Response]]


def _headers(scope: Scope) -> dict[str, str]:
    """Raw ASGI headers as a lowercase dict, decoded the way HTTP actually defines them.

    `latin-1`, NOT `utf-8`. Header field values are ISO-8859-1 on the wire (RFC 9110
    §5.5) and every ASGI server hands them over as raw bytes; Starlette's own `Headers`
    decodes `latin-1` for exactly this reason. Three middlewares here used the default
    `bytes.decode()`, so one non-UTF-8 byte in ANY header — trivially sent, by anyone,
    authenticated or not — raised inside the middleware chain. A middleware that raises
    is a 500 BEFORE routing: every endpoint at once, including `/healthz` and the
    never-shed `/hooks` surface an engine calls. latin-1 cannot fail: every byte maps.
    """
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _problem_response(exc: ProblemError, path: str) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=exc.as_problem(path),
        media_type=PROBLEM_CONTENT_TYPE,
        headers=exc.headers,
    )


class SecurityHeadersMiddleware:
    """Outermost: every response, including ones produced by other middleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = list(message.get("headers", []))
                existing = {k.lower() for k, _ in raw}
                for key, value in SECURITY_HEADERS.items():
                    if key.lower().encode() not in existing:
                        raw.append((key.encode(), value.encode()))
                message["headers"] = raw
            await send(message)

        await self.app(scope, receive, send_wrapper)


class CorrelationIdMiddleware:
    """Accept `X-Correlation-Id` else generate; echo it; bind it to the contextvar so
    every log line, problem body and audit row carries the same id (§3).

    It also opens and closes the OTHER request-scoped contextvar, `principal_var`. The
    auth dependency sets that one and nothing reset it, so anywhere requests share a
    task — an in-process ASGI transport, a test client — the next request began holding
    the previous caller's identity. Same failure the transaction-local GUCs are written
    to avoid, and it belongs at the same boundary: whatever sets request state, this is
    where the request ends.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        correlation_id = headers.get(CORRELATION_HEADER.lower()) or uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        # Explicitly cleared on the way IN as well: a request that never authenticates
        # must not read as the previous one.
        principal_token = principal_var.set(None)
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
                raw = list(message.get("headers", []))
                raw.append((CORRELATION_HEADER.encode(), correlation_id.encode()))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Path only, never the query string — filters can carry a phone number
            # (hard rule 6).
            log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "route": scope.get("path"),
                    "status": status_holder.get("status"),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            correlation_id_var.reset(token)
            principal_var.reset(principal_token)


def _payload_too_large(max_bytes: int) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="payload_too_large",
        title="Payload too large",
        detail=f"Request body exceeds {max_bytes} bytes.",
        status=413,
        remediation="Send a smaller body, or split the request.",
    )


class BodyLimitMiddleware:
    """Bootstrap step 4's body limit, on BOTH ways a body arrives.

    A declared `Content-Length` over the cap is refused before a single byte is buffered.
    That used to be the whole of it, and `Transfer-Encoding: chunked` — one header, no
    credential — declares no length at all, so an oversized chunked body walked straight
    past into `await request.json()` and was buffered whole. **The edge does not cover
    this**: `infra/nginx/calevate.conf.template` sets `client_max_body_size 25m` on the api
    vhost, which is twelve times this cap, so "nginx catches it" was true only of bodies
    twelve times bigger than the ones we meant to refuse.

    So the length is COUNTED as the body streams, which is the same bounded-read doctrine
    `ingest/meta.py::_read_bounded` and voice-runtime's twin already apply per-route —
    here it is applied once, for every route, including the ones nobody thought to bound.

    HOW THE REFUSAL IS DELIVERED, since it happens mid-request. Over the cap, the
    downstream app is handed `http.disconnect` — the one message an ASGI app is required
    to handle at any point in a body read — and everything it tries to send afterwards is
    dropped, so this middleware answers exactly once and the 413 is the caller's whole
    response. Dropping is conditional on nothing having been sent yet: a handler that had
    already begun a response and then read more body would otherwise get its response
    truncated, and a truncated 200 is worse than a large body.

    Counting rather than buffering, deliberately: buffering the body here to measure it
    would mean a request to an unrouted path pays for two megabytes of memory before
    anything decides it is a 404, which is a worse position than the one being fixed.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        declared = _headers(scope).get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await _problem_response(_payload_too_large(self.max_bytes), path)(scope, receive, send)
            return

        seen = 0
        over_limit = False
        responded = False

        async def counting_receive() -> Message:
            nonlocal seen, over_limit
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    over_limit = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal responded
            if over_limit and not responded:
                return
            if message["type"] == "http.response.start":
                responded = True
            await send(message)

        await self.app(scope, counting_receive, guarded_send)
        if over_limit and not responded:
            log.warning("payload_too_large", extra={"route": path, "bytes": seen})
            await _problem_response(_payload_too_large(self.max_bytes), path)(scope, receive, send)


class LoadShedMiddleware:
    """The big red switch's request-path face (BACKEND-PATTERNS §6). Health, auth,
    engine webhooks and the ops/admin surface are never shed — the operator must not
    be able to lock themselves out."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        status = await get_platform_status()
        if is_shed(status, path=path, method=method):
            problem = ProblemError(
                kind="transient",
                code="service_load_shed",
                title="Temporarily unavailable",
                # 503 is the ONE status allowed to keep its detailed message (§3).
                detail=f"The platform is in {status.mode} mode and is not accepting this request.",
                status=503,
                remediation="Retry shortly; the operations team has been notified.",
                headers={"Retry-After": "30"},
            )
            await _problem_response(problem, path)(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    """The dimensions that can be decided BEFORE routing and BEFORE authentication:
    per caller, and — on the ingest webhooks, which have no session — per `webhook_id`.
    The profile table and the counter live in `core/ratelimit.py`; the per-TENANT
    dimension is charged after authentication, in `core/auth.py`, because that is the
    first moment the tenant is a verified fact rather than a header a stranger typed.

    The caller is the bearer-token fingerprint when the request carries one, else the
    client address as `calevate_shared.client_address.client_ip` can vouch for it — the
    same one definition the audit rows and the signup quota now use.

    Redis being down must never 500 a request: `ratelimit.consume` fails OPEN and logs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _caller(self, scope: Scope, headers: dict[str, str]) -> str:
        """The bucket subject for the per-caller dimension.

        THREE FALLBACKS, IN DESCENDING ORDER OF WHAT WE CAN PROVE. A bearer token is the
        caller — as `core.context.bearer_token` reads one, which is the same reading every
        route authenticates with. It used to be `fingerprint(<the whole raw header>)`,
        and the gap between those two readings was a bucket the caller could choose:
        `bearer x`, `Bearer  x` and `Bearer x ` are one session and were three budgets,
        with the padding making it unbounded (see that function). Failing that, the
        address the edge vouched for. Failing THAT — outside `local`, an absent or
        unparseable `CF-Connecting-IP`, i.e. a broken edge — the socket peer, which
        behind nginx is one shared address for everyone.

        AN UNVERIFIED TOKEN IS STILL A TOKEN HERE, and that is a boundary worth stating
        rather than discovering: this runs before routing and before authentication, so
        `Bearer <32 random bytes>` buys a fresh bucket every time and an anonymous caller
        can walk past this dimension entirely. What bounds THAT caller is the edge's
        per-real-IP `limit_req` zones (module docstring), which is the layer that owns
        per-address limiting; what this dimension owns is "one authenticated caller
        cannot spend the tenant's budget alone", and that is the half the reading above
        restores.

        That last bucket is a self-inflicted platform-wide cap, and it is still the right
        answer: a limiter's degraded mode must refuse too much rather than too little,
        and it is exactly the behaviour this middleware had for EVERY unauthenticated
        request before the shared helper existed.

        IT ALSO ALERTS, through the same path the receiver uses for the same fault
        (`engine_intake.verify_source` → `webhook_source_rejected`, detail "client ip not
        established"). The two are one incident — the edge stopped setting
        `CF-Connecting-IP`, or something is reaching the container without passing
        nginx — and here it is SILENT rather than a refusal: every `audit_log.ip` starts
        recording NULL and every anonymous caller starts sharing one bucket, with nothing
        failing. A degradation nobody is told about is the shape this repo alerts on.
        `alert()` suppresses per fingerprint and holds a global hourly budget
        (BACKEND-PATTERNS §8), so a broken edge does not turn into a mail flood.
        """
        token = bearer_token(headers.get("authorization"))
        if token is not None:
            return f"t:{fingerprint(token)}"
        peer = (scope.get("client") or ("", 0))[0]
        resolved = client_ip(peer, headers, app_env=get_settings().app_env)
        if resolved is not None:
            return f"ip:{bucket_subject(resolved)}"
        alert(
            "ROUTE_HANDLER",
            "client_ip_unresolved",
            detail=(
                "no trusted hop vouched for a caller address; "
                "audit ip and per-caller limits are degraded"
            ),
            route=str(scope.get("path", "")),
        )
        return f"peer:{bucket_subject(peer or None)}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        profile = profile_for(path, method)
        if profile.per_client <= 0 and not profile.per_tenant:
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        caller = self._caller(scope, headers)
        decision = await consume(profile, "client", caller, profile.per_client)
        if decision.allowed and profile.tenant_from_last_path_segment and profile.per_tenant:
            # The `webhook_id` in `/hooks/v1/ingest/...` — the tenant dimension on a
            # surface that authenticates with a per-source secret rather than a session,
            # and the reason a lead flood no longer 429s the payment webhook.
            decision = await consume(
                profile,
                "hook",
                bucket_subject(path.rsplit("/", 1)[-1]),
                profile.per_tenant,
            )
        if not decision.allowed:
            log.warning("rate_limited", extra={"route": path, "profile": profile.name})
            await _problem_response(too_many_requests(decision), path)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def install_middleware(app: FastAPI, *, cors_origins: list[str]) -> None:
    """Added innermost-first; Starlette makes the last one outermost."""
    app.add_middleware(CorrelationIdMiddleware)  # observability
    app.add_middleware(LoadShedMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        # PUT WAS MISSING AND FIVE ROUTES WERE UNREACHABLE FROM A BROWSER: `PUT
        # /v1/billing/caps` (a client's own spend cap), `PUT …/feature-flags/{flag}`,
        # `PUT /v1/ops/config/{key}`, `PUT /v1/ops/secrets/{key}` — which is how a vendor
        # credential gets installed at all — and `DELETE /v1/ops/config/{key}`, which
        # sends `If-Match`. Nothing went red: the web tests mock `fetch`, and CORS is
        # enforced only by a browser, so the whole class is invisible to this suite
        # unless something asserts it. `tests/cors_contract_test.py` now does, by walking
        # the live route table rather than by listing what somebody remembered.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # Every custom header the client sends must be listed, or the browser fails
        # the PREFLIGHT and the request never reaches a handler — which looks like a
        # dead API rather than a config gap. X-Org-Slug carries tenant selection and
        # X-Impersonate-Org carries D-22 view-as, so omitting either breaks the whole
        # client realm while curl keeps working. X-Impersonation-Grant is the other half
        # of that pair — without it here, view-as fails the preflight and every client
        # screen an operator opens is a 403 the browser will not explain. `If-Match` is
        # the optimistic-concurrency header `client.ts` sends on the ops config delete;
        # the same test asserts this list against that file's request headers.
        allow_headers=[
            "Authorization",
            "Content-Type",
            CORRELATION_HEADER,
            "Idempotency-Key",
            "If-Match",
            ORG_HEADER,
            IMPERSONATE_HEADER,
            IMPERSONATION_GRANT_HEADER,
            "X-Confirm-Action",
        ],
        expose_headers=[CORRELATION_HEADER, "Idempotent-Replayed", "Retry-After"],
    )
    app.add_middleware(SecurityHeadersMiddleware)  # outermost


__all__ = [
    "CORRELATION_HEADER",
    "MAX_BODY_BYTES",
    "SECURITY_HEADERS",
    "BodyLimitMiddleware",
    "CorrelationIdMiddleware",
    "LoadShedMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "install_middleware",
]
