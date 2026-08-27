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
default blend of ~50 central banks is deliberate: a blended number is not a benchmark
anybody can look up, and `billing/rates.LIST_PRICE_USD_INR` already states this repo's
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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.ops.fx_rates import (
    BASE_CURRENCY,
    QUOTE_CURRENCY,
    ImplausibleRateError,
    latest_observation,
    record_observation,
    refresh_fx_snapshot,
)

log = get_logger(__name__)

#: The exact request. Spelled once, here, so the URL an operator re-runs by hand to
#: reproduce a disputed figure is the URL the platform used — it is stored on every row
#: (`fx_rate_observations.source_url`) rather than reconstructed by a reader.
RATE_URL = f"https://api.frankfurter.dev/v2/rate/{BASE_CURRENCY}/{QUOTE_CURRENCY}"
#: The provider to filter to. See the module docstring for why it is not the default blend.
PROVIDER = "FBIL"
#: `<api>:<provider>`, stamped on the row and on every `usage_events` row it converts.
SOURCE = f"frankfurter:{PROVIDER}"

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
    operator: it names what was wrong with the response, never the response itself."""


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


async def fetch_published_rate(client: httpx.AsyncClient | None = None) -> tuple[Decimal, date]:
    """One GET, parsed. RAISES `FxPullError` on anything that is not a usable rate.

    `client` is an injection seam, not a second way of doing this: the tests exercise the
    parser and the failure ladder against a stub transport, because the live host cannot
    be reached from CI either.
    """
    http = client or httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=False)
    try:
        response = await http.get(RATE_URL, params={"providers": PROVIDER})
    except httpx.HTTPError as exc:
        raise FxPullError(f"the request failed ({type(exc).__name__})") from exc
    finally:
        if client is None:
            await http.aclose()
    if response.status_code != 200:
        # Their 404 means "no data found" — which for a single-provider filter is the real
        # possibility that FBIL has published nothing for this pair — and is as much a
        # failed pull as a 500. Neither is guessed around.
        raise FxPullError(f"the endpoint answered HTTP {response.status_code}")
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


async def pull_fx_rate(ctx: dict[str, Any]) -> str:
    """Every five minutes: fetch the published USD/INR rate and store it if it is new.

    Returns a small JSON summary (arq keeps it), which is what makes "the tick ran and
    stored nothing" answerable without reading a day of logs — and "stored nothing" is
    the CORRECT and overwhelmingly common outcome, because the publication is daily.
    """
    attempt = int(ctx.get("job_try", 1))
    try:
        rate, as_of = await fetch_published_rate()
        async with untenanted_session() as session:
            observation, inserted = await record_observation(
                session,
                rate=rate,
                as_of=as_of,
                source=SOURCE,
                source_url=RATE_URL,
            )
    except ImplausibleRateError as exc:
        # NOT retried. The feed answered, and we refused its answer — trying again in
        # thirty seconds asks the same question and gets the same number. This is a
        # human's problem from the first occurrence, and the previous rate keeps serving
        # until it ages out on its own.
        log.error("fx_rate_implausible", extra={"source": SOURCE})
        alert("WORKER_TERMINAL", "fx_rate_implausible", detail=str(exc), source=SOURCE)
        raise
    except Exception as exc:
        log.warning("fx_pull_failed", extra={"source": SOURCE, "error": type(exc).__name__})
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        await _warn_if_silent()
        # Alert THEN raise: returning would file the tick as a success. `alert()`
        # de-duplicates per fingerprint with an hourly bucket (BACKEND-PATTERNS §8), so a
        # feed that is down all day pages once, not 288 times.
        alert(
            "WORKER_TERMINAL",
            "fx_pull_failed",
            detail=f"{exc} (after {attempt} attempt(s)). Costs convert at the last stored rate.",
            source=SOURCE,
        )
        raise

    # This process is made current immediately rather than waiting for its own poll: the
    # worker is where `_meter` converts, so the tick that fetched the rate is the one that
    # should already be using it.
    await refresh_fx_snapshot()
    summary = {
        "rate": str(observation.rate),
        "as_of": observation.as_of.isoformat(),
        "source": SOURCE,
        "inserted": inserted,
    }
    log.info("fx_rate_pulled", extra=summary)
    return json.dumps(summary)


__all__ = [
    "MAX_PULL_SILENCE",
    "PROVIDER",
    "PULL_MINUTES",
    "RATE_URL",
    "SOURCE",
    "FxPullError",
    "fetch_published_rate",
    "parse_rate_response",
    "pull_fx_rate",
]
