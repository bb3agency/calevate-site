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
from apps.api.engine.health import record_engine_failure

log = get_logger(__name__)

#: Every vendor call in this package. Long enough for a control-plane write, short enough
#: that an adapter reached from a request handler cannot hold one open for a minute.
REQUEST_TIMEOUT_S = 10.0

# --- Throttle handling (SURFACES §3.3) ---------------------------------------
# Bolna's rate limits ARE published now and this comment used to say they were not
# (VERIFIED-DOCS, `bolna-findings/mirror/pages/api-reference/rate-limiting.md:17-25`,
# announced `changelog/february-2026.md:51-67`): 500 requests/minute each on
# `/v2/agent/{agent_id}/executions`, `/v2/agent/{agent_id}` and `/call`, 1000/minute
# everywhere else, counted **per organisation** — "the rate limit is shared across all
# users within that organisation" — which for us means per Bolna account, not per tenant.
# Their guidance is the ladder below: *"Implement exponential backoff"*, and `limits.md`
# prints `2 ** i`.
#
# NOTHING CHANGES HERE AS A RESULT, and that is the finding rather than an omission. Our
# two callers are orders of magnitude inside it — the reconciliation poller fans out one
# request per agent per page on a ten-minute tick (`bolna._LISTING_PAGE_SIZE`), and the
# dispatcher cannot exceed `campaign_dispatch.PLATFORM_LINES_TOTAL` dials in flight — so
# 429 remains a response we meet without warning rather than one we can predict, which is
# what the ladder is for. Cartesia's are still unpublished (no account at all).
#
# Three deliberate limits on what we do about it:
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

#: Statuses on which the vendor REFUSED the request rather than PERFORMED it — so the
#: caller knows nothing was started, and on the dial path knows no line was seized.
#:
#: VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/errors.md:15-18`, one
#: row each and every one of them a statement about the REQUEST:
#:
#:   | `400` | Bad Request  | Invalid or missing parameter — check `message` ... |
#:   | `401` | Unauthorized | Missing or invalid API key ... |
#:   | `403` | Forbidden    | Valid key but insufficient permissions |
#:   | `404` | Not Found    | Resource ID doesn't exist or belongs to another account |
#:
#: and `POST /call` — the one route where being wrong about this dials a stranger —
#: documents exactly two responses in its own OpenAPI block, `200` and `400`
#: (`api-reference/calls/make.md:196-207`). An intermediary that answers one of these
#: (a WAF 403, a proxy 404 on a route it does not know) has by construction not forwarded
#: the request either, so the reading holds for the whole path and not just the origin.
#:
#: WHAT IS DELIBERATELY *NOT* IN THIS SET, because the cost asymmetry is one unsolicited
#: call against one contact a human looks at: every 5xx (a proxy can answer 502 AFTER the
#: vendor committed), and every 4xx the vendor does not document — 408, 409, 413, 422 and
#: anything else that appears later. The default for an unknown status is "the phone may
#: be ringing", and a status joins this set by being READ in their docs, never by looking
#: safe. 429 never reaches here: it has its own rung above.
REQUEST_REFUSED_STATUSES = frozenset({400, 401, 403, 404})

#: The bound that lets the vendor's error code into a log line at all — see
#: `_vendor_error_code`.
_INT32_MAX = 2**31 - 1


class EngineRejectedError(ProblemError):
    """`engine_rejected`, carrying the two facts this ladder used to throw away.

    The code, the kind, the title and the detail are unchanged and every existing reader
    keys off `code` exactly as before; what is new is that the raise site's own knowledge
    survives the raise:

    * **`vendor_status`** — the HTTP status. `dial_was_not_placed`
      (`apps/api/agents/service.py`) is the caller that needs it: that function used to
      have to treat a documented `400 agent_id is required` and an ambiguous `502` as one
      indistinguishable outcome, which meant a campaign contact was settled TERMINALLY as
      "this person may have been rung" for a refusal that proves nobody was.
    * **`vendor_error`** — the integer from the vendor's own error envelope, when there
      was one. See `_vendor_error_code` for why the integer and never the message.

    A SUBCLASS RATHER THAN A NEW ERROR CODE. `engine_rejected` is read by name in a dozen
    places (`pipeline.TRANSIENT_ENGINE_CODES`' complement, the alarm index row, the
    conformance clauses); splitting it into two codes would make every one of them a
    two-branch decision to keep a fact that belongs on the exception. `isinstance` is
    opt-in: a caller that does not care is not changed at all.
    """

    def __init__(self, *, status: int, vendor_error: int | None = None) -> None:
        super().__init__(
            kind="dependency",
            code="engine_rejected",
            title="Voice engine rejected the request",
            detail="The voice platform could not complete this operation.",
            failure_stage="CORE_LOGIC",
        )
        self.vendor_status = status
        self.vendor_error = vendor_error

    @property
    def request_refused(self) -> bool:
        """True when the vendor's own docs say this status means "I did not do it"."""
        return self.vendor_status in REQUEST_REFUSED_STATUSES


def _vendor_error_code(response: httpx.Response) -> int | None:
    """The integer out of the vendor's error envelope, and NOTHING else out of it.

    Their 4xx/5xx body is `{"error": <int>, "message": "<human text>"}` — declared
    `required: [error, message]` with `error` as `type: integer, format: int32`
    (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/api-reference/errors.md:26-33`,
    schema at `api-reference/calls/make.md:229-239`).

    **`message` NEVER LEAVES THIS FUNCTION**, and that is hard rule 6 rather than taste:
    it is the vendor quoting our request back at us. Their own worked examples for
    `POST /call` are `agent_id is required` and `recipient_phone_number is required`
    (`api-reference/calls/make.md:62-63`), i.e. the field being complained about is the
    caller's phone number, and `tests/engine_audit_test.py` drives a 400 whose body
    carries one.

    The INTEGER is different in kind and is the fact an operator actually needs: it is
    the vendor's own identifier for the refusal, so "every dial is failing" becomes a
    value to quote at their support desk rather than a shrug. It is admitted only when it
    really is an `int` inside the int32 range the schema declares — a bound that
    structurally cannot hold an E.164 number, since `919876543210` is two orders of
    magnitude past int32's ceiling — so this field cannot quietly become a PII channel if
    the vendor widens it later. `bool` is excluded explicitly because in Python it *is*
    an `int`, and `{"error": true}` is not a code.
    """
    if not response.content:
        return None
    try:
        payload = response.json()
    except ValueError:
        # An error body that is not JSON at all — an edge's HTML page in front of the
        # vendor. There is nothing to read; the status still says what happened.
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("error")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if -_INT32_MAX - 1 <= value <= _INT32_MAX else None


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
            # Counted BEFORE it is raised. "The vendor did not answer" is half of
            # OPERATIONS §4's engine-spike alarm, and it is the half a TOTAL outage
            # produces — a platform that is entirely down refuses the connection rather
            # than answering 502, so a strict 5xx reading is silent through the worst
            # case. `engine/health.py` argues the pairing; `record_engine_failure` never
            # raises, so a database hiccup here cannot replace the vendor's error with
            # ours. Counting lives HERE, in the one shared ladder, because it is the one
            # place both adapters pass through — which is the whole point of D-240.
            await record_engine_failure(engine, kind="unreachable")
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
    if 300 <= response.status_code < 400:
        # **A REDIRECT IS NOT AN ANSWER, AND UNTIL THIS RUNG EXISTED IT WAS A SUCCESS.**
        # Neither adapter passes `follow_redirects` (httpx defaults it to False), so a 3xx
        # arrives here as a response with a `Location` header and, usually, no body — and
        # every branch below reads "not >= 400" as "the vendor did what we asked". Measured
        # rather than reasoned: a 302 on `GET /v2/agent/{id}` produced an `AgentSnapshot`
        # with every `*_readable` False (a drift sweep that records `unreadable` forever
        # instead of an error), a 302 on `PUT` reported a publish that wrote nothing, and a
        # 302 on `GET /agent/{id}/execution/{id}` produced `engine_call_id=''`,
        # `status='failed'`, no cost and no transcript — VERBATIM the invented answer this
        # module's own docstring says the shared ladder exists to prevent, reached by a
        # status no clause covered.
        #
        # NOT FOLLOWED, and that is the decision rather than the easy fix. A 307/308
        # re-sends the BODY, so following one on `POST /call` is how one contact is dialled
        # twice by an edge misconfiguration nobody deployed; a cross-host redirect makes
        # httpx strip the `Authorization` header, so what we would follow it with is an
        # unauthenticated request; and `tests/crm_audit_test.py` already settles the
        # doctrine for outbound calls in this tree — "a 3xx is a failure, not a delivery".
        # Our base URLs are exact API roots the adapter pins, so a redirect off one is an
        # edge, a proxy or a moved API — an operator's problem, and one they can only act
        # on if it is reported.
        #
        # `engine_bad_response` rather than a code of its own: to every caller this is the
        # same fact as a 200 carrying a WAF challenge — the vendor answered, and the answer
        # is not one we can use — and the rung below already has that name, that kind and
        # that alarm index row. `record_engine_failure` is deliberately NOT called, for the
        # same reason it is not called on that rung: the health counter is the "is the
        # VENDOR broken" signal, and an intermediary answering 302 is not evidence about
        # the vendor's own health.
        log.warning(
            "engine_redirect_response",
            extra={"engine": engine, "status": response.status_code, "route": path},
        )
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="Voice engine returned an unreadable response",
            detail="The voice platform redirected the request instead of answering it.",
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
        # Never echo a vendor error body to a CLIENT — it is not user-safe, it is not our
        # vocabulary, and vendor error bodies quote the request (hard rule 6:
        # `tests/engine_audit_test.py` drives a 400 whose body carries a caller's number).
        #
        # THE OPERATOR LOG IS A DIFFERENT AUDIENCE AND USED TO GET THE SAME NOTHING. A
        # line reading `engine_error status=400 route=/call` says the vendor refused and
        # withholds the only fact that distinguishes "our agent id is stale" from "our key
        # was revoked" — the vendor's own numeric code, which their envelope always
        # carries and which we were parsing past. `_vendor_error_code` is where the bound
        # that keeps this hard-rule-6-safe is argued; the human `message` beside it is
        # still discarded unread.
        vendor_error = _vendor_error_code(response)
        log.warning(
            "engine_error",
            extra={
                "engine": engine,
                "status": response.status_code,
                "route": path,
                "vendor_error": vendor_error,
            },
        )
        if response.status_code >= 500:
            # 5xx only: a 4xx is US getting the request wrong, and counting it would
            # page an operator for a bug no vendor can fix. The 429 rung above returns
            # before reaching here, deliberately — a throttle is the vendor working as
            # designed and has its own ladder (D-204).
            await record_engine_failure(engine, kind="server_error")
        raise EngineRejectedError(status=response.status_code, vendor_error=vendor_error)
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
    "REQUEST_REFUSED_STATUSES",
    "REQUEST_TIMEOUT_S",
    "THROTTLE_BASE_S",
    "THROTTLE_MAX_ATTEMPTS",
    "THROTTLE_MAX_SLEEP_S",
    "THROTTLE_STATUS",
    "EngineRejectedError",
    "throttle_delay_s",
    "vendor_request",
]
