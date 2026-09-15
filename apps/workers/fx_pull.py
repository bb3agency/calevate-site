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

THE SOURCE: **FBIL, DIRECTLY** (D-609, 15 Sep 2026)
---------------------------------------------------
**Financial Benchmarks India Pvt Ltd** is the benchmark administrator whose daily
USD/INR reference rate is the number an Indian business reconciles a rupee ledger
against, and it is the number this platform has wanted since the feature shipped. Until
D-609 it was reached through an AGGREGATOR — `api.frankfurter.dev` with
`?providers=FBIL` — and the aggregator was a third party sitting in the money path for
no purpose except that it was already integrated. **The top rung now calls FBIL's own
endpoint.** It needs no API key, adds no deployable, and removes one party whose
availability, terms and reading of the source were all things we had to trust without
being able to check.

`billing/rates.LIST_PRICE_USD_INR` already states this repo's convention that the rate a
figure is struck at is a published Indian reference rate; this rung is the first one that
gets it from the publisher.

**REJECTED: SELF-HOSTING FRANKFURTER.** It is the escape hatch this module's own evidence
block used to name, and reading the software closed it. At pinned commit
`45e1b89ab0a725aedecdd1fa678a22eff5908a48` it is a **Ruby 4.0.6** service (puma, a
scheduler, SQLite) whose scheduler continuously backfills **ninety-nine** provider
adapters. That is a second language runtime, a second deployable, a second backup and
restore drill, and ninety-eight currency-source integrations this product will never
read — to serve ONE currency pair we can fetch in one GET. Going direct costs a parser.

THE WIRE CONTRACT, AND WHOSE READING OF FBIL IT IS
---------------------------------------------------
**EVIDENCE CLASS: VERIFIED-OSS-AT-PINNED-COMMIT — and it is FRANKFURTER'S READING OF
FBIL, NOT FBIL'S OWN PUBLISHED DOCUMENTATION.** Every line below is read from
`lib/provider/adapters/fbil.rb` in `github.com/lineofflight/frankfurter` at commit
`45e1b89ab0a725aedecdd1fa678a22eff5908a48` — i.e. from a third party's working client of
this endpoint. FBIL publishes no API documentation this tree has read, so nothing here is
the administrator's own statement of its contract and none of it may be quoted as such.

* `GET https://www.fbil.org.in/wasdm/refrates/fetchfiltered` with query parameters
  `fromDate` (`YYYY-MM-DD`), `toDate` (`YYYY-MM-DD`) and `authenticated` — whose value is
  the STRING `"false"`, not a boolean.
* The 200 body is a JSON **ARRAY** of records; their adapter raises on a non-array.
* Three fields are read per record: `subProdName` (string), `processRunDate` (a date
  string), `rate` (numeric). A record missing any of the three, or whose `rate` is not
  numeric, is SKIPPED.
* `subProdName` carries the pair AND ITS UNITS, matched with `INR / (\\d+) ([A-Z]{3})`:
  group 1 is the number of UNITS of the foreign currency the rate is quoted per, group 2
  is that currency. Their own comment's example is `"INR / 100 JPY"`, i.e. rupees per ONE
  HUNDRED yen. A record whose name does not match is skipped; `units == 0` is skipped;
  the rate is `rate / units`, and a result of `0` is skipped.
* The observation date is `processRunDate`.

**THE UNITS DIVISION IS THE WHOLE RISK ON THIS RUNG.** `FxQuote.rate` is INR per ONE
dollar, and a feed that ever published `"INR / 100 USD"` would, if units were assumed to
be 1, reprice every invoice by a factor of a hundred — the same defect class as
`engine/bolna._MINOR_UNITS_PER_MAJOR`, which once metered every call at 1/100th of cost.
So units are read from the record and divided as `Decimal`, never assumed, and
`ops/fx_rates.MAX_PLAUSIBLE_MOVE` stands behind the arithmetic as the second guard.

⚠ **UNVERIFIED — `www.fbil.org.in` IS EGRESS-BLOCKED FROM THIS ENVIRONMENT AND NO BYTE OF
A LIVE RESPONSE HAS BEEN SEEN.** Measured from this container on 15 Sep 2026:
`curl -sS -o /dev/null -w '%{http_code}' 'https://www.fbil.org.in/wasdm/refrates/fetchfiltered?...'`
→ `curl: (56) CONNECT tunnel failed, response 403`, HTTP `000`. So the LIVE RESPONSE
SHAPE is unverified in exactly the way `api.frankfurter.dev`'s was: this parser is
written against a third party's client of the endpoint and is the only thing standing
between a changed feed and every invoice. Two further facts about the live endpoint are
**UNKNOWN and are recorded as UNKNOWN rather than assumed**: whether FBIL rate-limits
this endpoint, and whether it requires a `User-Agent` (or any other header) to answer at
all. No header is invented here — the request sends what `httpx` sends by default — and
OPERATIONS §2 gate 39 is where a human with egress settles all three.

The failure direction is the one this module has always taken: a response this parser
does not recognise is REFUSED with the reason named, never guessed at, and the platform
keeps converting at the rate it already had.

THE LADDER: FBIL DIRECT, THEN FRANKFURTER'S FBIL, THEN FRANKFURTER'S DEFAULT, THEN THE
TYPED CONSTANT
--------------------------------------------------------------------------------------
Four rungs. The first is new (D-609); the other three are D-589's, unchanged, and the
incident that produced them is why a preference with nothing behind it is not allowed
here. Production, every five minutes, on schedule, with no alarm anywhere on the pull
path:

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

So the rungs are:

1. ``fbil:refrates`` — the administrator's own endpoint. The benchmark, from the
   benchmark's publisher, with nobody in between.
2. ``frankfurter:FBIL`` — the SAME benchmark read by a third party over a different host
   and a different network path. It is NOT redundant with rung 1 and that is why it
   survived D-609: rung 1 failing is most often `www.fbil.org.in` being unreachable or
   having changed its contract, and neither of those is true of `api.frankfurter.dev`.
   What the two rungs SHARE is the publisher, so when FBIL itself stops publishing they
   go stale together — which is what rung 3 is for.
3. ``frankfurter:default`` — the same Frankfurter endpoint with NO `providers` filter,
   i.e. the API's own default response. Named for the REQUEST that produced it rather
   than for what is in it: what that default blends is a claim about the vendor's
   composition that nothing in this tree has read, and a source string stamped on a money
   row may not carry one (hard rule 11). It is a real rate published TODAY, which is
   strictly better than a constant typed a fortnight ago, and it is obviously not the
   benchmark on any row.
4. ``configured:usd_inr_rate`` — the operator's typed number, unchanged, and reached only
   when every PUBLISHED rung is stale.

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
  old to serve, so preference and recency already agree, and when the benchmark resumes
  its newer publication takes the pair back with no state to reset and no flag to clear.

**A RUNG IS A REQUEST, A PARSER AND A SOURCE STRING.** Rung 1 speaks a different wire
language from rungs 2 and 3 — a different host, a dated query window, an ARRAY rather
than an object — and it is still ONE ladder walked by ONE loop. `FxRung` carries the
request builder and the parser as fields rather than the loop branching on which rung it
is holding: a second ladder, a second poller or an `if rung is FBIL_DIRECT_RUNG` inside
the walk are three spellings of the same defect, because each one is a place the
plausibility guard, the eager write or the per-rung staleness rule can be forgotten for
one rung and nobody notices until a bill is wrong.

**THE PLAUSIBILITY BAND APPLIES TO EVERY RUNG, AND AN IMPLAUSIBLE RUNG STOPS THE TICK
RATHER THAN HANDING OVER TO THE NEXT ONE.** Every rung is written through
`ops/fx_rates.record_observation`, which is where `ImplausibleRateError` lives, so a
fallback cannot route around the guard that exists because a vendor's minor-unit
assumption once metered every call at 1/100th of cost. Descending on a REFUSED rate would
be that same defect wearing a ladder: "the feed is quiet" is what the ladder is for, "the
feed answered and we do not believe it" is a human's problem from the first occurrence.

**THE STALENESS CEILING IS PER-RUNG**, because it is a property of a QUOTE and always
was: `FxQuote.usable` is asked of the rate this rung just published, so a fresh rung 3 is
not stale merely because rung 1 is. `MAX_QUOTE_AGE` itself stays one constant — it
bounds a daily publication cadence every published rung shares.

WHY A RUNG COULD NOT SERVE IS SAID IN TWO WORDS, NOT ONE
---------------------------------------------------------
`RungRefusal` is what an operator SORTS on (three values, three different answers) and
`FxRefusalCode` is what an operator ACTS on (the precise thing that was wrong). They are
separate because the old shape collapsed four unlike failures into one word: a non-200,
a body that is not an array, a body with no USD record and a `subProdName` this parser
cannot read all arrived as `unusable_response`, which reads like "the feed is quiet" and
is not — three of those four mean the contract moved under us, and the fourth means FBIL
answered about currencies that do not include the dollar. Every refusal now carries its
code into the `fx_rung_refused` log line, into `fx_source_degraded`'s fields and into
`fx_pull_failed`'s detail, so the alarm names the thing to go and look at.

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
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal
from urllib.parse import urlencode

import httpx
from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.fx import MAX_QUOTE_AGE
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

#: FBIL's own reference-rate endpoint, without the per-tick query string. THE TOP RUNG
#: (D-609). Spelled once, here, so the URL an operator re-runs by hand to reproduce a
#: disputed figure is the URL the platform used — each rung's FULL url (query string
#: included) is stored on the row it writes (`fx_rate_observations.source_url`) rather
#: than reconstructed by a reader.
FBIL_URL = "https://www.fbil.org.in/wasdm/refrates/fetchfiltered"

#: The value of FBIL's `authenticated` parameter. **A STRING, NOT A BOOLEAN**, because
#: that is what their client sends: `fbil.rb` passes `"false"`. A `False` here would go
#: on the wire as `False` (Python's repr, capitalised) and what an endpoint does with an
#: unrecognised value is exactly the kind of thing nobody may guess about a money path.
FBIL_AUTHENTICATED = "false"

#: How far back the FBIL request asks. **STRICTLY WIDER THAN THE STALENESS CEILING, AND
#: DERIVED FROM IT RATHER THAN TYPED**, which is the whole reason it is not five days.
#: Asking for exactly the usable window would make "FBIL published nothing usable" and
#: "FBIL answered about no dollar at all" the same response, and those need different
#: answers: the first is the feed being behind and is decided ONE place — `FxQuote.usable`
#: on a stored row, the same predicate money applies — while the second is the contract
#: or the content having moved and must be read by a human. Twice the ceiling means a
#: record that is merely too old still ARRIVES, is still recorded (the eager write), and
#: is refused as `stale_publication` by the one staleness rule; an empty result really is
#: an anomaly.
FBIL_WINDOW = MAX_QUOTE_AGE * 2

#: The Frankfurter endpoint behind rungs 2 and 3.
RATE_URL = f"https://api.frankfurter.dev/v2/rate/{BASE_CURRENCY}/{QUOTE_CURRENCY}"
#: The provider rung 2 filters Frankfurter to — the same administrator rung 1 calls
#: directly, read by a third party over a different host.
PROVIDER = "FBIL"

#: How FBIL names a pair AND ITS UNITS. Their own comment's example is `"INR / 100 JPY"`,
#: rupees per one hundred yen. `search` rather than `fullmatch`: this mirrors the Ruby
#: `=~` the contract was read from, and inventing an anchor here would refuse records
#: their own client accepts — a stricter guess is still a guess (hard rule 11).
_SUB_PROD_NAME = re.compile(r"INR / (\d+) ([A-Z]{3})")

#: Nothing is waiting on this request — no caller, no phone call — so the budget is
#: generous enough to survive a slow hop and short enough that a hung socket cannot hold
#: a worker slot into the next tick.
_TIMEOUT_S = 10.0

#: WHY A RUNG COULD NOT SERVE, in the word an operator SORTS on. A closed vocabulary, in
#: `incomplete_reason`'s house style, because it reaches an operator as a machine-readable
#: alarm field and a log key rather than as prose: the three cases have three different
#: answers. `stale_publication` is the feed working normally and simply being behind;
#: `request_failed` is availability (a status code, a refused socket); `unusable_response`
#: is the vendor's CONTRACT or CONTENT having changed under us, which is the one that must
#: be read rather than waited out.
RungRefusal = Literal["stale_publication", "request_failed", "unusable_response"]

#: WHAT WAS WRONG, in the word an operator ACTS on. `RungRefusal` says which of three
#: playbooks applies; this says which line of it. It exists because four unlike failures
#: used to arrive as the single word `unusable_response` — a non-200, a body that is not
#: the documented container, a body carrying no USD record, and a `subProdName` this
#: parser cannot read — and an alarm that cannot tell those apart reads like "the feed is
#: quiet", which three of the four are not. Every refusal carries one of these into the
#: `fx_rung_refused` log line, into `fx_source_degraded`'s and `fx_pull_failed`'s
#: `refusal_code` field (NOT `code` — that name is `alert()`'s own, for the alarm), and
#: into the alarm detail an operator reads.
FxRefusalCode = Literal[
    # availability — the request never produced a body to look at
    "request_failed",
    # the body was not the documented container
    "not_json",
    "not_an_object",
    "not_an_array",
    # the body was the right shape and said the wrong thing
    "wrong_pair",
    "rate_not_numeric",
    "rate_not_positive",
    "no_date",
    "date_not_iso",
    "date_in_future",
    # FBIL-specific: the array arrived and yielded no usable dollar rate
    "no_usd_record",
    "sub_prod_name_unparsable",
    # the ladder as a whole, when no rung produced a rate and none raised
    "ladder_exhausted",
]

#: WHICH RUNG IS SERVING, for the tick summary arq keeps and the log line an operator
#: greps. Same closed-vocabulary reasoning: "is this platform billing off the benchmark"
#: is a question that must be answerable without parsing a sentence.
ServingRung = Literal["preferred", "fallback_source", "configured_fallback"]

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

    Raised bare by the PARSERS, i.e. by the CONTRACT half — the response arrived and a
    parser refused it. That distinction became load-bearing when the ladder landed: the
    two halves are different `RungRefusal` values because they have different answers, so
    the subclass below carries the other one.

    `code` is the refusal in one machine-readable word. It is REQUIRED rather than
    defaulted, because a default is how a new failure mode ends up filed under an old
    one's playbook — the defect this vocabulary exists to stop.
    """

    def __init__(self, message: str, *, code: FxRefusalCode) -> None:
        super().__init__(message)
        self.code: Final[FxRefusalCode] = code


class FxFeedUnreachableError(FxPullError):
    """The request never produced a response this parser could even look at — a transport
    failure or a non-200. A SUBCLASS rather than a sibling so every existing `except
    FxPullError` keeps catching it; what it adds is that the ladder can tell availability
    (`request_failed`, wait for the next tick) from a changed contract
    (`unusable_response`, read the vendor's docs before trusting anything)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="request_failed")


def _publication_date(raw: str) -> date:
    """One spelling of "the date a source stamped on this rate", for every rung.

    ⚠ **THIS DOCSTRING USED TO SAY `date.fromisoformat` "ALSO ACCEPTS AN ISO DATETIME",
    AND THAT IS FALSE ON PYTHON 3.12 — WHICH IS EXACTLY THE BUG IT CAUSED.** Measured in
    this interpreter (3.12.3): `date.fromisoformat("2026-09-08 00:00:00")` and
    `...("2026-09-08T00:00:00")` both raise; only a bare `YYYY-MM-DD` parses. FBIL sends
    `"processRunDate": "2026-09-08 00:00:00"`, so every dollar record it published was
    refused `date_not_iso` on the first day the direct rung ran in production, and the
    ladder degraded to `frankfurter:default`. The claim was written from recollection of
    the 3.11 relaxation, which landed on `datetime.fromisoformat`, not on this one — a
    repo-internal sentence asserting an outside fact, which hard rule 11 exists to stop.

    **EVIDENCE: VENDOR-MEASURED, founder-relayed, 15 Sep 2026** — a live
    `GET https://www.fbil.org.in/wasdm/refrates/fetchfiltered?fromDate=2026-09-01&
    toDate=2026-09-15&authenticated=false` returned records shaped
    `{"processRunDate":"2026-09-08 00:00:00","subProdName":"INR / 1 USD",
    "displayTime":"2026-09-08 13:00:00","rate":94.717800,"comments":""}`. The host is
    egress-blocked from the build container, so that reading came from the VPS.

    So a bare date is tried first and a datetime second, and the TIME IS DISCARDED rather
    than compared: `as_of` is a PUBLICATION DATE, the staleness ceiling is measured in
    days, and FBIL stamps midnight on every row while putting the real publication hour in
    a different field (`displayTime`). Anything neither form parses is still a refusal with
    the field named — never a coerced date, because `as_of` is what the staleness ceiling
    is measured against and a wrong one is invisible.

    The future check is here rather than at the call sites because it is the same hazard
    for every feed: a date in the future is a clock or a parser problem, and it would make
    a stale rate look permanently fresh — it is the one value a bad feed could use to
    disable the ceiling entirely.
    """
    try:
        as_of = date.fromisoformat(raw)
    except ValueError:
        try:
            # A datetime, whose DATE is the publication day. `datetime.fromisoformat` is
            # the one that took the 3.11 relaxation, so it accepts the space separator
            # FBIL uses, a `T`, and an offset; `date.fromisoformat` accepts none of them.
            as_of = datetime.fromisoformat(raw).date()
        except ValueError:
            raise FxPullError(
                f"the publication date ({raw}) was not an ISO date or datetime",
                code="date_not_iso",
            ) from None
    if as_of > datetime.now(UTC).date() + timedelta(days=1):
        raise FxPullError(f"the publication date ({raw}) is in the future", code="date_in_future")
    return as_of


def _decoded(body: str) -> object:
    """The vendor's JSON, with **THE RATE NEVER TOUCHING A BINARY FLOAT**, which is the
    whole reason the parsers below exist rather than a `response.json()` call.

    Both feeds publish their rate as a JSON `number`, and `json.loads` turns a number into
    a `float` — so `88.4275` would already be `88.42749999999999...` before any of our
    code saw it, and a rate that cannot be written down exactly is one nobody can
    reconcile a ledger against. `parse_float=Decimal` hands the parser's own TEXT slice to
    `Decimal`, which is the only lossless path from their wire to hard rule 7's NUMERIC.
    `parse_int=Decimal` covers the day a rate is published as `90` rather than `90.0`.
    """
    try:
        return json.loads(body, parse_float=Decimal, parse_int=Decimal)
    except ValueError:
        raise FxPullError("the response was not JSON", code="not_json") from None


def parse_rate_response(body: str) -> tuple[Decimal, date]:
    """FRANKFURTER's JSON object to `(rate, as_of)`, or `FxPullError`. Rungs 2 and 3.

    Every field is checked rather than assumed, including the two that "cannot" be wrong:
    a `base`/`quote` that is not the pair we asked for means a redirect, a proxy or a
    changed route, and converting at somebody else's currency pair is the single most
    expensive way this could fail.
    """
    payload = _decoded(body)
    if not isinstance(payload, dict):
        raise FxPullError("the response was not a JSON object", code="not_an_object")

    base = payload.get("base")
    quote = payload.get("quote")
    if base != BASE_CURRENCY or quote != QUOTE_CURRENCY:
        raise FxPullError(
            f"the response is for {base}/{quote}, not {BASE_CURRENCY}/{QUOTE_CURRENCY}",
            code="wrong_pair",
        )

    raw_rate = payload.get("rate")
    if not isinstance(raw_rate, Decimal):
        # A string, a null, or a missing key. Refused rather than coerced: a feed that
        # changed the type of its money field has changed in a way somebody must read
        # about before we bill on it.
        raise FxPullError("the response carried no numeric `rate`", code="rate_not_numeric")
    if not raw_rate.is_finite() or raw_rate <= 0:
        raise FxPullError(
            "the response carried a non-positive or non-finite `rate`", code="rate_not_positive"
        )

    raw_date = payload.get("date")
    if not isinstance(raw_date, str):
        raise FxPullError("the response carried no `date`", code="no_date")
    return raw_rate, _publication_date(raw_date)


@dataclass(slots=True)
class _FbilTally:
    """Why each record of an FBIL array was passed over, counted rather than narrated.

    An operator staring at `no_usd_record` needs to know WHICH skip happened: "eleven
    records, all of them other currencies" is FBIL answering normally about a window in
    which it published no dollar rate, and "eleven records, none of whose names parsed" is
    the naming convention having changed. COUNTS ONLY — the vendor's own bytes never reach
    a log line or an alarm (hard rule 6's discipline, applied to a payload rather than to
    PII), so this is the whole of what a refusal is allowed to say about the body.
    """

    records: int = 0
    not_an_object: int = 0
    incomplete: int = 0
    name_unparsable: int = 0
    names_parsed: int = 0
    other_currency: int = 0
    zero_units: int = 0
    unusable_rate: int = 0
    date_unparsable: int = 0

    def __str__(self) -> str:
        """Every count, including the zeroes: "other_currency=0" is the fact that FBIL
        answered about nothing at all, and dropping it would leave the reader guessing
        whether the counter exists."""
        return ", ".join(
            f"{name}={value}"
            for name, value in (
                ("records", self.records),
                ("not_an_object", self.not_an_object),
                ("incomplete", self.incomplete),
                ("name_unparsable", self.name_unparsable),
                ("other_currency", self.other_currency),
                ("zero_units", self.zero_units),
                ("unusable_rate", self.unusable_rate),
                ("date_unparsable", self.date_unparsable),
            )
        )


def parse_fbil_response(body: str) -> tuple[Decimal, date]:
    """FBIL's JSON ARRAY to `(rate, as_of)` for USD, or `FxPullError`. Rung 1.

    **THE UNITS ARE READ, NEVER ASSUMED.** `subProdName` carries both the foreign currency
    and how many of it the rate is quoted per (`"INR / 100 JPY"` is rupees per one hundred
    yen), and `FxQuote.rate` is rupees per ONE dollar. Assuming `1` would be a silent
    factor-of-`units` error on every invoice, which is why the division is explicit, is
    `Decimal` on both sides, and is the first thing a reader of this function sees.

    **SKIPPING AND REFUSING ARE DIFFERENT ACTS.** A record that is not about the dollar,
    or that FBIL published incompletely, is SKIPPED — that is their own client's behaviour
    and the array is documented to carry every pair. But an array that yields NO dollar
    rate is REFUSED with the tally, because `[]` and "eleven records, none of them
    parseable" would otherwise both arrive as silence and be waited out.

    The newest `processRunDate` wins, and a later record with the same date supersedes an
    earlier one — the same tiebreak `ops/fx_rates.latest_observation` applies for the same
    reason: a correction is the one observation nobody may lose to an accident of order.
    """
    payload = _decoded(body)
    if not isinstance(payload, list):
        # Their own adapter raises here too. A non-array from this endpoint is an error
        # page, a login redirect or a changed contract — never a rate.
        raise FxPullError("the response was not a JSON array", code="not_an_array")

    tally = _FbilTally()
    best: tuple[date, Decimal] | None = None
    for record in payload:
        tally.records += 1
        if not isinstance(record, dict):
            tally.not_an_object += 1
            continue
        name = record.get("subProdName")
        run_date = record.get("processRunDate")
        raw_rate = record.get("rate")
        if not isinstance(name, str) or not isinstance(run_date, str):
            tally.incomplete += 1
            continue
        if not isinstance(raw_rate, Decimal) or not raw_rate.is_finite():
            # `rate` absent, null, or a string. Their client requires it numeric; so do we.
            tally.incomplete += 1
            continue
        matched = _SUB_PROD_NAME.search(name)
        if matched is None:
            tally.name_unparsable += 1
            continue
        tally.names_parsed += 1
        units, currency = Decimal(matched.group(1)), matched.group(2)
        if currency != BASE_CURRENCY:
            tally.other_currency += 1
            continue
        if units == 0:
            # Their client skips this rather than dividing. A zero-unit quote is a
            # publication defect, and the alternative is a ZeroDivisionError on money.
            tally.zero_units += 1
            continue
        rate = raw_rate / units
        if rate <= 0:
            tally.unusable_rate += 1
            continue
        try:
            as_of = _publication_date(run_date)
        except FxPullError as exc:
            if exc.code == "date_in_future":
                # NOT skipped: a future date is the one value that could disable the
                # staleness ceiling, so it is refused for the whole response rather than
                # quietly passed over in favour of an older record.
                raise
            tally.date_unparsable += 1
            continue
        if best is None or as_of >= best[0]:
            best = (as_of, rate)

    if best is None:
        if tally.names_parsed == 0 and tally.name_unparsable > 0:
            raise FxPullError(
                f"no record's `subProdName` matched `{_SUB_PROD_NAME.pattern}` ({tally}). "
                "FBIL's naming convention has changed and the units this platform divides "
                "by can no longer be read — re-read the field before trusting any rate.",
                code="sub_prod_name_unparsable",
            )
        if tally.date_unparsable > 0:
            # Every dollar record this response carried was passed over for its DATE
            # alone. That is a different fact from "FBIL published no dollar rate", and
            # it is the most likely first failure of this rung: nothing in this tree has
            # read FBIL's date format, `_publication_date` accepts ISO only, and a
            # coerced date would silently move the staleness ceiling. So it is named.
            raise FxPullError(
                f"every {BASE_CURRENCY} record was skipped for an unreadable "
                f"`processRunDate` ({tally}). FBIL's date format is not the ISO one this "
                "parser accepts — read OPERATIONS §2 gate 39 before changing it.",
                code="date_not_iso",
            )
        raise FxPullError(
            f"the response carried no usable {BASE_CURRENCY} record ({tally})",
            code="no_usd_record",
        )
    return best[1], best[0]


def _frankfurter_request(providers: str | None) -> Callable[[date], str]:
    """A Frankfurter rung's request. The date is ignored — their endpoint answers with
    the latest publication and takes no window — and the parameter is still in the
    signature because ONE ladder calls every rung the same way."""
    url = RATE_URL if providers is None else f"{RATE_URL}?{urlencode({'providers': providers})}"

    def build(_today: date) -> str:
        return url

    return build


def _fbil_request(today: date) -> str:
    """FBIL's request for one tick: the window ending today. See `FBIL_WINDOW` for why it
    is wider than the staleness ceiling, and `FBIL_AUTHENTICATED` for why `false` is a
    string."""
    query = urlencode(
        {
            "fromDate": (today - FBIL_WINDOW).isoformat(),
            "toDate": today.isoformat(),
            "authenticated": FBIL_AUTHENTICATED,
        }
    )
    return f"{FBIL_URL}?{query}"


@dataclass(frozen=True, slots=True)
class FxRung:
    """One published source, the exact request that reaches it, how to read its answer,
    and why it is here.

    A rung is a REQUEST plus a PARSER plus a SOURCE STRING, and they are defined together
    on purpose: the string is stamped on every `usage_events` row the rate converts, and
    hard rule 4 means that row can never be annotated afterwards — so the only thing that
    will ever explain a figure is a source an operator can turn back into the request that
    produced it, and a parser a reader can find from the source.

    **`url_for` AND `parse` ARE FIELDS, NOT A BRANCH IN THE WALK.** D-609 put a rung on the
    ladder that speaks a different wire language from the others (a different host, a
    dated query window, an ARRAY rather than an object). Carrying that difference in the
    rung keeps `_walk_ladder` one loop over one list; an `if rung is ...` inside the walk
    would be a second ladder wearing the first one's clothes, and every such branch is a
    place the plausibility guard, the eager write or the per-rung staleness rule can be
    forgotten for one rung.
    """

    #: `<api>:<publication>`, stamped on the observation row and on every converted figure.
    source: str
    #: The FULL request for a given day, query string and all. One spelling: what httpx is
    #: handed IS what is written to `source_url`, so the stored URL cannot drift from the
    #: one that was actually sent.
    url_for: Callable[[date], str]
    #: This feed's body to `(rate, as_of)`. Raises `FxPullError` on anything else.
    parse: Callable[[str], tuple[Decimal, date]]
    #: The operator's sentence for why this rung exists, used in the alarm that says the
    #: platform has fallen past it.
    why: str


#: THE PREFERRED RUNG (D-609). The benchmark administrator's own endpoint, with no
#: aggregator in the money path; see the module docstring.
FBIL_DIRECT_RUNG: Final = FxRung(
    source="fbil:refrates",
    url_for=_fbil_request,
    parse=parse_fbil_response,
    why="the Indian benchmark rate, from the administrator that publishes it",
)
#: FALLBACK 1. The same benchmark, read by a third party over a different host and network
#: path — so it survives rung 1's most likely failures without sharing them.
FRANKFURTER_FBIL_RUNG: Final = FxRung(
    source=f"frankfurter:{PROVIDER}",
    url_for=_frankfurter_request(PROVIDER),
    parse=parse_rate_response,
    why="the same Indian benchmark rate, read through an aggregator on a different host",
)
#: FALLBACK 2. The same endpoint with no provider filter — a rate the API itself
#: published today, which is what makes it better than a constant typed a fortnight ago.
FRANKFURTER_DEFAULT_RUNG: Final = FxRung(
    source="frankfurter:default",
    url_for=_frankfurter_request(None),
    parse=parse_rate_response,
    why=(
        "the rate API's own default response, which is a published rate from today rather "
        "than an operator's typed constant"
    ),
)

#: The ladder, in preference order. `pull_fx_rate` walks it and stops at the first rung
#: that can serve; nothing else in this repo encodes the order.
LADDER: Final[tuple[FxRung, ...]] = (
    FBIL_DIRECT_RUNG,
    FRANKFURTER_FBIL_RUNG,
    FRANKFURTER_DEFAULT_RUNG,
)
PREFERRED_RUNG: Final = LADDER[0]

#: The preferred rung's source, for the puller's OWN alarms (`_warn_if_silent`,
#: `fx_pull_failed`) — which are about this JOB rather than about any one rung, and which
#: have carried the preferred source as their `source` field since the feature shipped.
SOURCE = PREFERRED_RUNG.source


async def fetch_published_rate(
    rung: FxRung, client: httpx.AsyncClient | None = None, *, today: date | None = None
) -> tuple[Decimal, date]:
    """One GET at ONE rung, parsed by that rung's parser. RAISES `FxPullError` otherwise.

    **THE TRANSPORT HALF IS SHARED ACROSS EVERY RUNG AND THAT IS THE WHOLE REASON THIS
    TAKES A RUNG.** The timeout, the redirect policy, the status check and the refusal
    vocabulary are properties of "we fetch money's input over HTTP", not of any one
    vendor; only the URL and the body's grammar differ, and those are the rung's two
    fields. A second fetch function per feed would be a second place the redirect policy
    gets fixed one at a time.

    `client` is an injection seam, not a second way of doing this: the tests exercise the
    parsers and the failure ladder against a stub transport, because neither live host can
    be reached from CI either. `today` is the other seam — the FBIL window is a function
    of the date, so a test that pins the date pins the URL.
    """
    http = client or httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=False)
    url = rung.url_for(today or datetime.now(UTC).date())
    try:
        response = await http.get(url)
    except httpx.HTTPError as exc:
        raise FxFeedUnreachableError(f"the request failed ({type(exc).__name__})") from exc
    finally:
        if client is None:
            await http.aclose()
    if response.status_code != 200:
        # Frankfurter's 404 means "no data found" — which for a single-provider filter is
        # the real possibility that FBIL has published nothing for this pair — and is as
        # much a failed pull as a 500. FBIL's own endpoint is undocumented, so a non-200
        # from it is not interpreted at all, only reported with its status. Neither is
        # guessed around, and neither is a reason to stop asking: the ladder moves down.
        raise FxFeedUnreachableError(f"the endpoint answered HTTP {response.status_code}")
    return rung.parse(response.text)


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
class RungRefused:
    """One rung that could not serve: the word an operator sorts on, and the word they
    act on. Two fields rather than one because `unusable_response` alone sent four unlike
    failures to the same playbook."""

    rung: FxRung
    why: RungRefusal
    #: `None` exactly when the rung ANSWERED and simply published something too old —
    #: there was no error to name, and inventing a code for it would put the one benign
    #: refusal in the same vocabulary as the ones that need reading.
    code: FxRefusalCode | None

    def __str__(self) -> str:
        return f"{self.rung.source}={self.why}" + (f"/{self.code}" if self.code else "")


@dataclass(frozen=True, slots=True)
class LadderResult:
    """What one walk of the ladder found. `serving is None` means no published rung could
    serve, so the configured constant is what money will convert at."""

    #: The rung that is serving, its stored row, and whether THIS tick inserted that row.
    serving: tuple[FxRung, FxObservation, bool] | None
    #: Every rung that could not serve, in ladder order, with why.
    refusals: tuple[RungRefused, ...]
    #: The last exception a rung raised, kept so the failure path can report a CAUSE
    #: rather than "nothing worked".
    last_error: FxPullError | None

    def refusal_for(self, rung: FxRung) -> RungRefused | None:
        return next((refusal for refusal in self.refusals if refusal.rung is rung), None)

    @property
    def hard_failure(self) -> bool:
        """True when a rung did not merely publish something old — it did not answer, or
        answered something this parser refuses. That is the difference between "the feed
        is behind" (wait; the next tick asks again) and "the feed is broken" (retry, then
        page somebody), and the two must not share a failure path."""
        return any(refusal.why != "stale_publication" for refusal in self.refusals)


async def _walk_ladder(now: datetime) -> LadderResult:
    """Try each rung in preference order, stopping at the first that can serve.

    Every rung that PARSES is recorded even when it is too old to serve — see the module
    docstring — and every rung is recorded through `record_observation`, which is where
    the plausibility band lives, so no fallback can route around it. An
    `ImplausibleRateError` is alerted at the rung that produced it and then propagates:
    the ladder deliberately does NOT descend past a rate we refused to believe.
    """
    refusals: list[RungRefused] = []
    last_error: FxPullError | None = None
    for rung in LADDER:
        try:
            rate, as_of = await fetch_published_rate(rung, today=now.date())
        except FxPullError as exc:
            # The subclass is the sorting distinction: unreachable is availability, bare is
            # a changed contract. `exc.code` is the acting distinction — which of the two
            # dozen things that can be wrong actually was.
            why: RungRefusal = (
                "request_failed" if isinstance(exc, FxFeedUnreachableError) else "unusable_response"
            )
            last_error = exc
            refusals.append(RungRefused(rung=rung, why=why, code=exc.code))
            log.warning(
                "fx_rung_refused",
                extra={
                    "source": rung.source,
                    "reason": why,
                    "refusal_code": exc.code,
                    "detail": str(exc),
                    "error": type(exc).__name__,
                },
            )
            continue
        try:
            async with untenanted_session() as session:
                observation, inserted = await record_observation(
                    session,
                    rate=rate,
                    as_of=as_of,
                    source=rung.source,
                    source_url=rung.url_for(now.date()),
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
        # per-rung: a fresh rung 3 is not stale because rung 1 is. One spelling of the
        # rule — `FxQuote.usable`, the same predicate money and the ops panel apply.
        if observation.as_quote().usable(now):
            return LadderResult(
                serving=(rung, observation, inserted), refusals=tuple(refusals), last_error=None
            )
        refusals.append(RungRefused(rung=rung, why="stale_publication", code=None))
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
        failure = result.last_error or FxPullError(
            "no rung produced a usable rate", code="ladder_exhausted"
        )
        reasons = ", ".join(str(refusal) for refusal in result.refusals)
        log.warning(
            "fx_pull_failed",
            extra={"source": SOURCE, "error": type(failure).__name__, "refusal_code": failure.code},
        )
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
            # NOT `code=`: `alert()`'s second positional parameter IS the alarm code, so a
            # field by that name collides with it at the call. The refusal's own word gets
            # a name of its own rather than shadowing the alarm's.
            refusal_code=failure.code,
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
            extra={"refusals": ";".join(str(refusal) for refusal in result.refusals)},
        )
    elif result.serving[0] is PREFERRED_RUNG:
        serving_state = "preferred"
    else:
        serving_state = "fallback_source"
        rung, observation, _ = result.serving
        refused = result.refusal_for(PREFERRED_RUNG)
        preferred_reason: RungRefusal = refused.why if refused else "request_failed"
        preferred_code: FxRefusalCode | None = refused.code if refused else "request_failed"
        # DEGRADED, NOT DOWN. The rate is real and published today; what moved is the
        # provenance stamped on every `usage_events` row from this moment on, and hard
        # rule 4 means none of those rows can be annotated afterwards. So an operator is
        # told at the moment it moves, rather than discovering it in a reconciliation.
        alert(
            "CORE_LOGIC",
            "fx_source_degraded",
            detail=(
                f"The preferred USD/INR source {PREFERRED_RUNG.source} could not serve "
                f"({preferred_reason}{f'/{preferred_code}' if preferred_code else ''}), so vendor "
                f"costs are converting at {rung.source} — {rung.why}. The rate is real and "
                f"published ({observation.as_of.isoformat()}), but every usage_events row "
                "written from "
                "now on records the fallback source and cannot be re-stamped later. "
                f"Every rung that could not serve: {', '.join(str(r) for r in result.refusals)}."
            ),
            source=rung.source,
            preferred_source=PREFERRED_RUNG.source,
            reason=preferred_reason,
            # See the `fx_pull_failed` call above for why this is not `code=`.
            refusal_code=preferred_code or preferred_reason,
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
    "FBIL_AUTHENTICATED",
    "FBIL_DIRECT_RUNG",
    "FBIL_URL",
    "FBIL_WINDOW",
    "FRANKFURTER_DEFAULT_RUNG",
    "FRANKFURTER_FBIL_RUNG",
    "LADDER",
    "MAX_PULL_SILENCE",
    "PREFERRED_RUNG",
    "PROVIDER",
    "PULL_MINUTES",
    "RATE_URL",
    "SOURCE",
    "FxFeedUnreachableError",
    "FxPullError",
    "FxRefusalCode",
    "FxRung",
    "LadderResult",
    "RungRefusal",
    "RungRefused",
    "ServingRung",
    "fetch_published_rate",
    "parse_fbil_response",
    "parse_rate_response",
    "pull_fx_rate",
]
