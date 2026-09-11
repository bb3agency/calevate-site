"""Pull the published USD→INR rate, every five minutes, into the FX observation store.

WHAT THIS IS FOR
----------------
Every vendor on the cost side of this product invoices in dollars (Bolna, Azure) and
every figure this product records is rupees: `usage_events.unit_cost_paid` is INR, and
`engine/bolna.py::_cost` is the one place a dollar becomes one. Until now that
conversion used `Settings.usd_inr_rate` — a number an operator typed and a restart
applied — so the platform's margin drifted with the market and nobody could say by how
much. This job replaces the typing with a published rate and leaves the typed one as the
fallback for when the publication is missing.

THE SOURCE, AND EVERYTHING KNOWN ABOUT IT
-----------------------------------------
**Frankfurter** (`https://api.frankfurter.dev/v2`), filtered to the **FBIL** provider —
Financial Benchmarks India, the administrator whose daily USD/INR reference rate is the
benchmark Indian businesses reconcile against. Choosing FBIL rather than the API's
own default (unfiltered) response is deliberate: that answer is a blend whose
composition nothing in this tree has read, and a blended number is not a benchmark
anybody can look up. `billing/rates.LIST_PRICE_USD_INR` already states this repo's
convention that the rate a figure is struck at is a published Indian reference rate.

EVIDENCE (read 27 Aug 2026 — every fact below is from the project's own repository,
cloned at commit `60541ad190b6e192d2969038b2b299fb4800a8a2` from
`https://github.com/lineofflight/frankfurter`, because the API's own documentation host
IS EGRESS-BLOCKED FROM THIS ENVIRONMENT — see the UNVERIFIED note):

* server + endpoint + response shape — `lib/public/v2/openapi.json`:
  `servers[0].url = "https://api.frankfurter.dev/v2"`; `paths./rate/{base}/{quote}` GET
  returns the `Rate` schema, whose properties are exactly `date` (string, format date),
  `base`, `quote` and `rate` (`type: number`, `exclusiveMinimum: 0`); the documented
  example is `{"date": "2026-03-25", "base": "EUR", "quote": "USD", "rate": 1.1568}`.
  Errors are `404` ("No data found"), `422` and `503`, each a JSON object with a
  `message` string.
* the provider filter — `components.parameters.providers`: "Comma-separated list of data
  providers to include".
* FBIL — `lib/provider/adapters/fbil.rb`: "Financial Benchmarks India (FBIL). Publishes
  daily reference exchange rates for major currencies against the Indian rupee via a
  public JSON API."
* UPDATE FREQUENCY IS **DAILY**, not five-minutely, and this is the fact that shapes the
  whole design: `Provider.publish_cadence` in the OpenAPI enumerates
  `daily|weekly|monthly`, and `lib/versions/v2.rb::cache_control_for` caps the
  cache-control of a latest-rate query at the seconds remaining to UTC midnight, i.e.
  the vendor itself says the answer cannot change again today. The founder asked for a
  five-minute pull and gets one — the POLL is five-minutely so a new publication is in
  force within five minutes of appearing — but the DATA moves once a business day, which
  is why `observation_key` makes a repeat pull a no-op and why `core/fx.MAX_QUOTE_AGE` is
  measured in days rather than minutes.
* no API key: the v2 OpenAPI declares no `security` and no `components.securitySchemes`;
  nothing in the request below carries a credential.
* licence: MIT (`LICENSE`, "Copyright (c) Hakan Ensari"; `info.license` in the OpenAPI).
  ⚠ THAT COVERS THE SOFTWARE, NOT THE HOSTED SERVICE OR THE DATA. The MIT grant is not a
  commercial-use warranty for `api.frankfurter.dev`, and each upstream publisher carries
  its own terms (the `/providers` response exposes a `terms_url` per provider for exactly
  this). What makes that acceptable rather than a bet is that the same software is
  self-hostable — the README documents a one-command Docker deployment — so if the hosted
  endpoint's terms, availability or cadence ever fail us, `RATE_URL` moves to our own
  instance and nothing else in this file changes.
* RATE LIMITS: **UNKNOWN.** No primary artefact this session could read states one. The
  request rate here (288/day, one small GET) is not plausibly near any limit, and a 429
  is handled like any other non-2xx: the tick fails, the previous rate keeps serving.

⚠ **UNVERIFIED — `api.frankfurter.dev` IS EGRESS-BLOCKED FROM THIS ENVIRONMENT.** Every
foreign-exchange API host tried was refused by the egress proxy with a 403 on CONNECT
(measured 27 Aug 2026: `api.frankfurter.dev`, `api.frankfurter.app`, `open.er-api.com`,
`api.exchangerate.host`, `api.fxratesapi.com`, plus `www.ecb.europa.eu` and
`www.rbi.org.in` directly). So this adapter is written against the vendor's OWN OpenAPI
document and source, and NO BYTE OF A LIVE RESPONSE HAS BEEN SEEN. A human must run the
one command in OPERATIONS §2 gate 39 against the live endpoint and confirm the four field
names and the FBIL provider filter before this is trusted with money. Until then the
failure direction is safe: a response this parser does not recognise is REFUSED (never
guessed at), the platform keeps converting at `Settings.usd_inr_rate`, and the operator
is alerted.

THE LADDER: FBIL, THEN FRANKFURTER'S OWN DEFAULT, THEN THE TYPED CONSTANT
-------------------------------------------------------------------------
FBIL is PREFERRED and nothing below weakens that: it is the RBI-recognised Indian
benchmark an Indian business reconciles a rupee ledger against, which is the whole
argument of the section above. What changed on 11 Sep 2026 is that a preference with
nothing behind it is a single point of failure, and it failed. Production, every five
minutes, on schedule, with no alarm anywhere on the pull path:

    fx_rate_pulled rate=94.491400 as_of=2026-09-04 source=frankfurter:FBIL inserted=false

The pull was HEALTHY and the quote was seven days old — past `core/fx.MAX_QUOTE_AGE` —
so every vendor cost had quietly reverted to the operator's typed `usd_inr_rate`. Two
hand-run requests in the same minute separated the two failures that had looked like one:
the same URL WITHOUT the provider filter answered `2026-09-11`, and WITH
`providers=FBIL` answered `2026-09-04`. The API was publishing; the FBIL provider
specifically had stopped.
**EVIDENCE CLASS: VENDOR-MEASURED, founder-relayed** (two `curl`s against
`api.frankfurter.dev`, 11 Sep 2026). ⚠ NOT read from this container: the host is
egress-blocked here, as the block above records, and no byte of a live response has been
seen in this tree.

So there are three rungs, and the gap between the first and the last is no longer a week
of drift:

1. ``frankfurter:FBIL`` — the benchmark. Preferred whenever it can serve.
2. ``frankfurter:default`` — the SAME endpoint with NO `providers` filter, i.e. the API's
   own default response. Named for the REQUEST that produced it rather than for what is
   in it: what that default blends is a claim about the vendor's composition that nothing
   in this tree has read this session, and a source string stamped on a money row may not
   carry one (hard rule 11). It is a real rate published TODAY, which is strictly better
   than a constant typed a fortnight ago, and it is obviously not rung 1 on any row.
3. ``configured:usd_inr_rate`` — the operator's typed number, unchanged, and now reached
   only when every PUBLISHED rung is stale.

**A LOWER RUNG IS FETCHED ONLY WHEN A HIGHER ONE CANNOT SERVE; EVERY RUNG FETCHED IS
RECORDED.** Two rules, both load-bearing:

* the descent is LAZY, so a healthy day makes one request and stores one row, the
  preference costs nothing, and the platform never learns a number it did not need;
* the write is EAGER, so `fx_rate_observations` keeps what each rung actually said —
  including a stale FBIL row nobody served off — and `latest_observation`'s EXISTING rule
  (newest publication wins; among one publication date, the later row wins, so a
  correction supersedes) selects the serving rung with no second spelling of the ladder
  in SQL. That is why this is one row per rung rather than a preferred-rung-with-fallback
  shape: a usable lower rung is BY CONSTRUCTION newer than the higher rung that was too
  old to serve, so preference and recency already agree, and when FBIL resumes its newer
  publication takes the pair back with no state to reset and no flag to clear.

**THE PLAUSIBILITY BAND APPLIES TO EVERY RUNG, AND AN IMPLAUSIBLE RUNG STOPS THE TICK
RATHER THAN HANDING OVER TO THE NEXT ONE.** Every rung is written through
`ops/fx_rates.record_observation`, which is where `ImplausibleRateError` lives, so a
fallback cannot route around the guard that exists because a vendor's minor-unit
assumption once metered every call at 1/100th of cost. Descending on a REFUSED rate would
be that same defect wearing a ladder: "the feed is quiet" is what the ladder is for, "the
feed answered and we do not believe it" is a human's problem from the first occurrence.

**THE STALENESS CEILING IS PER-RUNG**, because it is a property of a QUOTE and always
was: `FxQuote.usable` is asked of the rate this rung just published, so a fresh rung 2 is
not stale merely because rung 1 is. `MAX_QUOTE_AGE` itself stays one constant — it
bounds a daily publication cadence both rungs share.

THREE STATES, THREE ALARMS (they used to be two, and two of them read alike)
---------------------------------------------------------------------------
* `fx_source_degraded` (CORE_LOGIC, raised here) — rung 1 cannot serve and a LOWER
  PUBLISHED rung is serving. Money is still converting at a rate somebody published
  today; what changed is the PROVENANCE on every `usage_events` row written from now on,
  and hard rule 4 means those rows can never be annotated later. Not urgent, and said so.
* `fx_rate_stale` (CORE_LOGIC, raised by `ops/fx_rates.refresh_fx_snapshot`) — EVERY
  published rung is past the ceiling, so the typed constant is serving. This is what that
  alarm meant before the ladder existed; it now means it about the whole ladder.
* `fx_pull_failed` / `fx_pull_silent` (WORKER_TERMINAL) — the PULLER itself is failing or
  has gone quiet. Unchanged.

IDEMPOTENT, KEYED, RETRIED (BACKEND-PATTERNS §4/§5)
---------------------------------------------------
* IDEMPOTENT at the row: `fx_rate_observations.observation_key` is UNIQUE and the insert
  is `ON CONFLICT DO NOTHING`. A five-minute poll of a daily publication inserts once and
  no-ops 287 times.
* SINGLE-FLIGHT three ways over, because this writes money's input: arq gives a cron the
  job id `fx_rate_pull:<intended run>` so two workers cannot run one tick; the write takes
  `pg_advisory_xact_lock` on the currency pair so the plausibility check and the insert
  are one critical section; and the unique key catches anything that still races.
* RETRIED, then ALERTED. There is no arq DLQ (`workers/settings.py`), so the last
  attempt's `alert()` IS the dead-letter mechanism. The defers are SHORT (30s, 60s)
  rather than the minutes `billing.issue_one_time_charges` uses, because the next tick is
  only five minutes away and a deferral that outlives its own schedule is just a second
  copy of the next tick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

import httpx
from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.ops.fx_rates import (
    BASE_CURRENCY,
    QUOTE_CURRENCY,
    FxObservation,
    ImplausibleRateError,
    latest_observation,
    record_observation,
    refresh_fx_snapshot,
)

log = get_logger(__name__)

#: The endpoint, without the per-rung query string. Spelled once, here, so the URL an
#: operator re-runs by hand to reproduce a disputed figure is the URL the platform used —
#: each rung's FULL url (query string included) is stored on the row it writes
#: (`fx_rate_observations.source_url`) rather than reconstructed by a reader.
RATE_URL = f"https://api.frankfurter.dev/v2/rate/{BASE_CURRENCY}/{QUOTE_CURRENCY}"
#: The provider the PREFERRED rung filters to. See the module docstring for why it is
#: preferred over the API's own default, and why that preference is not weakened by the
#: fallback below it.
PROVIDER = "FBIL"


@dataclass(frozen=True, slots=True)
class FxRung:
    """One published source, the exact request that reaches it, and why it is here.

    A rung is a REQUEST plus a SOURCE STRING, and the two are defined together on purpose:
    the string is stamped on every `usage_events` row the rate converts, and hard rule 4
    means that row can never be annotated afterwards — so the only thing that will ever
    explain a figure is a source an operator can turn back into the request that produced
    it. `url` is that request, verbatim, and it is what lands in `source_url`.
    """

    #: `<api>:<provider>`, stamped on the observation row and on every converted figure.
    source: str
    #: The `providers` query value, or `None` for the API's own default (unfiltered)
    #: response. `None` is a rung, not a missing value — see `url`.
    providers: str | None
    #: The operator's sentence for why this rung exists, used in the alarm that says the
    #: platform has fallen to it.
    why: str

    @property
    def url(self) -> str:
        """The FULL request, query string and all. One spelling: this is both what httpx
        is handed and what is written to the row, so the stored URL cannot drift from the
        one that was actually sent."""
        return RATE_URL if self.providers is None else f"{RATE_URL}?providers={self.providers}"


#: THE PREFERRED RUNG. The RBI-recognised Indian benchmark; see the module docstring.
FBIL_RUNG: Final = FxRung(
    source=f"frankfurter:{PROVIDER}",
    providers=PROVIDER,
    why=("the Indian benchmark rate a rupee ledger reconciles against"),
)
#: THE FALLBACK RUNG. The same endpoint with no provider filter — a rate the API itself
#: published today, which is what makes it better than a constant typed a fortnight ago.
DEFAULT_RUNG: Final = FxRung(
    source="frankfurter:default",
    providers=None,
    why=(
        "the rate API's own default response, which is a published rate from today rather "
        "than an operator's typed constant"
    ),
)

#: The ladder, in preference order. `pull_fx_rate` walks it and stops at the first rung
#: that can serve; nothing else in this repo encodes the order.
LADDER: Final[tuple[FxRung, ...]] = (FBIL_RUNG, DEFAULT_RUNG)
PREFERRED_RUNG: Final = LADDER[0]

#: Back-compatible alias for the preferred rung's source. Kept because it is what the
#: puller's own alarms are tagged with (`_warn_if_silent`) and what the production log
#: line has said since the feature shipped.
SOURCE = PREFERRED_RUNG.source

#: WHY A RUNG COULD NOT SERVE. A closed vocabulary, in `incomplete_reason`'s house style,
#: because it reaches an operator as a machine-readable alarm field and a log key rather
#: than as prose: the three cases have three different answers and an operator sorts on
#: them. `stale_publication` is the feed working normally and simply being behind;
#: `request_failed` is availability (a status code, a refused socket); `unusable_response`
#: is the vendor's CONTRACT having changed under us, which is the one that must be read
#: rather than waited out.
RungRefusal = Literal["stale_publication", "request_failed", "unusable_response"]

#: WHICH RUNG IS SERVING, for the tick summary arq keeps and the log line an operator
#: greps. Same closed-vocabulary reasoning: "is this platform billing off the benchmark"
#: is a question that must be answerable without parsing a sentence.
ServingRung = Literal["preferred", "fallback_source", "configured_fallback"]

#: Nothing is waiting on this request — no caller, no phone call — so the budget is
#: generous enough to survive a slow hop and short enough that a hung socket cannot hold
#: a worker slot into the next tick.
_TIMEOUT_S = 10.0

#: The schedule, in minutes past the hour — the founder's five minutes, spelled once here
#: so `settings.py` builds the `cron()` registration from it rather than repeating a set
#: that would drift from the docstring above it (the shape `engine_reconciliation` uses).
PULL_MINUTES = tuple(range(0, 60, 5))

#: Backoff by attempt. See the module docstring: short, because the next tick is close.
_RETRY_AFTER_S = (30, 60)

#: How long the store may go with NO SUCCESSFUL PULL before an operator is told, whatever
#: the data's own age says. THIS IS THE OTHER HALF OF `core/fx.MAX_QUOTE_AGE` and it
#: measures a different thing: that one bounds how old the RATE may be before money stops
#: using it, this one bounds how long the PULLER may be silent before somebody looks. They
#: differ because a weekend produces a two-day-old rate with a perfectly healthy poller,
#: and a dead poller on a Monday morning produces a fresh-looking rate that is about to
#: become a wrong one. Thirty minutes is six missed ticks — enough that a single blip or a
#: deploy does not page anybody, short enough that the feed is fixed long before the rate
#: itself ages out.
MAX_PULL_SILENCE = timedelta(minutes=30)


def _retry_after(attempt: int) -> int:
    return _RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]


class FxPullError(RuntimeError):
    """The pull did not produce a rate this deployment will store. Message is for an
    operator: it names what was wrong with the response, never the response itself.

    Raised bare by `parse_rate_response`, i.e. by the CONTRACT half — the response
    arrived and this parser refused it. That distinction became load-bearing when the
    ladder landed: the two halves are different `RungRefusal` values because they have
    different answers, so the subclass below carries the other one.
    """


class FxFeedUnreachableError(FxPullError):
    """The request never produced a response this parser could even look at — a transport
    failure or a non-200. A SUBCLASS rather than a sibling so every existing `except
    FxPullError` keeps catching it; what it adds is that the ladder can tell availability
    (`request_failed`, wait for the next tick) from a changed contract
    (`unusable_response`, read the vendor's docs before trusting anything)."""


def parse_rate_response(body: str) -> tuple[Decimal, date]:
    """The vendor's JSON to `(rate, as_of)`, or `FxPullError`.

    **THE RATE NEVER TOUCHES A BINARY FLOAT, AND THIS IS THE WHOLE REASON THIS FUNCTION
    EXISTS RATHER THAN A `response.json()` CALL.** The vendor publishes `rate` as a JSON
    `number` (`type: number` in their OpenAPI), and `json.loads` turns a number into a
    `float` — so `88.4275` would already be `88.42749999999999...` before any of our code
    saw it, and a rate that cannot be written down exactly is one nobody can reconcile a
    ledger against. `parse_float=Decimal` hands the parser's own TEXT slice to `Decimal`,
    which is the only lossless path from their wire to hard rule 7's NUMERIC.
    `parse_int=Decimal` covers the day the rate is published as `90` rather than `90.0`.

    Every field is checked rather than assumed, including the two that "cannot" be wrong:
    a `base`/`quote` that is not the pair we asked for means a redirect, a proxy or a
    changed route, and converting at somebody else's currency pair is the single most
    expensive way this could fail.
    """
    try:
        payload = json.loads(body, parse_float=Decimal, parse_int=Decimal)
    except ValueError:
        raise FxPullError("the response was not JSON") from None
    if not isinstance(payload, dict):
        raise FxPullError("the response was not a JSON object")

    base = payload.get("base")
    quote = payload.get("quote")
    if base != BASE_CURRENCY or quote != QUOTE_CURRENCY:
        raise FxPullError(
            f"the response is for {base}/{quote}, not {BASE_CURRENCY}/{QUOTE_CURRENCY}"
        )

    raw_rate = payload.get("rate")
    if not isinstance(raw_rate, Decimal):
        # A string, a null, or a missing key. Refused rather than coerced: a feed that
        # changed the type of its money field has changed in a way somebody must read
        # about before we bill on it.
        raise FxPullError("the response carried no numeric `rate`")
    if not raw_rate.is_finite() or raw_rate <= 0:
        raise FxPullError("the response carried a non-positive or non-finite `rate`")

    raw_date = payload.get("date")
    if not isinstance(raw_date, str):
        raise FxPullError("the response carried no `date`")
    try:
        as_of = date.fromisoformat(raw_date)
    except ValueError:
        raise FxPullError("the response's `date` was not an ISO date") from None
    if as_of > datetime.now(UTC).date() + timedelta(days=1):
        # A date in the future is a clock or a parser problem, and it would make a stale
        # rate look permanently fresh — `MAX_QUOTE_AGE` is measured against this field, so
        # it is the one value a bad feed could use to disable the staleness ceiling.
        raise FxPullError(f"the response's `date` ({raw_date}) is in the future")
    return raw_rate, as_of


async def fetch_published_rate(
    rung: FxRung, client: httpx.AsyncClient | None = None
) -> tuple[Decimal, date]:
    """One GET at ONE rung, parsed. RAISES `FxPullError` on anything that is not a rate.

    **THE PARSER IS SHARED ACROSS EVERY RUNG AND THAT IS THE WHOLE REASON THIS TAKES A
    RUNG RATHER THAN BEING COPIED.** Rung 2 is the same endpoint with one query parameter
    removed, so it has the same landmines — a future `date` that would disable the
    staleness ceiling, a `base`/`quote` that is not the pair we asked for, a `rate` whose
    type changed — and a second parser is a second place they get fixed one at a time.

    `client` is an injection seam, not a second way of doing this: the tests exercise the
    parser and the failure ladder against a stub transport, because the live host cannot
    be reached from CI either.
    """
    http = client or httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=False)
    try:
        response = await http.get(rung.url)
    except httpx.HTTPError as exc:
        raise FxFeedUnreachableError(f"the request failed ({type(exc).__name__})") from exc
    finally:
        if client is None:
            await http.aclose()
    if response.status_code != 200:
        # Their 404 means "no data found" — which for a single-provider filter is the real
        # possibility that FBIL has published nothing for this pair — and is as much a
        # failed pull as a 500. Neither is guessed around, and neither is a reason to stop
        # asking: the ladder simply moves down a rung.
        raise FxFeedUnreachableError(f"the endpoint answered HTTP {response.status_code}")
    return parse_rate_response(response.text)


async def _warn_if_silent() -> None:
    """Page an operator when the store has had no successful pull for too long.

    Runs on the FAILURE path only. `ops/fx_rates.refresh_fx_snapshot` alarms on the DATA
    going stale; this alarms on the PULLER going quiet, which happens first and is the
    signal that still has time to be acted on. Best-effort: a store we cannot read is
    already alarmed by the poll, and a second exception here would replace the failure
    the caller is about to report.
    """
    try:
        async with untenanted_session() as session:
            observation = await latest_observation(session)
    except Exception as exc:
        # Logged rather than swallowed: this runs on a path that is ALREADY failing, and a
        # silent return would hide the second failure behind the first.
        log.warning("fx_silence_check_failed", extra={"error": type(exc).__name__})
        return
    if observation is None:
        return
    silence = datetime.now(UTC) - observation.observed_at
    if silence > MAX_PULL_SILENCE:
        alert(
            "WORKER_TERMINAL",
            "fx_pull_silent",
            detail=(
                f"No USD/INR rate has been pulled for {int(silence.total_seconds() // 60)} "
                "minutes. Vendor costs are still being converted at the last published "
                "rate and will fall back to the configured USD_INR_RATE once it ages out."
            ),
            source=SOURCE,
        )


@dataclass(frozen=True, slots=True)
class LadderResult:
    """What one walk of the ladder found. `serving is None` means no published rung could
    serve, so the configured constant is what money will convert at."""

    #: The rung that is serving, its stored row, and whether THIS tick inserted that row.
    serving: tuple[FxRung, FxObservation, bool] | None
    #: Every rung that could not serve, in ladder order, with why.
    refusals: tuple[tuple[FxRung, RungRefusal], ...]
    #: The last exception a rung raised, kept so the failure path can report a CAUSE
    #: rather than "nothing worked".
    last_error: FxPullError | None

    def refusal_for(self, rung: FxRung) -> RungRefusal | None:
        return next((why for candidate, why in self.refusals if candidate is rung), None)

    @property
    def hard_failure(self) -> bool:
        """True when a rung did not merely publish something old — it did not answer, or
        answered something this parser refuses. That is the difference between "the feed
        is behind" (wait; the next tick asks again) and "the feed is broken" (retry, then
        page somebody), and the two must not share a failure path."""
        return any(why != "stale_publication" for _, why in self.refusals)


async def _walk_ladder(now: datetime) -> LadderResult:
    """Try each rung in preference order, stopping at the first that can serve.

    Every rung that PARSES is recorded even when it is too old to serve — see the module
    docstring — and every rung is recorded through `record_observation`, which is where
    the plausibility band lives, so no fallback can route around it. An
    `ImplausibleRateError` is alerted at the rung that produced it and then propagates:
    the ladder deliberately does NOT descend past a rate we refused to believe.
    """
    refusals: list[tuple[FxRung, RungRefusal]] = []
    last_error: FxPullError | None = None
    for rung in LADDER:
        try:
            rate, as_of = await fetch_published_rate(rung)
        except FxPullError as exc:
            # The subclass is the whole distinction: unreachable is availability, bare is
            # a contract change. Both are refusals; only one is worth reading docs over.
            why: RungRefusal = (
                "request_failed" if isinstance(exc, FxFeedUnreachableError) else "unusable_response"
            )
            last_error = exc
            refusals.append((rung, why))
            log.warning(
                "fx_rung_refused",
                extra={"source": rung.source, "reason": why, "error": type(exc).__name__},
            )
            continue
        try:
            async with untenanted_session() as session:
                observation, inserted = await record_observation(
                    session,
                    rate=rate,
                    as_of=as_of,
                    source=rung.source,
                    source_url=rung.url,
                )
        except ImplausibleRateError as exc:
            # NOT retried, and NOT descended past. The feed answered and we refused its
            # answer — asking again in thirty seconds gets the same number, and moving to
            # the next rung would let a broken rung hand the platform over without anybody
            # looking at it. A human's problem from the first occurrence; the previously
            # stored rate keeps serving until it ages out on its own.
            log.error("fx_rate_implausible", extra={"source": rung.source})
            alert("WORKER_TERMINAL", "fx_rate_implausible", detail=str(exc), source=rung.source)
            raise
        # The ceiling is asked of THIS rung's own quote, which is what makes staleness
        # per-rung: a fresh rung 2 is not stale because rung 1 is. One spelling of the
        # rule — `FxQuote.usable`, the same predicate money and the ops panel apply.
        if observation.as_quote().usable(now):
            return LadderResult(
                serving=(rung, observation, inserted), refusals=tuple(refusals), last_error=None
            )
        refusals.append((rung, "stale_publication"))
        log.warning(
            "fx_rung_refused",
            extra={
                "source": rung.source,
                "reason": "stale_publication",
                "as_of": observation.as_of.isoformat(),
            },
        )
    return LadderResult(serving=None, refusals=tuple(refusals), last_error=last_error)


async def pull_fx_rate(ctx: dict[str, Any]) -> str:
    """Every five minutes: walk the rate ladder and store what the serving rung published.

    Returns a small JSON summary (arq keeps it), which is what makes "the tick ran and
    stored nothing" answerable without reading a day of logs — and "stored nothing" is
    the CORRECT and overwhelmingly common outcome, because the publication is daily.
    """
    attempt = int(ctx.get("job_try", 1))
    now = datetime.now(UTC)
    try:
        result = await _walk_ladder(now)
    except ImplausibleRateError:
        # Already logged and alerted at the rung that produced it. Re-raised so the tick
        # is filed as the failure it is, and not retried — see `_walk_ladder`.
        raise
    except Exception as exc:
        # Anything that is NOT a rung refusing: the store is unreachable, the session
        # failed, the loop itself broke. A rung refusing never reaches here — it is
        # recorded in `refusals` and handled below — so this is infrastructure.
        log.warning("fx_pull_failed", extra={"source": SOURCE, "error": type(exc).__name__})
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        await _warn_if_silent()
        alert(
            "WORKER_TERMINAL",
            "fx_pull_failed",
            detail=f"{exc} (after {attempt} attempt(s)). Costs convert at the last stored rate.",
            source=SOURCE,
        )
        raise

    if result.serving is None and result.hard_failure:
        # NO rung served AND at least one did not answer properly. This is the failure the
        # retry ladder is for: a blip, a 503, a refused socket — all of which the next
        # attempt may well get past.
        failure = result.last_error or FxPullError("no rung produced a usable rate")
        reasons = ", ".join(f"{rung.source}={why}" for rung, why in result.refusals)
        log.warning("fx_pull_failed", extra={"source": SOURCE, "error": type(failure).__name__})
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from failure
        await _warn_if_silent()
        # Alert THEN raise: returning would file the tick as a success. `alert()`
        # de-duplicates per fingerprint with an hourly bucket (BACKEND-PATTERNS §8), so a
        # feed that is down all day pages once, not 288 times.
        alert(
            "WORKER_TERMINAL",
            "fx_pull_failed",
            detail=(
                f"{failure} (after {attempt} attempt(s); tried {reasons}). "
                "Costs convert at the last stored rate."
            ),
            source=SOURCE,
        )
        raise failure

    serving_state: ServingRung
    if result.serving is None:
        # EVERY published rung answered and every one of them is behind the ceiling. Not a
        # pull failure — the feeds are working, they are simply not publishing — so this
        # is neither retried nor paged from here. `refresh_fx_snapshot` below raises
        # `fx_rate_stale`, which is the alarm that has always meant "the typed constant is
        # what money is using", and now means it about the whole ladder.
        serving_state = "configured_fallback"
        log.warning(
            "fx_ladder_exhausted",
            extra={"refusals": ";".join(f"{r.source}={w}" for r, w in result.refusals)},
        )
    elif result.serving[0] is PREFERRED_RUNG:
        serving_state = "preferred"
    else:
        serving_state = "fallback_source"
        rung, observation, _ = result.serving
        preferred_refusal = result.refusal_for(PREFERRED_RUNG) or "request_failed"
        # DEGRADED, NOT DOWN. The rate is real and published today; what moved is the
        # provenance stamped on every `usage_events` row from this moment on, and hard
        # rule 4 means none of those rows can be annotated afterwards. So an operator is
        # told at the moment it moves, rather than discovering it in a reconciliation.
        alert(
            "CORE_LOGIC",
            "fx_source_degraded",
            detail=(
                f"The preferred USD/INR source {PREFERRED_RUNG.source} could not serve "
                f"({preferred_refusal}), so vendor costs are converting at {rung.source} — "
                f"{rung.why}. The rate is real and published ({observation.as_of.isoformat()}), "
                "but every usage_events row written from now on records the fallback source "
                "and cannot be re-stamped later."
            ),
            source=rung.source,
            preferred_source=PREFERRED_RUNG.source,
            reason=preferred_refusal,
        )

    # This process is made current immediately rather than waiting for its own poll: the
    # worker is where `_meter` converts, so the tick that fetched the rate is the one that
    # should already be using it. It also re-raises `fx_rate_stale` when nothing serves.
    await refresh_fx_snapshot()
    observation_or_none = result.serving[1] if result.serving is not None else None
    summary: dict[str, Any] = {
        "rate": str(observation_or_none.rate) if observation_or_none else None,
        "as_of": observation_or_none.as_of.isoformat() if observation_or_none else None,
        "source": result.serving[0].source if result.serving else None,
        "preferred_source": PREFERRED_RUNG.source,
        "serving": serving_state,
        "inserted": result.serving[2] if result.serving else False,
    }
    log.info("fx_rate_pulled", extra=summary)
    return json.dumps(summary)


__all__ = [
    "DEFAULT_RUNG",
    "FBIL_RUNG",
    "LADDER",
    "MAX_PULL_SILENCE",
    "PREFERRED_RUNG",
    "PROVIDER",
    "PULL_MINUTES",
    "RATE_URL",
    "SOURCE",
    "FxFeedUnreachableError",
    "FxPullError",
    "FxRung",
    "LadderResult",
    "RungRefusal",
    "ServingRung",
    "fetch_published_rate",
    "parse_rate_response",
    "pull_fx_rate",
]
