"""`POST /reports/v1/csp` — the browser tells us its Content-Security-Policy refused
something.

THIS IS THE ONLY ROUTE IN `apps/api` WITH NO CREDENTIAL OF ANY KIND, and that is not a
gap to be closed later: a violation report is sent by the browser's own reporting agent,
which holds nothing of ours and can be given nothing. Every other unauthenticated route in
this tree stands on a signature, a shared secret, a source-IP allowlist or a cookie
(`scripts/check_public_routes.UNAUTHENTICATED_ROUTES`); this one stands on ADMISSION
CONTROL, which is a different and weaker thing, and the module says so rather than
dressing it up.

WHY IT EXISTS. `apps/web/src/lib/security/csp.ts` served
`Content-Security-Policy-Report-Only` for months with no `report-uri` and no `report-to`,
so every violation went nowhere and the staged rollout's exit condition ("once a real
session shows no violations") could never be evaluated by anybody. D-541 enforces the
policy; this is the other half of that change, because an enforced policy with no
telemetry breaks screens silently — a CSP refusal happens in the browser and leaves
nothing in any server log.

═══════════════════════════════════════════════════════════════════════════════
THE ABUSE STORY, in the order a request meets it
═══════════════════════════════════════════════════════════════════════════════
1. **The edge.** `infra/nginx/calevate.conf.template`'s `api.` vhost puts everything
   outside `/healthz`, `/v1/auth/` and `/v1/admin/` in the `client_api` zone, so this path
   inherits a per-real-IP `limit_req` before the process is reached. Nothing new was added
   there: a report is a small POST from a real browser, which is what that zone is sized
   for.
2. **`BodyLimitMiddleware`** caps every request at 2 MiB — twelve times too generous for
   this endpoint, which is why `MAX_REPORT_BYTES` below is enforced HERE, by counting the
   stream. A declared `Content-Length` is refused before a byte is read, and a
   `Transfer-Encoding: chunked` body is refused the moment the count passes the cap
   (D-135 is the defect that shape caused once already).
3. **`RateLimitMiddleware`** resolves this path to the `csp_report` profile
   (`core/ratelimit.PROFILES`), keyed on the caller IP because there is no session and no
   tenant to key on. Sized in that table.
4. **`LoadShedMiddleware`** sheds it. This prefix is deliberately NOT in
   `core/loadshed.ALWAYS_ALLOWED_PREFIXES`: the three admissible reasons there are stay
   observable, stay able to act, and let a provider callback land, and telemetry about a
   refused subresource is none of them. Under load the right answer to a violation report
   is to drop it.
5. **The content type**, checked before the body is read at all. Two values are legitimate
   and no third is — see `_ACCEPTED_CONTENT_TYPES`.
6. **The document origin.** A report naming a page that is not one of OUR consoles is
   counted and dropped. It is the closest thing to a credential this route has and it is
   NOT authentication: a stranger can put our origin in a JSON body. What it buys is that
   the endpoint cannot be used as a free logging service for someone else's site, which
   is the realistic abuse of a public collector.
7. **Extension noise** (`csp_reports.is_extension_noise`) is dropped before anything is
   recorded. An ad blocker injecting a script into our page trips `script-src` on every
   navigation and says nothing about our policy.
8. **The answer is always `204`, with no body, whatever happened.** Nothing here is an
   oracle: a rejected origin, an unparsable body, a shape we do not know and a perfectly
   good report are indistinguishable from outside. There is also nothing to read back, so
   there is nothing for a prober to gain by trying.

WHAT IT DOES NOT DO, deliberately: no database write, no queue, no object storage, no
outbound call. A public endpoint that allocates a row is a public endpoint that fills a
disk, and hard rule 7's `usage_events` doctrine has nothing to do with browser telemetry.
Reports go where this repo already puts operational telemetry — the ERROR/WARNING log line
and, once per fingerprint per 15 minutes, `core/alerting.alert()` — which is the whole of
OPERATIONS §4's alarm path and already carries the flood bounds (`ALERT_REPEAT_INTERVAL_S`
900s per `stage:code`, a global 20/hour bucket with a burst of 6). One broken page cannot
page an operator a thousand times because every violation this route raises shares ONE
code, so the second and subsequent deliveries inside the window are counted and ride the
next one.

WHAT IS KEPT AND WHAT IS STRIPPED is `csp_reports.py`'s docstring, field by field, with
the reason for each. In one line: origins and directive names, never a path past the
realm segment, never `referrer`, never `script-sample`, and never `original-policy`
— which carries the request's own nonce.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response

from apps.api.core.alerting import alert
from apps.api.core.bootstrap import cors_origins_for_env
from apps.api.core.logging import get_logger
from apps.api.security.csp_reports import CspViolation, is_extension_noise, parse_reports

log = get_logger(__name__)

router = APIRouter(prefix="/reports/v1", tags=["security"])

#: The two content types a browser sends a violation report with: the legacy `report-uri`
#: shape and the Reporting API's. Anything else is a caller who is not a reporting agent,
#: and is refused before the body is read. Compared on the MEDIA TYPE only — a `charset`
#: parameter is legitimate and a match must not turn on it.
_ACCEPTED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"application/csp-report", "application/reports+json"}
)

#: 16 KiB. A violation report is a few hundred bytes; the Reporting API batches, and
#: `MAX_REPORTS_PER_POST` bounds that batch at 20. This is roughly fifty times what an
#: honest sender needs and one-hundred-and-twenty-eighth of the global body cap, which is
#: the point: an unauthenticated caller must not decide how much we allocate.
MAX_REPORT_BYTES = 16 * 1024

#: The one alarm code this route can raise. A LITERAL and a constant rather than a
#: formatted string, because it is the deduplication key `core/alerting` fingerprints on
#: (`stage:code`) — a code carrying the directive would give a page-load storm one
#: fingerprint per directive and defeat the flood bound this route depends on.
CSP_VIOLATION_CODE = "csp_violation"


def require_own_console_origin(violation: CspViolation) -> bool:
    """Is this report about a page WE serve?

    Named as this route's "credential" in `scripts/check_public_routes` and the name is
    chosen to be honest about what it is: admission control, not authentication. A
    stranger can write our origin into a JSON body, and nothing here can stop them. What
    it does stop is this endpoint being usable as free log storage for an unrelated site,
    and it keeps the log to violations somebody here can actually act on.

    The allowlist is `cors_origins_for_env()` — the same function the CORS layer and the
    CSRF `Origin` check read, so "an origin this product is served from" has ONE answer in
    the process. A report with no usable `document-uri` is refused: an unattributable
    violation is not actionable, and accepting it would be accepting anything.
    """
    realm = violation.document_realm
    if realm is None:
        return False
    return any(
        realm == origin or realm.startswith(f"{origin}/") for origin in cors_origins_for_env()
    )


async def _read_bounded(request: Request) -> bytes | None:
    """The body, or None when the sender exceeded `MAX_REPORT_BYTES`.

    Counted as it streams rather than trusted from `Content-Length`, for the reason
    `core/middleware.BodyLimitMiddleware` states at length: a `Transfer-Encoding: chunked`
    body declares no length, so a length check alone bounds nothing. The declared value is
    still checked first, because refusing before a byte is read is cheaper than refusing
    after 16 KiB of them.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_REPORT_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REPORT_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _media_type(raw: str | None) -> str:
    """`application/csp-report; charset=UTF-8` → `application/csp-report`."""
    return (raw or "").split(";", 1)[0].strip().lower()


@router.post(
    "/csp",
    status_code=204,
    response_class=Response,
    summary="Content-Security-Policy violation report (unauthenticated, by necessity)",
    description=(
        "Where browsers post CSP violation reports for the consoles. Unauthenticated "
        "because a reporting agent carries no credential; bounded, rate limited, and "
        "answered 204 whatever it is sent. Nothing is stored: a report becomes a "
        "redacted log line and, at most once per fingerprint per 15 minutes, an alarm."
    ),
    # OUT OF THE SCHEMA on purpose. The OpenAPI document is the contract the TypeScript
    # client is generated from (`pnpm -C apps/web gen:api`), and nothing in our own code
    # calls this — the caller is the browser's reporting agent, which was told where to
    # post by the `report-uri`/`report-to` directives and reads no schema. A generated
    # `postReportsV1Csp()` sitting in the client would be an invitation to call it from
    # application code, which is the one thing that must never happen: a report is
    # telemetry the browser emits, not an action a screen takes.
    include_in_schema=False,
)
async def receive_csp_report(request: Request) -> Response:
    """Take one delivery. Never raises, never blocks, never writes a row."""
    if _media_type(request.headers.get("content-type")) not in _ACCEPTED_CONTENT_TYPES:
        # 415 rather than 204: this one IS worth telling a caller about, because the only
        # senders that reach it are a misconfigured integration or a prober, and neither
        # learns anything from the status that the route's existence did not already tell
        # them. No body — a reporting agent does not read one.
        return Response(status_code=415)

    raw = await _read_bounded(request)
    if raw is None:
        log.warning("csp_report_oversized", extra={"cap_bytes": MAX_REPORT_BYTES})
        return Response(status_code=413)

    try:
        payload: Any = json.loads(raw) if raw else None
    except (ValueError, RecursionError):
        # `RecursionError` — not `ValueError` — is what `json.loads` raises on a deeply
        # nested document, and on a route with NO credential that is the shape somebody
        # sends on purpose (`ingest/routes.py` records the same trap on a signed one).
        # Both end here: a body we cannot read is counted and answered 204, never a 500.
        payload = None

    violations = parse_reports(payload)
    recorded: list[CspViolation] = []
    for violation in violations:
        if is_extension_noise(violation):
            # Counted, not recorded: this is the loudest noise source an enforced CSP has
            # and it is somebody's password manager, not our policy.
            log.info("csp_violation_extension_ignored", extra={"scheme": violation.blocked_origin})
            continue
        if not require_own_console_origin(violation):
            log.info("csp_report_foreign_origin_ignored", extra={"realm": violation.document_realm})
            continue
        recorded.append(violation)
        # Every field here has been through `csp_reports`' stripper; hard rule 6 is
        # satisfied by construction rather than by remembering not to log a URL.
        log.warning(
            "csp_violation",
            extra={
                "directive": violation.effective_directive,
                "blocked_origin": violation.blocked_origin,
                "document_realm": violation.document_realm,
                "source_origin": violation.source_origin,
                "line": violation.line_number,
                "disposition": violation.disposition,
            },
        )

    if recorded:
        # ONE alert per delivery, not one per violation: a page that trips six directives
        # is one problem. `alert()` then collapses everything past the first delivery in a
        # 15-minute window into a counter that rides the next one, so a storm across
        # thousands of browsers is at most four pages an hour from this code.
        first = recorded[0]
        alert(
            "BROWSER_RUNTIME",
            CSP_VIOLATION_CODE,
            detail=(
                f"{len(recorded)} Content-Security-Policy violation(s) in one report: "
                f"{first.fingerprint} on {first.document_realm}"
            ),
        )
    return Response(status_code=204)


__all__ = ["CSP_VIOLATION_CODE", "MAX_REPORT_BYTES", "require_own_console_origin", "router"]
