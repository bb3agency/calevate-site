"""THE ONE HTTP ladder every vendor adapter answers on (hard rule 2's inside face).

Hard rule 2 says only `apps/api/engine/` may see a vendor payload shape. It says nothing
about the LADDER that turns a vendor's HTTP response into our error vocabulary — and for
as long as each adapter carried its own copy of that ladder, "every adapter is held to
identical, checkable behaviour" (the conformance suite's own opening paragraph) was false
in exactly the place it is hardest to notice: the failure paths, which no fixture
exercised.

WHAT THE TWO COPIES ACTUALLY DISAGREED ABOUT — measured, not inferred (D-240):

* **429 + `Retry-After`** — `bolna` backed off and then raised `engine_rate_limited`
  (`transient`, retryable). `cartesia` raised `engine_rejected` (`dependency`, terminal)
  with no backoff at all.
* **200 with a non-JSON body** — `bolna` raised `engine_bad_response`. `cartesia`
  returned `{}`, and `get_execution` then built a SNAPSHOT out of it.
* **502, and a transport failure** — the two agreed.

Both halves matter and neither is cosmetic.

* **The throttle.** `bolna._request`'s own comment argues the case — "a throttle says
  nothing about the request, so on the campaign path it must not burn a contact's retry
  budget for a reason that has nothing to do with the contact" — and the second adapter
  did precisely that. `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` and
  `apps.api.agents.service` both key off `engine_rate_limited`, so a throttled Cartesia
  call was a terminal failure everywhere those two decide.
* **The unreadable success.** A WAF challenge, a CDN interstitial or a proxy maintenance
  page is a 200 carrying HTML, and it is the ordinary failure mode of an API behind an
  edge. `tests/adapter_escaping_exception_test.py` (P2.2) found and closed this on ONE
  adapter; on the other, `get_execution` answered with `engine_call_id=''`,
  `status='failed'`, no cost and no transcript — a conclusion drawn from nothing wearing
  the shape of a measurement, which is verbatim what `VoiceEngine.get_agent`'s contract
  clause forbids. Downstream that is a completed call recorded as failed, metered at
  nothing, archived with `{}` as the vendor's own document, and read `settled` by the
  reconciliation poller forever.

So there is now one ladder, and `packages/shared/tests/engine_conformance` has clauses
that FAIL a second copy that drifts (`test_a_throttled_vendor_is_reported_as_transient_
rather_than_as_a_rejection`, `test_a_success_we_cannot_read_never_becomes_an_answer`, and
the two beside them). The clauses run against every adapter that speaks HTTP, and the
suite refuses to let a new one opt out.

LOG CODES CARRY AN `engine` LABEL RATHER THAN A VENDOR PREFIX. `cartesia_request_failed`
and `engine_error` were the same event under two greppable names, which is the same drift
D-93 removed from the voice-runtime receiver's `if engine == "bolna":`. One code, one
label, one runbook line.

WHAT IS DELIBERATELY NOT HERE: the client. Each adapter still builds and owns its own
`httpx.AsyncClient` — base URL, auth header, vendor version pin — and hands it in. That
is the half that is genuinely per-vendor, and folding it in here would put vendor
specifics into the one module that has none.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: Every vendor call in this package. Long enough for a control-plane write, short enough
#: that an adapter reached from a request handler cannot hold one open for a minute.
REQUEST_TIMEOUT_S = 10.0

# --- Throttle handling (SURFACES §3.3) ---------------------------------------
# Vendor rate limits are unpublished (Bolna: pilot item; Cartesia: no account at all), so
# 429 is a response we will meet without warning. Three deliberate limits on what we do
# about it:
#
# 1. **429 ONLY.** A 429 means the request was refused, not performed — the one status
#    where retrying `POST /call` cannot dial a person twice. A 502/503/504 on the same
#    endpoint is ambiguous, so those are reported, never repeated. Retrying a
#    non-idempotent create because it "felt transient" is how a lead gets two calls.
# 2. **Jitter, always.** Our workers are throttled in the same second and would
#    otherwise retry in the same second; a synchronized herd is how a rate limit
#    becomes an outage. Full jitter, and a `Retry-After` is a floor we never undercut.
# 3. **A short ceiling.** Adapter calls happen inside request handlers as well as
#    workers, so the adapter may stall a request by a second or two — not by two
#    minutes. A `Retry-After` longer than the ceiling is not slept through: it is
#    reported as `transient`, which is the caller's cue to reschedule the work.
THROTTLE_STATUS = 429
THROTTLE_MAX_ATTEMPTS = 3
THROTTLE_BASE_S = 0.5
THROTTLE_MAX_SLEEP_S = 8.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """`Retry-After` in delay-seconds form. The HTTP-date form is not parsed on
    purpose: a clock-skewed date is worse than no hint, and the fallback is a sane
    backoff either way."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def throttle_delay_s(
    attempt: int,
    retry_after: float | None,
    *,
    rand: Callable[[], float] = random.random,
) -> float:
    """How long to wait before retry `attempt` (0-based). Never zero-variance.

    `rand` is injected so the jitter is assertable in a test — an un-jittered backoff
    passes every "does it retry" test ever written and still takes the platform down.
    """
    if retry_after is not None:
        # Their number is a FLOOR. Jitter goes on top so we do not all wake together
        # at exactly the moment they told everyone to wake.
        return retry_after + THROTTLE_BASE_S * rand()
    # Full jitter over an exponentially growing ceiling: the delay is uniform in
    # [0, capped], so two workers throttled in the same second do not wake in the same
    # second. A fixed backoff would just move the herd, not disperse it.
    capped = min(THROTTLE_BASE_S * (2.0**attempt), THROTTLE_MAX_SLEEP_S)
    return capped * rand()


async def vendor_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    engine: str,
    absent_is_success: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """One vendor round trip, with the throttle ladder and the error normalization.

    `absent_is_success` exists for `delete_agent` and for nothing else: the Protocol
    makes delete IDEMPOTENT, so "the object you asked me to remove is not here" is
    that method's postcondition rather than a failure. It is opt-in per call site
    because on every OTHER route a 404 is a real defect — `get_agent` raising on an
    unknown ref is a contract clause, and a path we got wrong 404s exactly the same
    way, which is how a wrong path gets FOUND.

    `client` is the adapter's own, already carrying its base URL, its credential and any
    version pin. This function never builds one, so it holds no vendor specifics and an
    adapter that has no credential still refuses in its own `_http()` before we are
    reached.
    """
    for attempt in range(THROTTLE_MAX_ATTEMPTS):
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProblemError(
                kind="dependency",
                code="engine_unreachable",
                title="Voice engine unreachable",
                detail="The voice platform did not respond.",
                failure_stage="CORE_LOGIC",
            ) from exc
        if response.status_code != THROTTLE_STATUS:
            break
        retry_after = _retry_after_seconds(response)
        last_attempt = attempt == THROTTLE_MAX_ATTEMPTS - 1
        if last_attempt or (retry_after is not None and retry_after > THROTTLE_MAX_SLEEP_S):
            break
        log.warning(
            "engine_throttled", extra={"engine": engine, "route": path, "attempt": attempt + 1}
        )
        await asyncio.sleep(throttle_delay_s(attempt, retry_after))

    if response.status_code == THROTTLE_STATUS:
        # Distinct from `engine_rejected` on purpose. A throttle says nothing about
        # the request — so on the campaign path it must not burn a contact's retry
        # budget for a reason that has nothing to do with the contact. `transient`
        # is the ladder rung that means "identical retry can work" (503, retryable),
        # and `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` reads exactly this code.
        log.warning("engine_throttle_exhausted", extra={"engine": engine, "route": path})
        raise ProblemError(
            kind="transient",
            code="engine_rate_limited",
            title="Voice engine is rate limiting us",
            detail="The voice platform is temporarily refusing new requests.",
            remediation="This will be retried automatically.",
            failure_stage="CORE_LOGIC",
        )
    if absent_is_success and response.status_code == 404:
        # NOT a swallowed error: the caller declared that an absent object satisfies
        # it. Logged at info so a compensation that found nothing to compensate is
        # still legible in the record — `delete_agent`'s caller is an orphan
        # reclaimer, and "there was no orphan" is a fact worth having.
        log.info("engine_delete_already_absent", extra={"engine": engine, "route": path})
        return {}
    if response.status_code >= 400:
        # Never echo a vendor error body to a client — it is not user-safe, it is not
        # our vocabulary, and vendor error bodies quote the request (hard rule 6:
        # `tests/engine_audit_test.py` drives a 400 whose body carries a caller's
        # number). Status and route only.
        log.warning(
            "engine_error",
            extra={"engine": engine, "status": response.status_code, "route": path},
        )
        raise ProblemError(
            kind="dependency",
            code="engine_rejected",
            title="Voice engine rejected the request",
            detail="The voice platform could not complete this operation.",
            failure_stage="CORE_LOGIC",
        )
    if not response.content:
        # A successful DELETE may answer 204/empty. `response.json()` raises on an
        # empty body, and a delete that "failed" only because the vendor said
        # nothing is the worst possible lie on this particular path.
        return {}
    try:
        payload = response.json()
    except ValueError:
        # A 2xx WITH A NON-JSON BODY (P2.2). The `>= 400` branch above raises first,
        # so what reaches here is a success status carrying something that is not
        # JSON: a WAF challenge, a proxy interstitial, a CDN maintenance page. Those
        # are the ordinary failure modes of an API behind an edge, and they are
        # indistinguishable from a real answer until the parse fails.
        #
        # `json.JSONDecodeError` is a `ValueError` — NOT a `ProblemError` and NOT an
        # `httpx.HTTPError` — so it is caught by nothing above.
        #
        # RAISED, never `{}`. An empty dict flows on to callers that read fields out of
        # it and fail somewhere further from the cause — and on `get_execution` it does
        # not fail at all: it produces a snapshot naming no call, priced at nothing, with
        # no transcript, which the pipeline writes as a failed call and the reconciliation
        # poller reads as settled forever. That was `cartesia._request`'s behaviour and
        # it is why this ladder is shared rather than described (D-240).
        log.warning(
            "engine_non_json_success",
            extra={"engine": engine, "status": response.status_code, "route": path},
        )
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="Voice engine returned an unreadable response",
            detail="The voice platform answered successfully with a body we could not read.",
            failure_stage="CORE_LOGIC",
        ) from None
    return payload if isinstance(payload, dict) else {"data": payload}


__all__ = [
    "REQUEST_TIMEOUT_S",
    "THROTTLE_BASE_S",
    "THROTTLE_MAX_ATTEMPTS",
    "THROTTLE_MAX_SLEEP_S",
    "THROTTLE_STATUS",
    "throttle_delay_s",
    "vendor_request",
]
