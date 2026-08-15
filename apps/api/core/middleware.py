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

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.api.core.context import (
    IMPERSONATE_HEADER,
    IMPERSONATION_GRANT_HEADER,
    ORG_HEADER,
    correlation_id_var,
    principal_var,
)
from apps.api.core.errors import PROBLEM_CONTENT_TYPE, ProblemError
from apps.api.core.loadshed import get_platform_status, is_shed
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis

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


class BodyLimitMiddleware:
    """Bootstrap step 4's body limit. Declared Content-Length over the cap is refused
    before a single byte is buffered."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = _headers(scope)
            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                problem = ProblemError(
                    kind="validation",
                    code="payload_too_large",
                    title="Payload too large",
                    detail=f"Request body exceeds {self.max_bytes} bytes.",
                    status=413,
                )
                await _problem_response(problem, str(scope.get("path", "")))(scope, receive, send)
                return
        await self.app(scope, receive, send)


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
    """Fixed-window limiter in Redis, per (identity, profile). Deliberately simple:
    the expensive surfaces (call dispatch, campaign launch) are additionally guarded
    by idempotency + spend caps, so this only has to stop obvious abuse.

    Identity is the bearer-token fingerprint when present, else the client IP taken
    from the CIDR-verified proxy header (DEPLOYMENT §5 restores the real caller IP).
    Redis being down must never 500 a request — the limiter fails OPEN and logs.
    """

    # prefix → (requests, window seconds)
    PROFILES: tuple[tuple[str, int, int], ...] = (
        ("/hooks", 600, 60),  # engine webhooks: generous, never the bottleneck
        ("/v1/leads", 120, 60),
        ("/v1/calls", 120, 60),
        ("/v1/admin", 300, 60),
        ("/v1", 240, 60),
    )
    EXEMPT: tuple[str, ...] = ("/healthz", "/openapi.json", "/docs")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _profile(self, path: str) -> tuple[str, int, int] | None:
        for prefix, limit, window in self.PROFILES:
            if path.startswith(prefix):
                return prefix, limit, window
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if any(path.startswith(p) for p in self.EXEMPT):
            await self.app(scope, receive, send)
            return
        profile = self._profile(path)
        if profile is None:
            await self.app(scope, receive, send)
            return

        prefix, limit, window = profile
        headers = _headers(scope)
        auth = headers.get("authorization", "")
        # Fingerprint, never the token itself — tokens must not reach Redis or logs.
        identity = (
            f"t:{hash(auth) & 0xFFFFFFFF:08x}"
            if auth
            else f"ip:{(scope.get('client') or ('unknown', 0))[0]}"
        )
        bucket = int(time.time() // window)
        key = f"calevate:rl:{prefix}:{identity}:{bucket}"
        try:
            redis = get_redis()
            count = int(await redis.incr(key))
            if count == 1:
                await redis.expire(key, window + 1)
        except Exception:
            log.warning("ratelimit_unavailable", extra={"route": path})
            await self.app(scope, receive, send)
            return

        if count > limit:
            retry_after = window - int(time.time() % window)
            problem = ProblemError(
                kind="transient",
                code="rate_limited",
                title="Too many requests",
                detail="Rate limit exceeded for this endpoint.",
                status=429,
                remediation=f"Retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
            await _problem_response(problem, path)(scope, receive, send)
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
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        # Every custom header the client sends must be listed, or the browser fails
        # the PREFLIGHT and the request never reaches a handler — which looks like a
        # dead API rather than a config gap. X-Org-Slug carries tenant selection and
        # X-Impersonate-Org carries D-22 view-as, so omitting either breaks the whole
        # client realm while curl keeps working. X-Impersonation-Grant is the other half
        # of that pair — without it here, view-as fails the preflight and every client
        # screen an operator opens is a 403 the browser will not explain.
        allow_headers=[
            "Authorization",
            "Content-Type",
            CORRELATION_HEADER,
            "Idempotency-Key",
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
