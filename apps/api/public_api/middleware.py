"""What every `/api/v1/` answer carries on the way out (D-1047).

- `Calevate-Version`: the version the answer was written in (W2.13).
- `RateLimit-Policy` / `RateLimit`: the key's own per-minute bucket and, on a call, the
  account's daily API call budget (W2.3).
- `Idempotent-Replayed: true` when an idempotent write was answered from its record.

And, once the answer is sent, one activity entry (W2.8): route template, status, problem
code, latency, never the path, query or body.

OUTERMOST, so it sees every answer the layers inside produce, the problem documents
included. A pure ASGI middleware rather than `BaseHTTPMiddleware`, which would run the app
in a second task and hide the facts a handler records.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.api.core.auth import API_KEY_CALL, PUBLIC_API_PREFIX, ApiKeyCall
from apps.api.core.context import request_facts_var
from apps.api.core.middleware import CORRELATION_HEADER
from apps.api.core.ratelimit import Decision, limit_fields
from apps.api.public_api import activity
from apps.api.public_api.deps import DAILY_DECISION, DAILY_POLICY
from apps.api.public_api.version import CURRENT_VERSION, VERSION_HEADER

#: How much of a problem document is read to find its `type` and `remediation`.
_PROBLEM_READ_MAX: Final = 16 * 1024
_PROBLEM_PREFIX: Final = "/problems/"
KEY_POLICY: Final = "per-key"


def _problem(body: bytes) -> tuple[str | None, str | None]:
    try:
        doc = json.loads(body)
    except ValueError:
        return None, None
    if not isinstance(doc, dict):
        return None, None
    kind = doc.get("type")
    code = kind.rsplit("/", 1)[-1] if isinstance(kind, str) and kind else None
    remediation = doc.get("remediation")
    return code, remediation if isinstance(remediation, str) else None


class PublicApiMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(PUBLIC_API_PREFIX):
            await self.app(scope, receive, send)
            return
        facts: dict[str, object] = {}
        reset = request_facts_var.set(facts)
        started = time.perf_counter()
        seen: dict[str, Any] = {"status": 500, "problem": False, "body": b"", "trace": None}

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                seen["status"] = int(message["status"])
                seen["problem"] = headers.get("content-type", "").startswith(
                    "application/problem+json"
                )
                seen["trace"] = headers.get(CORRELATION_HEADER)
                call = facts.get(API_KEY_CALL, scope.get(API_KEY_CALL))
                version = call.api_version if isinstance(call, ApiKeyCall) else CURRENT_VERSION
                headers[VERSION_HEADER] = version
                if facts.get("idempotent_replayed"):
                    headers["Idempotent-Replayed"] = "true"
                policies: list[tuple[str, int, Decision]] = []
                if isinstance(call, ApiKeyCall):
                    policies.append((KEY_POLICY, call.window_s, call.limit_decision))
                daily = facts.get(DAILY_DECISION, scope.get(DAILY_DECISION))
                if isinstance(daily, Decision):
                    policies.append((DAILY_POLICY, 86400, daily))
                for name, value in limit_fields(policies).items():
                    headers[name] = value
            elif message["type"] == "http.response.body" and seen["problem"]:
                if len(seen["body"]) < _PROBLEM_READ_MAX:
                    seen["body"] += message.get("body", b"")[:_PROBLEM_READ_MAX]
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            request_facts_var.reset(reset)
            call = facts.get(API_KEY_CALL, scope.get(API_KEY_CALL))
            if isinstance(call, ApiKeyCall):
                code, remediation = _problem(seen["body"]) if seen["problem"] else (None, None)
                route = facts.get("route")
                await activity.record(
                    {
                        "tenant_id": str(call.key.tenant_id),
                        "api_key_id": str(call.key.id),
                        "method": str(scope.get("method", "GET")),
                        # The TEMPLATE, never the resolved path (hard rule 6).
                        "route": route if isinstance(route, str) else "unmatched",
                        "status": str(seen["status"]),
                        "problem_code": code or "",
                        "remediation": remediation or "",
                        "trace_id": str(seen["trace"] or ""),
                        "latency_ms": str(int((time.perf_counter() - started) * 1000)),
                        "replayed": "1" if facts.get("idempotent_replayed") else "0",
                        "api_version": call.api_version,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )


__all__ = ["KEY_POLICY", "PublicApiMiddleware"]
