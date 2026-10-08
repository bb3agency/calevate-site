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

* **The throttle.** The argument is the one the first adapter made — "a throttle says
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
import json
import random
import re
from collections.abc import Callable
from typing import Any, Final

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger, redact_text
from apps.api.engine.health import record_engine_failure

log = get_logger(__name__)

#: Every vendor call in this package. Long enough for a control-plane write, short enough
#: that an adapter reached from a request handler cannot hold one open for a minute.
REQUEST_TIMEOUT_S = 10.0

# --- Throttle handling (SURFACES §3.3) ---------------------------------------
# A 429 refuses the request rather than performing it. The carrier (Vobiz) answers one when
# the account is over its calls-per-second OR its concurrent-call limit
# (`vobiz-findings/mirror/pages/call/make-call.md:134`), and its error envelope names the
# limit in `error.details.limitType`, with `error.details.retryAfter` in seconds
# (`errors.md:205-223`). The two need different answers:
#
# * `cps` clears within a second, so the ladder below backs off and retries, taking
#   `retryAfter` as the floor when no `Retry-After` header carries one.
# * the line limit clears only when a call ENDS, which a two-second backoff will not see, so
#   it is not retried at all: it is raised at once as `carrier_lines_busy` (transient, and a
#   dial that provably seized no line). The dial gate in `agents.service.dispatch_call`
#   counts lines before dialling (`engine/carrier_pacing.py`); this is the carrier's own
#   word for the case that count missed.
#
# The docs print one `limitType` value, `cps`; how the concurrency limit is spelled is
# UNKNOWN. So any OTHER named limit is read as the line limit (`is_line_limit`): a limit
# that is not per-second does not clear inside this ladder either way.
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
#
# **AND THERE IS NO CIRCUIT BREAKER.**
#
# THE CASE A BREAKER WOULD COVER IS NOT 429, IT IS SLOWNESS. `REQUEST_TIMEOUT_S` bounds
# ONE call, never the aggregate, so a vendor degrading to nine-second responses trips
# nothing above — every request succeeds — while each one holds its caller for nine
# seconds. That is the uncovered shape, and the question is whether anything else already
# bounds it. Read against the two callers, something does:
#
# * **The dial path is bounded twice over.** `campaign_dispatch._tick_lease` is a
#   platform-wide single-flight lease, so a slow tick cannot be joined by the next one
#   thirty seconds later — the second tick takes no lease, dials nothing and exits. And
#   within a tick the dials are SERIAL (`_dispatch_for_campaign` awaits one contact at a
#   time) and the tick's whole spend is capped by the outbound line pool
#   (`engine/carrier_pacing.outbound_line_pool`, two lines on a three-line account). So
#   the worst case is a handful of sequential ten-second calls, inside both
#   `WorkerSettings.job_timeout` (300s) and `TICK_LEASE_TTL_S` (330s). A degraded vendor
#   slows dialling; it cannot accumulate.
# * **The polling path is bounded by the job, and its failure is already alarmed.**
#   `pipeline.reconcile_outstanding_calls` probes up to `OUTSTANDING_PROBE_BUDGET` (200)
#   executions serially, which at ten seconds each does NOT fit in `job_timeout` — so arq
#   cancels the tick, and a cron cancelled three times running is the alert
#   `apps/workers/settings.py` already raises. The degradation surfaces as a named
#   incident rather than as silence.
#
# WHAT A BREAKER WOULD COST, against that. It is only useful if its state is SHARED — the
# four deployables are separate processes and a per-process breaker learns nothing from
# the other three — so it is a new Redis key with its own consistency, its own failure
# mode when Redis is the thing that is down, and its own half-open probe. On this vendor
# the half-open probe is the problem that decides it: the endpoint whose slowness we care
# about is `POST /call`, which is NOT idempotent, so "send one request to see if the
# vendor is back" is a live phone call to a real person placed by a state machine rather
# than by the compliance gate. An OPEN breaker is worse still — it refuses dials that
# `check_dispatch` has already cleared, which is a campaign that silently stops with no
# refusal recorded against any contact.
#
# So: bounded elsewhere, alarmed elsewhere, and the mechanism would put an unsolicited
# call in the hands of a timer. The gap this leaves is honest and named — a vendor that is
# slow but NOT failing makes campaigns dial slowly and makes reconciliation ticks die on
# `job_timeout`, and neither is repaired by tripping. It is also the gap the existing
# alarm cannot see: `engine/health.record_engine_failure` counts 5xx and unreachable
# minutes into `engine_error_spike`, i.e. FAILURES, and a nine-second 200 is not one. If
# that ever needs a control it is a LATENCY signal into that same surface — which already
# has the table, the window and the page — not a breaker in front of the dial.

THROTTLE_STATUS = 429
THROTTLE_MAX_ATTEMPTS = 3
THROTTLE_BASE_S = 0.5
THROTTLE_MAX_SLEEP_S = 8.0

#: The one `error.details.limitType` value the carrier documents, for its per-second limit
#: (`vobiz-findings/mirror/pages/errors.md:205-223`).
CPS_LIMIT_TYPE = "cps"


def is_line_limit(limit_type: str | None) -> bool:
    """Is this 429 over a limit that frees only when a call ends? Any named limit but `cps`."""
    return limit_type is not None and limit_type != CPS_LIMIT_TYPE


#: The code a dial is refused under when every line the account allows is in use. Raised
#: here for the carrier's own 429 and by the dial gate's line count
#: (`engine/carrier_pacing.py`); both mean no line was seized.
LINES_BUSY_CODE = "carrier_lines_busy"


def lines_busy_error() -> ProblemError:
    """`carrier_lines_busy`: every line is in use, so the call was not placed."""
    return ProblemError(
        kind="transient",
        code=LINES_BUSY_CODE,
        title="All lines are busy",
        detail="Every line on the calling account is in use right now, so the call was not placed.",
        remediation="Try again in a minute.",
        failure_stage="CORE_LOGIC",
    )


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

#: How much of the vendor's `message` is READ before anything is done to it. Not the
#: bound an operator sees — `redact_text` caps that at `core.logging._MAX_FREE_TEXT`
#: (200 characters) — this one bounds the WORK. What answers a 4xx is not always the
#: vendor: an edge, a WAF or a proxy can put a whole HTML page in an `error` body, and
#: running two regex passes over a megabyte of it, per failed request, on the dispatcher's
#: serial dial loop, is a cost a stranger gets to choose for us. 512 is past any message
#: this vendor has ever been documented to send (their own worked examples are twenty
#: characters) and is comfortably wider than the 200 that will survive, so the visible
#: text is never the one that was cut here.
_VENDOR_MESSAGE_READ_LIMIT = 512

#: Runs of anything that is not printable ASCII, replaced whole before redaction.
#:
#: THIS IS THE HALF `redact_text` CANNOT DO, and it is here rather than in the redactor
#: because it is a statement about a VENDOR ERROR ENVELOPE, not about free text in
#: general. `redact_text` recognises digit runs and email addresses; it cannot recognise
#: a name or a Telugu sentence, which is the whole of `core.logging.redact_exception`'s
#: argument for withholding exception messages outright. The class of hard-rule-6 data
#: this product actually holds in bulk is Telugu conversation, and it is not ASCII — so
#: holding the admitted text to printable ASCII removes it structurally, in the same way
#: the int32 bound removes an E.164 number from the `error` field, rather than by trusting
#: a route to be safe.
#:
#: A MARKER RATHER THAN A DROP, both ways. Dropping the whole message on one em dash
#: would throw away the diagnosis to punish a punctuation mark; silently deleting the run
#: would let `"agent<TELUGU>id"` read as a word we never saw. The marker says a thing was
#: there and was not shown. Control characters go the same way, which also means a vendor
#: cannot write newlines or terminal escapes into our log stream.
_NON_PRINTABLE_RE = re.compile(r"[^\x20-\x7e]+")
_NON_PRINTABLE = "[non-ascii]"


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
      was one. See `_vendor_error_code` for the bound that admits it.

    THE VENDOR'S `message` IS NOT HERE, AND `detail` IS NOT IT EITHER. Since 10 Sep 2026
    the ladder does log that sentence, bounded and redacted (`_vendor_error_message`) —
    but to the OPERATOR LOG and nowhere else, because `detail` is not an operator
    surface. `ProblemError.as_problem` puts `detail` in the problem+json body verbatim,
    `apps/web/src/lib/api/client.ts:75` makes it the message the browser throws, and
    `apps/web/src/lib/authn/problems.ts:12` says outright that "most screens in this app
    render `problem.detail`". `engine_rejected` is raised on client-realm routes as well
    as admin ones — a tenant editing a live agent re-publishes it, and the CRM dial
    buttons reach the same ladder — so a vendor string on `detail` is a vendor string on
    a client's screen, in the vendor's vocabulary, quoting a payload, on a surface hard
    rule 5's own "user-safe messages (no internals)" rule governs. It stays generic.

    It is not carried on the exception either: no caller has a use for it that the log
    line does not already serve, and `apps/workers/campaign_dispatch._dial_failure_reason`
    holds "the vendor's human message never reaches this process at all" as a
    by-construction property of hard rule 6. Adding an attribute nobody reads would cost
    that property and buy nothing.

    A SUBCLASS RATHER THAN A NEW ERROR CODE. `engine_rejected` is read by name in a dozen
    places (`pipeline.TRANSIENT_ENGINE_CODES`' complement, the alarm index row, the
    conformance clauses); splitting it into two codes would make every one of them a
    two-branch decision to keep a fact that belongs on the exception. `isinstance` is
    opt-in: a caller that does not care is not changed at all.
    """

    def __init__(
        self,
        *,
        status: int,
        vendor_error: int | None = None,
        refused_statuses: frozenset[int] = REQUEST_REFUSED_STATUSES,
    ) -> None:
        super().__init__(
            kind="dependency",
            code="engine_rejected",
            title="Voice engine rejected the request",
            detail="The voice platform could not complete this operation.",
            failure_stage="CORE_LOGIC",
        )
        self.vendor_status = status
        self.vendor_error = vendor_error
        self._refused_statuses = refused_statuses

    @property
    def request_refused(self) -> bool:
        """True when the vendor's own docs say this status means "I did not do it"."""
        return self.vendor_status in self._refused_statuses


#: A dial the VENDOR refused because the person opted out with it or is on its own
#: do-not-call list. A fact about the person, not the account: a batch dialler settles the
#: contact (`compliance.service.PERSON_LEVEL_REFUSALS`) rather than re-asking every thirty
#: minutes for ever, and nothing rang (`agents.service.DIAL_NOT_PLACED_CODES`).
RECIPIENT_OPTED_OUT_CODE = "engine_recipient_opted_out"


def recipient_opted_out_error() -> ProblemError:
    """`engine_recipient_opted_out`: the voice platform will not call this person. A refusal
    about one person and not an alarm, so a 4xx kind and no `failure_stage`."""
    return ProblemError(
        kind="business_rule",
        code=RECIPIENT_OPTED_OUT_CODE,
        title="This person cannot be called",
        detail="The voice platform has this number marked as not to be called, so the call "
        "was not placed.",
        remediation="Remove the number from the campaign or lead list.",
    )


class EngineRateLimitedError(ProblemError):
    """`engine_rate_limited`, carrying the vendor's `Retry-After` when it sent one.

    Same code, kind and wording as before, so every reader keyed on `code` is unchanged.
    `retry_after_s` is opt-in, for the dial gate's engine back-off
    (`engine/carrier_pacing.start_dial_backoff`): a dial refused for the workspace's call
    ceiling should hold the next dial off for as long as the vendor asked, not re-ask it
    for every contact the same tick claimed.
    """

    def __init__(self, *, retry_after_s: float | None = None) -> None:
        super().__init__(
            kind="transient",
            code="engine_rate_limited",
            title="Voice engine is rate limiting us",
            detail="The voice platform is temporarily refusing new requests.",
            remediation="The lines are busy. Try again in a minute.",
            failure_stage="CORE_LOGIC",
        )
        self.retry_after_s = retry_after_s


def _error_envelope(response: httpx.Response) -> dict[str, Any] | None:
    """The vendor's error body as a mapping, or None when there is not one to read.

    ONE PARSE, TWO READERS. `_vendor_error_code` and `_vendor_error_message` used to be
    one function because only one field was admitted; now that two are, parsing twice
    would mean four "this body is not what the schema says" branches in two places that
    have to agree, and a second `response.json()` over the same bytes on every failed
    request. The malformed shapes are decided here, once — no body, not JSON at all
    (an edge's HTML page in front of the vendor), or JSON that is not an object.
    """
    if not response.content:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _vendor_error_code(envelope: dict[str, Any] | None) -> int | None:
    """The integer out of the vendor's error envelope.

    Their 4xx/5xx body is `{"error": <int>, "message": "<human text>"}` — declared
    `required: [error, message]` with `error` as `type: integer, format: int32`
    (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/api-reference/errors.md:26-33`,
    schema at `api-reference/calls/make.md:229-239`).

    It is the vendor's own identifier for the refusal, so "every dial is failing" becomes
    a value to quote at their support desk rather than a shrug. It is admitted only when
    it really is an `int` inside the int32 range the schema declares — a bound that
    structurally cannot hold an E.164 number, since `919876543210` is two orders of
    magnitude past int32's ceiling — so this field cannot quietly become a PII channel if
    the vendor widens it later. `bool` is excluded explicitly because in Python it *is*
    an `int`, and `{"error": true}` is not a code.
    """
    if envelope is None:
        return None
    value = envelope.get("error")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if -_INT32_MAX - 1 <= value <= _INT32_MAX else None


def _vendor_error_message(envelope: dict[str, Any] | None) -> str | None:
    """The human half of the envelope, bounded and redacted — never the raw string.

    **THIS FUNCTION USED NOT TO EXIST, AND ITS DOCSTRING SAID `message` MUST NEVER LEAVE
    THE PARSER.** The production line that changed the reading, 10 Sep 2026 23:22:54:
    an operator pressed Publish, `POST /v2/agent` came back `400`, and the record was
    `engine_error status=400 route=/v2/agent vendor_error=null` beside a client-facing
    "The voice platform could not complete this operation." A 400 is not 401 — the key
    authenticated and the vendor refused the PAYLOAD — and we had thrown away the only
    sentence that says which field of it. There is no runbook page for that; there is
    only a shell and a guess.

    WHY THE OLD ARGUMENT WAS SOUND AND STILL TOO WIDE. It ran: the message is the vendor
    quoting our request back at us, their own worked examples for `POST /call` are
    `agent_id is required` and `recipient_phone_number is required`
    (`bolna-findings/mirror/pages/api-reference/calls/make.md:62-63`), and the field being
    complained about on that route IS a caller's phone number. All true — of `/call`. It
    is not true of `/v2/agent`, whose payload is prompts, model config and voice ids. But
    a PER-ROUTE ALLOWLIST is the wrong answer to that, and deliberately not what is built
    here: the vendor writes the string, so a "safe" route is only safe until they echo
    something else into it, and the person who adds route number six to the list a year
    from now inherits a promise nobody can keep.

    WHAT IS BUILT INSTEAD IS THE MECHANISM THIS REPO ALREADY HAS FOR EXACTLY THIS.
    `core.logging`'s own docstring names the case — "`redact_text()` — a value-level
    scrubber for the places where free text is unavoidable (an upstream error string that
    may quote a payload)" — and it is what every log extra, every rendered message and
    `alert()`'s body already pass through. So the message is admitted the way the integer
    is: only in a form we bound.

    THREE BOUNDS, IN THIS ORDER, AND NONE OF THEM DEPENDS ON THE ROUTE.

    1. **Read at most `_VENDOR_MESSAGE_READ_LIMIT`**, so an edge's HTML page cannot make
       us regex a megabyte per failure.
    2. **Non-printable-ASCII runs become a marker** (`_NON_PRINTABLE_RE`). This is the
       bound that answers `redact_exception`'s objection — that a redactor cannot
       recognise a name or a Telugu sentence — for the one data class this product holds
       in bulk. It is structural, like the int32 ceiling, not a judgement about a route.
    3. **`redact_text`**, which masks E.164-shaped digit runs and email addresses and
       caps the result at 200 characters. The cap is measured AFTER masking, and the read
       limit is wider than the cap, so no digit run can be cut in half by either bound and
       surface as a partial number: what a truncation removes was never shown at all.

    WHAT SURVIVES THE THREE IS STILL NOT PROVEN CLEAN, and that is stated rather than
    hidden: an English personal name inside a vendor error message would pass all three.
    That is a real residue, and it is accepted here on the same asymmetry the `error`
    field was accepted on — bounded exposure of a string the vendor wrote about OUR
    request, against a refusal an operator cannot diagnose at all. It is accepted for the
    LOG only. It reaches no client: see `EngineRejectedError.__init__` for why `detail`
    stays generic.
    """
    if envelope is None:
        return None
    raw = envelope.get("message")
    if not isinstance(raw, str):
        return None
    printable = _NON_PRINTABLE_RE.sub(_NON_PRINTABLE, raw[:_VENDOR_MESSAGE_READ_LIMIT])
    redacted = redact_text(printable).strip()
    # An envelope carrying `"message": "   "` has told us nothing, and a log key whose
    # value is an empty string reads like a bug in the reader rather than like silence
    # from the vendor. `None` is the same shape the other three malformed cases produce.
    return redacted or None


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


def _throttle_details(response: httpx.Response) -> tuple[str | None, float | None]:
    """`(limitType, retryAfter)` from a 429's error envelope, either one None when absent.

    The envelope is `{"error": {"details": {"limitType": "cps", "retryAfter": 1}}}`
    (`vobiz-findings/mirror/pages/errors.md:205-223`). Anything not in that shape is no
    information, and the ladder falls back to the header and its own backoff.
    """
    envelope = _error_envelope(response)
    error = envelope.get("error") if envelope is not None else None
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, dict):
        return None, None
    limit_type = details.get("limitType")
    retry_after = details.get("retryAfter")
    seconds = (
        float(retry_after)
        if isinstance(retry_after, int | float)
        and not isinstance(retry_after, bool)
        and retry_after >= 0
        else None
    )
    return (limit_type if isinstance(limit_type, str) else None), seconds


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


async def _vendor_response(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    engine: str,
    route: str,
    absent_is_success: bool,
    extra_refused_statuses: frozenset[int],
    **kwargs: Any,
) -> httpx.Response | None:
    """The throttle ladder and every refusal rung of `vendor_request`, shared with
    `vendor_audio_request`; None when an absent object is the caller's success."""
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
        limit_type, body_retry_after = _throttle_details(response)
        if is_line_limit(limit_type):
            # Lines free up when a call ends, not within this ladder's few seconds.
            break
        header_retry_after = _retry_after_seconds(response)
        retry_after = header_retry_after if header_retry_after is not None else body_retry_after
        last_attempt = attempt == THROTTLE_MAX_ATTEMPTS - 1
        if last_attempt or (retry_after is not None and retry_after > THROTTLE_MAX_SLEEP_S):
            break
        log.warning(
            "engine_throttled", extra={"engine": engine, "route": route, "attempt": attempt + 1}
        )
        await asyncio.sleep(throttle_delay_s(attempt, retry_after))

    if response.status_code == THROTTLE_STATUS:
        if is_line_limit(_throttle_details(response)[0]):
            log.warning("carrier_lines_busy", extra={"engine": engine, "route": route})
            raise lines_busy_error()
        # Distinct from `engine_rejected` on purpose. A throttle says nothing about
        # the request — so on the campaign path it must not burn a contact's retry
        # budget for a reason that has nothing to do with the contact. `transient`
        # is the ladder rung that means "identical retry can work" (503, retryable),
        # and `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` reads exactly this code.
        # The remediation is what a person pressing a button can do: nothing retries a
        # button press for them.
        log.warning("engine_throttle_exhausted", extra={"engine": engine, "route": route})
        header_after = _retry_after_seconds(response)
        raise EngineRateLimitedError(
            retry_after_s=(
                header_after if header_after is not None else _throttle_details(response)[1]
            )
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
            extra={"engine": engine, "status": response.status_code, "route": route},
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
        log.info("engine_delete_already_absent", extra={"engine": engine, "route": route})
        return None
    if response.status_code >= 400:
        # Never echo a vendor error body to a CLIENT — it is not user-safe, it is not our
        # vocabulary, and vendor error bodies quote the request (hard rule 6:
        # `tests/engine_audit_test.py` drives a 400 whose body carries a caller's number).
        #
        # THE OPERATOR LOG IS A DIFFERENT AUDIENCE AND USED TO GET THE SAME NOTHING. A
        # line reading `engine_error status=400 route=/call` says the vendor refused and
        # withholds the only facts that distinguish "our agent id is stale" from "our key
        # was revoked" — the vendor's own numeric code and the sentence beside it, both of
        # which their envelope always carries and both of which we were parsing past.
        # `_vendor_error_code` and `_vendor_error_message` are where the bounds that keep
        # each of them hard-rule-6-safe are argued; neither reaches the client body.
        #
        # `vendor_message` is NOT a key `REDACT_KEYS` matches, and that is deliberate
        # rather than lucky: a key containing `text`, `body` or `payload` would be
        # replaced wholesale by the formatter and this would have been an elaborate way
        # to log `[redacted]`. The value is redacted at the source instead, so it is safe
        # in `caplog.records` too — where the formatter has not run yet, and where
        # `tests/vendor_error_message_test.py` reads it precisely because an assertion
        # that only held after formatting would pass on a raw `log.warning` here.
        envelope = _error_envelope(response)
        vendor_error = _vendor_error_code(envelope)
        log.warning(
            "engine_error",
            extra={
                "engine": engine,
                "status": response.status_code,
                "route": route,
                "vendor_error": vendor_error,
                "vendor_message": _vendor_error_message(envelope),
            },
        )
        if response.status_code >= 500:
            # 5xx only: a 4xx is US getting the request wrong, and counting it would
            # page an operator for a bug no vendor can fix. The 429 rung above returns
            # before reaching here, deliberately — a throttle is the vendor working as
            # designed and has its own ladder (D-204).
            await record_engine_failure(engine, kind="server_error")
        raise EngineRejectedError(
            status=response.status_code,
            vendor_error=vendor_error,
            refused_statuses=REQUEST_REFUSED_STATUSES | extra_refused_statuses,
        )
    return response


async def vendor_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    engine: str,
    route: str,
    absent_is_success: bool = False,
    extra_refused_statuses: frozenset[int] = frozenset(),
    parse_float: Callable[[str], Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """One vendor round trip, with the throttle ladder and the error normalization.

    `route` is the path TEMPLATE (`/Account/{auth_id}/numbers/{number}/application`) and is
    the only form of the path any log line here carries. The concrete `path` holds whatever
    the caller interpolated into it — a phone number on the carrier's number-binding routes,
    the account's auth id on every carrier route — and a log record is read raw by `caplog`,
    by any handler that is not our formatter, and by Sentry's breadcrumbs, so redacting it at
    format time is not enough (hard rule 6). It is required, not defaulted to `path`, so a
    new call site cannot log a concrete path by omission.

    `extra_refused_statuses` widens `REQUEST_REFUSED_STATUSES` for ONE call site, and only
    with a status that vendor's own documentation defines as a refusal of that request
    (Vobiz's `402` on call create, `call/make-call.md:132`). The default set is unchanged
    for every other caller.

    `parse_float` is handed to `json.loads` for the success body, so a caller reading money
    can take every JSON number as `Decimal` and never pass it through a binary float.

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
    response = await _vendor_response(
        client,
        method,
        path,
        engine=engine,
        route=route,
        absent_is_success=absent_is_success,
        extra_refused_statuses=extra_refused_statuses,
        **kwargs,
    )
    if response is None:
        return {}
    if not response.content:
        # A successful DELETE may answer 204/empty. `response.json()` raises on an
        # empty body, and a delete that "failed" only because the vendor said
        # nothing is the worst possible lie on this particular path.
        return {}
    try:
        payload = json.loads(response.content, parse_float=parse_float)
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
            extra={"engine": engine, "status": response.status_code, "route": route},
        )
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="Voice engine returned an unreadable response",
            detail="The voice platform answered successfully with a body we could not read.",
            failure_stage="CORE_LOGIC",
        ) from None
    return payload if isinstance(payload, dict) else {"data": payload}


#: The most audio one vendor answer may carry. A spoken preview line is tens of kilobytes;
#: ten megabytes is the vendor's own ceiling on a clone's source recording.
AUDIO_MAX_BYTES: Final = 10 * 1024 * 1024


async def vendor_audio_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    engine: str,
    route: str,
    **kwargs: Any,
) -> tuple[bytes, str]:
    """`vendor_request` for a route that answers with audio rather than JSON: the bytes and
    their content type. A success that is not audio, or is empty or oversized, is refused as
    `engine_bad_response`, never handed on as a recording."""
    response = await _vendor_response(
        client,
        method,
        path,
        engine=engine,
        route=route,
        absent_is_success=False,
        extra_refused_statuses=frozenset(),
        **kwargs,
    )
    content_type = (
        ("" if response is None else response.headers.get("content-type", "").split(";")[0])
        .strip()
        .lower()
    )
    body = b"" if response is None else response.content
    if not content_type.startswith("audio/") or not body or len(body) > AUDIO_MAX_BYTES:
        log.warning(
            "engine_audio_unusable",
            extra={"engine": engine, "route": route, "bytes": len(body)},
        )
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="Voice engine returned an unreadable response",
            detail="The voice platform answered without usable audio.",
            failure_stage="CORE_LOGIC",
        )
    return body, content_type


__all__ = [
    "AUDIO_MAX_BYTES",
    "CPS_LIMIT_TYPE",
    "LINES_BUSY_CODE",
    "RECIPIENT_OPTED_OUT_CODE",
    "REQUEST_REFUSED_STATUSES",
    "REQUEST_TIMEOUT_S",
    "THROTTLE_BASE_S",
    "THROTTLE_MAX_ATTEMPTS",
    "THROTTLE_MAX_SLEEP_S",
    "THROTTLE_STATUS",
    "EngineRateLimitedError",
    "EngineRejectedError",
    "lines_busy_error",
    "recipient_opted_out_error",
    "throttle_delay_s",
    "vendor_audio_request",
    "vendor_request",
]
